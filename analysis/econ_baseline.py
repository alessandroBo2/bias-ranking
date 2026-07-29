#!/usr/bin/env python
"""Econometric baseline vs learning-to-rank: the head-to-head comparison.

Answers two supervisor questions with numbers:
  (1) HOW the methods are compared: same data, same split, same evaluation.
      An OLS rank regression (merit + seller dummies [+ CSS]) and the
      LambdaMART ranker are trained on identical 70/30 query-grouped splits
      and BOTH are scored with the same out-of-sample metric: mean
      per-SERP NDCG@10 computed by scikit-learn on the test pages.
  (2) WHAT "accuracy" and "comprehensiveness" mean operationally:
      accuracy   = out-of-sample ranking fidelity (the common NDCG@10);
      comprehensiveness = detection of heterogeneity: the OLS pooled CSS
      coefficient vs the by-surface split the ML attribution localises.

Usage:
    python econ_baseline.py --source organic  --db ../scraper/results_serpapi.db --seeds 5
    python econ_baseline.py --source sponsored --db ../results_serp_dma.db --seeds 5
"""
import argparse
import sqlite3
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

TOP_SELLERS = 30


def rel_tfidf(df):
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, max_features=20000)
    M = vec.fit_transform(pd.concat([df["keyword"], df["title"].fillna("")]))
    n = len(df); K, T = M[:n], M[n:]
    kn = np.sqrt(np.asarray(K.multiply(K).sum(1)).ravel())
    tn = np.sqrt(np.asarray(T.multiply(T).sum(1)).ravel())
    return np.asarray(K.multiply(T).sum(1)).ravel() / np.where(kn * tn == 0, 1, kn * tn)


def load(source, db):
    con = sqlite3.connect(db)
    if source == "organic":
        df = pd.read_sql("SELECT * FROM products WHERE language='IT'", con)
    else:
        df = pd.read_sql("SELECT * FROM serp_ads", con)
    con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
    df["seller"] = df["seller"].fillna("").str.strip().str.lower()
    df["rel"] = rel_tfidf(df)
    t = df["title"].fillna("")
    df["log_price"] = np.log1p(df["price_value"])
    df["title_len"] = t.str.len()
    df["title_words"] = t.str.split().apply(len)
    freq = df["seller"].value_counts()
    df["is_amazon"] = df["seller"].str.contains("amazon", case=False).astype(int)
    df["seller_freq_log"] = np.log1p(df["seller"].map(freq).fillna(0))
    if source == "sponsored":
        df["is_google_css"] = df["css_partner"].fillna("").str.lower().str.match("^google").astype(int)
        df["new_element"] = (df["unit_variant"] == "top_pla_group").astype(int)
    df["y"] = df["position"].apply(lambda p: 4 if p <= 2 else 3 if p <= 5 else 2 if p <= 10 else 1 if p <= 20 else 0)
    return df, freq


def design_matrix(df, freq, source, seller_cols):
    X = pd.DataFrame(index=df.index)
    for c in ("log_price", "rel", "title_len", "title_words"):
        X[c] = df[c]
    X = pd.concat([X, pd.get_dummies(df["category_l1"], prefix="cat", dtype=float)], axis=1)
    for s in seller_cols:
        X[f"s_{s[:20]}"] = (df["seller"] == s).astype(float)
    if source == "sponsored":
        X["is_google_css"] = df["is_google_css"]
    X["const"] = 1.0
    return X.astype(float)


def ndcg_eval(dte, score_col):
    from sklearn.metrics import ndcg_score
    tot, k = 0.0, 0
    for _, g in dte.groupby("run_id", sort=False):
        if len(g) < 2:
            continue
        tot += ndcg_score([g["y"].values], [g[score_col].values], k=10)
        k += 1
    return tot / k


