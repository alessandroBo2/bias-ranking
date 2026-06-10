# bias-ranking — Audit di bias su Google Shopping

Studio per capire se il ranking di Google Shopping favorisce certi venditori/prezzi **oltre**
ciò che il merito osservabile (rilevanza, prezzo, qualità) giustificherebbe.

Il repo contiene due parti:

```
scraper/    # baseline: raccolta dati da Google Shopping (ScraperAPI + fallback Apify)
analysis/   # audit con learning-to-rank (LightGBM/LambdaMART) + interpretazione SHAP
```

---

## scraper/ — raccolta dati

Pipeline che interroga Google Shopping per una lista di keyword (CSV multilingua IT/EN/DE),
con due backend:

- **ScraperAPI** (`scraper_api.py`) — backend primario, endpoint *structured*, economico;
- **Apify** (actor `burbn/google-shopping-scraper`) — backend storico / fallback, più ricco.

Output: tabella `products` in SQLite (`results.db`) + dump grezzi in `raw/` (non versionati).
Configurazione token via `.env` (vedi `.env.template`). Avvio guidato: `python main.py wizard`.

> **Limiti dei dati attuali** (importanti per leggere i risultati):
> 1. `rating`/`reviews_count` vuoti al ~98,6% → il backend structured di ScraperAPI non li
>    restituisce; arrivano solo dal path Apify (~1,4% delle righe).
> 2. **Manca il flag sponsorizzato/organico** → la variabile più diretta del "bias di Google"
>    non è catturata da nessuno dei due backend (Apify restituisce solo l'organico).
> 3. **Product id (`docid`/`catalogid`) presente nei grezzi ma scartato in fase di parsing** →
>    recuperabile senza ri-scraping; abilita l'analisi *within-product*.
> 4. Valuta confusa col locale (EN=USD, DE/IT=EUR) → prezzi non confrontabili tra mercati.

---

## analysis/ — audit learning-to-rank

Si addestra un modello a **ricostruire l'ordine di Google** dalle feature osservabili e si
confrontano due varianti:

- **solo merito**: prezzo, rilevanza keyword↔titolo, lunghezza titolo, categoria, branded/generic;
- **merito + venditore**: aggiunge `is_amazon`, `is_giant`, `seller_freq_log`.

Modello: **LightGBM `lambdarank`** raggruppato per SERP (`run_id`), valutato con **NDCG@10** su
SERP held-out, interpretato con **SHAP**. La rilevanza usa un encoder semantico multilingue
(MiniLM via `sentence-transformers`, oppure `model2vec` statico; fallback TF-IDF).

### Uso
```bash
cd analysis
bash setup.sh                 # crea l'ambiente 'bias' (torch cu124 di default; TORCH_VARIANT=cpu per CPU)
bash launch_bias.sh           # apre il notebook
# oppure da CLI:
bias/bin/python bias_ranking_audit.py --db ../results.db --country IT \
    --encoder sentence-transformers --model-path minilm_it --seeds 10
```
Genera: `bias_summary_<paese>_<encoder>.csv` + 3 grafici (NDCG, distribuzione lift, SHAP).
Vedi `glossario_audit.md` per la spiegazione non tecnica dei termini (merito, lift, NDCG, SHAP).

### Risultati attuali (mercato IT, 10 seed)

| encoder | solo merito | +venditore | lift | is_amazon SHAP |
|---|---|---|---|---|
| tfidf | 0,449 | 0,512 | +0,062 | −0,144 |
| model2vec | 0,450 | 0,513 | +0,063 | −0,145 |
| sentence-transformers (MiniLM) | 0,442 | 0,510 | +0,068 | −0,139 |

**Lettura:** il venditore migliora la ricostruzione dell'ordine (**lift ≈ +0,065**, stabile), ma è
guidato dalla **prevalenza** del venditore (`seller_freq_log`), non dall'identità Amazon — che anzi
è **penalizzata** (`is_amazon` SHAP negativo). Il risultato **non cambia** passando da TF-IDF al
MiniLM pieno → il lift non è rilevanza non misurata. **Nessuna prova di bias pro-venditore nel
ranking organico osservabile.** L'NDCG modesto (~0,49) indica che gran parte di ciò che muove
l'ordine di Google è **non osservabile** (sponsorizzato, personalizzazione, qualità).

Figure in `analysis/figures/`.

---

## Prossimi passi

1. **Recupero `catalogid` dai grezzi** (gratis) → audit *within-product* con product fixed-effects.
2. **Flag sponsorizzato** — la variabile mancante più importante. Richiede uno scraper SERP che
   catturi il blocco *shopping ads* (es. SerpApi `google_shopping`: espone `tag`/`badge` e
   `inline_shopping_results`, oltre a `product_id` e rating). Prima si valida a costo zero sul free
   plan con `analysis/validate_serpapi.py`, poi un solo re-scrape raccoglie organico + sponsorizzato
   + rating + product_id insieme.

   ```bash
   cd analysis
   # metti SERPAPI_KEY=... in .env (free plan), poi:
   python validate_serpapi.py                 # IT + DE, 3 keyword each
   python validate_serpapi.py --with-search   # controlla anche il blocco ads dell'engine 'google'
   ```
   Stampa la copertura di sponsorizzato/product_id/rating per locale e salva i grezzi in
   `validation_samples/` per ispezione.
3. Rating "qualità-aggiustata" e disegno quasi-sperimentale (un solo locale, stesse keyword nel tempo).
