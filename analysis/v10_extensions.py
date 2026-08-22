#!/usr/bin/env python
"""New estimations required by the supervisor's v9 review (thesis v10).

Sections (each prints a tagged block and saves a CSV where useful):
  [A] Panel diagnostics: PV/PW by cohort x wave; event study vs CW4;
      switch-back counts; aggregate reconciliation of the DiD.
  [B] Clustered inference for lifts: per-page NDCG@10 differences between
      nested models, clustered by query; MDE (2.8 x SE). D3 seller lift,
      D2 seller lift, D2 CSS lift conditional AND unconditional.
  [C] Amazon: pooled OLS (composition) vs product+page FE (within) in
      positions; placebo sellers; connected-set size; matched comparison.
  [D] Enriched merit (token overlap, brand match, price rank within
      product) and the seller lift upper-bound check on D3.
  [E] D1 cross-country descriptive audit: per-market seller lift and
      Amazon attribution (IT/DE vs US non-DMA benchmark), FX-converted.
  [F] RQ1 benchmark: observed within-page seller HHI vs a permutation
      benchmark that preserves page sizes.

Run from analysis/:  python v10_extensions.py --out v10_results.txt
"""
import argparse
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PANEL = r"..\serp_dma\panel5"
D3DB = r"..\scraper\results_serpapi.db"
D2DB = r"..\results_serp_dma.db"
D1DB = r"..\results.db"
USD_EUR = 0.92  # collection-period average, May-June 2026


# ----------------------------- shared helpers ------------------------------ #
def gain_label(p):
    return 4 if p <= 2 else 3 if p <= 5 else 2 if p <= 10 else 1 if p <= 20 else 0


def base_features(df):
    df = df.copy()
    df["seller"] = df["seller"].fillna("").str.strip().str.lower()
    df["title"] = df["title"].fillna("")
    df["log_price"] = np.log1p(df["price_value"])
    df["title_len"] = df["title"].str.len()
    df["title_words"] = df["title"].str.split().apply(len)
    df["is_amazon"] = df["seller"].str.contains("amazon", case=False).astype(int)
    df["y"] = df["position"].apply(gain_label)
    for c in ("category_l1", "category_l2"):
        df[c] = df[c].astype("category")
    return df


def rel_fit(df, tr_idx):
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, max_features=20000)
    vec.fit(pd.concat([df["keyword"].iloc[tr_idx], df["title"].iloc[tr_idx]]))
    K, T = vec.transform(df["keyword"]), vec.transform(df["title"])
    kn = np.sqrt(np.asarray(K.multiply(K).sum(1)).ravel())
    tn = np.sqrt(np.asarray(T.multiply(T).sum(1)).ravel())
    return np.asarray(K.multiply(T).sum(1)).ravel() / np.where(kn * tn == 0, 1, kn * tn)


def train_score(df, feats, tr, te_index):
    """Train on rows tr; return predictions aligned to te_index (a pandas Index)."""
    import lightgbm as lgb
    grp = lambda d: d.groupby("run_id", sort=False).size().values
    dtr = df.iloc[tr].sort_values("run_id")
    m = lgb.LGBMRanker(objective="lambdarank", metric="ndcg", n_estimators=300,
        learning_rate=0.05, num_leaves=31, min_child_samples=30, subsample=0.8,
        colsample_bytree=0.8, random_state=0, n_jobs=2, verbose=-1,
        label_gain=[0, 1, 3, 7, 15])
    cats = [c for c in ("category_l1", "category_l2") if c in feats]
    m.fit(dtr[feats], dtr["y"], group=grp(dtr), categorical_feature=cats)
    return m.predict(df.loc[te_index, feats])


def perpage_ndcg(dte, col):
    from sklearn.metrics import ndcg_score
    out = {}
    for rid, g in dte.groupby("run_id", sort=False):
        if len(g) < 2:
            continue
        out[rid] = ndcg_score([g["y"].values], [g[col].values], k=10)
    return pd.Series(out)


