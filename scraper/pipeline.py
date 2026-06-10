"""
pipeline.py — Carica query dal CSV multilingua, esegue scraping via Apify o ScraperAPI.

Formato CSV atteso:
    query_id,category_l1,category_l2,query_type,Query_EN,Query_IT,Query_DE

Backend disponibili:
    "apify"      — Apify actor burbn/google-shopping-scraper (default storico)
    "scraperapi" — ScraperAPI structured endpoint, con fallback automatico su Apify
                   per le query fallite (se apify_token è fornito)
"""
from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path

from apify_client import ApifyClientAsync

from models import QuerySpec, QueryResult, raw_item_to_scraped, LANG_TO_COUNTRY

GOOGLE_SHOPPING_ACTOR = "burbn/google-shopping-scraper"
RAW_DUMP_DIR = Path("raw")


def load_queries(
    csv_path: str | Path,
    language: str = "IT",
    max_results: int = 20,
) -> list[QuerySpec]:
    """
    Legge il CSV multilingua e restituisce QuerySpec per la lingua scelta.

    Args:
        csv_path:    percorso al CSV
        language:    IT | EN | DE — seleziona la colonna Query_XX
        max_results: risultati per query (default 20)
    """
    lang_col = f"Query_{language.upper()}"
    country = LANG_TO_COUNTRY.get(language.upper(), "IT")

    queries: list[QuerySpec] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if lang_col not in (reader.fieldnames or []):
            available = [c for c in (reader.fieldnames or []) if c.startswith("Query_")]
            raise ValueError(
                f"Colonna '{lang_col}' non trovata. Disponibili: {available}"
            )

        for row in reader:
            keyword = row[lang_col].strip()
            if not keyword:
                continue

            queries.append(
                QuerySpec(
                    query_id=row["query_id"].strip(),
                    keyword=keyword,
                    country=country,
                    language=language.upper(),
                    category_l1=row.get("category_l1", "").strip(),
                    category_l2=row.get("category_l2", "").strip(),
                    query_type=row.get("query_type", "generic").strip(),
                    max_results=max_results,
                )
            )
    return queries


async def _run_single_query(
    client: ApifyClientAsync,
    spec: QuerySpec,
    semaphore: asyncio.Semaphore,
) -> QueryResult:
    """Esegue una singola query su Apify con semaforo di concorrenza."""
    async with semaphore:
        t0 = time.monotonic()
        try:
            run = await client.actor(GOOGLE_SHOPPING_ACTOR).call(
                run_input={
                    "searchQuery": spec.keyword,
                    "country": spec.country.lower(),
                    "language": spec.language.lower(),
                    "limit": spec.max_results,
                }
            )

            run_id = run["id"]
            dataset = client.dataset(run["defaultDatasetId"])

            raw_items: list[dict] = []
            async for item in dataset.iterate_items():
                raw_items.append(item)

            # Dump raw items per audit/debug schema
            RAW_DUMP_DIR.mkdir(exist_ok=True)
            dump_path = RAW_DUMP_DIR / f"{run_id}_raw.json"
            with open(dump_path, "w", encoding="utf-8") as f:
                import json as _json
                _json.dump(
                    {"query_id": spec.query_id, "keyword": spec.keyword,
                     "language": spec.language, "items": raw_items},
                    f, ensure_ascii=False, indent=2,
                )

            scraped = [
                raw_item_to_scraped(raw, spec, i + 1, run_id)
                for i, raw in enumerate(raw_items)
            ]

            elapsed = time.monotonic() - t0
            return QueryResult(
                spec=spec, items=scraped, run_id=run_id, duration_s=elapsed
            )

        except Exception as exc:
            elapsed = time.monotonic() - t0
            return QueryResult(
                spec=spec, items=[], run_id="", duration_s=elapsed,
                error=str(exc),
            )


async def _run_apify_batch(
    queries: list[QuerySpec],
    apify_token: str,
    concurrency: int,
) -> list[QueryResult]:
    """Esegue un batch di query su Apify."""
    client = ApifyClientAsync(token=apify_token)
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [_run_single_query(client, spec, semaphore) for spec in queries]
    return list(await asyncio.gather(*tasks))


