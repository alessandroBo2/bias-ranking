"""
pipeline.py — Loads queries from the multilingual CSV, runs scraping via Apify or ScraperAPI.

Expected CSV format:
    query_id,category_l1,category_l2,query_type,Query_EN,Query_IT,Query_DE

Available backends:
    "apify"      — Apify actor burbn/google-shopping-scraper (historical default)
    "scraperapi" — ScraperAPI structured endpoint, with automatic fallback to Apify
                   for failed queries (if apify_token is provided)
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
    Reads the multilingual CSV and returns QuerySpec objects for the chosen language.

    Args:
        csv_path:    path to the CSV
        language:    IT | EN | DE — selects the Query_XX column
        max_results: results per query (default 20)
    """
    lang_col = f"Query_{language.upper()}"
    country = LANG_TO_COUNTRY.get(language.upper(), "IT")

    queries: list[QuerySpec] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if lang_col not in (reader.fieldnames or []):
            available = [c for c in (reader.fieldnames or []) if c.startswith("Query_")]
            raise ValueError(
                f"Column '{lang_col}' not found. Available: {available}"
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
    """Runs a single query on Apify with a concurrency semaphore."""
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

            # Dump raw items for audit/schema debugging
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
    """Runs a batch of queries on Apify."""
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
    Main pipeline: multilingual CSV → list of QueryResult.

    Args:
        csv_path:        path to the CSV
        apify_token:     Apify API token (used by backend="apify" and as fallback)
        language:        IT | EN | DE
        concurrency:     parallel queries
        max_results:     results per query
        backend:         "apify" (default) | "scraperapi"
        scraperapi_key:  ScraperAPI key (required if backend="scraperapi")
    """
    queries = load_queries(csv_path, language=language, max_results=max_results)
    if not queries:
        print("⚠ No queries found in the CSV.")
        return []

    country = LANG_TO_COUNTRY.get(language.upper(), "IT")
    print(f"📋 Loaded {len(queries)} queries from {csv_path}")
    print(f"🌐 Language: {language.upper()} → Country: {country}")
    print(f"🔧 Concurrency: {concurrency} | Max results/query: {max_results}")
    print(f"⚙️  Backend: {backend.upper()}")
    print()

    if backend == "scraperapi":
        if not scraperapi_key:
            raise ValueError("backend='scraperapi' requires scraperapi_key")

        from scraper_api import run_pipeline_sa, print_pipeline_report

        sa_concurrency = max(concurrency, 5)
        results = await run_pipeline_sa(queries, scraperapi_key, concurrency=sa_concurrency)
        print_pipeline_report(results, label="ScraperAPI")

        # Apify fallback for failed queries
        failed_specs = [r.spec for r in results if r.error is not None]
        if failed_specs and apify_token:
            print(f"\n🔄 Apify fallback for {len(failed_specs)} failed queries...")
            fallback_results = await _run_apify_batch(failed_specs, apify_token, concurrency)
            print_pipeline_report(fallback_results, label="Apify fallback")

            # Replace failed results with the fallbacks
            fallback_map = {r.spec.query_id: r for r in fallback_results}
            final: list[QueryResult] = []
            for r in results:
                if r.error is not None and r.spec.query_id in fallback_map:
                    final.append(fallback_map[r.spec.query_id])
                else:
                    final.append(r)
            return final

        return list(results)

    # --- backend == "apify" (historical behavior) ---
    results = await _run_apify_batch(queries, apify_token, concurrency)

    ok = [r for r in results if r.error is None]
    ko = [r for r in results if r.error is not None]
    total_items = sum(len(r.items) for r in ok)

    # max_results is a cap, not a guaranteed target — Google may return fewer
    # if the keyword is poorly indexed for that market.
    partial = [r for r in ok if len(r.items) < r.spec.max_results]

    print(f"\n{'='*60}")
    print(f"✅ Completed: {len(ok)}/{len(results)}")
    print(f"❌ Failed:    {len(ko)}")
    print(f"📦 Products:  {total_items}")
    if ok:
        avg = sum(r.duration_s for r in ok) / len(ok)
        print(f"⏱  Average time: {avg:.1f}s per query")

    for r in ko:
        print(f"   [FAIL] {r.spec.query_id} '{r.spec.keyword}': {r.error}")

    if partial:
        print(f"\n⚠ Partial results ({len(partial)} queries — Google "
              f"returned fewer products than requested):")
        for r in partial:
            print(f"   [{r.spec.language}] '{r.spec.keyword}': "
                  f"{len(r.items)}/{r.spec.max_results} (country={r.spec.country})")
        print("   Note: --max-results is an upper bound, not a target. "
              "Common causes: keyword poorly indexed for the country, "
              "language/keyword incompatible with the market.")

    return list(results)
