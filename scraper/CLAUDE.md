# CLAUDE.md — Istruzioni per Claude Code

## Contesto del progetto

Questo è il codice di tesi triennale in Data Science. L'obiettivo è analizzare il
**bias algoritmico nei risultati di Google Shopping** confrontando prezzi e seller
su tre mercati linguistici (IT / EN / DE) usando un dataset stratificato di query.

Lo studente ha già un account Apify (actor `burbn/google-shopping-scraper`) e un
account Anthropic. Le chiavi vanno inserite nel file `.env` prima di qualsiasi run.

---

## Struttura file

```
product_scraper/
├── .env                      # Chiavi API — da compilare (vedi Setup)
├── .env.template             # Template chiavi
├── requirements.txt          # Dipendenze Python
│
├── main.py                   # Entrypoint CLI — tutti i comandi partono da qui
├── models.py                 # Dataclass ScrapedItem + parsing prezzi multilingua
├── pipeline.py               # CSV → Apify Google Shopping (async, concorrente)
├── storage.py                # SQLite results.db + JSONL audit trail raw/
├── analytics.py              # Export Parquet + dashboard Plotly (6 grafici)
├── bias_analysis.py          # 5 metriche bias: HHI, Gini, CR-k, CoV, position
├── orchestrator.py           # Claude NL → genera query → pipeline → report
├── wizard.py                 # Pipeline guidata interattiva (terminale)
├── gui.py                    # Mini GUI tkinter: tab Wizard + tab Explorer
├── explore.py                # Esplorazione testuale del DB
├── extra_charts.py           # Dashboard cross-lingua e per categoria
│
├── queries_pilot_100.csv     # 100 query di test (IT/EN/DE) — per i primi test
├── queries_400_stratified.csv # 400 query stratificate per la tesi (6 cat, 3 lingue)
└── queries_5000.csv          # Dataset completo (5000 query) — non usare senza budget
```

**Output generati automaticamente:**
```
results.db               # Database SQLite (append-only)
raw/<run_id>_raw.json    # Dump JSON grezzo per audit
output/
  results.parquet        # Export colonnare
  dashboard.html         # Dashboard analytics (si apre nel browser)
  bias_dashboard.html    # Dashboard bias (si apre nel browser)
  bias_metrics.csv       # Metriche bias per query (per Excel/DuckDB)
  report.md              # Report generato da Claude (solo col comando 'ask')
```

---

## Setup iniziale (da fare una volta sola)

### 1. Verifica Python ≥ 3.10

```bash
python --version
# Su Windows potrebbe servire: py --version
```

### 2. Installa le dipendenze

```bash
pip install -r requirements.txt
```

Se `pip` non funziona: `pip3 install -r requirements.txt` oppure
`python -m pip install -r requirements.txt`.

### 3. Configura le chiavi API

```bash
# Copia il template
cp .env.template .env   # Linux/Mac
copy .env.template .env  # Windows
```

Apri `.env` con un editor di testo e inserisci:

```
APIFY_TOKEN=apify_api_xxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
```

- **APIFY_TOKEN**: da https://console.apify.com → Settings → Integrations → API token
- **ANTHROPIC_API_KEY**: da https://console.anthropic.com → API Keys

### 4. Verifica la configurazione

```bash
python -c "
from dotenv import load_dotenv; import os; load_dotenv()
at = os.environ.get('APIFY_TOKEN','')
ak = os.environ.get('ANTHROPIC_API_KEY','')
print('APIFY_TOKEN:', 'OK' if at.startswith('apify_api_') else 'MANCANTE')
print('ANTHROPIC_API_KEY:', 'OK' if ak.startswith('sk-ant-') else 'MANCANTE')
"
```

---

## Flusso di lavoro raccomandato per la tesi

### Fase A — Familiarizzazione (nessun costo)

```bash
# Verifica che i CSV siano leggibili
python -c "
import pandas as pd
df = pd.read_csv('queries_400_stratified.csv')
print(f'{len(df)} query, {df.category_l1.nunique()} categorie')
print(df.groupby(['category_l1','query_type']).size().unstack())
"
```

Poi apri la GUI per esplorare l'interfaccia:

```bash
python main.py gui
```

### Fase B — Primo test reale (~3-5 query, costo ~$0.35)

**Prima di spendere crediti Apify, il wizard mostra sempre un preventivo
e chiede conferma esplicita. Puoi sempre annullare.**

```bash
python main.py wizard
```

Seleziona: `queries_400_stratified.csv` → categoria `Electronics` → tipo `generic`
→ 3 query → lingua `IT` → 20 risultati → conferma.

Verifica che il DB contenga dati:

```bash
python main.py explore
```

### Fase C — Run completo tesi (400 query × 3 lingue, costo ~$179)

**Leggi attentamente il preventivo prima di confermare.**

```bash
python main.py wizard
```

Seleziona: `queries_400_stratified.csv` → `(tutte)` le categorie →
`(tutti)` i tipi → 400 query → lingue `IT` + `EN` + `DE` → 20 risultati.

Il run richiede circa 2-4 ore con concorrenza 3.

### Fase D — Analisi e dashboard

Se hai già i dati nel DB e vuoi solo rigenerare le analisi:

```bash
python main.py analytics   # apre dashboard.html nel browser
python main.py bias        # apre bias_dashboard.html nel browser
```

Oppure dalla GUI (tab Explorer → "Genera & Apri Analytics").

---

## Tutti i comandi disponibili

