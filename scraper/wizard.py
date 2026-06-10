"""
wizard.py — Pipeline guidata interattiva per studenti.

Flusso: scelta CSV → filtraggio query → preventivo costi → conferma →
        scrape → analytics → bias → commento didattico di Claude.

Uso:
    python main.py wizard

Zero dipendenze aggiuntive: usa solo input() della stdlib.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


# ─── Pricing burbn (USD) — vedi pricingPerEvent dell'actor ────────────
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
        print("  ⚠ Risposta obbligatoria.")


def ask_yesno(prompt: str, default: bool = True) -> bool:
    d = "s" if default else "n"
    s = ask(f"{prompt} (s/n)", default=d).lower()
    return s in ("s", "si", "sì", "y", "yes", "true", "1")


def ask_int(prompt: str, default: int, min_v: int = 1, max_v: int = 10_000) -> int:
    while True:
        s = ask(prompt, default=str(default))
        try:
            n = int(s)
        except ValueError:
            print("  ⚠ Devi inserire un numero intero.")
            continue
        if not (min_v <= n <= max_v):
            print(f"  ⚠ Valore fuori range [{min_v}-{max_v}].")
            continue
        return n


def ask_choice(prompt: str, options: list[str], default: str | None = None) -> str:
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        marker = "  ← default" if opt == default else ""
        print(f"    [{i}] {opt}{marker}")
    while True:
        s = input("  Scelta (numero): ").strip()
        if not s and default is not None:
            return default
        try:
            i = int(s)
            if 1 <= i <= len(options):
                return options[i - 1]
        except ValueError:
            pass
        print(f"  ⚠ Inserisci un numero da 1 a {len(options)}.")


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
        s = input(f"  Scelte (numeri separati da virgola, default {default_idx}): ").strip()
        if not s and defaults:
            return list(defaults)
        try:
            indices = [int(x.strip()) for x in s.split(",")]
            chosen = [options[i - 1] for i in indices if 1 <= i <= len(options)]
            if chosen:
                return chosen
        except ValueError:
            pass
        print("  ⚠ Inserisci numeri validi separati da virgola.")


# ═══════════════════════════════════════════════════════════════════════
# Step 1 — selezione CSV
# ═══════════════════════════════════════════════════════════════════════

def select_csv() -> Path:
    csvs = sorted(p for p in Path(".").glob("queries_*.csv")
                  if not p.name.startswith("_"))
    if not csvs:
        print("  ❌ Nessun file 'queries_*.csv' trovato nella cartella corrente.")
        sys.exit(1)
    options = [str(c) for c in csvs]
    chosen = ask_choice("Quale CSV di query vuoi usare?", options, default=options[0])
    return Path(chosen)


# ═══════════════════════════════════════════════════════════════════════
# Step 2 — filtraggio query
# ═══════════════════════════════════════════════════════════════════════

def filter_queries(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    print(f"\n  📋 Caricato {csv_path}: {len(df)} query totali")
    print(f"     Categorie L1: {sorted(df['category_l1'].unique())}")
    print(f"     Query types: {sorted(df['query_type'].unique())}")

    cats = ["(tutte)"] + sorted(df["category_l1"].unique().tolist())
    cat = ask_choice("Filtra per categoria L1", cats, default="(tutte)")
    if cat != "(tutte)":
        df = df[df["category_l1"] == cat]

    types = ["(tutti)"] + sorted(df["query_type"].unique().tolist())
    qt = ask_choice("Filtra per query type", types, default="(tutti)")
    if qt != "(tutti)":
        df = df[df["query_type"] == qt]

    df = df.reset_index(drop=True)
    print(f"\n  ✓ {len(df)} query dopo i filtri.")

    if df.empty:
        return df

    max_n = len(df)
    n = ask_int(
        f"Quante query vuoi prendere dalla cima della lista? (max {max_n})",
        default=min(3, max_n), min_v=1, max_v=max_n,
    )
    df = df.head(n)

    print(f"\n  📋 Anteprima:")
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
# Step 3 — configurazione scrape + preventivo
# ═══════════════════════════════════════════════════════════════════════

def configure_scrape(df_q: pd.DataFrame) -> tuple[list[str], int, int]:
    languages = ask_multichoice(
        "Su quali lingue vuoi scrapare?",
        options=["IT", "EN", "DE"], defaults=["IT"],
    )
    print()
    print("  ℹ️  Nota sui risultati per query:")
    print("     • L'actor Apify (burbn) impone un minimo di 20 risultati per chiamata.")
    print("     • Non è possibile richiederne meno: valori < 20 vengono rifiutati dall'API.")
    print("     • Per risparmiare crediti conviene ridurre il NUMERO DI QUERY,")
    print("       non i risultati per query.")
    print("     • Il valore che inserisci è un CAP massimo: Google può restituirne")
    print("       di meno se la keyword è poco indicizzata sul mercato scelto.")
    print()
    max_results = ask_int(
        "Risultati per query (min 20, imposto da Apify)",
        default=20, min_v=20, max_v=100,
    )
    concurrency = ask_int(
        "Concorrenza (query in parallelo)",
        default=3, min_v=1, max_v=10,
    )

    n_calls = len(df_q) * len(languages)
    cost_free = n_calls * (COST_START + max_results * COST_PER_RESULT_FREE)
    cost_bronze = n_calls * (COST_START + max_results * COST_PER_RESULT_BRONZE)

    header("PREVENTIVO COSTI Apify (actor burbn)")
    print(f"  Chiamate totali: {n_calls} = {len(df_q)} query × {len(languages)} lingue")
    print(f"  Risultati per query: {max_results} (max — Google può restituirne meno)")
    print(f"  ────────────────────────────────────────")
    print(f"  Costo FREE tier:                 ${cost_free:6.2f}")
    print(f"  Costo BRONZE (Starter $49/mese): ${cost_bronze:6.2f}")
    print(f"  ────────────────────────────────────────")
    print(f"  ⚠ Free tier: $5/mese di credito; oltre, l'actor non parte.")
    print(f"  💡 Per test economici: scegli poche query (2-5) a 20 risultati.")

    if not ask_yesno("\n  Procedi con questi parametri?", default=True):
        print("  ⛔ Annullato dall'utente.")
        sys.exit(0)

    return languages, max_results, concurrency


# ═══════════════════════════════════════════════════════════════════════
# Step 4 — esecuzione
# ═══════════════════════════════════════════════════════════════════════

def run_scrapes(df_q: pd.DataFrame, languages: list[str],
                max_results: int, concurrency: int) -> int:
    from pipeline import run_pipeline
    from storage import init_db, save_items

    apify_token = os.environ.get("APIFY_TOKEN", "")
    if not apify_token:
        print("  ❌ APIFY_TOKEN mancante nel .env")
        sys.exit(1)

    tmp_csv = Path("_wizard_selection.csv")
    df_q.to_csv(tmp_csv, index=False)

    total_saved = 0
    try:
        for lang in languages:
            header(f"4. SCRAPE — lingua {lang}")
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
    """Esegue analytics + bias. Ritorna (run_ts, df) per uso in claude_commentary."""
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
        print("  ⚠ DB vuoto, niente da analizzare.")
        return run_ts, df
    export_parquet(df, run_ts=run_ts)
    print_summary(df)
    html_analytics = build_dashboard(df, run_ts=run_ts)
    if html_analytics and html_analytics.exists():
        webbrowser.open(html_analytics.resolve().as_uri())
        print(f"  🌐 Dashboard aperta nel browser: {html_analytics}")

    header("6. ANALISI BIAS")
    print_bias_report(df)
    html_bias = build_bias_dashboard(df, run_ts=run_ts)
    export_bias_metrics_csv(df, run_ts=run_ts)
    if html_bias and html_bias.exists():
        webbrowser.open(html_bias.resolve().as_uri())
        print(f"  🌐 Bias dashboard aperta nel browser: {html_bias}")

    return run_ts, df


# ═══════════════════════════════════════════════════════════════════════
# Step 6 — commento didattico Claude
# ═══════════════════════════════════════════════════════════════════════

def claude_commentary(run_ts: str | None = None) -> None:
    header("7. COMMENTO DIDATTICO (Claude)")
    if not ask_yesno("Vuoi un commento di Claude sui risultati?", default=True):
        print("  ⏭ Skippato.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ⚠ ANTHROPIC_API_KEY non presente nel .env, skip.")
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

    prompt = f"""Sei un assistente didattico per uno studente che sta imparando l'analisi
