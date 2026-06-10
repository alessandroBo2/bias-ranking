#!/usr/bin/env python
"""
serpapi_shopping.py — Scraper di produzione su SerpApi (engine google_shopping).

Raccoglie l'organico dello Shopping tab con schema RICCO (product_id, rating, reviews,
source, delivery, tag) per l'audit di bias. Una ricerca SerpApi = una SERP (40 risultati).

Caratteristiche pensate per non sprecare budget:
  - --estimate : stima a secco quante ricerche servono (NESSUNA chiamata, $0).
  - resumable  : salva i (query_id, locale) completati; un re-run riparte da dove era.
  - --max-searches : tetto di sicurezza per non sforare il piano (es. 4900).
  - conta solo le ricerche andate a buon fine; su errore quota si ferma pulito.

Solo stdlib (urllib + sqlite3): nessuna dipendenza da installare.

Esempi:
  python serpapi_shopping.py --csv queries_5000.csv --locale IT --estimate
  python serpapi_shopping.py --csv queries_5000.csv --locale IT --db results_serpapi.db
  python serpapi_shopping.py --csv queries_5000.csv --locale IT --limit 100   # pilota
"""
from __future__ import annotations
import argparse, csv, json, os, sqlite3, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://serpapi.com/search"
LOCALE = {
    "IT": {"col": "Query_IT", "gl": "it", "hl": "it", "google_domain": "google.it",
           "location": "Milan, Lombardy, Italy", "currency": "EUR"},
    "DE": {"col": "Query_DE", "gl": "de", "hl": "de", "google_domain": "google.de",
           "location": "Berlin, Germany", "currency": "EUR"},
    "EN": {"col": "Query_EN", "gl": "us", "hl": "en", "google_domain": "google.com",
           "location": "New York, NY, United States", "currency": "USD"},
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  run_id TEXT, query_id TEXT, keyword TEXT, language TEXT, currency TEXT,
  category_l1 TEXT, category_l2 TEXT, query_type TEXT,
  position INTEGER, product_id TEXT, title TEXT, seller TEXT,
  price TEXT, price_value REAL, rating REAL, reviews_count INTEGER,
  delivery TEXT, tag TEXT, extensions TEXT, thumbnail TEXT, scraped_at TEXT
);
CREATE TABLE IF NOT EXISTS done (
  query_id TEXT, language TEXT, n_items INTEGER, scraped_at TEXT,
  PRIMARY KEY (query_id, language)
);
CREATE INDEX IF NOT EXISTS idx_products_run ON products(run_id);
CREATE INDEX IF NOT EXISTS idx_products_pid ON products(product_id);
"""


def load_api_key() -> str:
    key = os.environ.get("SERPAPI_KEY", "")
    if not key and Path(".env").exists():
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("SERPAPI_KEY") and "=" in line:
                key = line.split("=", 1)[1].strip().strip('"').strip("'"); break
    if not key:
        sys.exit("SERPAPI_KEY mancante. Mettila in .env (SERPAPI_KEY=...) o esportala.")
    return key


def read_queries(csv_path: str, locale: str, limit: int | None) -> list[dict]:
    col = LOCALE[locale]["col"]
    rows, seen = [], set()
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            kw = (r.get(col) or "").strip()
            if not kw or kw.lower() in seen:
                continue
            seen.add(kw.lower())
            rows.append({"query_id": r["query_id"], "keyword": kw,
                         "category_l1": r.get("category_l1", ""), "category_l2": r.get("category_l2", ""),
                         "query_type": r.get("query_type", "")})
    return rows[:limit] if limit else rows


def fetch(keyword: str, locale: str, api_key: str) -> dict:
    p = LOCALE[locale]
    params = {"engine": "google_shopping", "q": keyword, "api_key": api_key,
              "gl": p["gl"], "hl": p["hl"], "google_domain": p["google_domain"],
              "location": p["location"]}
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "bias-ranking/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_rows(data: dict, q: dict, locale: str) -> list[tuple]:
    p = LOCALE[locale]; run_id = f"{q['query_id']}_{locale}"
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for it in data.get("shopping_results", []) or []:
        ext = it.get("extensions") or []
        out.append((
            run_id, q["query_id"], q["keyword"], locale, p["currency"],
            q["category_l1"], q["category_l2"], q["query_type"],
            it.get("position"), it.get("product_id"), it.get("title"), it.get("source"),
            it.get("price"), it.get("extracted_price"), it.get("rating"), it.get("reviews"),
            it.get("delivery"), it.get("tag"),
            json.dumps(ext, ensure_ascii=False) if ext else None, it.get("thumbnail"), now,
        ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="queries_5000.csv")
    ap.add_argument("--locale", default="IT", choices=["IT", "DE", "EN"])
    ap.add_argument("--db", default="results_serpapi.db")
    ap.add_argument("--limit", type=int, default=None, help="usa solo le prime N query (pilota)")
    ap.add_argument("--max-searches", type=int, default=5000, help="tetto ricerche (anti-sforo piano)")
    ap.add_argument("--sleep", type=float, default=0.5, help="pausa tra chiamate (s)")
    ap.add_argument("--estimate", action="store_true", help="stima a secco, nessuna chiamata")
    a = ap.parse_args()

    queries = read_queries(a.csv, a.locale, a.limit)
    con = sqlite3.connect(a.db); con.executescript(SCHEMA)
    done = {r[0] for r in con.execute("SELECT query_id FROM done WHERE language=?", (a.locale,))}
    todo = [q for q in queries if q["query_id"] not in done]

    print(f"CSV={a.csv} | locale={a.locale} | query uniche={len(queries):,} | "
          f"già fatte={len(done):,} | da fare={len(todo):,}")
    if a.estimate:
        n = min(len(todo), a.max_searches)
        print(f"\nSTIMA: servono {n:,} ricerche (= {n:,} SERP × 40 risultati).")
        print(f"  Piani SerpApi: Starter 1.000 | Developer 5.000 | Production 15.000")
        fits = "Developer ($75)" if n <= 5000 else "Production ($150)" if n <= 15000 else "Big Data+"
        print(f"  Copertura minima: {fits}. Nessuna chiamata effettuata.")
        con.close(); return

    api_key = load_api_key()
    used = 0; rows_tot = 0; t0 = time.time()
    try:
        for i, q in enumerate(todo, 1):
            if used >= a.max_searches:
                print(f"\n⛔ raggiunto --max-searches={a.max_searches}. Stop pulito."); break
            try:
                data = fetch(q["keyword"], a.locale, api_key)
            except Exception as e:
                print(f"  [{i}/{len(todo)}] '{q['keyword'][:40]}' errore: {type(e).__name__}: {e}")
                # errori di quota/credito: meglio fermarsi che ciclare a vuoto
                if any(s in str(e).lower() for s in ("401", "403", "429", "run out", "quota")):
                    print("   → sembra un problema di chiave/quota: mi fermo."); break
                time.sleep(2); continue

            err = data.get("error")
            if err:
                print(f"  [{i}/{len(todo)}] errore SerpApi: {err}")
                if "run out" in err.lower() or "quota" in err.lower():
                    print("   → quota esaurita: mi fermo."); break
                continue

            rows = parse_rows(data, q, a.locale)
            con.execute("INSERT INTO done VALUES (?,?,?,?)",
                        (q["query_id"], a.locale, len(rows), datetime.now(timezone.utc).isoformat()))
            if rows:
                con.executemany("INSERT INTO products VALUES (" + ",".join(["?"]*21) + ")", rows)
            con.commit()
            used += 1; rows_tot += len(rows)
            if i % 25 == 0 or i == len(todo):
                rate = used / max(time.time() - t0, 1e-9)
                eta = (len(todo) - i) / max(rate, 1e-9) / 60
                print(f"  [{i}/{len(todo)}] ricerche usate={used} | righe={rows_tot:,} | "
                      f"~{rate:.1f}/s | ETA ~{eta:.0f} min")
    finally:
        con.close()

    print(f"\n✅ Fatto. Ricerche usate: {used:,} | righe scritte: {rows_tot:,} | DB: {a.db}")
    print("   Re-lancia lo stesso comando per riprendere le query mancanti (resumable).")


if __name__ == "__main__":
    main()