def clustered_lift(df, feats_a, feats_b, seeds=5, label=""):
    """Per-page NDCG diff between nested models; SE clustered by query."""
    from sklearn.model_selection import GroupShuffleSplit
    diffs_all = []
    for s in range(seeds):
        tr, te = next(GroupShuffleSplit(1, test_size=0.3, random_state=s)
                      .split(df, groups=df["keyword"]))
        df["rel"] = rel_fit(df, tr)
        freq = df["seller"].iloc[tr].value_counts()
        df["seller_freq_log"] = np.log1p(df["seller"].map(freq).fillna(0))
        df["is_giant"] = df["seller"].isin(freq.head(15).index).astype(int)
        dte = df.iloc[te].sort_values("run_id").copy()
        dte["sa"] = train_score(df, feats_a, tr, dte.index)
        dte["sb"] = train_score(df, feats_b, tr, dte.index)
        na, nb = perpage_ndcg(dte, "sa"), perpage_ndcg(dte, "sb")
        d = (nb - na).dropna().rename("d").to_frame()
        d["keyword"] = dte.drop_duplicates("run_id").set_index("run_id")["keyword"]
        diffs_all.append(d)
    D = pd.concat(diffs_all)
    qm = D.groupby("keyword")["d"].mean()          # cluster at query level
    est, se = qm.mean(), qm.std(ddof=1) / np.sqrt(len(qm))
    t = est / se if se > 0 else np.nan
    mde = 2.8 * se
    print(f"  [{label}] lift {est:+.4f} | clustered SE {se:.4f} | t {t:+.2f} "
          f"| n_query {len(qm):,} | MDE(80%) {mde:.4f}")
    return est, se, t, mde


# =========================== [A] panel diagnostics ========================== #
def section_A():
    print("\n===== [A] PANEL DIAGNOSTICS =====")
    g = pd.read_csv(PANEL + r"\gsrp_panel.csv")
    waves = sorted(g["wave"].unique())
    piv = g.pivot_table(index="cohort", columns="wave", values="pv_present", aggfunc="mean")
    npiv = g.pivot_table(index="cohort", columns="wave", values="new_design", aggfunc="mean")
    cnt = g.drop_duplicates("keyword")["cohort"].value_counts()
    print("PV presence by cohort x wave:")
    print(piv.round(3).to_string())
    print("new-design share by cohort x wave:")
    print(npiv.round(3).to_string())
    print("cohort sizes:", dict(cnt))
    piv.round(4).to_csv("v10_pv_by_cohort_wave.csv", encoding="utf-8-sig")

    # switch-backs: new_design 1 -> 0 between consecutive waves
    wide = g.pivot_table(index="keyword", columns="wave", values="new_design", aggfunc="max")
    total_rev = 0
    for a, b in zip(waves[:-1], waves[1:]):
        rev = int(((wide[a] == 1) & (wide[b] == 0)).sum())
        total_rev += rev
        print(f"switch-back {a}->{b}: {rev:,} queries")
    ever = int((wide.max(axis=1) == 1).sum())
    print(f"total switch-back events {total_rev:,} | queries ever treated {ever:,}")
    # contamination of the CW6 'control' in CW5
    c6 = g[(g["cohort"] == "2024w06")].drop_duplicates("keyword")["keyword"]
    treated_in_cw5 = wide.loc[wide.index.isin(c6), "2024w05"].fillna(0)
    print(f"CW6 cohort showing new design in CW5 (should be 0 by construction): "
          f"{int(treated_in_cw5.sum())}")
    # aggregate reconciliation CW4->CW5 for PV
    d45 = {}
    for coh in piv.index:
        if "2024w04" in piv.columns and "2024w05" in piv.columns:
            w = cnt.get(coh, 0) / cnt.sum()
            d45[coh] = (piv.loc[coh, "2024w05"] - piv.loc[coh, "2024w04"], round(w, 3))
    print("Delta PV CW4->CW5 by cohort (delta, panel weight):")
    for k, v in d45.items():
        print(f"  {k}: {v[0]:+.3f} (w {v[1]})")
    agg = sum(v[0] * v[1] for v in d45.values() if not np.isnan(v[0]))
    print(f"  weighted sum = {agg:+.4f} (aggregate Table-2 delta should match)")


# ====================== [B] clustered inference for lifts =================== #
def load_d3():
    con = sqlite3.connect(D3DB)
    df = pd.read_sql("SELECT * FROM products WHERE language='IT'", con); con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
    return base_features(df)


def load_d2():
    con = sqlite3.connect(D2DB)
    df = pd.read_sql("SELECT * FROM serp_ads", con); con.close()
    df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
    df = base_features(df)
    df["is_google_css"] = df["css_partner"].fillna("").str.lower().str.match("^google").astype(int)
    return df


