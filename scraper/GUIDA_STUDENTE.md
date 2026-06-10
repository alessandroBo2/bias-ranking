# Guida Studente — Product Scraper per Tesi

Questa guida ti porta dall'installazione all'analisi completa,
passo per passo. Segui l'ordine: ogni step verifica che il
precedente sia andato a buon fine.

---

## Prima di iniziare: cosa ti serve

| Cosa | Dove prenderlo |
|---|---|
| Python ≥ 3.10 | https://www.python.org/downloads/ |
| Account Apify (già fatto) | https://console.apify.com |
| Account Anthropic (già fatto) | https://console.anthropic.com |
| Le tue chiavi API | Vedi §1 qui sotto |

**Costi stimati per la tesi completa (400 query × 3 lingue):**
- Piano Apify Starter: $49/mese
- Crediti per le query: ~$130
- **Totale: ~$179** — resta nel budget di $200

---

## Passo 1 — Configura le chiavi API

Il progetto usa due servizi a pagamento. Le chiavi vanno nel file `.env`
(già presente nella cartella, senza valori).

**APIFY_TOKEN:**
1. Vai su https://console.apify.com
2. Click sul tuo avatar in alto a destra → **Settings**
3. Tab **Integrations** → **API token** → copia il token

**ANTHROPIC_API_KEY:**
1. Vai su https://console.anthropic.com
2. Menu **API Keys** → **Create Key** → copia la chiave

Apri il file `.env` con un editor di testo (Blocco Note va bene) e sostituisci i placeholder:

```
APIFY_TOKEN=apify_api_metti_qui_il_tuo_token
ANTHROPIC_API_KEY=sk-ant-metti_qui_la_tua_chiave
```

Salva il file. **Non condividere mai questo file con nessuno.**

---

## Passo 2 — Installa le dipendenze

Apri un terminale nella cartella del progetto ed esegui:

```bash
pip install -r requirements.txt
```

Attendi il completamento (1-3 minuti). Se vedi errori, prova:
```bash
python -m pip install -r requirements.txt
```

---

## Passo 3 — Verifica la configurazione

```bash
python -c "
from dotenv import load_dotenv; import os; load_dotenv()
at = os.environ.get('APIFY_TOKEN','')
ak = os.environ.get('ANTHROPIC_API_KEY','')
print('APIFY_TOKEN:', 'OK' if at.startswith('apify_api_') else 'MANCANTE o ERRATO')
print('ANTHROPIC_API_KEY:', 'OK' if ak.startswith('sk-ant-') else 'MANCANTE o ERRATA')
"
```

Devono comparire due `OK`. Se compare `MANCANTE`, torna al Passo 1.

---

## Passo 4 — Apri la GUI (punto di partenza consigliato)

```bash
python main.py gui
```

Si apre una finestra con due tab:
- **🧙 Wizard** — per eseguire la pipeline completa
- **🔍 Explorer** — per esplorare i dati già raccolti

Tienila aperta: la userai per tutto il lavoro.

---

## Passo 5 — Primo test (piccolo, economico)

Prima di spendere i $179 del run completo, fai un test con poche query.

Nella GUI, tab **Wizard**, clicca **🚀 Avvia Wizard**. Si apre un terminale. Segui le istruzioni:

1. **Quale CSV?** → scegli `queries_pilot_100.csv`
2. **Categoria L1?** → `(tutte)`
3. **Query type?** → `(tutti)`
4. **Quante query?** → digita `3`
5. **Lingue?** → scegli solo `IT` (digita `1`)
6. **Risultati per query?** → lascia `20` (non puoi mettere meno)
7. **Concorrenza?** → lascia `3`

Il wizard mostra il **preventivo costi** prima di procedere:
```
Costo FREE tier:                 $1.23
Costo BRONZE (Starter $49/mese): $0.32
```

Digita `s` per confermare. Il test impiega 1-3 minuti.

**Cosa aspettarti:** il wizard stampa i prodotti trovati, poi genera
automaticamente analytics e bias e apre le dashboard nel browser.

---

## Passo 6 — Esplora i dati del test

Nella GUI, tab **Explorer**, clicca **▶ Esegui Explorer**.
Vedrai una panoramica: quanti prodotti, per lingua, per categoria, top seller.

