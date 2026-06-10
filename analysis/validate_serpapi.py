#!/usr/bin/env python
"""
validate_serpapi.py — Validazione a costo ~zero (free plan) di SerpApi per l'audit.

google_shopping  -> risultati ORGANICI dello Shopping tab (product_id, rating, source...).
google + location -> per scoprire gli SPONSORIZZATI: PLA shopping (shopping_results/
                     immersive_products) e text ads (ads). Senza `location`/`google_domain`
                     Google non serve gli ads -> per questo prima tornava 0.

Stampa la copertura dei campi e SALVA i grezzi in validation_samples/.
Poche chiamate: 1/keyword su google_shopping (+1 con --with-search).

Uso:
    python validate_serpapi.py
    python validate_serpapi.py --with-search           # interroga anche 'google' con location
    python validate_serpapi.py --kw smartphone --locale IT --with-search
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.parse, urllib.request
from pathlib import Path

ENDPOINT = "https://serpapi.com/search"
SAMPLES_DIR = Path("validation_samples")

DEFAULT_KEYWORDS = {
    "IT": ["scarpe running", "lavatrice", "smartphone"],
    "DE": ["laufschuhe", "waschmaschine", "smartphone"],
    "EN": ["running shoes", "washing machine", "smartphone"],
}
LOCALE_PARAMS = {  # gl=paese, hl=lingua, google_domain, location (city-level, consigliata da SerpApi)
    "IT": {"gl": "it", "hl": "it", "google_domain": "google.it", "location": "Milan, Lombardy, Italy"},
    "DE": {"gl": "de", "hl": "de", "google_domain": "google.de", "location": "Berlin, Germany"},
    "EN": {"gl": "us", "hl": "en", "google_domain": "google.com", "location": "New York, NY, United States"},
}
SPONSORED_MARKERS = ("sponsor", "sponsorizz", "annuncio", "anzeige", "gesponsert")


def load_api_key() -> str:
    key = os.environ.get("SERPAPI_KEY", "")
    if not key and Path(".env").exists():
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SERPAPI_KEY") and "=" in line:
                key = line.split("=", 1)[1].strip().strip('"').strip("'"); break
    if not key:
        sys.exit("SERPAPI_KEY mancante. Mettila in .env (SERPAPI_KEY=...) o esportala.")
    return key


def fetch(engine: str, keyword: str, locale: str, api_key: str, with_location: bool) -> dict:
    p = LOCALE_PARAMS.get(locale, LOCALE_PARAMS["IT"])
    params = {"engine": engine, "q": keyword, "api_key": api_key,
              "gl": p["gl"], "hl": p["hl"], "google_domain": p["google_domain"]}
    if with_location:                     # location serve all'engine 'google' per far comparire gli ads
        params["location"] = p["location"]
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "bias-ranking-validator/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _nonempty(v) -> bool:
    return v not in (None, "", [], {}, 0)


def analyze_shopping(data: dict) -> dict:
    items = data.get("shopping_results", []) or []
    n = len(items)
    fields = ["product_id", "rating", "reviews", "source", "price", "delivery", "tag", "badge", "extensions"]
    cov = {f: sum(1 for it in items if _nonempty(it.get(f))) for f in fields}
    sponsored = 0; tags = set()
    for it in items:
        blob = (str(it.get("tag", "")) + " " + str(it.get("badge", "")) + " " +
                " ".join(map(str, it.get("extensions", []) or []))).lower()
        for t in (it.get("tag"), it.get("badge")):
            if t: tags.add(str(t))
        if any(m in blob for m in SPONSORED_MARKERS): sponsored += 1
    return {"n": n, "cov": cov, "sponsored": sponsored, "tags": sorted(tags)[:8]}


def report_shopping(title: str, r: dict) -> None:
    print(f"\n  {title}")
    if r["n"] == 0:
        print("    nessun shopping_results (controlla locale/quota)"); return
    n = r["n"]; pct = lambda k: f"{r['cov'][k]/n*100:5.1f}%"
    print(f"    items: {n}  | product_id {pct('product_id')} rating {pct('rating')} "
          f"source {pct('source')} delivery {pct('delivery')}")
    print(f"    tag {pct('tag')} badge {pct('badge')} -> sponsorizzati(marker): {r['sponsored']}/{n}")
    if r["tags"]: print(f"    esempi tag/badge: {r['tags']}")


def inspect_google(g: dict) -> dict:
    """Cerca gli ADS nell'engine 'google' e verifica se gli item sono DAVVERO sponsorizzati."""
    blocks = {k: len(g.get(k) or []) for k in
              ["shopping_results", "immersive_products", "ads", "product_results"]}
    relevant = [k for k in g.keys()
                if any(s in k.lower() for s in ("shopping", "ads", "product", "immersive"))]
    # cerca marker sponsorizzati DENTRO gli item, e raccogli le chiavi di un item campione
    pool = (g.get("immersive_products") or []) + (g.get("shopping_results") or []) + (g.get("ads") or [])
    marked = 0; sample_keys = []
    for it in pool:
        if isinstance(it, dict):
            if not sample_keys:
                sample_keys = sorted(it.keys())
            blob = json.dumps(it, ensure_ascii=False).lower()
            if any(m in blob for m in SPONSORED_MARKERS):
                marked += 1
    return {"blocks": blocks, "relevant_keys": relevant,
            "marked_sponsored": marked, "sample_item_keys": sample_keys}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw", nargs="+")
    ap.add_argument("--locale", action="append", choices=["IT", "DE", "EN"])
    ap.add_argument("--with-search", action="store_true")
    a = ap.parse_args()

    api_key = load_api_key()
    locales = a.locale or ["IT", "DE"]
    SAMPLES_DIR.mkdir(exist_ok=True)
    calls = 0; verdict = {}

    for loc in locales:
        kws = a.kw or DEFAULT_KEYWORDS.get(loc, DEFAULT_KEYWORDS["IT"])
        print(f"\n{'='*64}\n  LOCALE {loc}\n{'='*64}")
        spons = pid = rat = False
        for kw in kws:
            try:
                d = fetch("google_shopping", kw, loc, api_key, with_location=True); calls += 1
            except Exception as e:
                print(f"  '{kw}' -> errore: {type(e).__name__}: {e}"); continue
            (SAMPLES_DIR / f"shopping_{loc}_{kw.replace(' ','_')}.json").write_text(
                json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            r = analyze_shopping(d)
            report_shopping(f"[google_shopping] '{kw}'", r)
            pid |= r["cov"]["product_id"] > 0
            rat |= r["cov"]["rating"] > 0
            spons |= r["sponsored"] > 0

            if a.with_search:
                try:
                    g = fetch("google", kw, loc, api_key, with_location=True); calls += 1
                    (SAMPLES_DIR / f"search_{loc}_{kw.replace(' ','_')}.json").write_text(
                        json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")
                    gi = inspect_google(g)
                    b = gi["blocks"]
                    print(f"    [google +location] shopping_results={b['shopping_results']} "
                          f"immersive_products={b['immersive_products']} ads(text)={b['ads']}")
                    print(f"      marker 'Sponsored' negli item: {gi['marked_sponsored']} | "
                          f"chiavi item: {gi['sample_item_keys'][:14]}")
                    spons |= gi["marked_sponsored"] > 0   # solo marker REALE, non semplice presenza
                except Exception as e:
                    print(f"    [google] errore: {type(e).__name__}: {e}")
        verdict[loc] = {"sponsored": spons, "product_id": pid, "rating": rat}

    print(f"\n{'='*64}\n  VERDETTO  (chiamate: {calls})\n{'='*64}")
    ok = lambda b: "OK " if b else "-- "
    for loc, v in verdict.items():
        print(f"  {loc}:  sponsorizzato {ok(v['sponsored'])}  product_id {ok(v['product_id'])}  "
              f"rating {ok(v['rating'])}")
    print("\n  Grezzi in validation_samples/. Se 'sponsorizzato' resta a -- anche con --with-search,")
    print("  apri un search_*.json e guarda 'chiavi rilevanti' per capire dove Google mette gli ads.")


if __name__ == "__main__":
    main()
