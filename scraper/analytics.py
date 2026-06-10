"""
analytics.py — Export Parquet + dashboard interattiva Plotly.

Uso:
    python analytics.py                  # dashboard completa
    python analytics.py --export-only    # solo export Parquet
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from storage import DB_PATH

OUTPUT_DIR = Path("output")


def load_dataframe(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Carica tutti i prodotti dal DB in un DataFrame."""
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query("SELECT * FROM products", conn)
    conn.close()

    if df.empty:
        print("⚠ Database vuoto. Esegui prima la pipeline.")
        return df

    df["scraped_at"] = pd.to_datetime(df["scraped_at"], utc=True, errors="coerce")
    return df


def export_parquet(df: pd.DataFrame, path: Path | None = None,
                   run_ts: str | None = None) -> Path:
    """Esporta il DataFrame in formato Parquet."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    if path is None:
        ts = run_ts or datetime.now().strftime("%Y%m%d_%H%M")
        path = OUTPUT_DIR / f"results_{ts}.parquet"
    df.to_parquet(path, index=False, engine="pyarrow")
    print(f"📁 Parquet esportato: {path} ({len(df)} righe)")
    return path


def build_dashboard(df: pd.DataFrame, run_ts: str | None = None) -> Path | None:
    """Genera una dashboard HTML interattiva con Plotly. Ritorna il path HTML."""
    if df.empty:
        return None

    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = run_ts or datetime.now().strftime("%Y%m%d_%H%M")
    df_priced = df.dropna(subset=["price_value"])

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Price distribution by L1 category",
            "Products found by L1 category",
            "Top 15 sellers by frequency",
            "Average price by L2 category (top 15)",
            "Generic vs Branded — price distribution",
            "Global price distribution",
        ),
        vertical_spacing=0.08,
        horizontal_spacing=0.10,
    )

    # 1. Box plot prezzi per category_l1
    if not df_priced.empty:
        for cat in df_priced["category_l1"].unique():
            subset = df_priced[df_priced["category_l1"] == cat]
            fig.add_trace(
                go.Box(y=subset["price_value"], name=cat, showlegend=False),
                row=1, col=1,
            )

    # 2. Bar chart: prodotti per category_l1
    counts = df.groupby("category_l1").size().sort_values(ascending=True)
    fig.add_trace(
        go.Bar(
            x=counts.values, y=counts.index,
            orientation="h", showlegend=False, marker_color="#636EFA",
        ),
        row=1, col=2,
    )

    # 3. Top 15 seller
    seller_counts = (
        df[df["seller"] != ""]
        .groupby("seller").size()
        .nlargest(15).sort_values(ascending=True)
    )
    fig.add_trace(
        go.Bar(
            x=seller_counts.values, y=seller_counts.index,
            orientation="h", showlegend=False, marker_color="#EF553B",
        ),
        row=2, col=1,
    )

    # 4. Prezzo medio per category_l2 (top 15)
    if not df_priced.empty:
        avg_price = (
            df_priced.groupby("category_l2")["price_value"]
            .mean().nlargest(15).sort_values(ascending=True)
        )
        fig.add_trace(
            go.Bar(
                x=avg_price.values, y=avg_price.index,
                orientation="h", showlegend=False, marker_color="#00CC96",
            ),
            row=2, col=2,
        )

    # 5. Generic vs Branded
    if not df_priced.empty:
        for qt in ["generic", "branded"]:
            subset = df_priced[df_priced["query_type"] == qt]
            if not subset.empty:
                fig.add_trace(
                    go.Histogram(
                        x=subset["price_value"], name=qt,
                        opacity=0.6, nbinsx=30,
                    ),
                    row=3, col=1,
                )

    # 6. Istogramma prezzi globale
    if not df_priced.empty:
        fig.add_trace(
            go.Histogram(
                x=df_priced["price_value"],
                nbinsx=40, showlegend=False, marker_color="#FFA15A",
            ),
            row=3, col=2,
        )

    fig.update_layout(
        height=1200, width=1400,
        title_text="📊 Product Scraper — Analytics Dashboard",
        title_x=0.5,
        template="plotly_white",
        barmode="overlay",
    )

    html_path = OUTPUT_DIR / f"dashboard_{ts}.html"
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    print(f"📊 Dashboard HTML: {html_path}")

    try:
        png_path = OUTPUT_DIR / f"dashboard_{ts}.png"
        fig.write_image(str(png_path), scale=2)
        print(f"🖼  Dashboard PNG: {png_path}")
    except Exception:
        print("ℹ  Export PNG saltato (installa kaleido per abilitarlo)")

    return html_path


def print_summary(df: pd.DataFrame) -> None:
    """Stampa un riepilogo testuale."""
    if df.empty:
        return

    print(f"\n{'='*60}")
    print("📈 DATA SUMMARY")
    print(f"{'='*60}")
    print(f"Total products:     {len(df)}")
    print(f"Distinct keywords:  {df['keyword'].nunique()}")
    print(f"Distinct sellers:   {df['seller'].nunique()}")
    print(f"L1 categories:      {df['category_l1'].nunique()}")
    print(f"L2 categories:      {df['category_l2'].nunique()}")
    print(f"Languages:          {', '.join(df['language'].unique())}")
    print(f"Generic / Branded:  {(df['query_type']=='generic').sum()} / {(df['query_type']=='branded').sum()}")

    df_priced = df.dropna(subset=["price_value"])
    if not df_priced.empty:
        print(f"\nPrices:")
        print(f"  Min:    {df_priced['price_value'].min():.2f}")
        print(f"  Max:    {df_priced['price_value'].max():.2f}")
        print(f"  Mean:   {df_priced['price_value'].mean():.2f}")
        print(f"  Median: {df_priced['price_value'].median():.2f}")

        print(f"\nAverage price by L1 category:")
        for cat, grp in df_priced.groupby("category_l1"):
            print(f"  {cat:<30s} {grp['price_value'].mean():>10.2f}  ({len(grp)} products)")

    print(f"\nTop 5 cheapest products:")
    for _, row in df_priced.nsmallest(5, "price_value").iterrows():
        print(f"  {row['price_value']:>8.2f}  {row['title'][:60]}")

    print(f"\nTop 5 most expensive products:")
    for _, row in df_priced.nlargest(5, "price_value").iterrows():
        print(f"  {row['price_value']:>8.2f}  {row['title'][:60]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analytics prodotti")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    df = load_dataframe(args.db)
    if df.empty:
        return

    export_parquet(df)
    print_summary(df)

    if not args.export_only:
        build_dashboard(df)


if __name__ == "__main__":
    main()
