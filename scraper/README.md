# Product Scraper

Pipeline di scraping prodotti da Google Shopping via Apify, con analytics
Plotly e orchestratore Claude.

## Architettura

```
queries_pilot_100.csv ──► pipeline.py ──► Apify Google Shopping
queries_5000.csv                                │
                                                ▼
                                        results.db (SQLite)
                                        raw/*.jsonl (audit)
                                                │
                                                ▼
                                        analytics.py ──► output/dashboard.html
                                                         output/results.parquet

orchestrator.py ──► Claude genera query ──► pipeline ──► Claude analizza
                                                         output/report.md
```

## Setup

```bash
# 1. Installa dipendenze
pip install -r requirements.txt

# 2. Configura le chiavi API
cp .env.template .env
# Edita .env:
#   APIFY_TOKEN=apify_api_...
#   ANTHROPIC_API_KEY=sk-ant-...
```

## Formato CSV

Il CSV deve avere queste colonne:

```
query_id,category_l1,category_l2,query_type,Query_EN,Query_IT,Query_DE
```

Il flag `--lang` seleziona quale colonna usare come keyword.

## Uso

### 0. GUI grafica (consigliato per chi inizia)

```bash
python main.py gui
```

Apre una finestra con due tab:
- **Wizard** — avvia la pipeline guidata in un terminale separato; pulsanti rapidi per
  rieseguire solo Analytics o Bias sui dati già in DB.
- **Explorer** — form con filtri (lingua, categoria, keyword, campione) e output inline.
  Pulsanti per aprire le dashboard HTML nel browser.

Richiede solo Python standard (tkinter incluso). Zero dipendenze extra.

### 0b. Pipeline guidata da terminale

```bash
python main.py wizard
```

Versione terminale del wizard, identica nel flusso ma interattiva via `input()`.

### 1. Test pilota (100 query, scelta avanzata)

```bash
# Solo italiano
python main.py scrape queries_pilot_100.csv --lang IT

# Tedesco, con 5 query parallele
python main.py scrape queries_pilot_100.csv --lang DE --concurrency 5

# Inglese, max 10 risultati per query (risparmia crediti)
python main.py scrape queries_pilot_100.csv --lang EN --max-results 10
```

### 2. Run completo (5000 query)

```bash
# ATTENZIONE: 5000 query consumano crediti Apify significativi.
# Stima: ~$15-40 su piano Starter, dipende dai risultati per query.
python main.py scrape queries_5000.csv --lang IT --concurrency 5
```

### 3. Analytics

```bash
# Dashboard interattiva + Parquet + riepilogo
python main.py analytics

# Solo export Parquet (per DuckDB, Polars, ecc.)
python main.py analytics --export-only
```

### 4. Analisi bias (sbilanciamento Google Shopping)

```bash
# Report completo: testo + dashboard HTML + metriche CSV
python main.py bias

# Solo report testuale a terminale
python main.py bias --format text

# Solo dashboard HTML interattiva
python main.py bias --format html

# Solo export metriche CSV (per Excel, DuckDB, ecc.)
python main.py bias --format csv
```

Per il confronto cross-lingua, esegui lo scraping in più lingue prima:
```bash
python main.py scrape queries_pilot_100.csv --lang IT
python main.py scrape queries_pilot_100.csv --lang EN
python main.py scrape queries_pilot_100.csv --lang DE
python main.py bias
```

### 5. Esplorazione database

```bash
# Panoramica completa: prodotti, lingue, categorie, seller
python main.py explore

# Filtra per lingua o categoria
python main.py explore --lang IT
python main.py explore --cat "Electronics"

# Dettaglio prezzi cross-lingua per una keyword specifica
python main.py explore --keyword "mountain bike economici"

# Lista run Apify con timestamp
python main.py explore --runs

# Campione casuale di prodotti
python main.py explore --sample 30
```

### 6. Orchestratore Claude (linguaggio naturale)

```bash
# Query singola — Claude genera le query, le esegue, analizza i risultati
python main.py ask "Cerco un notebook gaming sotto 1500€ con RTX 4070"

# Modalità interattiva
python main.py ask --interactive
```

## Struttura file

```
product_scraper/
├── .env.template          # Template chiavi API
├── requirements.txt       # Dipendenze Python
├── main.py                # Entrypoint CLI
├── models.py              # Dataclass e parsing
├── pipeline.py            # CSV → Apify → QueryResult
├── storage.py             # SQLite + JSONL
├── analytics.py           # Parquet + dashboard Plotly
├── bias_analysis.py       # Analisi sbilanciamento Google Shopping
├── orchestrator.py        # Claude NL orchestrator
├── wizard.py              # Pipeline guidata interattiva (main.py wizard)
├── gui.py                 # Mini GUI tkinter (main.py gui)
├── explore.py             # Esplorazione DB via terminale (main.py explore)
├── extra_charts.py        # Dashboard cross-lingua + per categoria
├── queries_pilot_100.csv  # Test pilota (100 query)
└── queries_5000.csv       # Dataset completo (5000 query)
```

## Output generati

```
product_scraper/
├── results.db               # Database SQLite
├── raw/                     # JSONL grezzi per audit
│   └── <run_id>.jsonl
└── output/
    ├── results.parquet      # Export colonnare
    ├── dashboard.html       # Dashboard interattiva
    ├── bias_dashboard.html  # Dashboard bias (6 grafici)
    ├── bias_metrics.csv     # Metriche bias per query
    └── report.md            # Report Claude (solo con 'ask')
```

## Uso con Claude Code

Lo studente può usare Claude Code per eseguire il progetto:

```bash
# 1. Installa Claude Code (richiede Node.js ≥ 18)
npm install -g @anthropic-ai/claude-code

# 2. Entra nella cartella del progetto
cd product_scraper

# 3. Avvia Claude Code
claude

# 4. Chiedi a Claude Code di eseguire
> installa le dipendenze e fai un test con 10 query dal pilot
> esegui lo scraping del pilot completo in italiano
> genera la dashboard analytics
```

Claude Code ha accesso diretto al filesystem e al terminale, quindi può
installare dipendenze, eseguire la pipeline, vedere gli errori e correggerli
in autonomia. L'unica cosa da fare prima è configurare il `.env` con i token.