async def run_pipeline(
    csv_path: str | Path,
    apify_token: str,
    language: str = "IT",
    concurrency: int = 3,
    max_results: int = 20,
    backend: str = "apify",
    scraperapi_key: str | None = None,
) -> list[QueryResult]:
    """
    Pipeline principale: CSV multilingua → lista di QueryResult.

    Args:
        csv_path:        percorso al CSV
        apify_token:     token API Apify (usato da backend="apify" e come fallback)
        language:        IT | EN | DE
        concurrency:     query parallele
        max_results:     risultati per query
        backend:         "apify" (default) | "scraperapi"
        scraperapi_key:  chiave ScraperAPI (richiesta se backend="scraperapi")
    """
    queries = load_queries(csv_path, language=language, max_results=max_results)
    if not queries:
        print("⚠ Nessuna query trovata nel CSV.")
        return []

    country = LANG_TO_COUNTRY.get(language.upper(), "IT")
    print(f"📋 Caricate {len(queries)} query da {csv_path}")
    print(f"🌐 Lingua: {language.upper()} → Country: {country}")
    print(f"🔧 Concorrenza: {concurrency} | Max risultati/query: {max_results}")
    print(f"⚙️  Backend: {backend.upper()}")
    print()

    if backend == "scraperapi":
        if not scraperapi_key:
            raise ValueError("backend='scraperapi' richiede scraperapi_key")

        from scraper_api import run_pipeline_sa, print_pipeline_report

        sa_concurrency = max(concurrency, 5)
        results = await run_pipeline_sa(queries, scraperapi_key, concurrency=sa_concurrency)
        print_pipeline_report(results, label="ScraperAPI")

        # Fallback Apify per le query fallite
        failed_specs = [r.spec for r in results if r.error is not None]
        if failed_specs and apify_token:
            print(f"\n🔄 Fallback Apify per {len(failed_specs)} query fallite...")
            fallback_results = await _run_apify_batch(failed_specs, apify_token, concurrency)
            print_pipeline_report(fallback_results, label="Apify fallback")

            # Sostituisci i risultati falliti con i fallback
            fallback_map = {r.spec.query_id: r for r in fallback_results}
            final: list[QueryResult] = []
            for r in results:
                if r.error is not None and r.spec.query_id in fallback_map:
                    final.append(fallback_map[r.spec.query_id])
                else:
                    final.append(r)
            return final

        return list(results)

    # --- backend == "apify" (comportamento storico) ---
    results = await _run_apify_batch(queries, apify_token, concurrency)

    ok = [r for r in results if r.error is None]
    ko = [r for r in results if r.error is not None]
    total_items = sum(len(r.items) for r in ok)

    # max_results è un cap, non un target garantito — Google può restituire meno
    # se la keyword è poco indicizzata per quel mercato.
    partial = [r for r in ok if len(r.items) < r.spec.max_results]

    print(f"\n{'='*60}")
    print(f"✅ Completate: {len(ok)}/{len(results)}")
    print(f"❌ Fallite:    {len(ko)}")
    print(f"📦 Prodotti:   {total_items}")
    if ok:
        avg = sum(r.duration_s for r in ok) / len(ok)
        print(f"⏱  Tempo medio: {avg:.1f}s per query")

    for r in ko:
        print(f"   [FAIL] {r.spec.query_id} '{r.spec.keyword}': {r.error}")

    if partial:
        print(f"\n⚠ Risultati parziali ({len(partial)} query — Google ha "
              f"restituito meno prodotti di quelli richiesti):")
        for r in partial:
            print(f"   [{r.spec.language}] '{r.spec.keyword}': "
                  f"{len(r.items)}/{r.spec.max_results} (country={r.spec.country})")
        print("   Nota: --max-results è un upper bound, non un target. "
              "Cause comuni: keyword poco indicizzata sul country, "
              "lingua/keyword incompatibile col mercato.")

    return list(results)
