# -*- coding: utf-8 -*-
r"""Two-wave pre/post DMA comparison on common queries.

Pre  wave: 2023w24 (authors' shopping-unit data, `panel_outcomes.csv`
           from build_panel.py --dta final_2023_24.dta)
Post wave: 2024w14 (3 April 2024, our parsed sample, `serp_ads` table)

The comparison is restricted to the CLASSIC shopping unit (the object the
2023 data observes) and to positions <= 16, replicating the authors'
cleaning, so both waves measure the same construct. Outcomes per query:
su_present, google_css_share, google_css_first_slot, rival_css_present,
n_css_partners.

Caveat (documented, unavoidable until the authors' 2024 waves arrive):
the two waves come from different collection instruments (authors' crawler
vs our parser). Both observe the same rendered objects (PLA slots and the
"Von ..." CSS label), and the within-query design removes query-level
composition, but instrument effects cannot be excluded; the same pipeline
re-runs unchanged on the authors' 2024 files when available.

Usage:
    python prepost_2023_2024.py --panel panel/panel_outcomes.csv \
        --db ../results_serp_dma.db --out-dir panel
"""
import argparse
import os
import sqlite3

import numpy as np
import pandas as pd

MAX_POSITION = 16
OUTCOMES = ["su_present", "google_css_share", "google_css_first_slot",
            "rival_css_present", "n_css_partners"]


def outcomes_2024_from_serp_ads(db_path):
    con = sqlite3.connect(db_path)
    try:
        ads = pd.read_sql("SELECT run_id, keyword, position, css_partner, unit_variant, "
                          "su_google FROM serp_ads", con)
    finally:
        con.close()
    ads["css_partner"] = ads["css_partner"].str.strip().str.lower()
    ads["is_google_css"] = ads["css_partner"].fillna("").str.match(r"^google").astype(int)
    # page-level SU presence comes from the crawl overview flag (validated vs containers)
    su = ads.groupby("keyword")["su_google"].max().rename("su_present")
    # classic unit only, authors' position cleaning
    cl = ads[(ads["unit_variant"] == "top") & (ads["position"] <= MAX_POSITION)]
    grp = cl.sort_values("position").groupby("keyword", sort=False)
    oc = grp.agg(google_css_share=("is_google_css", "mean"),
                 google_css_first_slot=("is_google_css", "first"),
                 rival_css_present=("is_google_css", lambda s: int((s == 0).any())),
                 n_css_partners=("css_partner", "nunique")).reset_index()
    out = su.reset_index().merge(oc, on="keyword", how="left")
    out["wave"] = "2024w14"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--panel", default="panel/panel_outcomes.csv")
    ap.add_argument("--db", default="../results_serp_dma.db")
    ap.add_argument("--out-dir", default="panel")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    pre = pd.read_csv(a.panel)
    pre = pre[pre["wave"] == "2023w24"]
    post = outcomes_2024_from_serp_ads(a.db)

    common = sorted(set(pre["keyword"]) & set(post["keyword"]))
    print(f"query 2023: {pre['keyword'].nunique():,} | query 2024 (sample): "
          f"{post['keyword'].nunique():,} | common: {len(common):,}")
    if not common:
        raise SystemExit("no common queries — check keyword normalisation")

    p1 = pre[pre["keyword"].isin(common)].set_index("keyword")
    p2 = post[post["keyword"].isin(common)].set_index("keyword")

    rows = []
    for oc in OUTCOMES:
        a1, a2 = p1[oc].astype(float), p2[oc].astype(float)
        both = pd.concat([a1.rename("pre"), a2.rename("post")], axis=1).dropna()
        d = both["post"] - both["pre"]
        se = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else np.nan
        rows.append(dict(outcome=oc, n_queries=len(both),
                         pre_mean=both["pre"].mean(), post_mean=both["post"].mean(),
                         diff_mean=d.mean(), diff_se=se,
                         t_stat=(d.mean() / se) if se and se > 0 else np.nan))
    res = pd.DataFrame(rows).round(4)
    res.to_csv(os.path.join(a.out_dir, "prepost_2023w24_2024w14.csv"),
               index=False, encoding="utf-8-sig")
    print(res.to_string(index=False))
    print(f"-> {os.path.join(a.out_dir, 'prepost_2023w24_2024w14.csv')}")


if __name__ == "__main__":
    main()
