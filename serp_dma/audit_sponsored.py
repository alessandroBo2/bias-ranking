#!/usr/bin/env python
"""
Bias audit on the SPONSORED layer (shopping unit of the general SERPs, DMA data).

Same protocol as analysis/bias_ranking_audit.py (LambdaMART grouped by SERP,
NDCG@10 on held-out SERPs, multi-seed), applied to the `serp_ads` table with three models:

  A. merit only      : log_price, rel, title_len, title_words, category_l1/l2
  B. + seller        : is_amazon, is_giant, seller_freq_log
  C. + CSS identity  : is_google_css (is the ad placed by Google's CSS?)

The C−B lift measures whether the Google-CSS identity predicts the slot BEYOND merit and seller.
SHAP computed with LightGBM pred_contrib (no dependency on the shap package).

Differences from the organic audit, motivated:
  - no `is_branded` (here query_type is always 'generic': constant feature);
  - `rel` is TF-IDF only by default (titles and keywords are both in German; pass
    --encoder model2vec/sentence-transformers if the environment has them).

Example:
  python audit_sponsored.py --db ../results_serp_dma.db --seeds 10
"""
from __future__ import annotations
import argparse, sqlite3, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

MERIT    = ["log_price", "rel", "title_len", "title_words", "category_l1", "category_l2"]
PLATFORM = ["is_amazon", "is_giant", "seller_freq_log"]
CSS      = ["is_google_css"]
CAT      = ["category_l1", "category_l2"]


def rel_tfidf(df):
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, max_features=20000)
    M = vec.fit_transform(pd.concat([df["keyword"], df["title"].fillna("")]))
    n = len(df); K, T = M[:n], M[n:]
    kn = np.sqrt(np.asarray(K.multiply(K).sum(1)).ravel())
    tn = np.sqrt(np.asarray(T.multiply(T).sum(1)).ravel())
    return np.asarray(K.multiply(T).sum(1)).ravel() / np.where(kn * tn == 0, 1, kn * tn)


def load(db_path, language="DE"):
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql("SELECT * FROM serp_ads WHERE language = ?", con, params=(language,))
    finally:
        con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
    if df.empty:
        raise SystemExit(f"No rows with a valid price for language='{language}'.")
    return df


def load_panel(parquet_path, wave):
    """Panel offers built by build_panel.py (e.g. the 2023 baseline wave)."""
    df = pd.read_parquet(parquet_path)
    df = df[df["wave"] == wave]
    df = df[df["price_value"].notna() & (df["price_value"] > 0) & df["title"].notna()]
    if df.empty:
        raise SystemExit(f"No usable rows for wave='{wave}' in {parquet_path}.")
    return df.reset_index(drop=True)


def build_features(df, rel):
    df = df.copy(); df["rel"] = rel
    t = df["title"].fillna("")
    df["log_price"]   = np.log1p(df["price_value"])
    df["title_len"]   = t.str.len()
    df["title_words"] = t.str.split().apply(len)
    df["is_amazon"]   = df["seller"].fillna("").str.contains("amazon", case=False).astype(int)
    df["is_giant"]    = df["seller"].isin(df["seller"].value_counts().head(15).index).astype(int)
    df["seller_freq_log"] = np.log1p(df["seller"].map(df["seller"].value_counts()).fillna(0))
    df["is_google_css"]   = df["css_partner"].fillna("").str.lower().str.match(r"^google").astype(int)
    for c in CAT: df[c] = df[c].astype("category")
    df["y"] = df["position"].apply(lambda p: 4 if p <= 2 else 3 if p <= 5 else 2 if p <= 10 else 1 if p <= 20 else 0)
    return df


def _split(df, seed):
    from sklearn.model_selection import GroupShuffleSplit
    return next(GroupShuffleSplit(1, test_size=0.3, random_state=seed).split(df, groups=df["run_id"]))


def _grp(d): return d.groupby("run_id", sort=False).size().values


def _train(df, feats, tr, te):
    import lightgbm as lgb
    dtr = df.iloc[tr].sort_values("run_id"); dte = df.iloc[te].sort_values("run_id")
    m = lgb.LGBMRanker(objective="lambdarank", metric="ndcg", n_estimators=300, learning_rate=0.05,
        num_leaves=31, min_child_samples=30, subsample=0.8, colsample_bytree=0.8, random_state=0,
        n_jobs=2, verbose=-1, label_gain=[0, 1, 3, 7, 15])
    m.fit(dtr[feats], dtr["y"], group=_grp(dtr), eval_set=[(dte[feats], dte["y"])], eval_group=[_grp(dte)],
          eval_at=[10], categorical_feature=[c for c in CAT if c in feats])
    return m, dte, m.best_score_["valid_0"]["ndcg@10"]


