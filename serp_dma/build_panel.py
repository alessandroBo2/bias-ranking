# -*- coding: utf-8 -*-
r"""Builds the balanced panel from the shared temporal shopping-unit data.

Primary mode (real data): one single Stata file with all waves
(`final_2023_24.dta`, one row per PLA plus a placeholder row per query
when no shopping unit was shown), processed in chunks:

    python build_panel.py --dta "<...>\shopping unit data\final_2023_24.dta" --out-dir panel

Legacy mode (one file per wave + external category file) is kept for
other data drops: --data-dir <dir> --queries <file>.

Outputs:
  - panel_offers.parquet   (all PLA offers, repo schema + `wave`)
  - panel_outcomes.csv     (per query x wave: queried, su_present, CSS outcomes)
  - attrition_report.csv   (queries per wave, balanced-panel count, offers)

Cleaning replicated from the authors, for comparability:
  - position <= 16
  - lowercase of cssname / merchantlink
Missing values arrive as the literal string 'NA' and are converted to NaN.
"""
import argparse
import glob
import os
import re

import numpy as np
import pandas as pd

# --- real schema of final_2023_24.dta -> repo schema ------------------------ #
DTA_MAPPING = {
    "query": "keyword",
    "category": "category_l1",
    "subcategory": "category_l2",
    "time": "run_id",
    "positioninsu": "position",
    "merchantlink": "seller",
    "merchantname": "seller_name",
    "cssname": "css_partner",
    "productname": "title",
    "price": "price_raw",
    "rating": "rating",
    "totalratings": "rating_count_raw",
    "totalplas": "total_plas",
    "d_su": "su_present",
    "d_css_pla": "d_css_pla",
}
GOOGLE_CSS_PATTERN = r"^google"          # after lowercasing
MAX_POSITION = 16                         # authors' cleaning
CHUNK = 500_000

PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:\.\d{1,2})?)")


def parse_price_series(s):
    """German-formatted price strings ('1.234,56', 'NA') -> float EUR."""
    s = s.astype(str).str.extract(PRICE_RE, expand=False)
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _clean_chunk(ch):
    ch = ch.rename(columns={k: v for k, v in DTA_MAPPING.items() if k in ch.columns})
    ch["wave"] = ch["year"].astype(str) + "w" + ch["week"].astype(str).str.zfill(2)
    for c in ("css_partner", "seller"):
        ch[c] = ch[c].replace("NA", np.nan)
        ch[c] = ch[c].str.strip().str.lower()
    ch["is_google_css"] = ch["css_partner"].fillna("").str.match(GOOGLE_CSS_PATTERN).astype(int)
    return ch


