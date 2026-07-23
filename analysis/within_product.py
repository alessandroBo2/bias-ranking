#!/usr/bin/env python
"""Within-product fixed-effects test on the SerpApi organic re-collection.

The cleanest identity test: the same product (product_id) offered by
different sellers across SERPs — does one seller obtain systematically
better positions once the product itself (brand, quality, popularity) is
held fixed by construction?

Design: keep products observed in >=2 offers with >=2 distinct sellers;
demean outcome and regressors within product_id (product fixed effects);
OLS on the demeaned data; cluster-robust SEs by product_id.

Usage:
    python within_product.py --db ../scraper/results_serpapi.db [--language IT]
"""
import argparse
import sqlite3

import numpy as np
import pandas as pd

REGRESSORS = ["log_price", "is_amazon", "is_giant", "seller_freq_log"]


def cluster_ols(X, y, clusters):
    """OLS beta + cluster-robust (CR0) standard errors."""
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    for g in np.unique(clusters):
        m = clusters == g
        Xg, eg = X[m], resid[m]
        s = Xg.T @ eg
        meat += np.outer(s, s)
    V = XtX_inv @ meat @ XtX_inv
    return beta, np.sqrt(np.diag(V))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="../scraper/results_serpapi.db")
    ap.add_argument("--language", default="IT")
    ap.add_argument("--out", default="within_product_results.csv")
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    df = pd.read_sql(
        "SELECT product_id, run_id, keyword, position, seller, price_value, rating, "
        "reviews_count FROM products WHERE language = ? AND product_id IS NOT NULL "
        "AND product_id != ''", con, params=(a.language,))
    con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0) & df["seller"].notna()]
    df["seller"] = df["seller"].str.strip().str.lower()

    # multi-seller products only
    g = df.groupby("product_id")["seller"].nunique()
    multi = g[g >= 2].index
    d = df[df["product_id"].isin(multi)].copy()
    print(f"offers {len(df):,} | products {df['product_id'].nunique():,} | "
          f"multi-seller products {len(multi):,} | offers in FE sample {len(d):,}")
    if len(d) < 100:
        raise SystemExit("FE sample too small — check product_id coverage")

    d["log_price"] = np.log1p(d["price_value"])
    freq = df["seller"].value_counts()
    d["is_amazon"] = d["seller"].str.contains("amazon", case=False).astype(float)
    d["is_giant"] = d["seller"].isin(freq.head(15).index).astype(float)
    d["seller_freq_log"] = np.log1p(d["seller"].map(freq).fillna(0))

    # product fixed effects via within-demeaning
    y = d["position"].astype(float)
    y = (y - d.groupby("product_id")["position"].transform("mean")).values
    X = np.column_stack([
        (d[c] - d.groupby("product_id")[c].transform("mean")).values for c in REGRESSORS])
    clusters = pd.factorize(d["product_id"])[0]

    beta, se = cluster_ols(X, y, clusters)
    res = pd.DataFrame({"regressor": REGRESSORS, "coef": beta, "se": se,
                        "t": beta / np.where(se == 0, np.nan, se)})
    res["n_offers"] = len(d)
    res["n_products"] = d["product_id"].nunique()
    res.round(4).to_csv(a.out, index=False, encoding="utf-8-sig")
    print(res.round(4).to_string(index=False))
    print(f"-> {a.out}")
    print("Reading: negative coef = the trait moves the offer UP the ranking "
          "(better position) for the SAME product; positive = pushed down.")


if __name__ == "__main__":
    main()
