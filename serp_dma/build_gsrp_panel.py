# -*- coding: utf-8 -*-
r"""Builds the page-level (GSRP) panel from the authors' googledata files.

One row per executed query per wave, with the page-design flag and the
element-visibility outcomes the prominence analysis needs:

  - new_design       : d_design != 'Shopping' (the post-DMA page layout)
  - pv_present/first : Google's Product Viewer element (small or large)
  - pw_present/first : the Product Websites box (the rival-CSS surface)
  - su_top           : classic Shopping Unit at the top of the page
  - css_top10/3/1    : rival-CSS links in the organic top-k
  - rollout cohort   : first wave in which the query shows the new design

Usage:
    python build_gsrp_panel.py --gsrp-dir "<...>\gsrp data" --out-dir panel
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gsrp-dir", required=True)
    ap.add_argument("--out-dir", default="panel")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    qmap = pd.read_stata(os.path.join(a.gsrp_dir, "queries_for_merge.dta"),
                         columns=["time", "query", "category", "subcategory"])
    qmap = qmap.drop_duplicates("time")

    parts = []
    for f in sorted(glob.glob(os.path.join(a.gsrp_dir, "googledata_*.dta"))):
        df = pd.read_stata(f)
        df["wave"] = df["year"].astype(int).astype(str) + "w" + \
                     df["week"].astype(int).astype(str).str.zfill(2)
        df = df.merge(qmap, on="time", how="left")
        unmerged = df["query"].isna().sum()
        print(f"{os.path.basename(f)}: {len(df):,} rows | wave {df['wave'].iloc[0]} "
              f"| unmerged {unmerged:,} ({unmerged / len(df):.2%})", flush=True)
        df = df[df["query"].notna()]
        pv = df["n_product_viewer_small"].fillna(0) + df["n_product_viewer_large"].fillna(0)
        out = pd.DataFrame({
            "wave": df["wave"],
            "keyword": df["query"],
            "category_l1": df["category"],
            "category_l2": df["subcategory"],
            "new_design": (df["d_design"].astype(str).str.strip().str.lower() != "shopping").astype(int),
            "su_top": df["d_su_top"].fillna(0).astype(int),
            "pv_present": (pv > 0).astype(int),
            "pw_present": (df["n_product_websites"].fillna(0) > 0).astype(int),
            "pv_first": (df["first_product_viewer"] == 1).astype(int),
            "pw_first": (df["first_product_websites"] == 1).astype(int),
            "css_top10": df["n_css_top_10"].fillna(0),
            "css_top3": df["n_css_top_3"].fillna(0),
            "css_top1": df["n_css_top_1"].fillna(0),
            "css_organic": df["n_css_organic"].fillna(0),
        })
        # one row per query x wave (rare duplicate crawls: keep the first)
        parts.append(out.drop_duplicates(["wave", "keyword"]))

    g = pd.concat(parts, ignore_index=True)
    waves = sorted(g["wave"].unique())
    # rollout cohort: first wave with the new design (2023 wave is all-old by construction)
    treated = g[g["new_design"] == 1].groupby("keyword")["wave"].min().rename("cohort")
    g = g.merge(treated, on="keyword", how="left")
    g["cohort"] = g["cohort"].fillna("never")

    g.to_csv(os.path.join(a.out_dir, "gsrp_panel.csv"), index=False, encoding="utf-8-sig")
    print(f"\nwaves: {waves} | queries: {g['keyword'].nunique():,} | rows: {len(g):,}")
    print("\nnew-design share per wave:")
    print(g.groupby("wave")["new_design"].mean().round(3).to_string())
    print("\ncohort sizes:")
    print(g.drop_duplicates("keyword")["cohort"].value_counts().to_string())


if __name__ == "__main__":
    main()