def build_from_single_dta(paths, out_dir):
    if isinstance(paths, str):
        paths = [paths]
    os.makedirs(out_dir, exist_ok=True)
    usecols = ["year", "week"] + list(DTA_MAPPING.keys())
    offers_parts, query_parts = [], []
    tot = 0
    for path in paths:
        print(f"-- file: {os.path.basename(path)}", flush=True)
        with pd.read_stata(path, columns=usecols, chunksize=CHUNK) as rdr:
            for i, ch in enumerate(rdr):
                tot += len(ch)
                ch = _clean_chunk(ch)
                # per-query presence (placeholder rows included)
                query_parts.append(ch.groupby(["wave", "keyword"], sort=False)
                                     .agg(su_present=("su_present", "max"),
                                          category_l1=("category_l1", "first"),
                                          category_l2=("category_l2", "first"))
                                     .reset_index())
                # offer rows: a PLA slot exists and passes the position cleaning
                off = ch[ch["position"].notna() & (ch["position"] <= MAX_POSITION)].copy()
                if len(off):
                    off["price_value"] = parse_price_series(off["price_raw"])
                    off["rating_count"] = pd.to_numeric(
                        off["rating_count_raw"].replace("NA", np.nan), errors="coerce")
                    off["title"] = off["title"].replace("NA", np.nan)
                    keep = ["wave", "run_id", "keyword", "category_l1", "category_l2",
                            "position", "title", "seller", "seller_name", "css_partner",
                            "is_google_css", "price_value", "rating", "rating_count",
                            "total_plas", "d_css_pla"]
                    offers_parts.append(off[keep])
                print(f"chunk {i + 1}: {tot:,} rows processed", flush=True)

    offers = pd.concat(offers_parts, ignore_index=True)
    # per-query presence may span chunk borders: re-aggregate
    queries = (pd.concat(query_parts, ignore_index=True)
                 .groupby(["wave", "keyword"], sort=False)
                 .agg(su_present=("su_present", "max"),
                      category_l1=("category_l1", "first"),
                      category_l2=("category_l2", "first"))
                 .reset_index())

    waves = sorted(queries["wave"].unique())
    per_wave_sets = {w: set(queries.loc[queries["wave"] == w, "keyword"]) for w in waves}
    in_all = set.intersection(*per_wave_sets.values())

    # outcomes per (query x wave) on the balanced panel
    q = queries[queries["keyword"].isin(in_all)].copy()
    off_b = offers[offers["keyword"].isin(in_all)]
    grp = off_b.sort_values("position").groupby(["wave", "keyword"], sort=False)
    oc = grp.agg(n_offers=("position", "size"),
                 google_css_share=("is_google_css", "mean"),
                 google_css_first_slot=("is_google_css", "first"),
                 rival_css_present=("is_google_css", lambda s: int((s == 0).any())),
                 n_css_partners=("css_partner", "nunique"),
                 median_price=("price_value", "median")).reset_index()
    out = q.merge(oc, on=["wave", "keyword"], how="left")
    zero = {"n_offers": 0, "google_css_share": np.nan, "google_css_first_slot": np.nan,
            "n_css_partners": 0, "rival_css_present": np.nan}
    out = out.fillna({k: v for k, v in zero.items() if not pd.isna(v)})

    rep = (queries.groupby("wave").agg(queries_in_wave=("keyword", "nunique"),
                                       su_share=("su_present", "mean")).reset_index())
    rep["queries_balanced_panel"] = len(in_all)
    rep = rep.merge(offers.groupby("wave").size().rename("offer_rows").reset_index(),
                    on="wave", how="left")

    offers.to_parquet(os.path.join(out_dir, "panel_offers.parquet"), index=False)
    out.to_csv(os.path.join(out_dir, "panel_outcomes.csv"), index=False, encoding="utf-8-sig")
    rep.to_csv(os.path.join(out_dir, "attrition_report.csv"), index=False)

    print(f"\nrows read {tot:,} | offer rows {len(offers):,} | waves: {waves}")
    print(f"balanced panel: {len(in_all):,} queries x {len(waves)} waves")
    print(rep.round(3).to_string(index=False))
    return out


# --------------------- legacy multi-file mode (unchanged core) -------------- #
LEGACY_MAPPING = {
    "cssname": "css_partner", "merchantlink": "seller", "merchant": "seller",
    "position": "position", "pos": "position", "query": "keyword",
    "keyword": "keyword", "time": "run_id", "timestamp": "run_id",
    "price": "price_value", "title": "title",
}


def load_wave_file(path):
    wave = os.path.splitext(os.path.basename(path))[0]
    df = pd.read_stata(path) if path.lower().endswith(".dta") else pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns={k: v for k, v in LEGACY_MAPPING.items() if k in df.columns})
    missing = [c for c in ("keyword", "position", "css_partner") if c not in df.columns]
    if missing:
        raise SystemExit(f"[{wave}] missing columns after mapping: {missing}\n"
                         f"available: {sorted(df.columns)}")
    df["css_partner"] = df["css_partner"].astype(str).str.strip().str.lower()
    if "seller" in df.columns:
        df["seller"] = df["seller"].astype(str).str.strip().str.lower()
    df["position"] = pd.to_numeric(df["position"], errors="coerce")
    df = df[df["position"].notna() & (df["position"] <= MAX_POSITION)]
    df["wave"] = wave
    df["is_google_css"] = df["css_partner"].str.match(GOOGLE_CSS_PATTERN).astype(int)
    return df.reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dta", nargs="+", help="one or more Stata wave files (real data drop)")
    ap.add_argument("--data-dir", help="legacy: one file per wave")
    ap.add_argument("--queries", help="legacy: external category file")
    ap.add_argument("--out-dir", default="panel")
    args = ap.parse_args()
    if args.dta:
        build_from_single_dta(args.dta, args.out_dir)
        return
    if not args.data_dir:
        raise SystemExit("pass --dta <file> or --data-dir <dir>")
    files = sorted(glob.glob(os.path.join(args.data_dir, "*.dta")) +
                   glob.glob(os.path.join(args.data_dir, "*.csv")))
    if args.queries:
        files = [f for f in files if os.path.abspath(f) != os.path.abspath(args.queries)]
    waves = [load_wave_file(f) for f in files]
    df = pd.concat(waves, ignore_index=True)
    os.makedirs(args.out_dir, exist_ok=True)
    df.to_parquet(os.path.join(args.out_dir, "panel_offers.parquet"), index=False)
    print(f"waves: {len(waves)} | offers {len(df):,} (legacy mode: outcomes not computed)")


if __name__ == "__main__":
    main()