Prova anche:
- Seleziona lingua `IT` e riesegui
- Scrivi una keyword nel campo apposito e riesegui

---

## Passo 7 — Run completo per la tesi

Quando sei pronto (e hai il piano Apify Starter attivo):

1. Nella GUI → **🚀 Avvia Wizard**
2. CSV → `queries_400_stratified.csv`
3. Categoria → `(tutte)`
4. Tipo → `(tutti)`
5. Quante query → `400`
6. Lingue → `IT`, `EN`, `DE` (tutte e tre, digita `1,2,3`)
7. Risultati → `20`
8. Concorrenza → `3`

Il wizard mostra il preventivo (~$179). Leggi con attenzione, poi conferma.

**Durata stimata:** 3-5 ore. Puoi lasciarlo girare in background.

Al termine si aprono automaticamente nel browser:
- `output/dashboard.html` — analytics generali
- `output/bias_dashboard.html` — analisi di bias

---

## Passo 8 — Analisi dei risultati

Se vuoi rigenerare le analisi senza rieseguire lo scraping:

```bash
python main.py analytics   # rigenera dashboard analytics
python main.py bias        # rigenera dashboard bias
```

Per esplorare i dati a terminale con filtri:
```bash
python main.py explore                             # panoramica completa
python main.py explore --lang IT                   # solo dati italiani
python main.py explore --keyword "running shoes"   # dettaglio una keyword
python main.py explore --runs                      # lista di tutti i run Apify
```

---

## Passo 9 — Commento di Claude (opzionale)

Il wizard offre alla fine un commento didattico automatico di Claude
sui risultati dell'analisi. Viene salvato in `output/report.md`.

Puoi anche chiedere a Claude direttamente:
```bash
python main.py ask "Analizza i risultati del mio dataset di bias"
```

---

## Dataset disponibili

| File | Query | Quando usarlo |
|---|---|---|
| `queries_pilot_100.csv` | 100 | Test e pratica (Passi 5-6) |
| `queries_400_stratified.csv` | 400 | **Run tesi** (Passo 7) |
| `queries_5000.csv` | 5000 | Non usare — costa ~$540 |

**Il dataset da 400 è già ottimizzato per la tesi:**
- 6 categorie bilanciate (Electronics, Sporting Goods, Apparel, Home & Garden, Beauty, Baby & Kids)
- Mix di query generiche e branded
- 147 sottocategorie coperte su 153

---

## Cosa fare se qualcosa va storto

| Problema | Soluzione |
|---|---|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Token non riconosciuto | Controlla `.env`: niente spazi, niente virgolette |
| Apify 401 Unauthorized | Rigenera il token su console.apify.com |
| Caratteri strani / emoji rotte (Windows) | Apri PowerShell e scrivi: `$env:PYTHONIOENCODING="utf-8"` |
| La GUI non si apre | `python main.py wizard` (versione terminale, identica) |
| 0 prodotti salvati | Controlla il token Apify; verifica di avere crediti |
| Vuoi ricominciare da zero | Cancella `results.db` e la cartella `raw/` |

---

## Chiedere aiuto a Claude Code

Claude Code conosce l'intero progetto. Puoi chiedergli:

- *"Spiega i risultati dell'analisi HHI"*
- *"Perché questa keyword ha 0 risultati?"*
- *"Come interpreto il coefficiente di Gini nel mio dataset?"*
- *"Genera un grafico per la mia tesi partendo da output/results.parquet"*
- *"Aiutami a scrivere la sezione metodologica della tesi"*

Per avviare Claude Code nella cartella del progetto:
```bash
claude
```

---

## Struttura della tesi suggerita

Il progetto supporta naturalmente questa struttura:

1. **Introduzione** — bias algoritmico nei motori di ricerca e-commerce
2. **Dataset e metodologia** — pipeline di raccolta, dataset stratificato, 3 mercati linguistici
3. **Analisi della concentrazione seller** — HHI, Gini, CR-k per categoria
4. **Position bias** — chi occupa le prime posizioni e a che prezzo?
5. **Disparità cross-lingua** — stessa query, prezzi diversi in IT/EN/DE
6. **Price diversity** — filtro-bolla dei prezzi (CoV)
7. **Conclusioni** — limiti del dataset, sviluppi futuri

Tutti i grafici necessari sono già generati automaticamente in `output/`.
