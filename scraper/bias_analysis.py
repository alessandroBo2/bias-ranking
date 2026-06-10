"""
bias_analysis.py — Analisi di sbilanciamento nelle risposte Google Shopping.

Rileva:
  1. Concentrazione seller (HHI, Gini, CR-k)
  2. Position bias (chi occupa sistematicamente le prime posizioni?)
  3. Disparità cross-lingua (stesso prodotto, prezzi diversi per paese)
  4. Price clustering (i risultati coprono davvero il mercato?)
  5. Category coverage (Google restituisce risultati bilanciati?)
  6. Seller dominance per categoria

Uso:
    python bias_analysis.py                # analisi completa + report
    python bias_analysis.py --format html  # anche dashboard HTML
    python bias_analysis.py --format csv   # export metriche in CSV
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from storage import DB_PATH

OUTPUT_DIR = Path("output")


# ═══════════════════════════════════════════════════════════════════════════
# 1. CONCENTRAZIONE SELLER
# ═══════════════════════════════════════════════════════════════════════════

def herfindahl_hirschman_index(shares: np.ndarray) -> float:
    """
    Indice HHI: somma dei quadrati delle quote di mercato.
    Range: 1/N (perfetta concorrenza) → 1.0 (monopolio).
    Soglie DoJ USA: <0.15 competitivo, 0.15-0.25 moderato, >0.25 concentrato.
    """
    return float(np.sum(shares ** 2))


def gini_coefficient(values: np.ndarray) -> float:
    """
    Coefficiente di Gini: misura la disuguaglianza nella distribuzione.
    0.0 = perfetta uguaglianza, 1.0 = massima disuguaglianza.
    """
    values = np.sort(values)
    n = len(values)
    if n == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * values) - (n + 1) * np.sum(values)) / (n * np.sum(values)))


def concentration_ratio(counts: pd.Series, k: int = 3) -> float:
    """CR-k: quota cumulativa dei top-k seller."""
    total = counts.sum()
    if total == 0:
        return 0.0
    return float(counts.nlargest(k).sum() / total)


def seller_concentration_analysis(df: pd.DataFrame) -> dict:
    """
    Analisi completa della concentrazione seller.
    Restituisce metriche globali e per categoria.
    """
    results = {}

    # Globale
    seller_counts = df[df["seller"] != ""].groupby("seller").size()
    if len(seller_counts) > 0:
        shares = seller_counts.values / seller_counts.sum()
        results["global"] = {
            "hhi": herfindahl_hirschman_index(shares),
            "gini": gini_coefficient(seller_counts.values.astype(float)),
            "cr3": concentration_ratio(seller_counts, 3),
            "cr5": concentration_ratio(seller_counts, 5),
            "cr10": concentration_ratio(seller_counts, 10),
            "n_sellers": len(seller_counts),
            "top10_sellers": seller_counts.nlargest(10).to_dict(),
        }

    # Per categoria L1
    results["by_category"] = {}
    for cat in df["category_l1"].unique():
        cat_df = df[(df["category_l1"] == cat) & (df["seller"] != "")]
        cat_counts = cat_df.groupby("seller").size()
        if len(cat_counts) >= 3:
            shares = cat_counts.values / cat_counts.sum()
            results["by_category"][cat] = {
                "hhi": herfindahl_hirschman_index(shares),
                "gini": gini_coefficient(cat_counts.values.astype(float)),
                "cr3": concentration_ratio(cat_counts, 3),
                "n_sellers": len(cat_counts),
                "top3": cat_counts.nlargest(3).to_dict(),
            }

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 2. POSITION BIAS
# ═══════════════════════════════════════════════════════════════════════════

def position_bias_analysis(df: pd.DataFrame) -> dict:
    """
    Analizza se certi seller occupano sistematicamente le prime posizioni.

    Metriche:
    - Posizione media per seller (chi sta sempre in alto?)
    - % di volte in top-3 / top-5 per seller
    - Correlazione posizione-prezzo (Google favorisce i più cari?)
    """
    results = {}
    df_with_seller = df[df["seller"] != ""].copy()

    if df_with_seller.empty:
        return results

    # Posizione media per seller (solo seller con >= 5 apparizioni)
    seller_pos = df_with_seller.groupby("seller")["position"].agg(["mean", "count"])
    seller_pos = seller_pos[seller_pos["count"] >= 5].sort_values("mean")

    results["avg_position_top15"] = {
        row.Index: {"avg_pos": round(row.mean, 2), "appearances": int(row.count)}
        for row in seller_pos.head(15).itertuples()
    }

    # % in top-3 e top-5
    top3_mask = df_with_seller["position"] <= 3
    top5_mask = df_with_seller["position"] <= 5

    top3_counts = df_with_seller[top3_mask].groupby("seller").size()
    top5_counts = df_with_seller[top5_mask].groupby("seller").size()
    total_queries = df_with_seller["query_id"].nunique()

    results["top3_dominance"] = {
        seller: {
            "count": int(count),
            "pct_of_queries": round(count / total_queries * 100, 1),
        }
        for seller, count in top3_counts.nlargest(10).items()
    }

    results["top5_dominance"] = {
        seller: {
            "count": int(count),
            "pct_of_queries": round(count / total_queries * 100, 1),
        }
        for seller, count in top5_counts.nlargest(10).items()
    }

    # Correlazione posizione-prezzo
    df_pos_price = df_with_seller.dropna(subset=["price_value"])
    if len(df_pos_price) > 10:
        corr = df_pos_price["position"].corr(df_pos_price["price_value"])
        results["position_price_correlation"] = {
            "pearson_r": round(corr, 4),
            "interpretation": (
                "Google tends to show more expensive products first"
                if corr < -0.1 else
                "Google tends to show cheaper products first"
                if corr > 0.1 else
                "No significant position-price correlation"
            ),
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 3. DISPARITÀ CROSS-LINGUA
# ═══════════════════════════════════════════════════════════════════════════

def cross_language_analysis(df: pd.DataFrame) -> dict:
    """
    Confronta i risultati per lo stesso prodotto tra lingue diverse.
    Richiede che il dataset contenga query in più lingue.
    """
    languages = df["language"].unique()
    if len(languages) < 2:
        return {"note": "At least 2 languages required for cross-language comparison."}

    results = {}
    df_priced = df.dropna(subset=["price_value"])

    # Confronto prezzo medio per categoria L2 tra lingue
    price_by_lang_cat = (
        df_priced
        .groupby(["language", "category_l2"])["price_value"]
        .agg(["mean", "median", "count"])
        .reset_index()
    )

    # Trova categorie presenti in più lingue
    multi_lang_cats = (
        price_by_lang_cat
        .groupby("category_l2")["language"]
        .nunique()
    )
    multi_lang_cats = multi_lang_cats[multi_lang_cats >= 2].index

    disparities = []
    for cat in multi_lang_cats:
        cat_data = price_by_lang_cat[price_by_lang_cat["category_l2"] == cat]
        if len(cat_data) >= 2:
            prices = cat_data.set_index("language")["mean"]
            max_p = prices.max()
            min_p = prices.min()
            if min_p > 0:
                disparity_pct = (max_p - min_p) / min_p * 100
                disparities.append({
                    "category_l2": cat,
                    "prices_by_lang": prices.round(2).to_dict(),
                    "disparity_pct": round(disparity_pct, 1),
                    "cheapest_lang": prices.idxmin(),
                    "most_expensive_lang": prices.idxmax(),
                })

    disparities.sort(key=lambda x: x["disparity_pct"], reverse=True)
    results["price_disparities"] = disparities[:20]

    # Conteggio risultati per lingua
    results["results_per_language"] = df.groupby("language").size().to_dict()

    # Seller overlap tra lingue
    sellers_by_lang = {
        lang: set(df[df["language"] == lang]["seller"].unique()) - {""}
        for lang in languages
    }
    lang_pairs = [
        (l1, l2)
        for i, l1 in enumerate(languages)
        for l2 in languages[i + 1:]
    ]
    results["seller_overlap"] = {}
    for l1, l2 in lang_pairs:
        s1, s2 = sellers_by_lang.get(l1, set()), sellers_by_lang.get(l2, set())
        if s1 and s2:
            overlap = s1 & s2
            results["seller_overlap"][f"{l1}-{l2}"] = {
                "shared_sellers": len(overlap),
                "only_in_" + l1: len(s1 - s2),
                "only_in_" + l2: len(s2 - s1),
                "jaccard_similarity": round(len(overlap) / len(s1 | s2), 3),
            }

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 4. PRICE CLUSTERING
# ═══════════════════════════════════════════════════════════════════════════

def price_diversity_analysis(df: pd.DataFrame) -> dict:
    """
    Quanto sono diversificati i risultati di prezzo?
    Un basso CoV o una distribuzione concentrata suggeriscono che Google
    restituisce risultati troppo omogenei (filter bubble di prezzo).
    """
    results = {}
    df_priced = df.dropna(subset=["price_value"])

    by_keyword = {}
    for kw, grp in df_priced.groupby("keyword"):
        prices = grp["price_value"].values
        if len(prices) >= 5:
            by_keyword[kw] = {
                "count": len(prices),
                "mean": round(float(np.mean(prices)), 2),
                "std": round(float(np.std(prices)), 2),
                "cov": round(float(np.std(prices) / np.mean(prices)), 3) if np.mean(prices) > 0 else 0,
                "iqr": round(float(np.percentile(prices, 75) - np.percentile(prices, 25)), 2),
                "range_pct": round(
                    float((np.max(prices) - np.min(prices)) / np.mean(prices) * 100), 1
                ) if np.mean(prices) > 0 else 0,
            }

    # Ordina per CoV (basso = poca diversità = possibile bias)
    sorted_by_cov = sorted(by_keyword.items(), key=lambda x: x[1]["cov"])

    results["least_diverse"] = dict(sorted_by_cov[:10])
    results["most_diverse"] = dict(sorted_by_cov[-10:])

    # Media globale del CoV
    covs = [v["cov"] for v in by_keyword.values()]
    if covs:
        results["global_avg_cov"] = round(float(np.mean(covs)), 3)
        results["interpretation"] = (
            "Results show low price diversity (possible filter bubble)"
            if np.mean(covs) < 0.3 else
            "Results show average price diversity"
            if np.mean(covs) < 0.7 else
            "Results show high price diversity"
        )

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 5. CATEGORY COVERAGE BIAS
# ═══════════════════════════════════════════════════════════════════════════

def category_coverage_analysis(df: pd.DataFrame) -> dict:
    """
    Google restituisce lo stesso numero di risultati per ogni categoria?
    Categorie con pochi risultati potrebbero essere penalizzate dall'algoritmo.

    Una "query" è qui intesa come una singola interrogazione effettiva
    (query_id, language): la stessa keyword in lingue diverse conta come
    interrogazioni distinte. Senza questa distinzione, una query eseguita in
    3 lingue gonfierebbe il conteggio "risultati per query" di un fattore 3.
    """
    results = {}

    # Risultati per (categoria, interrogazione = query_id × lingua)
    avg_by_cat = (
        df.groupby(["category_l1", "query_id", "language"])
        .size().reset_index(name="n_results")
    )
    cat_avg = avg_by_cat.groupby("category_l1")["n_results"].mean()

    results["avg_results_per_query_by_category"] = cat_avg.round(1).to_dict()

    global_avg = avg_by_cat["n_results"].mean()
    results["global_avg_results_per_query"] = round(global_avg, 1)

    # Categorie sotto-rappresentate (< 70% della media globale)
    underserved = cat_avg[cat_avg < global_avg * 0.7]
    if not underserved.empty:
        results["underserved_categories"] = underserved.round(1).to_dict()

    # Distribuzione anche per lingua per esporre asimmetrie cross-lingua
    avg_by_cat_lang = (
        avg_by_cat.groupby(["category_l1", "language"])["n_results"]
        .mean().round(1).unstack()
    )
    results["avg_results_per_query_by_category_lang"] = (
        avg_by_cat_lang.fillna(0).to_dict(orient="index")
    )

    # % di risultati con prezzo per categoria (Google non mostra sempre il prezzo)
    price_coverage = df.groupby("category_l1")["price_value"].apply(
        lambda x: round(x.notna().mean() * 100, 1)
    )
    results["price_coverage_by_category"] = price_coverage.to_dict()

    return results


# ═══════════════════════════════════════════════════════════════════════════
# REPORT TESTUALE
# ═══════════════════════════════════════════════════════════════════════════

def print_bias_report(df: pd.DataFrame) -> dict:
    """Esegue tutte le analisi e stampa un report testuale."""
    print(f"\n{'='*70}")
    print("🔍 BIAS ANALYSIS — GOOGLE SHOPPING")
    print(f"{'='*70}")
    print(f"Dataset: {len(df)} products, {df['keyword'].nunique()} keywords, "
          f"{df['language'].nunique()} language(s)\n")

    all_results = {}

    # 1. Seller concentration
    print(f"\n{'─'*70}")
    print("1. SELLER CONCENTRATION")
    print(f"{'─'*70}")
    conc = seller_concentration_analysis(df)
    all_results["seller_concentration"] = conc

    if "global" in conc:
        g = conc["global"]
        hhi = g["hhi"]
        hhi_label = (
            "COMPETITIVE" if hhi < 0.15 else
            "MODERATELY CONCENTRATED" if hhi < 0.25 else
            "HIGHLY CONCENTRATED"
        )
        print(f"  HHI:            {hhi:.4f}  [{hhi_label}]")
        print(f"  Gini:           {g['gini']:.3f}  (0=equality, 1=monopoly)")
        print(f"  CR-3:           {g['cr3']:.1%}  (top 3 sellers' market share)")
        print(f"  CR-5:           {g['cr5']:.1%}")
        print(f"  CR-10:          {g['cr10']:.1%}")
        print(f"  Unique sellers: {g['n_sellers']}")
        print(f"\n  Top 10 sellers:")
        for seller, count in g["top10_sellers"].items():
            pct = count / sum(g["top10_sellers"].values()) * 100
            bar = "█" * int(pct / 2)
            print(f"    {seller:<35s} {count:>5d}  ({pct:>5.1f}%)  {bar}")

    if conc.get("by_category"):
        print(f"\n  HHI by category:")
        for cat, m in sorted(conc["by_category"].items(), key=lambda x: x[1]["hhi"], reverse=True):
            flag = " ⚠️" if m["hhi"] > 0.25 else ""
            print(f"    {cat:<30s}  HHI={m['hhi']:.4f}  CR3={m['cr3']:.1%}  "
                  f"({m['n_sellers']} sellers){flag}")

    # 2. Position bias
    print(f"\n{'─'*70}")
    print("2. POSITION BIAS")
    print(f"{'─'*70}")
    pos = position_bias_analysis(df)
    all_results["position_bias"] = pos

    if pos.get("position_price_correlation"):
        ppc = pos["position_price_correlation"]
        print(f"  Position↔price correlation: r={ppc['pearson_r']}")
        print(f"  → {ppc['interpretation']}")

    if pos.get("top3_dominance"):
        print(f"\n  Sellers dominating top-3 positions:")
        for seller, info in list(pos["top3_dominance"].items())[:7]:
            print(f"    {seller:<35s}  {info['count']:>4d} times  "
                  f"({info['pct_of_queries']:.1f}% of queries)")

    # 3. Cross-language disparities
    print(f"\n{'─'*70}")
    print("3. CROSS-LANGUAGE PRICE DISPARITIES")
    print(f"{'─'*70}")
    cross = cross_language_analysis(df)
    all_results["cross_language"] = cross

    if cross.get("note"):
        print(f"  {cross['note']}")
        print("  Tip: run scraping with --lang IT, --lang EN, --lang DE")
        print("  to obtain comparable data.")
    else:
        if cross.get("price_disparities"):
            print(f"  Top price disparities across languages:")
            for d in cross["price_disparities"][:10]:
                prices_str = ", ".join(f"{l}={p:.0f}€" for l, p in d["prices_by_lang"].items())
                print(f"    {d['category_l2']:<30s}  Δ={d['disparity_pct']:.0f}%  ({prices_str})")

        if cross.get("seller_overlap"):
            print(f"\n  Seller overlap across languages:")
            for pair, info in cross["seller_overlap"].items():
                print(f"    {pair}: {info['shared_sellers']} shared, "
                      f"Jaccard={info['jaccard_similarity']:.3f}")

    # 4. Price diversity
    print(f"\n{'─'*70}")
    print("4. PRICE DIVERSITY (FILTER BUBBLE)")
    print(f"{'─'*70}")
    pdiv = price_diversity_analysis(df)
    all_results["price_diversity"] = pdiv

    if pdiv.get("global_avg_cov") is not None:
        print(f"  Global average CoV: {pdiv['global_avg_cov']:.3f}")
        print(f"  → {pdiv.get('interpretation', '')}")

    if pdiv.get("least_diverse"):
        print(f"\n  Queries with LOWEST price diversity (possible filter bubble):")
        for kw, m in list(pdiv["least_diverse"].items())[:5]:
            print(f"    {kw:<40s}  CoV={m['cov']:.3f}  range={m['range_pct']:.0f}%  "
                  f"(n={m['count']})")

    # 5. Category coverage
    print(f"\n{'─'*70}")
    print("5. CATEGORY COVERAGE")
    print(f"{'─'*70}")
    cov = category_coverage_analysis(df)
    all_results["category_coverage"] = cov

    if cov.get("avg_results_per_query_by_category"):
        print(f"  Average results per (query × language) — global avg: {cov['global_avg_results_per_query']}:")
        for cat, avg in sorted(
            cov["avg_results_per_query_by_category"].items(),
            key=lambda x: x[1], reverse=True,
        ):
            flag = " ⚠️ under-represented" if avg < cov["global_avg_results_per_query"] * 0.7 else ""
            print(f"    {cat:<30s}  {avg:>5.1f} results/query{flag}")

    by_lang = cov.get("avg_results_per_query_by_category_lang") or {}
    if by_lang:
        all_langs = sorted({l for d in by_lang.values() for l in d.keys()})
        if all_langs:
            print(f"\n  Breakdown by language (avg results/query):")
            header = "    " + "category".ljust(30) + "  " + "  ".join(f"{l:>6}" for l in all_langs)
            print(header)
            for cat, lang_map in sorted(by_lang.items()):
                cells = []
                for l in all_langs:
                    v = lang_map.get(l, 0)
                    cells.append(f"{v:>6.1f}" if v else "    -")
                print(f"    {cat:<30s}  " + "  ".join(cells))

    if cov.get("price_coverage_by_category"):
        print(f"\n  % results with visible price:")
        for cat, pct in sorted(
            cov["price_coverage_by_category"].items(),
            key=lambda x: x[1],
        ):
            flag = " ⚠️" if pct < 50 else ""
            print(f"    {cat:<30s}  {pct:>5.1f}%{flag}")

    print(f"\n{'='*70}")
    print("END OF REPORT")
    print(f"{'='*70}\n")

    return all_results


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD BIAS
# ═══════════════════════════════════════════════════════════════════════════

def build_bias_dashboard(df: pd.DataFrame, run_ts: str | None = None) -> Path | None:
    """Dashboard Plotly dedicata all'analisi di bias. Ritorna il path HTML."""
    from datetime import datetime
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = run_ts or datetime.now().strftime("%Y%m%d_%H%M")
    df_priced = df.dropna(subset=["price_value"])
    df_with_seller = df[df["seller"] != ""]

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Seller Concentration (Lorenz curve)",
            "Average position of top sellers",
            "Position distribution for top 5 sellers",
            "Price diversity by category (CoV)",
            "Results per query by category",
            "Sellers in top-3 by frequency",
        ),
        vertical_spacing=0.10,
        horizontal_spacing=0.10,
    )

    # 1. Lorenz curve per concentrazione seller
    seller_counts = df_with_seller.groupby("seller").size().sort_values()
    cumulative = np.cumsum(seller_counts.values) / seller_counts.sum()
    x_pct = np.arange(1, len(cumulative) + 1) / len(cumulative)

    fig.add_trace(
        go.Scatter(x=x_pct, y=cumulative, name="Lorenz", showlegend=False,
                   line=dict(color="#EF553B", width=2)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=[0, 1], y=[0, 1], name="Perfect equality",
                   showlegend=False, line=dict(color="gray", dash="dash")),
        row=1, col=1,
    )

    # 2. Posizione media top seller
    if not df_with_seller.empty:
        seller_pos = (
            df_with_seller.groupby("seller")["position"]
            .agg(["mean", "count"])
        )
        seller_pos = seller_pos[seller_pos["count"] >= 5].nsmallest(15, "mean")
        fig.add_trace(
            go.Bar(
                x=seller_pos["mean"].values,
                y=seller_pos.index,
                orientation="h", showlegend=False, marker_color="#636EFA",
            ),
            row=1, col=2,
        )

    # 3. Box plot posizioni per top 5 seller
    top5_sellers = df_with_seller.groupby("seller").size().nlargest(5).index
    for seller in top5_sellers:
        subset = df_with_seller[df_with_seller["seller"] == seller]
        fig.add_trace(
            go.Box(y=subset["position"], name=seller[:20], showlegend=False),
            row=2, col=1,
        )

    # 4. CoV box plot per categoria (sostituisce bar chart illeggibile con 1364 barre)
    cov_data = []
    for kw, grp in df_priced.groupby("keyword"):
        if len(grp) >= 5 and grp["price_value"].mean() > 0:
            cov_val = grp["price_value"].std() / grp["price_value"].mean()
            cat = grp["category_l1"].iloc[0] if "category_l1" in grp.columns else "Unknown"
            cov_data.append({"keyword": kw, "cov": cov_val, "category": cat})
    if cov_data:
        cov_df = pd.DataFrame(cov_data)
        _box_colors = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3"]
        _categories = sorted(cov_df["category"].unique())
        for _i, _cat in enumerate(_categories):
            _subset = cov_df[cov_df["category"] == _cat]
            fig.add_trace(
                go.Box(
                    y=_subset["cov"].clip(upper=10),
                    name=_cat[:20],
                    marker_color=_box_colors[_i % len(_box_colors)],
                    showlegend=False,
                    boxmean=True,
                ),
                row=2, col=2,
            )

    # 5. Risultati per query per categoria
    results_per_q = (
        df.groupby(["category_l1", "query_id"]).size()
        .reset_index(name="n_results")
    )
    for cat in df["category_l1"].unique():
        subset = results_per_q[results_per_q["category_l1"] == cat]
        fig.add_trace(
            go.Box(y=subset["n_results"], name=cat, showlegend=False),
            row=3, col=1,
        )

    # 6. Top seller in posizioni 1-3
    top3 = df_with_seller[df_with_seller["position"] <= 3]
    top3_counts = top3.groupby("seller").size().nlargest(10).sort_values(ascending=True)
    fig.add_trace(
        go.Bar(
            x=top3_counts.values, y=top3_counts.index,
            orientation="h", showlegend=False, marker_color="#AB63FA",
        ),
        row=3, col=2,
    )

    fig.update_layout(
        height=1400, width=1400,
        title_text="🔍 Bias Analysis — Google Shopping",
        title_x=0.5,
        template="plotly_white",
    )

    html_path = OUTPUT_DIR / f"bias_dashboard_{ts}.html"
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    print(f"📊 Bias dashboard: {html_path}")
    return html_path


