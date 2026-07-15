"""
main.py — Entrypoint of the product scraper.

Usage:
    # Pipeline from CSV (default: language IT)
    python main.py scrape queries_pilot_100.csv
    python main.py scrape queries_pilot_100.csv --lang EN
    python main.py scrape queries_pilot_100.csv --lang DE --concurrency 5

    # Analytics on the collected data
    python main.py analytics
    python main.py analytics --export-only

    # Claude orchestrator (natural language)
    python main.py ask "Cerco un SSD NVMe 2TB sotto 150€"
    python main.py ask --interactive
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv


def cmd_scrape(args: argparse.Namespace) -> None:
    """Runs the scraping pipeline from CSV."""
    from pipeline import run_pipeline
    from storage import init_db, save_items

    apify_token = os.environ.get("APIFY_TOKEN", "")
    scraperapi_key = os.environ.get("SCRAPERAPI_KEY", "")
    backend = args.backend

    if backend == "scraperapi" and not scraperapi_key:
        print("❌ SCRAPERAPI_KEY missing from .env (required for --backend scraperapi)")
        sys.exit(1)
    if backend == "apify" and not apify_token:
        print("❌ APIFY_TOKEN missing from .env")
        sys.exit(1)
    if not apify_token and not scraperapi_key:
        print("❌ No token found in .env (APIFY_TOKEN or SCRAPERAPI_KEY)")
        sys.exit(1)

    async def _run():
        results = await run_pipeline(
            args.csv,
            apify_token,
            language=args.lang,
            concurrency=args.concurrency,
            max_results=args.max_results,
            backend=backend,
            scraperapi_key=scraperapi_key or None,
        )

        conn = init_db()
        total = 0
        for r in results:
            if r.items:
                n = save_items(r.items, conn)
                total += n
        conn.close()

        print(f"\n💾 {total} products saved to results.db")
        print("   Run 'python main.py analytics' for the charts.")

    asyncio.run(_run())


def cmd_analytics(args: argparse.Namespace) -> None:
    """Generates analytics and dashboard."""
    import webbrowser
    from datetime import datetime
    from analytics import load_dataframe, export_parquet, print_summary, build_dashboard

    df = load_dataframe()
    if df.empty:
        return

    run_ts = datetime.now().strftime("%Y%m%d_%H%M")
    export_parquet(df, run_ts=run_ts)
    print_summary(df)

    if not args.export_only:
        html = build_dashboard(df, run_ts=run_ts)
        if html and html.exists():
            webbrowser.open(html.resolve().as_uri())


def cmd_ask(args: argparse.Namespace) -> None:
    """Claude orchestrator: NL → queries → scraping → analysis."""
    from orchestrator import orchestrate, interactive_mode

    apify_token = os.environ.get("APIFY_TOKEN", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not apify_token:
        print("❌ APIFY_TOKEN missing from .env")
        sys.exit(1)

    if args.interactive:
        asyncio.run(interactive_mode(apify_token, anthropic_key))
    elif args.query:
        report = asyncio.run(
            orchestrate(args.query, apify_token, anthropic_key,
                        concurrency=args.concurrency)
        )
        print(f"\n{report}")
    else:
        print("Specify a query or use --interactive")


def cmd_wizard(args: argparse.Namespace) -> None:
    """Interactive guided pipeline for students."""
    from wizard import run
    run()


def cmd_gui(args: argparse.Namespace) -> None:
    """Mini tkinter GUI for wizard and explorer."""
    from gui import launch
    launch()


def cmd_explore(args: argparse.Namespace) -> None:
    """Explore results.db from the terminal."""
    from explore import explore
    explore(
        lang=args.lang,
        cat=args.cat,
        keyword=args.keyword,
        show_runs=args.runs,
        sample=args.sample,
    )


def cmd_bias(args: argparse.Namespace) -> None:
    """Google Shopping bias analysis."""
    import webbrowser
    from datetime import datetime
    from bias_analysis import (
        print_bias_report, build_bias_dashboard, export_bias_metrics_csv,
    )
    from analytics import load_dataframe

    df = load_dataframe()
    if df.empty:
        return

    run_ts = datetime.now().strftime("%Y%m%d_%H%M")
    fmt = args.format
    if fmt in ("text", "all"):
        print_bias_report(df)
    if fmt in ("html", "all"):
        html = build_bias_dashboard(df, run_ts=run_ts)
        if html and html.exists():
            webbrowser.open(html.resolve().as_uri())
    if fmt in ("csv", "all"):
        export_bias_metrics_csv(df, run_ts=run_ts)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="product_scraper",
        description="Product scraping pipeline: Apify + analytics + Claude orchestrator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- scrape ---
    p_scrape = subparsers.add_parser("scrape", help="Scraping from multilingual CSV")
    p_scrape.add_argument("csv", help="Path to the queries CSV")
    p_scrape.add_argument(
        "--lang", "-l", default="IT", choices=["IT", "EN", "DE"],
        help="Language to use: IT | EN | DE (default: IT)",
    )
    p_scrape.add_argument(
        "--concurrency", "-c", type=int, default=3,
        help="Parallel queries (default: 3)",
    )
    p_scrape.add_argument(
        "--max-results", "-m", type=int, default=20,
        help="Results per query (default: 20)",
    )
    p_scrape.add_argument(
        "--backend", "-b", default="scraperapi", choices=["apify", "scraperapi"],
        help="Scraping backend: scraperapi (default) | apify",
    )
    p_scrape.set_defaults(func=cmd_scrape)

    # --- analytics ---
    p_analytics = subparsers.add_parser("analytics", help="Dashboard and analytics")
    p_analytics.add_argument("--export-only", action="store_true")
    p_analytics.set_defaults(func=cmd_analytics)

    # --- ask ---
    p_ask = subparsers.add_parser("ask", help="Ask Claude (orchestrator)")
    p_ask.add_argument("query", nargs="?", help="What you are looking for (natural language)")
    p_ask.add_argument("--interactive", "-i", action="store_true")
    p_ask.add_argument("--concurrency", "-c", type=int, default=3)
    p_ask.set_defaults(func=cmd_ask)

    # --- wizard ---
    p_wiz = subparsers.add_parser(
        "wizard",
        help="Interactive guided pipeline (recommended to get started)",
    )
    p_wiz.set_defaults(func=cmd_wizard)

    # --- explore ---
    p_exp = subparsers.add_parser("explore", help="Explore results.db from the terminal")
    p_exp.add_argument("--lang", "-l", help="Filter by language (IT|EN|DE)")
    p_exp.add_argument("--cat", "-c", help="Filter by L1 category")
    p_exp.add_argument("--keyword", "-k", help="Price detail for a keyword")
    p_exp.add_argument("--runs", action="store_true", help="List Apify runs")
    p_exp.add_argument("--sample", "-s", type=int, metavar="N", help="Show N random products")
    p_exp.set_defaults(func=cmd_explore)

    # --- gui ---
    p_gui = subparsers.add_parser("gui", help="Mini GUI for wizard and explorer")
    p_gui.set_defaults(func=cmd_gui)

    # --- bias ---
    p_bias = subparsers.add_parser("bias", help="Google Shopping bias analysis")
    p_bias.add_argument(
        "--format", "-f", choices=["text", "html", "csv", "all"], default="all",
        help="Output format (default: all)",
    )
    p_bias.set_defaults(func=cmd_bias)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
