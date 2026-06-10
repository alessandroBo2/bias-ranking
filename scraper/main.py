"""
main.py — Entrypoint del product scraper.

Uso:
    # Pipeline da CSV (default: lingua IT)
    python main.py scrape queries_pilot_100.csv
    python main.py scrape queries_pilot_100.csv --lang EN
    python main.py scrape queries_pilot_100.csv --lang DE --concurrency 5

    # Analytics sui dati raccolti
    python main.py analytics
    python main.py analytics --export-only

    # Orchestratore Claude (linguaggio naturale)
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
    """Esegue la pipeline di scraping da CSV."""
    from pipeline import run_pipeline
    from storage import init_db, save_items

    apify_token = os.environ.get("APIFY_TOKEN", "")
    scraperapi_key = os.environ.get("SCRAPERAPI_KEY", "")
    backend = args.backend

    if backend == "scraperapi" and not scraperapi_key:
        print("❌ SCRAPERAPI_KEY mancante nel .env (richiesta per --backend scraperapi)")
        sys.exit(1)
    if backend == "apify" and not apify_token:
        print("❌ APIFY_TOKEN mancante nel .env")
        sys.exit(1)
    if not apify_token and not scraperapi_key:
        print("❌ Nessun token trovato nel .env (APIFY_TOKEN o SCRAPERAPI_KEY)")
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

        print(f"\n💾 {total} prodotti salvati in results.db")
        print("   Esegui 'python main.py analytics' per i grafici.")

    asyncio.run(_run())


def cmd_analytics(args: argparse.Namespace) -> None:
    """Genera analytics e dashboard."""
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
    """Orchestratore Claude: NL → query → scraping → analisi."""
    from orchestrator import orchestrate, interactive_mode

    apify_token = os.environ.get("APIFY_TOKEN", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not apify_token:
        print("❌ APIFY_TOKEN mancante nel .env")
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
        print("Specifica una query o usa --interactive")


def cmd_wizard(args: argparse.Namespace) -> None:
    """Pipeline guidata interattiva per studenti."""
    from wizard import run
    run()


def cmd_gui(args: argparse.Namespace) -> None:
    """Mini GUI tkinter per wizard ed explorer."""
    from gui import launch
    launch()


def cmd_explore(args: argparse.Namespace) -> None:
    """Esplora results.db via terminale."""
    from explore import explore
    explore(
        lang=args.lang,
        cat=args.cat,
        keyword=args.keyword,
        show_runs=args.runs,
        sample=args.sample,
    )


def cmd_bias(args: argparse.Namespace) -> None:
    """Analisi di sbilanciamento Google Shopping."""
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
        description="Pipeline scraping prodotti: Apify + analytics + Claude orchestrator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- scrape ---
    p_scrape = subparsers.add_parser("scrape", help="Scraping da CSV multilingua")
    p_scrape.add_argument("csv", help="Percorso al CSV delle query")
    p_scrape.add_argument(
        "--lang", "-l", default="IT", choices=["IT", "EN", "DE"],
        help="Lingua da usare: IT | EN | DE (default: IT)",
    )
    p_scrape.add_argument(
        "--concurrency", "-c", type=int, default=3,
        help="Query parallele (default: 3)",
    )
    p_scrape.add_argument(
        "--max-results", "-m", type=int, default=20,
        help="Risultati per query (default: 20)",
    )
    p_scrape.add_argument(
        "--backend", "-b", default="scraperapi", choices=["apify", "scraperapi"],
        help="Backend scraping: scraperapi (default) | apify",
    )
    p_scrape.set_defaults(func=cmd_scrape)

    # --- analytics ---
    p_analytics = subparsers.add_parser("analytics", help="Dashboard e analytics")
    p_analytics.add_argument("--export-only", action="store_true")
    p_analytics.set_defaults(func=cmd_analytics)

    # --- ask ---
    p_ask = subparsers.add_parser("ask", help="Chiedi a Claude (orchestratore)")
    p_ask.add_argument("query", nargs="?", help="Cosa cerchi (linguaggio naturale)")
    p_ask.add_argument("--interactive", "-i", action="store_true")
    p_ask.add_argument("--concurrency", "-c", type=int, default=3)
    p_ask.set_defaults(func=cmd_ask)

    # --- wizard ---
    p_wiz = subparsers.add_parser(
        "wizard",
        help="Pipeline guidata interattiva (consigliato per iniziare)",
    )
    p_wiz.set_defaults(func=cmd_wizard)

    # --- explore ---
    p_exp = subparsers.add_parser("explore", help="Esplora results.db via terminale")
    p_exp.add_argument("--lang", "-l", help="Filtra per lingua (IT|EN|DE)")
    p_exp.add_argument("--cat", "-c", help="Filtra per categoria L1")
    p_exp.add_argument("--keyword", "-k", help="Dettaglio prezzi per una keyword")
    p_exp.add_argument("--runs", action="store_true", help="Lista run Apify")
    p_exp.add_argument("--sample", "-s", type=int, metavar="N", help="Mostra N prodotti casuali")
    p_exp.set_defaults(func=cmd_explore)

    # --- gui ---
    p_gui = subparsers.add_parser("gui", help="Mini GUI per wizard ed explorer")
    p_gui.set_defaults(func=cmd_gui)

    # --- bias ---
    p_bias = subparsers.add_parser("bias", help="Analisi sbilanciamento Google Shopping")
    p_bias.add_argument(
        "--format", "-f", choices=["text", "html", "csv", "all"], default="all",
        help="Formato output (default: all)",
    )
    p_bias.set_defaults(func=cmd_bias)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
