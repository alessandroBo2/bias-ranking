# -*- coding: utf-8 -*-
r"""Extracts the shopping offers (PLAs) from Google SERPs saved as HTML.

Input:  a folder of SERPs `<timestamp>_google.html` (DMA-paper-style crawl)
        + a folder of overview files `*_queries.xlsx` (per-query flags).
Output: `serp_ads` table in a SQLite database (+ optional parquet/csv),
        with column names compatible with the repo's `products` table
        (keyword, title, price_value, seller, position, category_l1/l2,
        run_id, language) plus the columns specific to the sponsored layer
        (css_partner, unit_variant, sponsored_unit).

Usage:
    python parse_serp_ads.py --html-dir "...\raw html files" \
        --overview-dir "...\overview query files" \
        --db results_serp_dma.db [--parquet serp_ads.parquet] [--limit 50]
"""
import argparse
import glob
import os
import re
import sqlite3

import pandas as pd
from bs4 import BeautifulSoup


def parse_price(txt):
    """'1.234,56 €' -> 1234.56 (German format)."""
    if not txt:
        return None
    m = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2})", txt)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def unit_variant(el):
    """Distinguishes the classic shopping unit ('top'/'rhs', class commercial-unit-*)
    from the new post-DMA element ('top_pla_group', class top-pla-group/cu-container)."""
    for anc in el.parents:
        if not anc.name:
            continue
        cls = " ".join(anc.get("class", []))
        if "commercial-unit" in cls:
            if "top" in cls:
                return "top"
            if "rhs" in cls:
                return "rhs"
            return "commercial-other"
    return "top_pla_group"


def parse_serp(path):
    ts = os.path.basename(path).replace("_google.html", "")
    with open(path, encoding="utf-8", errors="replace") as fh:
        soup = BeautifulSoup(fh.read(), "lxml")
    rows, pos = [], 0
    for u in soup.select(".pla-unit"):
        cont = u.select_one(".pla-unit-container")
        if cont is None:  # wrapper without content (hovercard etc.)
            continue
        pos += 1
        title_el = cont.select_one(".pla-unit-title")
        price_el = cont.select_one("span.e10twf")
        merch_el = cont.select_one(".LbUacb span[aria-label]")
        merchant = None
        if merch_el:
            merchant = merch_el["aria-label"].removeprefix("Von ").strip()
        elif cont.select_one(".LbUacb"):
            merchant = cont.select_one(".LbUacb").get_text(strip=True)
        shipping = rating_count = css = None
        ext = cont.select_one(".pla-extensions-container")
        if ext:
            ship_el = ext.select_one(".mxB4Q .T4OwTb")
            shipping = ship_el.get_text(strip=True) if ship_el else None
            r_el = ext.select_one(".QhqGkb")
            if r_el:
                m = re.search(r"([\d.]+)", r_el.get_text())
                rating_count = int(m.group(1).replace(".", "")) if m else None
            css_el = ext.select_one(".azW0ve")
            if css_el:
                css = css_el.get_text(strip=True).removeprefix("Von ").strip()
        price_txt = price_el.get_text(strip=True) if price_el else None
        variant = unit_variant(u)
        rows.append(dict(
            run_id=ts, position=pos,
            title=title_el.get_text(" ", strip=True) if title_el else None,
            price_value=parse_price(price_txt), currency="EUR",
            seller=merchant, shipping_text=shipping, rating_count=rating_count,
            css_partner=css, unit_variant=variant,
            sponsored_unit=int(variant in ("top", "rhs", "commercial-other")),
        ))
    return rows


def load_overview(overview_dir):
    files = sorted(glob.glob(os.path.join(overview_dir, "*.xlsx")))
    ov = pd.concat((pd.read_excel(f) for f in files), ignore_index=True)
    ov = ov.rename(columns={"query": "keyword", "category": "category_l1",
                            "subcategory": "category_l2"})
    return ov[["time", "keyword", "query_original", "category_l1", "category_l2",
               "su_google", "blocked", "servererror"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--html-dir", required=True)
    ap.add_argument("--overview-dir", required=True)
    ap.add_argument("--db", default="results_serp_dma.db")
    ap.add_argument("--parquet", default=None)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--limit", type=int, default=None, help="only the first N html files (test)")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.html_dir, "*_google.html")))
    if args.limit:
        files = files[: args.limit]
    rows = []
    for i, f in enumerate(files):
        rows.extend(parse_serp(f))
        if (i + 1) % 100 == 0:
            print(f"{i + 1}/{len(files)} files, {len(rows)} offers", flush=True)

    ads = pd.DataFrame(rows)
    ov = load_overview(args.overview_dir)
    ads = ads.merge(ov, left_on="run_id", right_on="time", how="left").drop(columns="time")
    ads["language"] = "DE"
    ads["query_type"] = "generic"

    con = sqlite3.connect(args.db)
    try:
        ads.to_sql("serp_ads", con, if_exists="replace", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS idx_serp_ads_run ON serp_ads(run_id)")
    finally:
        con.close()
    if args.parquet:
        ads.to_parquet(args.parquet, index=False)
    if args.csv:
        ads.to_csv(args.csv, index=False, encoding="utf-8-sig")
    print(f"saved: {len(ads)} offers from {ads['run_id'].nunique()} SERPs -> {args.db} (table serp_ads)")


if __name__ == "__main__":
    main()
