"""
explore.py — Explore results.db from the terminal (zero extra deps).

Usage:
    python main.py explore                  # full overview
    python main.py explore --lang IT        # filter by language
    python main.py explore --cat "Electronics"
    python main.py explore --keyword "mountain bike economici"
    python main.py explore --runs           # list Apify runs
    python main.py explore --sample 20      # product sample
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path("results.db")


# ─── helpers ────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print("❌ results.db not found. Run a scrape first.")
        raise SystemExit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _load(where: str = "1=1", params: tuple = ()) -> pd.DataFrame:
    conn = _connect()
    df = pd.read_sql_query(
        f"SELECT * FROM products WHERE {where}", conn, params=params
    )
    conn.close()
    return df


def _sep(title: str = "") -> None:
    bar = "─" * 64
    if title:
        print(f"\n{bar}\n  {title}\n{bar}")
    else:
        print(bar)


def _fmt_price(v) -> str:
    if pd.isna(v) or v is None:
        return "   —"
    return f"{v:>7.2f}"


# ─── views ──────────────────────────────────────────────────────────────

def view_overview(df: pd.DataFrame) -> None:
    _sep("DATABASE OVERVIEW")
    print(f"  Total products   : {len(df):,}")
    print(f"  Unique queries   : {df['query_id'].nunique():,}")
    print(f"  Unique keywords  : {df['keyword'].nunique():,}")
    print(f"  Apify runs       : {df['run_id'].nunique():,}")
    if "scraped_at" in df.columns and not df["scraped_at"].isna().all():
        print(f"  From             : {df['scraped_at'].min()[:10]}")
        print(f"  To               : {df['scraped_at'].max()[:10]}")
    n_price = df["price_value"].notna().sum()
    pct = n_price / len(df) * 100 if len(df) else 0
    print(f"  With price       : {n_price:,}  ({pct:.0f}%)")


def view_by_language(df: pd.DataFrame) -> None:
    _sep("BY LANGUAGE")
    g = (
        df.groupby("language")
        .agg(
            n_prodotti=("id", "count"),
            n_keyword=("keyword", "nunique"),
            prezzo_medio=("price_value", "mean"),
            prezzo_min=("price_value", "min"),
            prezzo_max=("price_value", "max"),
        )
        .reset_index()
        .sort_values("n_prodotti", ascending=False)
    )
    header = f"  {'Language':<8}  {'Products':>9}  {'Keyword':>8}  "
    header += f"{'Avg price':>13}  {'Min':>8}  {'Max':>8}"
    print(header)
    print("  " + "─" * 62)
    for _, row in g.iterrows():
        print(
            f"  {row['language']:<8}  {int(row['n_prodotti']):>9,}  "
            f"{int(row['n_keyword']):>8,}  "
            f"{_fmt_price(row['prezzo_medio']):>13}  "
            f"{_fmt_price(row['prezzo_min']):>8}  "
            f"{_fmt_price(row['prezzo_max']):>8}"
        )


def view_by_category(df: pd.DataFrame) -> None:
    _sep("BY L1 CATEGORY")
    g = (
        df.groupby("category_l1")
        .agg(
            n_prodotti=("id", "count"),
            n_lingue=("language", "nunique"),
            n_keyword=("keyword", "nunique"),
            prezzo_medio=("price_value", "mean"),
        )
        .reset_index()
        .sort_values("n_prodotti", ascending=False)
    )
    header = f"  {'Category':<26}  {'Products':>9}  {'Langs':>7}  {'Keyword':>8}  {'Avg price':>10}"
    print(header)
    print("  " + "─" * 66)
    for _, row in g.iterrows():
        cat = str(row["category_l1"])[:25]
        print(
            f"  {cat:<26}  {int(row['n_prodotti']):>9,}  "
            f"{int(row['n_lingue']):>7,}  "
            f"{int(row['n_keyword']):>8,}  "
            f"{_fmt_price(row['prezzo_medio']):>10}"
        )


def view_top_sellers(df: pd.DataFrame, top: int = 15) -> None:
    _sep(f"TOP {top} SELLERS BY FREQUENCY")
    df_sel = df[df["seller"].notna() & (df["seller"] != "")]
    if df_sel.empty:
        print("  No sellers recorded.")
        return
    g = df_sel["seller"].value_counts().head(top)
    for seller, count in g.items():
        pct = count / len(df) * 100
        bar = "█" * int(pct / 2)
        print(f"  {str(seller)[:35]:<35}  {count:>5,}  {pct:>5.1f}%  {bar}")


def view_runs(df: pd.DataFrame) -> None:
    _sep("APIFY RUNS (most recent first)")
    if "run_id" not in df.columns or df["run_id"].isna().all():
        print("  No run_id recorded.")
        return
    g = (
        df.groupby("run_id")
        .agg(
            n=("id", "count"),
            keyword=("keyword", "first"),
            lingua=("language", "first"),
            when=("scraped_at", "max"),
        )
        .reset_index()
        .sort_values("when", ascending=False)
        .head(30)
    )
    print(f"  {'Run ID':<36}  {'N':>5}  {'Lang':<6}  {'Keyword':<35}  {'Date'}")
    print("  " + "─" * 100)
    for _, row in g.iterrows():
        rid = str(row["run_id"])[:35]
        kw = str(row["keyword"])[:34]
        when = str(row["when"])[:16] if row["when"] else ""
        print(
            f"  {rid:<36}  {int(row['n']):>5,}  {str(row['lingua']):<6}  "
            f"{kw:<35}  {when}"
        )


def view_keyword_prices(df: pd.DataFrame, keyword: str) -> None:
    sub = df[df["keyword"].str.lower() == keyword.lower()]
    if sub.empty:
        print(f"  No products for keyword '{keyword}'.")
        return
    _sep(f"KEYWORD: {keyword}  ({len(sub)} products)")
    g = (
        sub.groupby("language")
        .agg(
            n=("id", "count"),
            media=("price_value", "mean"),
            mediana=("price_value", "median"),
            min=("price_value", "min"),
            max=("price_value", "max"),
            std=("price_value", "std"),
        )
        .reset_index()
    )
    print(f"  {'Language':<8}  {'N':>5}  {'Mean':>8}  {'Median':>8}  "
          f"{'Min':>8}  {'Max':>8}  {'Std':>8}")
    print("  " + "─" * 64)
    for _, row in g.iterrows():
        print(
            f"  {row['language']:<8}  {int(row['n']):>5,}  "
            f"{_fmt_price(row['media']):>8}  "
            f"{_fmt_price(row['mediana']):>8}  "
            f"{_fmt_price(row['min']):>8}  "
            f"{_fmt_price(row['max']):>8}  "
            f"{_fmt_price(row['std']):>8}"
        )
    _sep("PRODUCT SAMPLE")
    cols = ["language", "title", "price_value", "seller", "position"]
    sample = sub[cols].sort_values(["language", "position"]).head(30)
    for _, r in sample.iterrows():
        title = str(r["title"])[:50]
        seller = str(r.get("seller", ""))[:20]
        price = _fmt_price(r["price_value"])
        print(f"  [{r['language']}] pos{int(r['position']) if pd.notna(r['position']) else '?':>2}  "
              f"{price}  {title:<50}  {seller}")


def view_sample(df: pd.DataFrame, n: int = 20) -> None:
    _sep(f"RANDOM SAMPLE ({n} products)")
    cols = ["language", "category_l1", "keyword", "title", "price_value", "seller", "position"]
    sample = df[cols].sample(min(n, len(df)), random_state=42)
    for _, r in sample.iterrows():
        title = str(r["title"])[:45]
        kw = str(r["keyword"])[:25]
        price = _fmt_price(r["price_value"])
        print(f"  [{r['language']}] {kw:<25}  {price}  {title}")


# ─── entrypoint ─────────────────────────────────────────────────────────

def explore(
    lang: str | None = None,
    cat: str | None = None,
    keyword: str | None = None,
    show_runs: bool = False,
    sample: int | None = None,
) -> None:
    conditions, params = [], []
    if lang:
        conditions.append("language = ?")
        params.append(lang.upper())
    if cat:
        conditions.append("category_l1 = ?")
        params.append(cat)
    where = " AND ".join(conditions) if conditions else "1=1"

    df = _load(where, tuple(params))

    if df.empty:
        print("⚠ No products found with the given filters.")
        return

    if keyword:
        view_keyword_prices(df, keyword)
        return

    if show_runs:
        view_runs(df)
        return

    if sample is not None:
        view_sample(df, sample)
        return

    view_overview(df)
    view_by_language(df)
    view_by_category(df)
    view_top_sellers(df)
    print()
