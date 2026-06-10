"""
scraper_api.py — Backend ScraperAPI per Google Shopping.

Alternativa ad Apify: usa il structured endpoint di ScraperAPI
(https://api.scraperapi.com/structured/google/shopping) che gestisce
internamente proxy residenziali, fingerprinting e CAPTCHA.

Costo: ~25 crediti/request. Piano Hobby (100k crediti/mese = $29)
copre comodamente 1.200 query (30.000 crediti).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx

from models import QuerySpec, QueryResult, ScrapedItem, parse_price

SCRAPERAPI_SHOPPING_URL = "https://api.scraperapi.com/structured/google/shopping"
RAW_DUMP_DIR = Path("raw")

_LANG_TO_COUNTRY_CODE = {"IT": "it", "EN": "us", "DE": "de"}
_LANG_TO_HL = {"IT": "it", "EN": "en", "DE": "de"}
_LANG_TO_TLD = {"IT": "it", "EN": "com", "DE": "de"}


def _decode_sa_link(link: str) -> str:
    """Estrae l'URL reale dal proxy ScraperAPI, altrimenti restituisce il link as-is."""
    if not link or "api.scraperapi.com" not in link:
        return link
    from urllib.parse import urlparse, parse_qs
    try:
        params = parse_qs(urlparse(link).query)
        return params.get("url", [link])[0]
    except Exception:
        return link


def _sa_item_to_scraped(
    item: dict,
    spec: QuerySpec,
    position: int,
    run_id: str,
) -> ScrapedItem:
    """Converte un item ScraperAPI → ScrapedItem normalizzato."""
    price_raw = item.get("price", "") or ""

    # ScraperAPI fornisce `extracted_price` già parsato — usarlo direttamente
    # evita ambiguità nel formato (es. "1.234,56 €" vs "1,234.56 €").
    ep = item.get("extracted_price")
    if ep is not None:
        try:
            price_value = float(str(ep).replace(",", "."))
            currency = "EUR" if "€" in price_raw else ("USD" if "$" in price_raw else "")
        except (ValueError, TypeError):
            price_value, currency = parse_price(price_raw)
    else:
        price_value, currency = parse_price(price_raw)

    rating = item.get("rating")
    if rating is not None:
        try:
            rating = float(rating)
        except (ValueError, TypeError):
            rating = None

    reviews = item.get("reviews")
    if reviews is not None:
        try:
            reviews = int(str(reviews).replace(",", "").replace(".", "").replace(" ", ""))
        except (ValueError, TypeError):
            reviews = None

    # Scarta i thumbnail base64 (data URI) — sono enormi e inutili per l'analisi
    raw_thumb = item.get("thumbnail", "") or ""
    image_url = "" if raw_thumb.startswith("data:") else raw_thumb

    return ScrapedItem(
        query_id=spec.query_id,
        keyword=spec.keyword,
        language=spec.language,
        title=item.get("title", "N/A"),
        price_raw=price_raw,
        price_value=price_value,
        currency=currency,
        seller=item.get("source", ""),
        rating=rating,
        reviews_count=reviews,
        url=_decode_sa_link(item.get("link", "")),
        image_url=image_url,
        position=position,
        category_l1=spec.category_l1,
        category_l2=spec.category_l2,
        query_type=spec.query_type,
        run_id=run_id,
    )


async def _run_single_query_sa(
    client: httpx.AsyncClient,
    api_key: str,
    spec: QuerySpec,
    semaphore: asyncio.Semaphore,
) -> QueryResult:
    """Esegue una singola query su ScraperAPI con semaforo di concorrenza."""
    async with semaphore:
        t0 = time.monotonic()
        run_id = f"sa_{spec.query_id}_{int(t0 * 1000)}"

        try:
            params = {
                "api_key": api_key,
                "query": spec.keyword,
                "country_code": _LANG_TO_COUNTRY_CODE.get(spec.language, "it"),
                "tld": _LANG_TO_TLD.get(spec.language, "it"),
                "hl": _LANG_TO_HL.get(spec.language, "it"),
                "num": min(spec.max_results, 100),
            }

            resp = await client.get(
                SCRAPERAPI_SHOPPING_URL,
                params=params,
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()

            raw_items: list[dict] = data.get("shopping_results", [])

            RAW_DUMP_DIR.mkdir(exist_ok=True)
            dump_path = RAW_DUMP_DIR / f"{run_id}_raw.json"
            # Rimuovi thumbnail base64 dal dump — riducono la leggibilità senza
            # aggiungere valore analitico (i data URI possono pesare centinaia di KB ciascuno).
            clean_items = [
                {k: v for k, v in it.items()
                 if not (k == "thumbnail" and isinstance(v, str) and v.startswith("data:"))}
                for it in raw_items
            ]
            with open(dump_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "query_id": spec.query_id,
                        "keyword": spec.keyword,
                        "language": spec.language,
                        "source": "scraperapi",
                        "items": clean_items,
                    },
                    fh,
                    ensure_ascii=False,
                    indent=2,
                )

            scraped = [
                _sa_item_to_scraped(item, spec, i + 1, run_id)
                for i, item in enumerate(raw_items)
            ]

            elapsed = time.monotonic() - t0
            return QueryResult(
                spec=spec, items=scraped, run_id=run_id, duration_s=elapsed
            )

        except Exception as exc:
            elapsed = time.monotonic() - t0
            return QueryResult(
                spec=spec, items=[], run_id="", duration_s=elapsed, error=str(exc)
            )


async def run_pipeline_sa(
    queries: list[QuerySpec],
    api_key: str,
    concurrency: int = 5,
) -> list[QueryResult]:
    """
    Esegue una lista di QuerySpec via ScraperAPI.

    Args:
        queries:     lista di query già caricate dal CSV
        api_key:     chiave ScraperAPI
        concurrency: richieste parallele (ScraperAPI regge bene 5-10)
    """
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:
        tasks = [
            _run_single_query_sa(client, api_key, spec, semaphore)
            for spec in queries
        ]
        results = await asyncio.gather(*tasks)

    return list(results)


def print_pipeline_report(results: list[QueryResult], label: str = "ScraperAPI") -> None:
    """Stampa il report sintetico di una pipeline run."""
    ok = [r for r in results if r.error is None]
    ko = [r for r in results if r.error is not None]
    total_items = sum(len(r.items) for r in ok)
    partial = [r for r in ok if r.items and len(r.items) < r.spec.max_results]

    print(f"\n{'='*60}")
    print(f"[{label}] ✅ Completate: {len(ok)}/{len(results)}")
    print(f"[{label}] ❌ Fallite:    {len(ko)}")
    print(f"[{label}] 📦 Prodotti:   {total_items}")
    if ok:
        avg = sum(r.duration_s for r in ok) / len(ok)
        print(f"[{label}] ⏱  Tempo medio: {avg:.1f}s per query")

    for r in ko:
        print(f"   [FAIL] {r.spec.query_id} '{r.spec.keyword}': {r.error}")

    if partial:
        print(f"\n⚠ Risultati parziali ({len(partial)} query):")
        for r in partial:
            print(
                f"   [{r.spec.language}] '{r.spec.keyword}': "
                f"{len(r.items)}/{r.spec.max_results}"
            )