| Comando | Cosa fa | Costo Apify |
|---|---|---|
| `python main.py gui` | Apre la GUI grafica | No |
| `python main.py wizard` | Pipeline guidata interattiva | Sì (con preventivo) |
| `python main.py scrape <csv> --lang IT` | Scraping diretto da CSV | Sì |
| `python main.py analytics` | Dashboard Plotly + Parquet | No |
| `python main.py bias` | Analisi bias (5 metriche) + dashboard | No |
| `python main.py explore` | Panoramica DB a terminale | No |
| `python main.py explore --lang IT` | Filtra per lingua | No |
| `python main.py explore --keyword "..."` | Prezzi cross-lingua per keyword | No |
| `python main.py explore --runs` | Lista run Apify con timestamp | No |
| `python main.py explore --sample 20` | Campione casuale prodotti | No |
| `python main.py ask "..."` | Claude genera query → scrape → report | Sì |
| `python main.py ask --interactive` | Modalità conversazionale Claude | Sì |

### Opzioni scraping

```bash
python main.py scrape queries_400_stratified.csv \
  --lang IT \          # IT | EN | DE
  --concurrency 3 \    # query in parallelo (1-10, default 3)
  --max-results 20     # risultati per query (minimo 20, imposto da Apify)
```

---

## Dataset disponibili

| File | Query | Uso |
|---|---|---|
| `queries_pilot_100.csv` | 100 | Test e familiarizzazione |
| `queries_400_stratified.csv` | 400 | **Dataset tesi** — stratificato su 6 cat. L1 |
| `queries_5000.csv` | 5000 | Dataset completo (non usare, costo ~$540) |

**Struttura CSV:**
```
query_id, category_l1, category_l2, query_type, Query_EN, Query_IT, Query_DE
```

**Il dataset da 400 query è bilanciato:**
- 6 categorie L1, ~66-67 query ciascuna
- Split branded/generic proporzionale al pool reale
- 147/153 sottocategorie L2 coperte
- Tutte le query hanno le 3 traduzioni popolate

---

## Comportamento del database

- `results.db` è **append-only**: ogni run aggiunge dati senza sovrascrivere.
- **Stesso run Apify rieseguito** → nuovo `run_id` → nuove righe (snapshot prezzi).
- **Stesso run importato due volte** → righe ignorate (`INSERT OR IGNORE` su `run_id, position`).
- **Per ripartire da zero**: elimina `results.db` e la cartella `raw/`.

---

## Metriche di bias implementate

1. **Concentrazione seller** — HHI (Herfindahl-Hirschman Index), Gini, CR-3/CR-5
2. **Position bias** — correlazione posizione × prezzo medio; chi occupa le prime 3?
3. **Disparità cross-lingua** — stesso `query_id` in IT/EN/DE: delta prezzi %
4. **Price clustering** — CoV (Coefficient of Variation) per filtro-bolla prezzi
5. **Category coverage** — Google restituisce risultati bilanciati tra categorie?

---

## Note tecniche importanti

- **`--max-results 20` è il minimo assoluto** imposto dall'actor Apify `burbn`.
  Non è possibile richiederne meno. Per risparmiare crediti: riduci il numero
  di query, non i risultati per query.
- **`--max-results` è un cap, non un target**: Google può restituire meno prodotti
  se la keyword è poco indicizzata per quel mercato. La pipeline stampa avviso.
- **Rating e reviews** possono essere NULL: Google non li espone sempre.
  Tutti i grafici filtrano i null automaticamente.
- **Encoding su Windows**: se vedi errori di caratteri, esegui prima
  `$env:PYTHONIOENCODING="utf-8"` in PowerShell.

---

## Troubleshooting

| Errore | Causa | Soluzione |
|---|---|---|
| `ModuleNotFoundError` | Dipendenze non installate | `pip install -r requirements.txt` |
| `APIFY_TOKEN mancante` | `.env` non configurato | Vedi Setup §3 |
| `Apify 401 Unauthorized` | Token sbagliato o scaduto | Rigenera token su console.apify.com |
| `input.limit must be >= 20` | Hai passato `--max-results < 20` | Usa almeno 20 |
| `database is locked` | Un altro processo usa results.db | Chiudi altri terminali |
| `TypeError: float object...` | Cella CSV vuota letta come NaN | Normale, il codice lo gestisce |
| `0 prodotti salvati` | Apify ha restituito 0 risultati | Controlla il token; riprova |
| Dashboard non si apre | Browser non trovato | Apri manualmente `output/dashboard.html` |

---

## Come aiutare lo studente (istruzioni per Claude Code)

1. **Prima di qualsiasi run Apify**, verifica che `.env` sia configurato e mostra
   il preventivo costi stimato per il numero di query che vuole eseguire.

2. **Non suggerire mai `--max-results` inferiore a 20**: l'actor lo rifiuta.

3. **Il dataset corretto per la tesi è `queries_400_stratified.csv`**, non il pilot.
   Il pilot serve solo per i test iniziali.

4. **Se lo studente chiede di analizzare i dati**, esegui sempre prima
   `python main.py explore` per mostrare quanti dati ci sono nel DB.

5. **Se lo studente vuole ricominciare da zero**, chiedi conferma esplicita
   prima di suggerire di cancellare `results.db`.

6. **Per problemi di encoding su Windows**: aggiungi sempre
   `$env:PYTHONIOENCODING="utf-8"` prima dei comandi PowerShell.