MERIT = ["log_price", "rel", "title_len", "title_words", "category_l1", "category_l2"]
SELLER = ["is_amazon", "is_giant", "seller_freq_log"]


def section_B(d3, d2):
    print("\n===== [B] CLUSTERED LIFT TESTS + MDE =====")
    clustered_lift(d3, MERIT, MERIT + SELLER, label="D3 seller lift")
    clustered_lift(d2, MERIT, MERIT + SELLER, label="D2 seller lift")
    clustered_lift(d2, MERIT + SELLER, MERIT + SELLER + ["is_google_css"],
                   label="D2 CSS lift conditional on seller")
    clustered_lift(d2, MERIT, MERIT + ["is_google_css"],
                   label="D2 CSS lift UNconditional")


# ============ [C] Amazon: pooled vs FE, placebos, connected set ============= #
def section_C(d3):
    print("\n===== [C] AMAZON: POOLED vs WITHIN, PLACEBOS =====")
    import statsmodels.api as sm
    d = d3[d3["product_id"].notna() & (d3["product_id"] != "")].copy()
    y = d["position"].astype(float)

    X0 = pd.DataFrame({"is_amazon": d["is_amazon"].astype(float), "const": 1.0})
    r0 = sm.OLS(y, X0).fit(cov_type="cluster", cov_kwds={"groups": d["keyword"]})
    print(f"pooled OLS (no controls): is_amazon {r0.params['is_amazon']:+.3f} "
          f"(SE {r0.bse['is_amazon']:.3f}) — composition effect, in positions")

    # product + page two-way FE via double demeaning (approximation, then exact on connected set)
    g = d.groupby("product_id")["seller"].nunique()
    multi = g[g >= 2].index
    dd = d[d["product_id"].isin(multi)].copy()
    print(f"multi-seller sample: {len(dd):,} offers, {len(multi):,} products")
    # connected set of product-page bipartite graph
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    pid = pd.factorize(dd["product_id"])[0]
    rid = pd.factorize(dd["run_id"])[0] + pid.max() + 1
    n = rid.max() + 1
    m = sp.coo_matrix((np.ones(len(dd)), (pid, rid)), shape=(n, n))
    ncomp, lab = connected_components(m + m.T, directed=False)
    comp_of_rows = lab[pid]
    biggest = pd.Series(comp_of_rows).value_counts()
    print(f"two-way FE connected components: {ncomp:,}; largest holds "
          f"{biggest.iloc[0]:,} offers ({biggest.iloc[0]/len(dd):.1%} of the FE sample)")

    def within_coef(dd, col):
        w = dd.copy()
        w["x"] = w[col].astype(float)
        for _ in range(3):  # alternating demeaning approximates two-way FE
            for k in ("product_id", "run_id"):
                for v in ("position", "x", "log_price"):
                    w[v] = w[v] - w.groupby(k)[v].transform("mean")
        X = sm.add_constant(w[["x", "log_price"]])
        r = sm.OLS(w["position"].astype(float), X).fit(
            cov_type="cluster", cov_kwds={"groups": dd["product_id"]})
        return r.params["x"], r.bse["x"]

    dd["position"] = d3.loc[dd.index, "position"].astype(float)
    dd["log_price"] = d3.loc[dd.index, "log_price"].astype(float)
    c, s = within_coef(dd, "is_amazon")
    print(f"product+page FE: is_amazon {c:+.3f} (SE {s:.3f}) — within effect, in positions")

    print("placebo sellers (same specification):")
    rows = [("is_amazon", c, s)]
    for name, pat in [("ebay", "ebay"), ("mediaworld", "mediaworld"),
                      ("unieuro", "unieuro"), ("zalando", "zalando"),
                      ("eprice", "eprice"), ("leroymerlin", "leroy")]:
        dd[f"is_{name}"] = dd["seller"].str.contains(pat, case=False).astype(int)
        if dd[f"is_{name}"].sum() < 200:
            print(f"  is_{name}: <200 offerte, saltato"); continue
        cc, ss = within_coef(dd, f"is_{name}")
        rows.append((f"is_{name}", cc, ss))
        print(f"  is_{name}: {cc:+.3f} (SE {ss:.3f}) | offers {dd[f'is_{name}'].sum():,}")
    pd.DataFrame(rows, columns=["seller", "coef", "se"]).round(4) \
        .to_csv("v10_placebo_sellers.csv", index=False, encoding="utf-8-sig")

    # matched within-product comparison: same product, price within ±10%, rating ±0.3
    dd2 = d[d["product_id"].isin(multi)].copy()
    dd2["rating"] = pd.to_numeric(dd2["rating"], errors="coerce")
    matched = []
    for _, gp in dd2.groupby("product_id"):
        am = gp[gp["is_amazon"] == 1]; riv = gp[gp["is_amazon"] == 0]
        for _, a in am.iterrows():
            m = riv[(abs(riv["price_value"] - a["price_value"]) <= 0.10 * a["price_value"])]
            if a["rating"] == a["rating"]:
                m = m[(m["rating"].isna()) | (abs(m["rating"] - a["rating"]) <= 0.3)]
            if len(m):
                matched.append(a["position"] - m["position"].mean())
    marr = pd.Series(matched)
    print(f"matched pairs (price ±10%, rating ±0.3): n={len(marr):,} | "
          f"mean Amazon-minus-rival position {marr.mean():+.2f} | SE {marr.std()/np.sqrt(len(marr)):.2f}")


