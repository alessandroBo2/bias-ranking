#!/usr/bin/env python
"""
validate_serpapi.py — Validazione a costo ~zero (free plan) di SerpApi per l'audit.

Verifica, sui TUOI locali, se l'engine google_shopping restituisce davvero le variabili
che ci servono e che oggi mancano:
  - flag SPONSORIZZATO  (campi `tag` / `badge`, oppure blocco shopping ads)
  - product_id          (identità prodotto, per l'analisi within-product)
  - rating / reviews
  - source (venditore), extensions, delivery

Per ogni keyword stampa la copertura dei campi e SALVA la risposta grezza in
`validation_samples/` per ispezione manuale. Usa pochissime chiamate (1 per keyword,
+1 se attivi --with-search), così resti dentro il free plan.

Uso:
    # serve una API key SerpApi free: mettila in .env  ->  SERPAPI_KEY=xxxx
    python validate_serpapi.py
    python validate_serpapi.py --with-search        # interroga anche l'engine 'google' (ads PLA)
    python validate_serpapi.py --kw "scarpe running" "lavatrice" --locale IT

Free plan: ~100 ricerche/mese. Il default (3 kw × 2 locali) = 6 ricerche.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://serpapi.com/search"
SAMPLES_DIR = Path("validation_samples")

# Keyword di default (commerciali, alta probabilità di ads). Modificabili da CLI.
DEFAULT_KEYWORDS = {
    "IT": ["scarpe running", "lavatrice", "smartphone"],
    "DE": ["laufschuhe", "waschmaschine", "smartphone"],
}
LOCALE_PARAMS = {  # gl = paese, hl = lingua
    "IT": {"gl": "it", "hl": "it"},
    "DE": {"gl": "de", "hl": "de"},
    "EN": {"gl": "us", "hl": "en"},
}

# parole che marcano un annuncio in tag/badge (multilingua) — etichette reali di Google
SPONSORED_MARKERS = ("sponsor", "sponsorizz", "annuncio", "anzeige", "gesponsert")


def load_api_key() -> str:
    """Legge SERPAPI_KEY da ambiente o da .env (parser minimale)."""
    key = os.environ.get("SERPAPI_KEY", "")
    if not key:
        env = Path(".env")
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("SERPAPI_KEY") and "=" in line:
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        sys.exit("❌ SERPAPI_KEY mancante. Mettila in .env (SERPAPI_KEY=...) o esportala.")
    return key


def fetch(engine: str, keyword: str, locale: str, api_key: str) -> dict:
    params = {
        "engine": engine,
        "q": keyword,
        "api_key": api_key,
        **LOCALE_PARAMS.get(locale, LOCALE_PARAMS["IT"]),
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "bias-ranking-validator/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _nonempty(v) -> bool:
    return v not in (None, "", [], {}, 0)


def analyze_shopping(data: dict) -> dict:
    """Copertura dei campi chiave su shopping_results + ricerca di marker sponsorizzati."""
    items = data.get("shopping_results", []) or []
    n = len(items)
    fields = ["product_id", "rating", "reviews", "source", "price", "extracted_price",
              "delivery", "extensions", "tag", "badge"]
    cov = {f: sum(1 for it in items if _nonempty(it.get(f))) for f in fields}

    # marker sponsorizzati in tag/badge/extensions
    sponsored = 0
    sample_tags = set()
    for it in items:
        blob = " ".join(str(it.get(k, "")) for k in ("tag", "badge")).lower()
        ext = " ".join(map(str, it.get("extensions", []) or [])).lower()
        for t in (it.get("tag"), it.get("badge")):
            if t:
                sample_tags.add(str(t))
        if any(m in blob or m in ext for m in SPONSORED_MARKERS):
            sponsored += 1

    # blocchi top-level potenzialmente legati agli ads
    ad_keys = [k for k in data.keys()
               if k in ("ads", "shopping_ads", "inline_shopping_results")
               or "sponsor" in k.lower() or "inline_shopping" in k.lower()]

    return {"n": n, "cov": cov, "sponsored": sponsored,
            "sample_tags": sorted(sample_tags)[:8], "ad_keys": ad_keys,
            "top_keys": list(data.keys())}


def report_block(title: str, r: dict) -> None:
    print(f"\n  {title}")
    if r["n"] == 0:
        print("    ⚠ nessun shopping_results (controlla locale/quota)")
        return
    print(f"    items: {r['n']}")
    def pct(k): return f"{r['cov'][k]/r['n']*100:5.1f}%"
    print(f"    product_id {pct('product_id')} | rating {pct('rating')} | reviews {pct('reviews')} "
          f"| source {pct('source')} | delivery {pct('delivery')}")
    print(f"    tag {pct('tag')} | badge {pct('badge')} | extensions {pct('extensions')}")
    print(f"    → SPONSORIZZATI rilevati (marker in tag/badge/extensions): {r['sponsored']}/{r['n']}")
    if r["sample_tags"]:
        print(f"    esempi tag/badge: {r['sample_tags']}")
    if r["ad_keys"]:
        print(f"    blocchi top-level ads-like: {r['ad_keys']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw", nargs="+", help="keyword (override dei default)")
    ap.add_argument("--locale", action="append", choices=["IT", "DE", "EN"],
                    help="locale (ripetibile). Default: IT, DE")
    ap.add_argument("--with-search", action="store_true",
                    help="interroga anche l'engine 'google' (blocco shopping ads / PLA)")
    a = ap.parse_args()

    api_key = load_api_key()
    locales = a.locale or ["IT", "DE"]
    SAMPLES_DIR.mkdir(exist_ok=True)

    calls = 0
    verdict = {}
    for loc in locales:
        kws = a.kw or DEFAULT_KEYWORDS.get(loc, DEFAULT_KEYWORDS["IT"])
        print(f"\n{'='*64}\n  LOCALE {loc}\n{'='*64}")
        spons_any = False; pid_any = False; rating_any = False
        for kw in kws:
            try:
                data = fetch("google_shopping", kw, loc, api_key); calls += 1
            except Exception as e:
                print(f"\n  '{kw}' → errore: {type(e).__name__}: {e}")
                continue
            (SAMPLES_DIR / f"shopping_{loc}_{kw.replace(' ','_')}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            r = analyze_shopping(data)
            report_block(f"[google_shopping] '{kw}'", r)
            spons_any |= r["sponsored"] > 0 or bool(r["ad_keys"])
            pid_any |= r["cov"]["product_id"] > 0
            rating_any |= r["cov"]["rating"] > 0

            if a.with_search:
                try:
                    g = fetch("google", kw, loc, api_key); calls += 1
                    (SAMPLES_DIR / f"search_{loc}_{kw.replace(' ','_')}.json").write_text(
                        json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")
                    inl = g.get("inline_shopping_results") or g.get("shopping_results") or []
                    ads = g.get("ads") or g.get("shopping_ads") or []
                    print(f"    [google] inline_shopping_results: {len(inl)} | ads block: {len(ads)}")
                    spons_any |= len(inl) > 0 or len(ads) > 0
                except Exception as e:
                    print(f"    [google] errore: {type(e).__name__}: {e}")

        verdict[loc] = {"sponsored": spons_any, "product_id": pid_any, "rating": rating_any}

    print(f"\n{'='*64}\n  VERDETTO  (chiamate usate: {calls})\n{'='*64}")
    for loc, v in verdict.items():
        ok = lambda b: "✅" if b else "❌"
        print(f"  {loc}:  sponsorizzato {ok(v['sponsored'])}   "
              f"product_id {ok(v['product_id'])}   rating {ok(v['rating'])}")
    print("\n  Campioni grezzi salvati in validation_samples/ (ispezionabili a mano).")
    print("  Se 'sponsorizzato' è ❌ su google_shopping, rilancia con --with-search per")
    print("  controllare il blocco ads dell'engine 'google'.")


if __name__ == "__main__":
    main()
