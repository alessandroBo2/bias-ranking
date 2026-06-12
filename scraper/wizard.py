"""
wizard.py — Interactive guided pipeline for students.

Flow: CSV choice → query filtering → cost estimate → confirmation →
        scrape → analytics → bias → Claude's didactic commentary.

Usage:
    python main.py wizard

Zero additional dependencies: uses only stdlib input().
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


# ─── burbn pricing (USD) — see the actor's pricingPerEvent ────────────
COST_START = 0.008
COST_PER_RESULT_FREE = 0.020
COST_PER_RESULT_BRONZE = 0.005


# ═══════════════════════════════════════════════════════════════════════
# UI helpers (zero deps)
# ═══════════════════════════════════════════════════════════════════════

def header(title: str) -> None:
    bar = "═" * 64
    print(f"\n{bar}\n  {title}\n{bar}")


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        s = input(f"  {prompt}{suffix}: ").strip()
        if s:
            return s
        if default is not None:
            return default
        print("  ⚠ Answer required.")


def ask_yesno(prompt: str, default: bool = True) -> bool:
    d = "y" if default else "n"
    s = ask(f"{prompt} (y/n)", default=d).lower()
    return s in ("y", "yes", "true", "1")


def ask_int(prompt: str, default: int, min_v: int = 1, max_v: int = 10_000) -> int:
    while True:
        s = ask(prompt, default=str(default))
        try:
            n = int(s)
        except ValueError:
            print("  ⚠ You must enter an integer.")
            continue
        if not (min_v <= n <= max_v):
            print(f"  ⚠ Value out of range [{min_v}-{max_v}].")
            continue
        return n


def ask_choice(prompt: str, options: list[str], default: str | None = None) -> str:
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        marker = "  ← default" if opt == default else ""
        print(f"    [{i}] {opt}{marker}")
    while True:
        s = input("  Choice (number): ").strip()
        if not s and default is not None:
            return default
        try:
            i = int(s)
            if 1 <= i <= len(options):
                return options[i - 1]
        except ValueError:
            pass
        print(f"  ⚠ Enter a number from 1 to {len(options)}.")


def ask_multichoice(prompt: str, options: list[str],
                    defaults: list[str] | None = None) -> list[str]:
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        marker = "  ← default" if defaults and opt in defaults else ""
        print(f"    [{i}] {opt}{marker}")
    default_idx = (
        ",".join(str(options.index(x) + 1) for x in defaults) if defaults else ""
    )
    while True:
        s = input(f"  Choices (comma-separated numbers, default {default_idx}): ").strip()
        if not s and defaults:
            return list(defaults)
        try:
            indices = [int(x.strip()) for x in s.split(",")]
            chosen = [options[i - 1] for i in indices if 1 <= i <= len(options)]
            if chosen:
                return chosen
        except ValueError:
            pass
        print("  ⚠ Enter valid comma-separated numbers.")


# ═══════════════════════════════════════════════════════════════════════
# Step 1 — CSV selection
# ═══════════════════════════════════════════════════════════════════════

def select_csv() -> Path:
    csvs = sorted(p for p in Path(".").glob("queries_*.csv")
                  if not p.name.startswith("_"))
    if not csvs:
        print("  ❌ No 'queries_*.csv' file found in the current folder.")
        sys.exit(1)
    options = [str(c) for c in csvs]
    chosen = ask_choice("Which queries CSV do you want to use?", options, default=options[0])
    return Path(chosen)


# ═══════════════════════════════════════════════════════════════════════
# Step 2 — query filtering
# ═══════════════════════════════════════════════════════════════════════

def filter_queries(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    print(f"\n  📋 Loaded {csv_path}: {len(df)} total queries")
    print(f"     L1 categories: {sorted(df['category_l1'].unique())}")
    print(f"     Query types: {sorted(df['query_type'].unique())}")

    cats = ["(all)"] + sorted(df["category_l1"].unique().tolist())
    cat = ask_choice("Filter by L1 category", cats, default="(all)")
    if cat != "(all)":
        df = df[df["category_l1"] == cat]

    types = ["(all)"] + sorted(df["query_type"].unique().tolist())
    qt = ask_choice("Filter by query type", types, default="(all)")
    if qt != "(all)":
        df = df[df["query_type"] == qt]

    df = df.reset_index(drop=True)
    print(f"\n  ✓ {len(df)} queries after filtering.")

    if df.empty:
        return df

    max_n = len(df)
    n = ask_int(
        f"How many queries do you want from the top of the list? (max {max_n})",
        default=min(3, max_n), min_v=1, max_v=max_n,
    )
    df = df.head(n)

    print(f"\n  📋 Preview:")
    for _, row in df.iterrows():
        keywords = next(
            (str(v).strip() for col in ("Query_IT", "Query_EN", "Query_DE")
             if (v := row.get(col)) and str(v).strip() not in ("", "nan")),
            "?",
        )
        print(f"    [{row['query_id']}] {keywords[:50]:<50}  "
              f"({row['category_l1']}, {row['query_type']})")

    return df


# ═══════════════════════════════════════════════════════════════════════
# Step 3 — scrape configuration + estimate
# ═══════════════════════════════════════════════════════════════════════

def configure_scrape(df_q: pd.DataFrame) -> tuple[list[str], int, int]:
    languages = ask_multichoice(
        "Which languages do you want to scrape?",
        options=["IT", "EN", "DE"], defaults=["IT"],
    )
    print()
    print("  ℹ️  Note on results per query:")
    print("     • The Apify actor (burbn) enforces a minimum of 20 results per call.")
    print("     • You cannot request fewer: values < 20 are rejected by the API.")
    print("     • To save credits, reduce the NUMBER OF QUERIES,")
    print("       not the results per query.")
    print("     • The value you enter is a maximum CAP: Google may return")
    print("       fewer if the keyword is poorly indexed in the chosen market.")
    print()
    max_results = ask_int(
        "Results per query (min 20, imposed by Apify)",
        default=20, min_v=20, max_v=100,
    )
    concurrency = ask_int(
        "Concurrency (parallel queries)",
        default=3, min_v=1, max_v=10,
    )

    n_calls = len(df_q) * len(languages)
    cost_free = n_calls * (COST_START + max_results * COST_PER_RESULT_FREE)
    cost_bronze = n_calls * (COST_START + max_results * COST_PER_RESULT_BRONZE)

    header("Apify COST ESTIMATE (burbn actor)")
    print(f"  Total calls: {n_calls} = {len(df_q)} queries × {len(languages)} languages")
    print(f"  Results per query: {max_results} (max — Google may return fewer)")
    print(f"  ────────────────────────────────────────")
    print(f"  FREE tier cost:                  ${cost_free:6.2f}")
    print(f"  BRONZE cost (Starter $49/month): ${cost_bronze:6.2f}")
    print(f"  ────────────────────────────────────────")
    print(f"  ⚠ Free tier: $5/month credit; beyond that, the actor won't start.")
    print(f"  💡 For cheap tests: pick few queries (2-5) at 20 results.")

    if not ask_yesno("\n  Proceed with these parameters?", default=True):
        print("  ⛔ Cancelled by the user.")
        sys.exit(0)

    return languages, max_results, concurrency


# ═══════════════════════════════════════════════════════════════════════
# Step 4 — execution
# ═══════════════════════════════════════════════════════════════════════

def run_scrapes(df_q: pd.DataFrame, languages: list[str],
                max_results: int, concurrency: int) -> int:
    from pipeline import run_pipeline
    from storage import init_db, save_items

    apify_token = os.environ.get("APIFY_TOKEN", "")
    if not apify_token:
        print("  ❌ APIFY_TOKEN missing in .env")
        sys.exit(1)

    tmp_csv = Path("_wizard_selection.csv")
    df_q.to_csv(tmp_csv, index=False)

    total_saved = 0
    try:
        for lang in languages:
            header(f"4. SCRAPE — language {lang}")
            results = asyncio.run(run_pipeline(
                tmp_csv, apify_token,
                language=lang,
                concurrency=concurrency,
                max_results=max_results,
            ))
            conn = init_db()
            for r in results:
                if r.items:
                    total_saved += save_items(r.items, conn)
            conn.close()
    finally:
        tmp_csv.unlink(missing_ok=True)

    return total_saved


# ═══════════════════════════════════════════════════════════════════════
# Step 5 — analytics + bias
# ═══════════════════════════════════════════════════════════════════════

def run_analysis() -> tuple[str, "pd.DataFrame"]:
    """Runs analytics + bias. Returns (run_ts, df) for use in claude_commentary."""
    import webbrowser
    from datetime import datetime
    from analytics import (
        load_dataframe, export_parquet, print_summary, build_dashboard,
    )
    from bias_analysis import (
        print_bias_report, build_bias_dashboard, export_bias_metrics_csv,
    )

    run_ts = datetime.now().strftime("%Y%m%d_%H%M")

    header("5. ANALYTICS")
    df = load_dataframe()
    if df.empty:
        print("  ⚠ Empty DB, nothing to analyze.")
        return run_ts, df
    export_parquet(df, run_ts=run_ts)
    print_summary(df)
    html_analytics = build_dashboard(df, run_ts=run_ts)
    if html_analytics and html_analytics.exists():
        webbrowser.open(html_analytics.resolve().as_uri())
        print(f"  🌐 Dashboard opened in the browser: {html_analytics}")

    header("6. BIAS ANALYSIS")
    print_bias_report(df)
    html_bias = build_bias_dashboard(df, run_ts=run_ts)
    export_bias_metrics_csv(df, run_ts=run_ts)
    if html_bias and html_bias.exists():
        webbrowser.open(html_bias.resolve().as_uri())
        print(f"  🌐 Bias dashboard opened in the browser: {html_bias}")

    return run_ts, df


# ═══════════════════════════════════════════════════════════════════════
# Step 6 — Claude didactic commentary
# ═══════════════════════════════════════════════════════════════════════

def claude_commentary(run_ts: str | None = None) -> None:
    header("7. DIDACTIC COMMENTARY (Claude)")
    if not ask_yesno("Do you want a Claude commentary on the results?", default=True):
        print("  ⏭ Skipped.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ⚠ ANTHROPIC_API_KEY not present in .env, skip.")
        return

    from anthropic import Anthropic
    from analytics import load_dataframe
    from bias_analysis import (
        seller_concentration_analysis, position_bias_analysis,
        cross_language_analysis, price_diversity_analysis,
        category_coverage_analysis,
    )

    df = load_dataframe()
    if df.empty:
        return

    summary = {
        "n_products": int(len(df)),
        "n_queries": int(df["keyword"].nunique()),
        "languages": sorted(df["language"].unique().tolist()),
        "categories_l1": sorted(df["category_l1"].unique().tolist()),
        "categories_l2": sorted(df["category_l2"].unique().tolist()),
        "concentration": seller_concentration_analysis(df),
        "position_bias": position_bias_analysis(df),
        "cross_language": cross_language_analysis(df),
        "price_diversity": price_diversity_analysis(df),
        "category_coverage": category_coverage_analysis(df),
    }
    summary_json = json.dumps(summary, indent=2, default=str, ensure_ascii=False)

    prompt = f"""You are a didactic assistant for a student learning the analysis
