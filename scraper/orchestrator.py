"""
orchestrator.py — Claude come orchestratore intelligente.

Uso:
    python orchestrator.py "Cerco un notebook gaming sotto 1500€"
    python orchestrator.py --interactive
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
import tempfile
from pathlib import Path

import anthropic

from models import QuerySpec, LANG_TO_COUNTRY
from pipeline import run_pipeline
from storage import init_db, save_items

MODEL = "claude-sonnet-4-20250514"


def _build_query_generation_prompt(user_request: str) -> str:
    return f"""Sei un assistente specializzato in ricerca prodotti su Google Shopping.

L'utente ha fatto questa richiesta:
"{user_request}"

Genera una lista di query di ricerca ottimizzate per Google Shopping.
Le query devono coprire varianti e sinonimi del prodotto.

Rispondi SOLO con un JSON valido, senza markdown né testo aggiuntivo.
Formato:
[
  {{"query_id": "001", "keyword": "...", "language": "IT", "category_l1": "...", "category_l2": "...", "query_type": "generic", "max_results": 20}},
  ...
]

category_l1 deve essere una di: Electronics, Sporting Goods, Apparel & Accessories, Home & Garden, Beauty & Personal Care, Baby & Kids.
query_type: "generic" o "branded".
language: "IT", "EN", o "DE" — scegli in base alla lingua della richiesta.

Genera tra 3 e 8 query, non di più."""


def _build_analysis_prompt(user_request: str, results_summary: str) -> str:
    return f"""You are an expert market analyst.

The user searched for:
"{user_request}"

Results from Google Shopping scraping:
{results_summary}

Produce a structured report in English:
1. **Overview**: products found, price range
2. **Best deals**: top 5 by value for money
3. **Seller analysis**: who offers the best prices
4. **Recommendation**: what to buy and where
5. **Warnings**: suspicious prices or products to avoid

Be concrete. Include prices and links."""


def generate_queries(
    client: anthropic.Anthropic,
    user_request: str,
) -> list[QuerySpec]:
    """Claude genera query strutturate da una richiesta NL."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[
            {"role": "user", "content": _build_query_generation_prompt(user_request)}
        ],
    )

    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
    if raw_text.endswith("```"):
        raw_text = raw_text.rsplit("```", 1)[0]

    queries_data = json.loads(raw_text)
    return [
        QuerySpec(
            query_id=q["query_id"],
            keyword=q["keyword"],
            country=LANG_TO_COUNTRY.get(q.get("language", "IT"), "IT"),
            language=q.get("language", "IT"),
            category_l1=q.get("category_l1", ""),
            category_l2=q.get("category_l2", ""),
            query_type=q.get("query_type", "generic"),
            max_results=q.get("max_results", 20),
        )
        for q in queries_data
    ]


def analyze_results(
    client: anthropic.Anthropic,
    user_request: str,
    results_summary: str,
) -> str:
    """Claude analizza i risultati e produce un report."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[
            {"role": "user", "content": _build_analysis_prompt(user_request, results_summary)}
        ],
    )
    return response.content[0].text


def _results_to_summary(all_items: list) -> str:
    """Sommario testuale dei risultati per l'analisi Claude."""
    if not all_items:
        return "Nessun risultato trovato."

    lines = []
    for item in all_items:
        price_str = f"{item.price_value:.2f}€" if item.price_value else "N/D"
        rating_str = f"★{item.rating:.1f}" if item.rating else ""
        lines.append(
            f"- {item.title[:80]} | {price_str} | {item.seller} | {rating_str} | {item.url}"
        )

    if len(lines) > 150:
        lines = lines[:150]
        lines.append(f"... e altri {len(all_items) - 150} prodotti omessi")

    return "\n".join(lines)


def _queries_to_temp_csv(queries: list[QuerySpec]) -> Path:
    """Scrive le query in un CSV temporaneo nel formato multilingua atteso."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
    )
    writer = csv.DictWriter(
        tmp,
        fieldnames=["query_id", "category_l1", "category_l2", "query_type",
                     "Query_EN", "Query_IT", "Query_DE"],
    )
    writer.writeheader()
    for q in queries:
        row = {
            "query_id": q.query_id,
            "category_l1": q.category_l1,
            "category_l2": q.category_l2,
            "query_type": q.query_type,
            "Query_EN": "", "Query_IT": "", "Query_DE": "",
        }
        row[f"Query_{q.language}"] = q.keyword
        writer.writerow(row)
    tmp.close()
    return Path(tmp.name)


async def orchestrate(
    user_request: str,
    apify_token: str,
    anthropic_key: str | None = None,
    concurrency: int = 3,
) -> str:
    """Flusso completo: NL → query → scraping → analisi → report."""
    kwargs = {}
    if anthropic_key:
        kwargs["api_key"] = anthropic_key
    client = anthropic.Anthropic(**kwargs)

    # Step 1: genera query
    print("🧠 Claude sta generando le query di ricerca...")
    queries = generate_queries(client, user_request)
    print(f"   → {len(queries)} query generate:")
    for q in queries:
        print(f"     [{q.query_id}] {q.keyword} ({q.language})")

    # Step 2: CSV temporaneo → pipeline
    # Raggruppa per lingua ed esegui
    csv_path = _queries_to_temp_csv(queries)
    languages_used = {q.language for q in queries}

    all_results = []
    for lang in languages_used:
        results = await run_pipeline(
            csv_path, apify_token, language=lang, concurrency=concurrency
        )
        all_results.extend(results)

    csv_path.unlink(missing_ok=True)

    # Step 3: salva in DB
    conn = init_db()
    all_items = []
    for r in all_results:
        if r.items:
            save_items(r.items, conn)
            all_items.extend(r.items)
    conn.close()

    # Step 4: analisi con Claude
    print("\n🧠 Claude sta analizzando i risultati...")
    summary = _results_to_summary(all_items)
    report = analyze_results(client, user_request, summary)

    from datetime import datetime
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M")
    report_path = output_dir / f"report_{run_ts}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n📝 Report salvato: {report_path}")

    return report


async def interactive_mode(apify_token: str, anthropic_key: str | None = None) -> None:
    """Modalità interattiva."""
    print("🔍 Product Scraper — Modalità Interattiva")
    print("   Scrivi cosa cerchi, oppure 'quit' per uscire.\n")

    while True:
        try:
            request = input("🛒 Cosa cerchi? > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if request.lower() in ("quit", "exit", "q"):
            break
        if not request:
            continue

        report = await orchestrate(request, apify_token, anthropic_key)
        print(f"\n{'='*60}")
        print(report)
        print(f"{'='*60}\n")


def main() -> None:
    import os
    from dotenv import load_dotenv

    load_dotenv()
    apify_token = os.environ.get("APIFY_TOKEN", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not apify_token:
        print("❌ APIFY_TOKEN non trovato. Configura il file .env")
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        asyncio.run(interactive_mode(apify_token, anthropic_key))
    elif len(sys.argv) > 1:
        request = " ".join(sys.argv[1:])
        report = asyncio.run(orchestrate(request, apify_token, anthropic_key))
        print(f"\n{report}")
    else:
        print("Uso:")
        print('  python orchestrator.py "Cerco un notebook gaming sotto 1500€"')
        print("  python orchestrator.py --interactive")


if __name__ == "__main__":
    main()