# ==================== [D] enriched merit upper-bound check ================== #
def section_D(d3):
    print("\n===== [D] ENRICHED MERIT (upper-bound check) =====")
    d = d3.copy()
    qtok = d["keyword"].str.lower().str.split().apply(set)
    ttok = d["title"].str.lower().str.split().apply(set)
    d["tok_overlap"] = [len(a & b) / max(len(a), 1) for a, b in zip(qtok, ttok)]
    first = d["title"].str.split().str[0].str.lower()
    d["brand_match"] = [1 if f and f in q else 0 for f, q in zip(first, d["keyword"].str.lower())]
    d["price_rank_prod"] = d.groupby("product_id")["price_value"].rank(pct=True).fillna(0.5)
    ENR = MERIT + ["tok_overlap", "brand_match", "price_rank_prod"]
    clustered_lift(d, ENR, ENR + SELLER, label="D3 seller lift, ENRICHED merit")


# ===================== [E] D1 cross-country descriptive ===================== #
def section_E():
    print("\n===== [E] D1 CROSS-COUNTRY (US = non-DMA benchmark; descriptive) =====")
    con = sqlite3.connect(D1DB)
    for mk in ("IT", "DE", "EN"):
        df = pd.read_sql("SELECT * FROM products WHERE language=?", con, params=(mk,))
        df = df[df["price_value"].notna() & (df["price_value"] > 0)].reset_index(drop=True)
        if mk == "EN":
            df["price_value"] = df["price_value"] * USD_EUR
        df = base_features(df)
        est, se, t, _ = clustered_lift(df, MERIT, MERIT + SELLER, seeds=5,
                                       label=f"D1 seller lift {mk}")
        amz = df["is_amazon"].mean()
        top1 = df[df["position"] <= 3]["is_amazon"].mean()
        print(f"    {mk}: Amazon share of offers {amz:.3f} | of top-3 slots {top1:.3f} "
              f"| offers {len(df):,}")
    con.close()


# ========================= [F] RQ1 permutation benchmark ==================== #
def section_F(d3):
    print("\n===== [F] RQ1: OBSERVED vs PERMUTATION BENCHMARK =====")
    def page_hhi(d):
        return d.groupby("run_id")["seller"].apply(
            lambda s: ((s.value_counts() / len(s)) ** 2).sum())
    obs = page_hhi(d3)
    rng = np.random.default_rng(0)
    perm = d3.copy()
    perm["seller"] = rng.permutation(perm["seller"].values)
    bench = page_hhi(perm)
    print(f"observed mean page HHI {obs.mean():.4f} | permutation benchmark {bench.mean():.4f} "
          f"| ratio {obs.mean()/bench.mean():.2f}")
    print(f"share of pages with HHI > 0.25: observed {(obs>0.25).mean():.3f} "
          f"| benchmark {(bench>0.25).mean():.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", default="ABCDEF")
    a = ap.parse_args()
    d3 = load_d3() if any(c in a.sections for c in "BCDF") else None
    d2 = load_d2() if "B" in a.sections else None
    if "A" in a.sections: section_A()
    if "B" in a.sections: section_B(d3, d2)
    if "C" in a.sections: section_C(d3)
    if "D" in a.sections: section_D(d3)
    if "E" in a.sections: section_E()
    if "F" in a.sections: section_F(d3)
    print("\nDONE")


if __name__ == "__main__":
    main()
