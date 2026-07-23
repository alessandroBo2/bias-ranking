#!/usr/bin/env python
"""Quality-adjusted paired audit on the SerpApi organic re-collection.

Re-estimates the seller lift with the QUALITY block (rating, review count)
added to merit: if the lift shrinks materially, part of the original seller
signal was unmeasured quality; if it survives, the quality channel is closed.

Models (same protocol as the main audits — grouped 70/30, multi-seed, NDCG@10):
  A. merit                    (log_price, rel, title_len, title_words, categories)
  Q. merit + quality          (rating, reviews)
  B. merit + seller           (is_amazon, is_giant, seller_freq_log)
  C. merit + quality + seller

Seller lift unadjusted = B - A;  quality-adjusted seller lift = C - Q.

Usage:
    python quality_audit.py --db ../scraper/results_serpapi.db --language IT --seeds 10
"""
import argparse
import sqlite3
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

MERIT   = ["log_price", "rel", "title_len", "title_words", "category_l1", "category_l2"]
QUALITY = ["rating", "log_reviews", "has_rating"]
SELLER  = ["is_amazon", "is_giant", "seller_freq_log"]
CAT     = ["category_l1", "category_l2"]


def rel_tfidf(df):
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, max_features=20000)
    M = vec.fit_transform(pd.concat([df["keyword"], df["title"].fillna("")]))
    n = len(df); K, T = M[:n], M[n:]
    kn = np.sqrt(np.asarray(K.multiply(K).sum(1)).ravel())
    tn = np.sqrt(np.asarray(T.multiply(T).sum(1)).ravel())
    return np.asarray(K.multiply(T).sum(1)).ravel() / np.where(kn * tn == 0, 1, kn * tn)


def build(df):
    df = df.copy()
    t = df["title"].fillna("")
    df["log_price"] = np.log1p(df["price_value"])
    df["title_len"] = t.str.len()
    df["title_words"] = t.str.split().apply(len)
    df["seller"] = df["seller"].fillna("").str.strip().str.lower()
    freq = df["seller"].value_counts()
    df["is_amazon"] = df["seller"].str.contains("amazon", case=False).astype(int)
    df["is_giant"] = df["seller"].isin(freq.head(15).index).astype(int)
    df["seller_freq_log"] = np.log1p(df["seller"].map(freq).fillna(0))
    df["has_rating"] = df["rating"].notna().astype(int)
    df["rating"] = df["rating"].fillna(0)
    df["log_reviews"] = np.log1p(pd.to_numeric(df["reviews_count"], errors="coerce").fillna(0))
    for c in CAT:
        df[c] = df[c].astype("category")
    df["y"] = df["position"].apply(lambda p: 4 if p <= 2 else 3 if p <= 5 else 2 if p <= 10 else 1 if p <= 20 else 0)
    return df


def _split(df, seed):
    from sklearn.model_selection import GroupShuffleSplit
    return next(GroupShuffleSplit(1, test_size=0.3, random_state=seed).split(df, groups=df["run_id"]))


def _train(df, feats, tr, te):
    import lightgbm as lgb
    grp = lambda d: d.groupby("run_id", sort=False).size().values
    dtr = df.iloc[tr].sort_values("run_id"); dte = df.iloc[te].sort_values("run_id")
    m = lgb.LGBMRanker(objective="lambdarank", metric="ndcg", n_estimators=300, learning_rate=0.05,
        num_leaves=31, min_child_samples=30, subsample=0.8, colsample_bytree=0.8, random_state=0,
        n_jobs=2, verbose=-1, label_gain=[0, 1, 3, 7, 15])
    m.fit(dtr[feats], dtr["y"], group=grp(dtr), eval_set=[(dte[feats], dte["y"])],
          eval_group=[grp(dte)], eval_at=[10],
          categorical_feature=[c for c in CAT if c in feats])
    return m.best_score_["valid_0"]["ndcg@10"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="../scraper/results_serpapi.db")
    ap.add_argument("--language", default="IT")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--out", default="quality_adjusted_summary.csv")
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    df = pd.read_sql("SELECT * FROM products WHERE language = ?", con, params=(a.language,))
    con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
    print(f"rows {len(df):,} | SERPs {df['run_id'].nunique():,} | "
          f"rating coverage {df['rating'].notna().mean():.1%}")
    df["rel"] = rel_tfidf(df)
    df = build(df)

    rows = []
    for s in range(a.seeds):
        tr, te = _split(df, s)
        nA = _train(df, MERIT, tr, te)
        nQ = _train(df, MERIT + QUALITY, tr, te)
        nB = _train(df, MERIT + SELLER, tr, te)
        nC = _train(df, MERIT + QUALITY + SELLER, tr, te)
        rows.append((nA, nQ, nB, nC, nB - nA, nC - nQ, nQ - nA))
        print(f"seed {s}: lift unadj {nB-nA:+.3f} | lift quality-adj {nC-nQ:+.3f} "
              f"| quality lift {nQ-nA:+.3f}", flush=True)
    A = np.array(rows)
    summary = pd.DataFrame({
        "metric": ["NDCG merit", "NDCG +quality", "NDCG +seller", "NDCG +quality+seller",
                   "seller lift (unadjusted) mean", "seller lift (unadjusted) std",
                   "seller lift (quality-adjusted) mean", "seller lift (quality-adjusted) std",
                   "quality lift mean", "quality lift std"],
        "value": [A[:,0].mean(), A[:,1].mean(), A[:,2].mean(), A[:,3].mean(),
                  A[:,4].mean(), A[:,4].std(), A[:,5].mean(), A[:,5].std(),
                  A[:,6].mean(), A[:,6].std()],
        "n_seeds": a.seeds, "layer": f"organic_serpapi_{a.language}",
    })
    summary.round(4).to_csv(a.out, index=False, encoding="utf-8-sig")
    print(summary.round(4).to_string(index=False))
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
