#!/usr/bin/env python
"""
Google Shopping bias audit — Learning-to-rank (LambdaMART) with a semantic encoder.
CLI version, aligned with the notebook bias_ranking_audit.ipynb.

Encoders:
  sentence-transformers -> full MiniLM (paraphrase-multilingual-MiniLM-L12-v2). Needs torch.
                           Use --model-path to load it OFFLINE from a local folder.
  model2vec             -> static multilingual, no torch, CPU-only. Default in the sandbox.
  tfidf                 -> lexical proxy, for comparison.

Examples:
  python bias_ranking_audit.py --db results.db --country IT --encoder sentence-transformers --model-path minilm_it
  python bias_ranking_audit.py --db results.db --country IT --encoder model2vec --seeds 10
"""
from __future__ import annotations
import argparse, sqlite3, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

ST_MODEL  = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
M2V_MODEL = "minishlab/potion-multilingual-128M"

try:
    import torch
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
except Exception:
    DEVICE = "cpu"


# ----------------------------- relevance ----------------------------------- #
def _cosine_rows(K, T):
    K = K / (np.linalg.norm(K, axis=1, keepdims=True) + 1e-9)
    T = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-9)
    return (K * T).sum(1)

def _encode_unique(enc, texts):
    uniq = pd.Index(texts.fillna("").unique())
    emb = np.asarray(enc(uniq.tolist()))
    return emb[uniq.get_indexer(texts.fillna(""))]

def rel_sentence_transformers(df, model_path=""):
    from sentence_transformers import SentenceTransformer
    src = model_path or ST_MODEL
    kw = {"local_files_only": True} if model_path else {}
    m = SentenceTransformer(src, device=DEVICE, **kw)
    enc = lambda xs: m.encode(xs, normalize_embeddings=True, show_progress_bar=False, batch_size=256)
    return (_encode_unique(enc, df["keyword"]) * _encode_unique(enc, df["title"])).sum(1)

def rel_model2vec(df, model_path=""):
    from model2vec import StaticModel
    m = StaticModel.from_pretrained(model_path or M2V_MODEL)
    enc = lambda xs: m.encode(xs, show_progress_bar=False)
    return _cosine_rows(_encode_unique(enc, df["keyword"]), _encode_unique(enc, df["title"]))

def rel_tfidf(df, model_path=""):
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, max_features=20000)
    M = vec.fit_transform(pd.concat([df["keyword"], df["title"].fillna("")]))
    n = len(df); K, T = M[:n], M[n:]
    kn = np.sqrt(np.asarray(K.multiply(K).sum(1)).ravel())
    tn = np.sqrt(np.asarray(T.multiply(T).sum(1)).ravel())
    return np.asarray(K.multiply(T).sum(1)).ravel() / np.where(kn * tn == 0, 1, kn * tn)

def compute_relevance(df, encoder, model_path=""):
    fn = {"sentence-transformers": rel_sentence_transformers,
          "model2vec": rel_model2vec, "tfidf": rel_tfidf}[encoder]
    try:
        return fn(df, model_path), encoder
    except Exception as e:
        print(f"[rel] '{encoder}' unavailable ({type(e).__name__}: {e}) -> TF-IDF fallback")
        return rel_tfidf(df), "tfidf(fallback)"


# ----------------------------- features ------------------------------------- #
MERIT    = ["log_price", "rel", "title_len", "title_words", "is_branded", "category_l1", "category_l2"]
PLATFORM = ["is_amazon", "is_giant", "seller_freq_log"]
CAT      = ["category_l1", "category_l2"]

def load(db_path, country):
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql("SELECT * FROM products WHERE language = ?", con, params=(country,))
    finally:
        con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
    if df.empty:
        raise SystemExit(f"No rows with a valid price for language='{country}'.")
    return df

def build_features(df, rel):
    df = df.copy(); df["rel"] = rel
    t = df["title"].fillna("")
    df["log_price"]   = np.log1p(df["price_value"])
    df["title_len"]   = t.str.len()
    df["title_words"] = t.str.split().apply(len)
    df["is_branded"]  = (df["query_type"] == "branded").astype(int)
    df["is_amazon"]   = df["seller"].fillna("").str.contains("amazon", case=False).astype(int)
    df["is_giant"]    = df["seller"].isin(df["seller"].value_counts().head(15).index).astype(int)
    df["seller_freq_log"] = np.log1p(df["seller"].map(df["seller"].value_counts()).fillna(0))
    for c in CAT: df[c] = df[c].astype("category")
    df["y"] = df["position"].apply(lambda p: 4 if p <= 2 else 3 if p <= 5 else 2 if p <= 10 else 1 if p <= 20 else 0)
    return df


# ----------------------------- training ------------------------------------ #
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

