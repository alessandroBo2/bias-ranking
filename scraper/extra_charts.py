"""
extra_charts.py — Additional charts for multilingual/multi-category analysis.
Exports PNGs via kaleido for quick inspection.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from storage import DB_PATH

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

LANG_COLORS = {"IT": "#1f77b4", "DE": "#ff7f0e", "EN": "#2ca02c"}


def load() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT * FROM products", conn)
    conn.close()
    return df


def cross_lang_dashboard(df: pd.DataFrame) -> None:
    """6-panel focused on the dynamic cross-language comparison."""
    df_p = df.dropna(subset=["price_value"])
    languages = sorted(df["language"].unique())

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Price distribution by language (boxplot)",
            "Overlaid price histograms by language",
            "Position vs price (scatter, colored by language)",
            "Average price by L2 category × language (heatmap)",
            "Top 5 most expensive products by language",
            "Rating: distribution by language",
        ),
        vertical_spacing=0.10,
        horizontal_spacing=0.13,
        specs=[
            [{"type": "box"}, {"type": "histogram"}],
            [{"type": "scatter"}, {"type": "heatmap"}],
            [{"type": "bar"}, {"type": "box"}],
        ],
    )

    # 1. Price boxplot by language
    for lang in languages:
        sub = df_p[df_p["language"] == lang]
        fig.add_trace(
            go.Box(y=sub["price_value"], name=lang,
                   marker_color=LANG_COLORS.get(lang, "#888"),
                   showlegend=False, boxmean="sd"),
            row=1, col=1,
        )

    # 2. Overlaid histogram
    for lang in languages:
        sub = df_p[df_p["language"] == lang]
        fig.add_trace(
            go.Histogram(x=sub["price_value"], name=lang,
                         marker_color=LANG_COLORS.get(lang, "#888"),
                         opacity=0.55, nbinsx=20),
            row=1, col=2,
        )
    fig.update_layout(barmode="overlay")

    # 3. Position vs price scatter (1 trace per language)
    for lang in languages:
        sub = df_p[df_p["language"] == lang]
        fig.add_trace(
            go.Scatter(x=sub["position"], y=sub["price_value"],
                       mode="markers", name=lang,
                       marker=dict(color=LANG_COLORS.get(lang, "#888"),
                                   size=9, opacity=0.65),
                       showlegend=False),
            row=2, col=1,
        )

    # 4. Heatmap of average price by L2 category × language
    pivot = (df_p.groupby(["category_l2", "language"])["price_value"]
             .mean().unstack().round(0))
    pivot = pivot.reindex(columns=languages)
    fig.add_trace(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns, y=pivot.index,
            colorscale="Viridis",
            text=[[f"€{v:.0f}" if not np.isnan(v) else "n/a" for v in row]
                  for row in pivot.values],
            texttemplate="%{text}",
            colorbar=dict(title="€", x=1.0, len=0.28, y=0.5),
        ),
        row=2, col=2,
    )

    # 5. Top 5 highest prices per language (concatenated)
    rows = []
    for lang in languages:
        top = df_p[df_p["language"] == lang].nlargest(5, "price_value")
        for _, r in top.iterrows():
            rows.append({
                "label": f"[{lang}] {r['title'][:32]}",
                "price": r["price_value"],
                "lang": lang,
            })
    if rows:
        top_df = pd.DataFrame(rows).sort_values("price")
        fig.add_trace(
            go.Bar(
                x=top_df["price"], y=top_df["label"],
                orientation="h", showlegend=False,
                marker_color=[LANG_COLORS.get(l, "#888") for l in top_df["lang"]],
                text=[f"€{p:.0f}" for p in top_df["price"]],
                textposition="auto",
            ),
            row=3, col=1,
        )

    # 6. Rating boxplot by language
    for lang in languages:
        sub = df[(df["language"] == lang) & df["rating"].notna()]
        if len(sub) > 0:
            fig.add_trace(
                go.Box(y=sub["rating"], name=lang,
                       marker_color=LANG_COLORS.get(lang, "#888"),
                       showlegend=False, boxmean="sd"),
                row=3, col=2,
            )

    fig.update_xaxes(title_text="€ price", row=1, col=1)
    fig.update_xaxes(title_text="€ price", row=1, col=2)
    fig.update_yaxes(title_text="count", row=1, col=2)
    fig.update_xaxes(title_text="position (1=top)", row=2, col=1)
    fig.update_yaxes(title_text="€ price", row=2, col=1)
    fig.update_xaxes(title_text="€ price", row=3, col=1)
    fig.update_yaxes(title_text="rating (0-5)", row=3, col=2)

    fig.update_layout(
        height=1400, width=1500,
        title_text=f"🌍 Multilingual comparison — {len(languages)} languages, "
                   f"{df['category_l2'].nunique()} L2 categories, {len(df)} products",
        title_x=0.5,
        template="plotly_white",
        margin=dict(l=80, r=80, t=120, b=60),
    )

    html_path = OUTPUT_DIR / "cross_lang_dashboard.html"
    png_path = OUTPUT_DIR / "cross_lang_dashboard.png"
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    fig.write_image(str(png_path), scale=2)
    print(f"✓ {html_path}")
    print(f"✓ {png_path}")


def category_dashboard(df: pd.DataFrame) -> None:
    """Cross-category comparison (Electronics vs Sporting Goods, etc.)."""
    df_p = df.dropna(subset=["price_value"])
    cats = sorted(df_p["category_l2"].unique())

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Price distribution by L2 category",
            "Generic vs Branded — price distribution",
            "Top sellers by L2 category (% share)",
            "Price coverage (% products with a price) by category",
        ),
        vertical_spacing=0.13,
        horizontal_spacing=0.13,
        specs=[
            [{"type": "box"}, {"type": "histogram"}],
            [{"type": "bar"}, {"type": "bar"}],
        ],
    )

    # 1. Boxplot by L2 category
    for cat in cats:
        sub = df_p[df_p["category_l2"] == cat]
        fig.add_trace(
            go.Box(y=sub["price_value"], name=cat,
                   showlegend=False, boxmean="sd"),
            row=1, col=1,
        )

    # 2. Generic vs Branded histogram
    for qt, color in [("generic", "#636EFA"), ("branded", "#EF553B")]:
        sub = df_p[df_p["query_type"] == qt]
        if len(sub):
            fig.add_trace(
                go.Histogram(x=sub["price_value"], name=qt,
                             marker_color=color, opacity=0.6, nbinsx=25),
                row=1, col=2,
            )

    # 3. Top sellers per category (top 5 for each)
    rows = []
    for cat in cats:
        sub = df[(df["category_l2"] == cat) & (df["seller"] != "")]
        if len(sub) == 0:
            continue
        sc = sub.groupby("seller").size()
        total = sc.sum()
        for s, n in sc.nlargest(5).items():
            rows.append({"cat": cat, "seller": f"[{cat[:10]}] {s[:18]}",
                         "pct": n / total * 100})
    if rows:
        sdf = pd.DataFrame(rows).sort_values(["cat", "pct"])
        fig.add_trace(
            go.Bar(x=sdf["pct"], y=sdf["seller"],
                   orientation="h", showlegend=False,
                   marker_color="#00CC96",
                   text=[f"{p:.0f}%" for p in sdf["pct"]],
                   textposition="auto"),
            row=2, col=1,
        )

    # 4. Price coverage by category
    cov = (df.groupby("category_l2")["price_value"]
           .apply(lambda x: x.notna().mean() * 100)
           .sort_values(ascending=True))
    fig.add_trace(
        go.Bar(x=cov.values, y=cov.index, orientation="h",
               showlegend=False, marker_color="#FFA15A",
               text=[f"{p:.0f}%" for p in cov.values],
               textposition="auto"),
        row=2, col=2,
    )

    fig.update_xaxes(title_text="€ price", row=1, col=2)
    fig.update_yaxes(title_text="count", row=1, col=2)
    fig.update_xaxes(title_text="% of category total", row=2, col=1)
    fig.update_xaxes(title_text="% products with a price", row=2, col=2)

    fig.update_layout(
        height=1100, width=1500,
        title_text="📦 Cross-category comparison",
        title_x=0.5,
        template="plotly_white",
        barmode="overlay",
        margin=dict(l=80, r=40, t=120, b=60),
    )

    html_path = OUTPUT_DIR / "category_dashboard.html"
    png_path = OUTPUT_DIR / "category_dashboard.png"
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    fig.write_image(str(png_path), scale=2)
    print(f"✓ {html_path}")
    print(f"✓ {png_path}")


def export_bias_png(df: pd.DataFrame) -> None:
    """Saves the bias dashboard as a PNG as well."""
    df_priced = df.dropna(subset=["price_value"])
    df_with_seller = df[df["seller"] != ""]

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Seller concentration (Lorenz curve)",
            "Average position of top sellers (n>=3)",
            "Position distribution for top 5 sellers",
            "Price diversity per query (CoV)",
            "Results per (query_id, language) by category",
            "Sellers in top-3 by frequency",
        ),
        vertical_spacing=0.10,
        horizontal_spacing=0.10,
    )

    # 1. Lorenz
    sc = df_with_seller.groupby("seller").size().sort_values()
    cum = np.cumsum(sc.values) / sc.sum()
    x = np.arange(1, len(cum) + 1) / len(cum)
    fig.add_trace(go.Scatter(x=x, y=cum, name="Lorenz",
                             line=dict(color="#EF553B", width=3),
                             showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1],
                             line=dict(color="gray", dash="dash"),
                             showlegend=False), row=1, col=1)

    # 2. Average position of top sellers
    sp = df_with_seller.groupby("seller")["position"].agg(["mean", "count"])
    sp = sp[sp["count"] >= 3].nsmallest(15, "mean")
    fig.add_trace(go.Bar(x=sp["mean"].values, y=sp.index,
                         orientation="h", showlegend=False,
                         marker_color="#636EFA",
                         text=[f"{m:.1f}" for m in sp["mean"]],
                         textposition="auto"), row=1, col=2)

    # 3. Position boxplot for top 5 sellers
    top5 = df_with_seller.groupby("seller").size().nlargest(5).index
    for s in top5:
        sub = df_with_seller[df_with_seller["seller"] == s]
        fig.add_trace(go.Box(y=sub["position"], name=s[:20],
                             showlegend=False), row=2, col=1)

    # 4. CoV per query (distinguished by (query_id, language))
    cov_data = []
    for (qid, lang), grp in df_priced.groupby(["query_id", "language"]):
        if len(grp) >= 5 and grp["price_value"].mean() > 0:
            cov_data.append({
                "label": f"[{lang}] {grp['keyword'].iloc[0][:25]}",
                "cov": grp["price_value"].std() / grp["price_value"].mean(),
            })
    if cov_data:
        cov_df = pd.DataFrame(cov_data).sort_values("cov")
        fig.add_trace(go.Bar(x=cov_df["cov"], y=cov_df["label"],
                             orientation="h", showlegend=False,
                             marker_color="#00CC96",
                             text=[f"{c:.2f}" for c in cov_df["cov"]],
                             textposition="auto"), row=2, col=2)

    # 5. Results by category
    rpq = (df.groupby(["category_l1", "query_id", "language"])
           .size().reset_index(name="n"))
    for cat in df["category_l1"].unique():
        sub = rpq[rpq["category_l1"] == cat]
        fig.add_trace(go.Box(y=sub["n"], name=cat,
                             showlegend=False), row=3, col=1)

    # 6. Seller top-3
    t3 = df_with_seller[df_with_seller["position"] <= 3]
    tc = t3.groupby("seller").size().nlargest(10).sort_values()
    fig.add_trace(go.Bar(x=tc.values, y=tc.index, orientation="h",
                         showlegend=False, marker_color="#AB63FA",
                         text=[str(v) for v in tc.values],
                         textposition="auto"), row=3, col=2)

    fig.update_layout(
        height=1500, width=1500,
        title_text=f"🔍 Bias Analysis — {len(df)} products, "
                   f"{df['language'].nunique()} languages, "
                   f"{df['seller'].replace('', np.nan).nunique()} sellers",
        title_x=0.5, template="plotly_white",
    )

    png_path = OUTPUT_DIR / "bias_dashboard.png"
    html_path = OUTPUT_DIR / "bias_dashboard.html"
    fig.write_image(str(png_path), scale=2)
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    print(f"✓ {png_path}")
    print(f"✓ {html_path}")


if __name__ == "__main__":
    df = load()
    cross_lang_dashboard(df)
    category_dashboard(df)
    export_bias_png(df)
