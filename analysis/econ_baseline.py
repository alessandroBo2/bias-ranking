#!/usr/bin/env python
"""Econometric baseline vs learning-to-rank under the leakage-safe protocol.

Head-to-head comparison of an OLS rank regression and the LambdaMART
ranker with three fairness rules: same data, same query-held-out 70/30
splits, same evaluator (scikit-learn mean per-SERP NDCG@10 on unseen
queries). All data-dependent transformations — TF-IDF vocabulary,
seller-frequency counts, the top-seller dummy list — are fitted on the
training partition only and applied to the held-out queries (an unseen
seller gets zero frequency and no dummy), matching the thesis's
validation protocol (Section 5.4).

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
GIANTS = 15


def load(source, db):
    con = sqlite3.connect(db)
    if source == "organic":
        df = pd.read_sql("SELECT * FROM products WHERE language='IT'", con)
    else:
        df = pd.read_sql("SELECT * FROM serp_ads", con)
    con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
    df["seller"] = df["seller"].fillna("").str.strip().str.lower()
    df["title"] = df["title"].fillna("")
    t = df["title"]
    df["log_price"] = np.log1p(df["price_value"])
    df["title_len"] = t.str.len()
    df["title_words"] = t.str.split().apply(len)
    if source == "sponsored":
        df["is_google_css"] = df["css_partner"].fillna("").str.lower().str.match("^google").astype(int)
        df["new_element"] = (df["unit_variant"] == "top_pla_group").astype(int)
    df["is_amazon"] = df["seller"].str.contains("amazon", case=False).astype(int)
    df["y"] = df["position"].apply(lambda p: 4 if p <= 2 else 3 if p <= 5 else 2 if p <= 10 else 1 if p <= 20 else 0)
    return df


def rel_train_only(df, tr_idx):
    """TF-IDF fitted on the training partition only; applied to all rows."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, max_features=20000)
    tr_texts = pd.concat([df["keyword"].iloc[tr_idx], df["title"].iloc[tr_idx]])
    vec.fit(tr_texts)
    K = vec.transform(df["keyword"])
    T = vec.transform(df["title"])
    kn = np.sqrt(np.asarray(K.multiply(K).sum(1)).ravel())
    tn = np.sqrt(np.asarray(T.multiply(T).sum(1)).ravel())
    return np.asarray(K.multiply(T).sum(1)).ravel() / np.where(kn * tn == 0, 1, kn * tn)


def seller_stats_train_only(df, tr_idx):
    freq = df["seller"].iloc[tr_idx].value_counts()
    sf = np.log1p(df["seller"].map(freq).fillna(0))
    top = [s for s in freq.head(TOP_SELLERS).index if s]
    return sf, top