def train_ltr(df, feats, tr, te, cats):
    import lightgbm as lgb
    grp = lambda d: d.groupby("run_id", sort=False).size().values
    dtr = df.iloc[tr].sort_values("run_id"); dte = df.iloc[te].sort_values("run_id").copy()
    m = lgb.LGBMRanker(objective="lambdarank", metric="ndcg", n_estimators=300, learning_rate=0.05,
        num_leaves=31, min_child_samples=30, subsample=0.8, colsample_bytree=0.8, random_state=0,
        n_jobs=2, verbose=-1, label_gain=[0, 1, 3, 7, 15])
    m.fit(dtr[feats], dtr["y"], group=grp(dtr), categorical_feature=cats)
    dte["score_ltr"] = m.predict(dte[feats])
    return dte


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["organic", "sponsored"], required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--seeds", type=int, default=5)
    a = ap.parse_args()

    df, freq = load(a.source, a.db)
    seller_cols = [s for s in freq.head(TOP_SELLERS).index if s]
    print(f"[{a.source}] rows {len(df):,} | SERPs {df['run_id'].nunique():,} | "
          f"seller dummies {len(seller_cols)}")

    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.linear_model import LinearRegression
    feats_ltr = ["log_price", "rel", "title_len", "title_words", "category_l1", "category_l2",
                 "is_amazon", "seller_freq_log"] + (["is_google_css"] if a.source == "sponsored" else [])
    for c in ("category_l1", "category_l2"):
        df[c] = df[c].astype("category")

    rows = []
    for s in range(a.seeds):
        tr, te = next(GroupShuffleSplit(1, test_size=0.3, random_state=s)
                      .split(df, groups=df["run_id"]))
        X = design_matrix(df, freq, a.source, seller_cols)
        ols = LinearRegression().fit(X.iloc[tr], df["position"].iloc[tr].astype(float))
        dte = df.iloc[te].sort_values("run_id").copy()
        dte["score_ols"] = -ols.predict(X.iloc[te].loc[dte.index])
        dte = dte.join(train_ltr(df, feats_ltr, tr, te,
                                 ["category_l1", "category_l2"])["score_ltr"])
        n_ols = ndcg_eval(dte, "score_ols")
        n_ltr = ndcg_eval(dte, "score_ltr")
        rows.append((n_ols, n_ltr, n_ltr - n_ols))
        print(f"seed {s}: NDCG@10 OLS {n_ols:.3f} | LTR {n_ltr:.3f} | gap {n_ltr-n_ols:+.3f}",
              flush=True)
    A = np.array(rows)
    print(f"\n{a.seeds} seeds | OLS {A[:,0].mean():.3f}±{A[:,0].std():.3f} | "
          f"LTR {A[:,1].mean():.3f}±{A[:,1].std():.3f} | gap {A[:,2].mean():+.3f}±{A[:,2].std():.3f}")

    # coefficient table with HC3 SEs on the full sample (inference, not prediction)
    try:
        import statsmodels.api as sm
        X = design_matrix(df, freq, a.source, seller_cols)
        res = sm.OLS(df["position"].astype(float), X).fit(cov_type="HC3")
        keep = ["is_google_css"] if a.source == "sponsored" else []
        keep += [c for c in X.columns if c.startswith("s_amazon")] + ["log_price", "rel"]
        tab = pd.DataFrame({"coef": res.params[keep], "se": res.bse[keep],
                            "t": res.tvalues[keep]}).round(4)
        print("\nOLS coefficients (position; HC3):"); print(tab.to_string())
        if a.source == "sponsored":
            X2 = X.copy()
            X2["gcss_x_new"] = df["is_google_css"] * df["new_element"]
            res2 = sm.OLS(df["position"].astype(float), X2).fit(cov_type="HC3")
            het = pd.DataFrame({"coef": res2.params[["is_google_css", "gcss_x_new"]],
                                "se": res2.bse[["is_google_css", "gcss_x_new"]],
                                "t": res2.tvalues[["is_google_css", "gcss_x_new"]]}).round(4)
            print("\nHeterogeneity check (Google-CSS x new element interaction):")
            print(het.to_string())
        tab.to_csv(f"econ_baseline_{a.source}_coefs.csv", encoding="utf-8-sig")
    except ImportError:
        print("statsmodels not installed - coefficient table skipped")
    pd.DataFrame({"metric": ["NDCG OLS mean", "NDCG OLS std", "NDCG LTR mean", "NDCG LTR std",
                             "gap mean", "gap std"],
                  "value": [A[:,0].mean(), A[:,0].std(), A[:,1].mean(), A[:,1].std(),
                            A[:,2].mean(), A[:,2].std()],
                  "source": a.source, "n_seeds": a.seeds}) \
        .round(4).to_csv(f"econ_baseline_{a.source}_ndcg.csv", index=False, encoding="utf-8-sig")
    print(f"-> econ_baseline_{a.source}_ndcg.csv / _coefs.csv")


if __name__ == "__main__":
    main()
