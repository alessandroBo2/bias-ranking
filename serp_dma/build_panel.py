# -*- coding: utf-8 -*-
r"""Builds the balanced panel from the shared temporal runs (Paul's format).

Input:  a folder with one file per wave (Stata .dta or .csv) at the
        offer/PLA level, plus `queries_for_merge.dta` with the categories.
Output: - panel_offers.parquet   (all offers, serp_ads schema + `wave` column)
        - panel_outcomes.csv     (outcomes per query x wave, computable in both regimes)
        - attrition_report.csv   (queries per wave, unmerged rows, balanced panel)

Cleaning replicated from the authors' for comparability:
  - position <= 16
  - lowercase of cssname / merchantlink

Usage:
    python build_panel.py --data-dir <.dta folder> --queries queries_for_merge.dta \
        --out-dir panel/ [--query-key query] [--time-key time]

The schema of the source files is mapped onto the repo's in SCHEMA_MAPPING
(see SCHEMA_MAPPING.md); if an expected column is missing, the script lists the
available columns instead of failing silently.
"""
import argparse
import glob
import os
import re
import sys

import pandas as pd

# --- Paul -> repo schema map (update here after inspecting the files) ------- #
SCHEMA_MAPPING = {
    "cssname": "css_partner",
    "merchantlink": "seller",
    "merchant": "seller",
    "position": "position",
    "pos": "position",
    "query": "keyword",
    "keyword": "keyword",
    "time": "run_id",
    "timestamp": "run_id",
    "price": "price_value",
    "title": "title",
}
GOOGLE_CSS_PATTERN = r"^google"          # after lowercasing
MAX_POSITION = 16                         # the authors' cleaning
NEW_ELEMENT_COLUMNS = ["unit_variant", "element", "unittype", "unit_type"]  # candidates


def load_wave(path, query_key, time_key):
    wave = os.path.splitext(os.path.basename(path))[0]
    df = pd.read_stata(path) if path.lower().endswith(".dta") else pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    rename = {src: dst for src, dst in SCHEMA_MAPPING.items() if src in df.columns}
    df = df.rename(columns=rename)
    missing = [c for c in ("keyword", "position", "css_partner") if c not in df.columns]
    if missing:
        raise SystemExit(
            f"[{wave}] required columns missing after the mapping: {missing}\n"
            f"available columns: {sorted(df.columns)}\n"
            f"-> update SCHEMA_MAPPING in build_panel.py"
        )
    # cleaning replicated from the authors
    df["css_partner"] = df["css_partner"].astype(str).str.strip().str.lower()
    if "seller" in df.columns:
        df["seller"] = df["seller"].astype(str).str.strip().str.lower()
    df["position"] = pd.to_numeric(df["position"], errors="coerce")
    df = df[df["position"].notna() & (df["position"] <= MAX_POSITION)]
    df["wave"] = wave
    df["is_google_css"] = df["css_partner"].str.match(GOOGLE_CSS_PATTERN).astype(int)
    # unit variant (only exists in the post-redesign runs)
    unit_col = next((c for c in NEW_ELEMENT_COLUMNS if c in df.columns), None)
    df["unit_variant"] = df[unit_col].astype(str).str.lower() if unit_col else pd.NA
    return df.reset_index(drop=True)


def outcomes(df):
    """Outcomes per (wave, keyword), defined so they are computable in both regimes."""
    rows = []
    for (wave, kw), g in df.groupby(["wave", "keyword"], sort=False):
        first = g.loc[g["position"].idxmin()] if len(g) else None
        rows.append({
            "wave": wave,
            "keyword": kw,
            "n_offers": len(g),
            "google_css_share": g["is_google_css"].mean(),
            "google_css_first_slot": int(first["is_google_css"]) if first is not None else pd.NA,
            "rival_css_present": int((g["is_google_css"] == 0).any()),
            "n_css_partners": g["css_partner"].nunique(),
            # metrics of the new element: only defined where the variant exists
            "new_element_present": (
                int(g["unit_variant"].str.contains(r"pla.group|cu.container|new", na=False).any())
                if g["unit_variant"].notna().any() else pd.NA
            ),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--queries", required=True, help="queries_for_merge.dta (categories)")
    ap.add_argument("--out-dir", default="panel")
    ap.add_argument("--query-key", default="keyword", help="query key in the categories file")
    ap.add_argument("--time-key", default="run_id")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(args.data_dir, "*.dta")) +
                   glob.glob(os.path.join(args.data_dir, "*.csv")))
    files = [f for f in files if os.path.abspath(f) != os.path.abspath(args.queries)]
    if not files:
        raise SystemExit(f"no wave file in {args.data_dir}")
    waves = [load_wave(f, args.query_key, args.time_key) for f in files]
    df = pd.concat(waves, ignore_index=True)

    # category merge + report of unmerged rows (never silenced)
    q = pd.read_stata(args.queries) if args.queries.lower().endswith(".dta") else pd.read_csv(args.queries)
    q.columns = [c.strip().lower() for c in q.columns]
    qkey = args.query_key if args.query_key in q.columns else "query" if "query" in q.columns else None
    if qkey is None:
        raise SystemExit(f"query key not found in {args.queries}; columns: {sorted(q.columns)}")
    catcols = [c for c in q.columns if re.search("categ|subcat", c)] or [c for c in q.columns if c != qkey]
    df = df.merge(q[[qkey] + catcols].drop_duplicates(qkey),
                  left_on="keyword", right_on=qkey, how="left", indicator=True)
    unmerged = df[df["_merge"] == "left_only"]
    df = df.drop(columns="_merge")

    # balanced panel: queries present in ALL the waves
    per_wave = df.groupby("wave")["keyword"].nunique()
    in_all = set.intersection(*[set(w["keyword"].unique()) for w in waves])
    balanced = df[df["keyword"].isin(in_all)]

    # attrition report
    rep = per_wave.rename("queries_in_wave").reset_index()
    rep["queries_balanced_panel"] = len(in_all)
    rep = rep.merge(unmerged.groupby("wave").size().rename("unmerged_rows").reset_index(),
                    on="wave", how="left").fillna({"unmerged_rows": 0})
    rep.to_csv(os.path.join(args.out_dir, "attrition_report.csv"), index=False)

    balanced.to_parquet(os.path.join(args.out_dir, "panel_offers.parquet"), index=False)
    outcomes(balanced).to_csv(os.path.join(args.out_dir, "panel_outcomes.csv"), index=False)

    print(f"waves: {len(waves)} | total offers {len(df):,} | balanced panel: "
          f"{len(in_all)} queries x {len(waves)} waves = {len(balanced):,} offers")
    print(f"rows without a category (unmerged): {len(unmerged):,} "
          f"({len(unmerged) / max(len(df), 1):.2%}) — details in attrition_report.csv")
    print(rep.to_string(index=False))


if __name__ == "__main__":
    main()