def design_matrix(df, source, top_sellers):
    X = pd.DataFrame(index=df.index)
    for c in ("log_price", "rel", "title_len", "title_words", "seller_freq_log"):
        X[c] = df[c]
    X = pd.concat([X, pd.get_dummies(df["category_l1"], prefix="cat", dtype=float)], axis=1)
    for s in top_sellers:
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["organic", "sponsored"], required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--seeds", type=int, default=5)
    a = ap.parse_args()

    df = load(a.source, a.db)
    for c in ("category_l1", "category_l2"):
        df[c] = df[c].astype("category")
    print(f"[{a.source}] rows {len(df):,} | SERPs {df['run_id'].nunique():,} | "
          f"queries {df['keyword'].nunique():,}")

    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.linear_model import LinearRegression
    import lightgbm as lgb

    feats_ltr = ["log_price", "rel", "title_len", "title_words", "category_l1", "category_l2",
                 "is_amazon", "seller_freq_log"] + (["is_google_css"] if a.source == "sponsored" else [])

    rows = []
    for s in range(a.seeds):
        # query-held-out split: all pages of a keyword on one side
        tr, te = next(GroupShuffleSplit(1, test_size=0.3, random_state=s)
                      .split(df, groups=df["keyword"]))
        df["rel"] = rel_train_only(df, tr)
        df["seller_freq_log"], top = seller_stats_train_only(df, tr)

        X = design_matrix(df, a.source, top)
        ols = LinearRegression().fit(X.iloc[tr], df["position"].iloc[tr].astype(float))
        dte = df.iloc[te].sort_values("run_id").copy()
        dte["score_ols"] = -ols.predict(X.iloc[te].loc[dte.index])

        grp = lambda d: d.groupby("run_id", sort=False).size().values
        dtr = df.iloc[tr].sort_values("run_id")
        m = lgb.LGBMRanker(objective="lambdarank", metric="ndcg", n_estimators=300,
            learning_rate=0.05, num_leaves=31, min_child_samples=30, subsample=0.8,
            colsample_bytree=0.8, random_state=0, n_jobs=2, verbose=-1,
            label_gain=[0, 1, 3, 7, 15])
        m.fit(dtr[feats_ltr], dtr["y"], group=grp(dtr),
              categorical_feature=["category_l1", "category_l2"])
        dte["score_ltr"] = m.predict(dte[feats_ltr])

        n_ols, n_ltr = ndcg_eval(dte, "score_ols"), ndcg_eval(dte, "score_ltr")
        rows.append((n_ols, n_ltr, n_ltr - n_ols))
        print(f"seed {s}: NDCG@10 OLS {n_ols:.3f} | LTR {n_ltr:.3f} | gap {n_ltr-n_ols:+.3f}",
              flush=True)
    A = np.array(rows)
    print(f"\n{a.seeds} seeds | OLS {A[:,0].mean():.3f}±{A[:,0].std():.3f} | "
          f"LTR {A[:,1].mean():.3f}±{A[:,1].std():.3f} | gap {A[:,2].mean():+.3f}±{A[:,2].std():.3f}")

    # inference table on the full sample (interpretation, not prediction)
    try:
        import statsmodels.api as sm
        df["rel"] = rel_train_only(df, np.arange(len(df)))
        df["seller_freq_log"], top = seller_stats_train_only(df, np.arange(len(df)))
        X = design_matrix(df, a.source, top)
        res = sm.OLS(df["position"].astype(float), X).fit(cov_type="HC3")
        keep = (["is_google_css"] if a.source == "sponsored" else []) + \
               [c for c in X.columns if c.startswith("s_amazon")] + ["log_price", "rel"]
        tab = pd.DataFrame({"coef": res.params[keep], "se": res.bse[keep],
                            "t": res.tvalues[keep]}).round(4)
        print("\nOLS coefficients (position; HC3):"); print(tab.to_string())
        if a.source == "sponsored":
            X2 = X.copy(); X2["gcss_x_new"] = df["is_google_css"] * df["new_element"]
            r2 = sm.OLS(df["position"].astype(float), X2).fit(cov_type="HC3")
            het = pd.DataFrame({"coef": r2.params[["is_google_css", "gcss_x_new"]],
                                "se": r2.bse[["is_google_css", "gcss_x_new"]],
                                "t": r2.tvalues[["is_google_css", "gcss_x_new"]]}).round(4)
            print("\nHeterogeneity check (Google-CSS x new element):"); print(het.to_string())
        tab.to_csv(f"econ_baseline_{a.source}_coefs.csv", encoding="utf-8-sig")
    except ImportError:
        print("statsmodels not installed - coefficient table skipped")
    pd.DataFrame({"metric": ["NDCG OLS mean", "NDCG OLS std", "NDCG LTR mean", "NDCG LTR std",
                             "gap mean", "gap std"],
                  "value": [A[:,0].mean(), A[:,0].std(), A[:,1].mean(), A[:,1].std(),
                            A[:,2].mean(), A[:,2].std()],
                  "source": a.source, "n_seeds": a.seeds, "protocol": "query-held-out, train-only transforms"}) \
        .round(4).to_csv(f"econ_baseline_{a.source}_ndcg.csv", index=False, encoding="utf-8-sig")
    print(f"-> econ_baseline_{a.source}_ndcg.csv / _coefs.csv")


if __name__ == "__main__":
    main()