of bias in search-engine results (Google Shopping).

I'm giving you the output of an analysis on a dataset of scraped products.
Write a DIDACTIC and CLEAR commentary (max 600 words) in English:

1. Summarize the dataset's key numbers (volume, coverage, languages, categories).
2. Explain what the concentration metrics (HHI, Gini, CR-k) indicate
   in THIS specific case, putting the numbers in context.
3. If there is significant cross-language price disparity, highlight it
   and try to explain the possible causes (local market, currency,
   Google's positioning, sample size).
4. Identify any price "filter bubbles" (low CoV) and what
   they mean in practice.
5. Conclude with 2-3 limitations of the current dataset and what to add
   (more queries, more languages, more categories) to make it more robust.

Language: friendly but rigorous, no unexplained jargon.
Output: plain Markdown text, no preamble ("Here's the commentary..."),
ready to paste into a report.

Analysis data (JSON):
```json
{summary_json}
```
"""
    print("  💬 Asking Claude to comment on the results...")
    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    commentary = msg.content[0].text

    from datetime import datetime
    ts = run_ts or datetime.now().strftime("%Y%m%d_%H%M")
    out = Path("output") / f"report_{ts}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(commentary, encoding="utf-8")

    in_tok = msg.usage.input_tokens
    out_tok = msg.usage.output_tokens
    # Haiku 4.5: $1/Mtok input, $5/Mtok output (approx, see official pricing)
    cost = in_tok / 1_000_000 * 1.0 + out_tok / 1_000_000 * 5.0

    print(f"\n  📄 Commentary saved to {out}")
    print(f"  💵 Tokens: {in_tok} in / {out_tok} out  (~${cost:.4f} with Claude Haiku 4.5)")
    print()
    print("  " + "─" * 60)
    for line in commentary.splitlines():
        print(f"  {line}")
    print("  " + "─" * 60)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def _db_product_count() -> int:
    """Returns the number of products currently in results.db (0 if it doesn't exist)."""
    db = Path("results.db")
    if not db.exists():
        return 0
    try:
        import sqlite3
        conn = sqlite3.connect(str(db))
        n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return 0


def run() -> None:
    load_dotenv()

    header("WIZARD — Guided Product Scraper")
    print("  I'll take you step by step from query choice → scrape → analysis → commentary.")
    print("  Press Ctrl+C at any time to exit.")

    # If the DB already has data, offer "analysis only" mode
    n_existing = _db_product_count()
    skip_scrape = False
    if n_existing > 0:
        print(f"\n  ℹ️  results.db already contains {n_existing} products.")
        skip_scrape = ask_yesno(
            "Do you want to skip scraping and work only on analyzing the existing data?",
            default=False,
        )

    if not skip_scrape:
        header("1. Input CSV choice")
        csv_path = select_csv()

        header("2. Query filtering")
        df_q = filter_queries(csv_path)
        if df_q.empty:
            print("  ⚠ No query selected, exiting.")
            return

        header("3. Scrape configuration")
        languages, max_results, concurrency = configure_scrape(df_q)

        n_saved = run_scrapes(df_q, languages, max_results, concurrency)
        print(f"\n  ✅ New products saved to results.db: {n_saved}")
    else:
        print(f"\n  ⏭ Scraping skipped — using the {n_existing} existing products.")

    run_ts, _ = run_analysis()
    claude_commentary(run_ts=run_ts)

    header("GENERATED FILES SUMMARY")
    out_dir = Path("output")
    if out_dir.exists():
        for f in sorted(out_dir.glob("*")):
            size_kb = f.stat().st_size / 1024
            print(f"    • {f}  ({size_kb:.1f} KB)")
    print("\n  ✓ Guided pipeline completed.\n")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n  ⛔ Interrupted by the user.\n")
        sys.exit(130)