di bias nei risultati dei motori di ricerca (Google Shopping).

Ti passo l'output di un'analisi su un dataset di prodotti scrapati.
Scrivi un commento DIDATTICO e CHIARO (max 600 parole) in italiano:

1. Riassumi i numeri chiave del dataset (volume, copertura, lingue, categorie).
2. Spiega cosa indicano le metriche di concentrazione (HHI, Gini, CR-k)
   in QUESTO specifico caso, contestualizzando i numeri.
3. Se c'è disparità di prezzo cross-lingua significativa, sottolineala
   e prova a spiegarne le cause possibili (mercato locale, valuta,
   posizionamento di Google, dimensione campione).
4. Identifica eventuali "filter bubble" di prezzo (CoV basso) e cosa
   significano operativamente.
5. Concludi con 2-3 limiti del dataset corrente e cosa aggiungere
   (più query, più lingue, più categorie) per renderlo più solido.

Linguaggio: amichevole ma rigoroso, niente jargon non spiegato.
Output: testo Markdown puro, senza preamboli ("Ecco il commento..."),
pronto da incollare in un report.

Dati di analisi (JSON):
```json
{summary_json}
```
"""
    print("  💬 Sto chiedendo a Claude di commentare i risultati...")
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
    # Haiku 4.5: $1/Mtok input, $5/Mtok output (approx, vedi pricing ufficiale)
    cost = in_tok / 1_000_000 * 1.0 + out_tok / 1_000_000 * 5.0

    print(f"\n  📄 Commento salvato in {out}")
    print(f"  💵 Tokens: {in_tok} in / {out_tok} out  (~${cost:.4f} con Claude Haiku 4.5)")
    print()
    print("  " + "─" * 60)
    for line in commentary.splitlines():
        print(f"  {line}")
    print("  " + "─" * 60)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def _db_product_count() -> int:
    """Ritorna il numero di prodotti attualmente in results.db (0 se non esiste)."""
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

    header("WIZARD — Product Scraper guidato")
    print("  Ti porto passo per passo da scelta query → scrape → analisi → commento.")
    print("  Premi Ctrl+C in qualsiasi momento per uscire.")

    # Se il DB ha già dati, offri la modalità "solo analisi"
    n_existing = _db_product_count()
    skip_scrape = False
    if n_existing > 0:
        print(f"\n  ℹ️  results.db contiene già {n_existing} prodotti.")
        skip_scrape = ask_yesno(
            "Vuoi saltare lo scraping e lavorare solo sull'analisi dei dati esistenti?",
            default=False,
        )

    if not skip_scrape:
        header("1. Scelta CSV di input")
        csv_path = select_csv()

        header("2. Filtraggio query")
        df_q = filter_queries(csv_path)
        if df_q.empty:
            print("  ⚠ Nessuna query selezionata, esco.")
            return

        header("3. Configurazione scrape")
        languages, max_results, concurrency = configure_scrape(df_q)

        n_saved = run_scrapes(df_q, languages, max_results, concurrency)
        print(f"\n  ✅ Prodotti nuovi salvati in results.db: {n_saved}")
    else:
        print(f"\n  ⏭ Scraping saltato — utilizzo i {n_existing} prodotti esistenti.")

    run_ts, _ = run_analysis()
    claude_commentary(run_ts=run_ts)

    header("RIEPILOGO FILE GENERATI")
    out_dir = Path("output")
    if out_dir.exists():
        for f in sorted(out_dir.glob("*")):
            size_kb = f.stat().st_size / 1024
            print(f"    • {f}  ({size_kb:.1f} KB)")
    print("\n  ✓ Pipeline guidata completata.\n")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n  ⛔ Interrotto dall'utente.\n")
        sys.exit(130)