# ═══════════════════════════════════════════════════════════════════════════
# EXPORT CSV METRICHE
# ═══════════════════════════════════════════════════════════════════════════

def export_bias_metrics_csv(df: pd.DataFrame, run_ts: str | None = None) -> Path:
    """Esporta le metriche di bias in CSV per ulteriori analisi."""
    from datetime import datetime
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = run_ts or datetime.now().strftime("%Y%m%d_%H%M")

    # Metriche per keyword
    rows = []
    df_priced = df.dropna(subset=["price_value"])
    df_with_seller = df[df["seller"] != ""]

    for kw, grp in df.groupby("keyword"):
        grp_priced = grp.dropna(subset=["price_value"])
        grp_seller = grp[grp["seller"] != ""]

        row = {
            "keyword": kw,
            "category_l1": grp["category_l1"].iloc[0],
            "category_l2": grp["category_l2"].iloc[0],
            "query_type": grp["query_type"].iloc[0],
            "language": grp["language"].iloc[0],
            "n_results": len(grp),
            "n_sellers": grp_seller["seller"].nunique(),
            "price_mean": round(grp_priced["price_value"].mean(), 2) if len(grp_priced) else None,
            "price_std": round(grp_priced["price_value"].std(), 2) if len(grp_priced) > 1 else None,
            "price_cov": round(
                grp_priced["price_value"].std() / grp_priced["price_value"].mean(), 3
            ) if len(grp_priced) > 1 and grp_priced["price_value"].mean() > 0 else None,
            "has_price_pct": round(grp["price_value"].notna().mean() * 100, 1),
        }

        # HHI per seller nella query
        if len(grp_seller) > 0:
            sc = grp_seller.groupby("seller").size()
            shares = sc.values / sc.sum()
            row["seller_hhi"] = round(herfindahl_hirschman_index(shares), 4)
        else:
            row["seller_hhi"] = None

        rows.append(row)

    metrics_df = pd.DataFrame(rows)
    csv_path = OUTPUT_DIR / f"bias_metrics_{ts}.csv"
    metrics_df.to_csv(csv_path, index=False)
    print(f"📄 Metriche bias: {csv_path}")
    return csv_path


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Analisi bias Google Shopping")
    parser.add_argument(
        "--format", "-f", choices=["text", "html", "csv", "all"], default="all",
        help="Formato output (default: all)",
    )
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))
    df = pd.read_sql_query("SELECT * FROM products", conn)
    conn.close()

    if df.empty:
        print("⚠ Database vuoto. Esegui prima la pipeline di scraping.")
        return

    if args.format in ("text", "all"):
        print_bias_report(df)

    if args.format in ("html", "all"):
        build_bias_dashboard(df)

    if args.format in ("csv", "all"):
        export_bias_metrics_csv(df)


if __name__ == "__main__":
    main()