def _make_plots(country, used, results, A, sv, dte, lift_single):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shap
    tag = f"{country}_{used}"

    # 1) NDCG@10 by model
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ks = list(results); vs = [results[k] for k in ks]
    ax.barh(ks, vs, color=["#bdbdbd", "#bdbdbd", "#4c78a8", "#e45756"]); ax.invert_yaxis()
    ax.set_xlim(0.35, max(vs) + 0.03)
    for y, v in enumerate(vs):
        ax.text(v + 0.003, y, f"{v:.3f}", va="center", fontsize=10)
    ax.set_xlabel("NDCG@10 (held-out SERPs)")
    ax.set_title(f"Reconstructing Google's order — {country} ({used})")
    plt.tight_layout(); plt.savefig(f"nb_ndcg_{tag}.png", dpi=120, bbox_inches="tight"); plt.close()

    # 2) lift distribution across seeds
    fig, ax = plt.subplots(figsize=(7, 3.2))
    rng = np.random.default_rng(1)
    ax.axvline(0, color="#999", lw=1, ls="--")
    ax.scatter(A[:, 2], rng.normal(0, 0.03, len(A)), color="#e45756", alpha=0.8, zorder=3)
    ax.errorbar(A[:, 2].mean(), 0, xerr=A[:, 2].std(), fmt="o", color="black", capsize=4, zorder=4,
                label=f"mean {A[:,2].mean():+.3f} ± {A[:,2].std():.3f}")
    ax.set_yticks([]); ax.set_xlabel("lift NDCG@10 (merit+seller − merit only)")
    ax.set_title(f"Seller lift across {len(A)} splits"); ax.legend(loc="upper left", fontsize=9)
    plt.tight_layout(); plt.savefig(f"nb_lift_{tag}.png", dpi=120, bbox_inches="tight"); plt.close()

    # 3) SHAP summary (merit+seller model, seed-42 split)
    shap.summary_plot(sv, dte[MERIT + PLATFORM], show=False, max_display=10)
    plt.tight_layout(); plt.savefig(f"nb_shap_{tag}.png", dpi=120, bbox_inches="tight"); plt.close()
    print(f"-> figures: nb_ndcg_{tag}.png, nb_lift_{tag}.png, nb_shap_{tag}.png")


def run(df, used, country, n_seeds=10, out_csv=True, make_plots=True):
    import shap
    # baselines + single split (seed 42)
    tr, te = _split(df, 42); dte_all = df.iloc[te].sort_values("run_id")
    rng = np.random.default_rng(0)
    nd_rand  = _ndcg_baseline(dte_all, lambda g: rng.random(len(g)))
    nd_price = _ndcg_baseline(dte_all, lambda g: -g["price_value"].values)
    mA, _, nA = _train(df, MERIT, tr, te)
    mB, dte, nB = _train(df, MERIT + PLATFORM, tr, te)
    print(f"NDCG@10 | random {nd_rand:.3f} | price {nd_price:.3f} | "
          f"merit only {nA:.3f} | +seller {nB:.3f} | lift {nB-nA:+.3f}")
    results = {"random": nd_rand, "price ascending": nd_price,
               "merit only": nA, "merit + seller": nB}
    sv_main = shap.TreeExplainer(mB).shap_values(dte[MERIT + PLATFORM])

    # multi-seed stability
    rows = []
    for s in range(n_seeds):
        tr, te = _split(df, s)
        _, _, a = _train(df, MERIT, tr, te)
        mB2, dte_s, b = _train(df, MERIT + PLATFORM, tr, te)
        sv = shap.TreeExplainer(mB2).shap_values(dte_s[MERIT + PLATFORM])
        ia = dte_s["is_amazon"].values
        sa = sv[:, (MERIT + PLATFORM).index("is_amazon")][ia == 1].mean()
        rows.append((a, b, b - a, sa))
    A = np.array(rows)
    print(f"[{used}] {n_seeds} seeds | lift {A[:,2].mean():+.3f} ± {A[:,2].std():.3f} "
          f"| is_amazon SHAP {A[:,3].mean():+.3f} ± {A[:,3].std():.3f}")

    if out_csv:
        pd.DataFrame({
            "metric": ["NDCG random", "NDCG price", "NDCG merit only", "NDCG +seller",
                       "lift mean", "lift std", "is_amazon SHAP mean", "is_amazon SHAP std"],
            "value": [nd_rand, nd_price, A[:,0].mean(), A[:,1].mean(),
                      A[:,2].mean(), A[:,2].std(), A[:,3].mean(), A[:,3].std()],
            "country": country, "encoder": used, "n_seeds": n_seeds,
        }).to_csv(f"bias_summary_{country}_{used}.csv", index=False)
        print(f"-> bias_summary_{country}_{used}.csv")

    if make_plots:
        try:
            _make_plots(country, used, results, A, sv_main, dte, nB - nA)
        except Exception as e:
            print(f"[plot] skipping figures ({type(e).__name__}: {e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="results.db")
    ap.add_argument("--country", default="IT")
    ap.add_argument("--encoder", default="model2vec",
                    choices=["sentence-transformers", "model2vec", "tfidf"])
    ap.add_argument("--model-path", default="", help="local model folder (offline loading)")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--no-plots", action="store_true", help="do not generate the PNGs")
    a = ap.parse_args()
    print(f"DB={a.db} | country={a.country} | encoder={a.encoder} | device={DEVICE}"
          + (f" | model-path={a.model_path}" if a.model_path else ""))
    df = load(a.db, a.country)
    print(f"rows {len(df):,} | SERPs {df['run_id'].nunique()}")
    rel, used = compute_relevance(df, a.encoder, a.model_path)
    print(f"relevance: {used} | mean={np.mean(rel):.3f} std={np.std(rel):.3f}")
    df = build_features(df, rel)
    run(df, used, a.country, n_seeds=a.seeds, make_plots=not a.no_plots)


if __name__ == "__main__":
    main()
