# Product Scraper

A product scraping pipeline for Google Shopping via Apify, with Plotly analytics
and a Claude orchestrator.

## Architecture

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

orchestrator.py ──► Claude generates queries ──► pipeline ──► Claude analyzes
                                                         output/report.md
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure the API keys
cp .env.template .env
# Edit .env:
#   APIFY_TOKEN=apify_api_...
#   ANTHROPIC_API_KEY=sk-ant-...
```

## CSV format

The CSV must have these columns:

```
query_id,category_l1,category_l2,query_type,Query_EN,Query_IT,Query_DE
```

The `--lang` flag selects which column to use as the keyword.

## Usage

### 0. Graphical GUI (recommended for beginners)

```bash
python main.py gui
```

Opens a window with two tabs:
- **Wizard** — launches the guided pipeline in a separate terminal; quick buttons to
  re-run only Analytics or Bias on the data already in the DB.
- **Explorer** — form with filters (language, category, keyword, sample) and inline output.
  Buttons to open the HTML dashboards in the browser.

Requires only standard Python (tkinter included). Zero extra dependencies.

### 0b. Guided pipeline from the terminal

```bash
python main.py wizard
```

Terminal version of the wizard, identical in flow but interactive via `input()`.

### 1. Pilot test (100 queries, advanced choice)

```bash
# Italian only
python main.py scrape queries_pilot_100.csv --lang IT

# German, with 5 parallel queries
python main.py scrape queries_pilot_100.csv --lang DE --concurrency 5

# English, max 10 results per query (saves credits)
python main.py scrape queries_pilot_100.csv --lang EN --max-results 10
```

### 2. Full run (5000 queries)

```bash
# WARNING: 5000 queries consume significant Apify credits.
# Estimate: ~$15-40 on the Starter plan, depending on results per query.
python main.py scrape queries_5000.csv --lang IT --concurrency 5
```

### 3. Analytics

```bash
# Interactive dashboard + Parquet + summary
python main.py analytics

# Parquet export only (for DuckDB, Polars, etc.)
python main.py analytics --export-only
```

### 4. Bias analysis (Google Shopping imbalance)

```bash
# Full report: text + HTML dashboard + CSV metrics
python main.py bias

# Text report in the terminal only
python main.py bias --format text

# Interactive HTML dashboard only
python main.py bias --format html

# CSV metrics export only (for Excel, DuckDB, etc.)
python main.py bias --format csv
```

For the cross-language comparison, run the scraping in multiple languages first:
```bash
python main.py scrape queries_pilot_100.csv --lang IT
python main.py scrape queries_pilot_100.csv --lang EN
python main.py scrape queries_pilot_100.csv --lang DE
python main.py bias
```

### 5. Database exploration

```bash
# Full overview: products, languages, categories, sellers
python main.py explore

# Filter by language or category
python main.py explore --lang IT
python main.py explore --cat "Electronics"

# Cross-language price detail for a specific keyword
python main.py explore --keyword "cheap mountain bikes"

# List Apify runs with timestamps
python main.py explore --runs

# Random sample of products
python main.py explore --sample 30
```

### 6. Claude orchestrator (natural language)

```bash
# Single query — Claude generates the queries, runs them, analyzes the results
python main.py ask "Looking for a gaming laptop under 1500€ with an RTX 4070"

# Interactive mode
python main.py ask --interactive
```

## File structure

```
product_scraper/
├── .env.template          # API keys template
├── requirements.txt       # Python dependencies
├── main.py                # CLI entry point
├── models.py              # Dataclasses and parsing
├── pipeline.py            # CSV → Apify → QueryResult
├── storage.py             # SQLite + JSONL
├── analytics.py           # Parquet + Plotly dashboard
├── bias_analysis.py       # Google Shopping imbalance analysis
├── orchestrator.py        # Claude NL orchestrator
├── wizard.py              # Interactive guided pipeline (main.py wizard)
├── gui.py                 # Minimal tkinter GUI (main.py gui)
├── explore.py             # DB exploration from the terminal (main.py explore)
├── extra_charts.py        # Cross-language + per-category dashboard
├── queries_pilot_100.csv  # Pilot test (100 queries)
└── queries_5000.csv       # Full dataset (5000 queries)
```

## Generated output

```
product_scraper/
├── results.db               # SQLite database
├── raw/                     # Raw JSONL for audit
│   └── <run_id>.jsonl
└── output/
    ├── results.parquet      # Columnar export
    ├── dashboard.html       # Interactive dashboard
    ├── bias_dashboard.html  # Bias dashboard (6 charts)
    ├── bias_metrics.csv     # Bias metrics per query
    └── report.md            # Claude report (only with 'ask')
```

## Use with Claude Code

The student can use Claude Code to run the project:

```bash
# 1. Install Claude Code (requires Node.js ≥ 18)
npm install -g @anthropic-ai/claude-code

# 2. Enter the project folder
cd product_scraper

# 3. Start Claude Code
claude

# 4. Ask Claude Code to run it
> install the dependencies and do a test with 10 queries from the pilot
> run the full pilot scraping in Italian
> generate the analytics dashboard
```

Claude Code has direct access to the filesystem and the terminal, so it can
install dependencies, run the pipeline, see the errors and fix them
on its own. The only thing to do first is to configure `.env` with the tokens.