def _ndcg_baseline(dte, score):
    from sklearn.metrics import ndcg_score
    tot = 0.0; k = 0
    for _, g in dte.groupby("run_id", sort=False):
        if len(g) < 2: continue
        tot += ndcg_score([g["y"].values], [score(g)], k=10); k += 1
    return tot / k


def _shap_mean(model, dte, feats, feat, mask=None):
    """Mean SHAP of `feat` via pred_contrib (last column = base value, we discard it)."""
    contrib = model.predict(dte[feats], pred_contrib=True)[:, :-1]
    col = contrib[:, feats.index(feat)]
    if mask is not None:
        col = col[mask]
    return col.mean() if len(col) else np.nan


def run(df, n_seeds=10, out_csv=True, tag="sponsored_DE"):
    tr, te = _split(df, 42); dte_all = df.iloc[te].sort_values("run_id")
    rng = np.random.default_rng(0)
    nd_rand  = _ndcg_baseline(dte_all, lambda g: rng.random(len(g)))
    nd_price = _ndcg_baseline(dte_all, lambda g: -g["price_value"].values)
    _, _, nA = _train(df, MERIT, tr, te)
    _, _, nB = _train(df, MERIT + PLATFORM, tr, te)
    _, _, nC = _train(df, MERIT + PLATFORM + CSS, tr, te)
    print(f"NDCG@10 | random {nd_rand:.3f} | price {nd_price:.3f} | merit {nA:.3f} "
          f"| +seller {nB:.3f} | +CSS {nC:.3f} | seller lift {nB-nA:+.3f} | CSS lift {nC-nB:+.3f}")

    rows = []
    for s in range(n_seeds):
        tr, te = _split(df, s)
        _, _, a = _train(df, MERIT, tr, te)
        _, _, b = _train(df, MERIT + PLATFORM, tr, te)
        mC, dte_s, c = _train(df, MERIT + PLATFORM + CSS, tr, te)
        feats = MERIT + PLATFORM + CSS
        s_css = _shap_mean(mC, dte_s, feats, "is_google_css", dte_s["is_google_css"].values == 1)
        s_amz = _shap_mean(mC, dte_s, feats, "is_amazon", dte_s["is_amazon"].values == 1)
        rows.append((a, b, c, b - a, c - b, s_css, s_amz))
    A = np.array(rows)
    print(f"{n_seeds} seeds | seller lift {A[:,3].mean():+.3f} ± {A[:,3].std():.3f} "
          f"| CSS lift {A[:,4].mean():+.3f} ± {A[:,4].std():.3f}")
    print(f"SHAP is_google_css (Google-CSS ads) {A[:,5].mean():+.3f} ± {A[:,5].std():.3f} "
          f"| SHAP is_amazon (Amazon ads) {A[:,6].mean():+.3f} ± {A[:,6].std():.3f}")

    if out_csv:
        pd.DataFrame({
            "metric": ["NDCG random", "NDCG price", "NDCG merit only", "NDCG +seller", "NDCG +CSS",
                       "seller lift mean", "seller lift std", "CSS lift mean", "CSS lift std",
                       "is_google_css SHAP mean", "is_google_css SHAP std",
                       "is_amazon SHAP mean", "is_amazon SHAP std"],
            "value": [nd_rand, nd_price, A[:,0].mean(), A[:,1].mean(), A[:,2].mean(),
                      A[:,3].mean(), A[:,3].std(), A[:,4].mean(), A[:,4].std(),
                      A[:,5].mean(), A[:,5].std(), A[:,6].mean(), A[:,6].std()],
            "layer": tag, "n_seeds": n_seeds,
        }).to_csv(f"bias_summary_{tag}.csv", index=False)
        print(f"-> bias_summary_{tag}.csv")
    return A


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="../results_serp_dma.db")
    ap.add_argument("--parquet", help="panel_offers.parquet from build_panel.py (overrides --db)")
    ap.add_argument("--wave", default="2023w24", help="wave to audit when using --parquet")
    ap.add_argument("--language", default="DE")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--tag", default=None, help="label used in the output CSV name")
    a = ap.parse_args()
    if a.parquet:
        df = load_panel(a.parquet, a.wave)
        tag = a.tag or f"sponsored_{a.wave}"
    else:
        df = load(a.db, a.language)
        tag = a.tag or f"sponsored_{a.language}"
    gshare = df["css_partner"].fillna("").str.lower().str.match(r"^google").mean()
    print(f"rows {len(df):,} | SERPs {df['run_id'].nunique()} | Google-CSS share {gshare:.3f}")
    rel = rel_tfidf(df)
    print(f"relevance: tfidf | mean={np.mean(rel):.3f} std={np.std(rel):.3f}")
    df = build_features(df, rel)
    run(df, n_seeds=a.seeds, tag=tag)


if __name__ == "__main__":
    main()
