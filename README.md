# bias-ranking — Google Shopping bias audit

A study to understand whether Google Shopping ranking favours certain sellers/prices **beyond**
what observable merit (relevance, price, quality) would justify.

The repo has two parts:

```
scraper/    # baseline: data collection from Google Shopping (ScraperAPI + Apify fallback)
analysis/   # audit with learning-to-rank (LightGBM/LambdaMART) + SHAP interpretation
```

---

## scraper/ — data collection

A pipeline that queries Google Shopping for a list of keywords (multilingual IT/EN/DE CSV),
with two backends:

- **ScraperAPI** (`scraper_api.py`) — primary backend, *structured* endpoint, cheap;
- **Apify** (actor `burbn/google-shopping-scraper`) — historical / fallback backend, richer.

Output: `products` table in SQLite (`results.db`) + raw dumps in `raw/` (not versioned).
Token configuration via `.env` (see `.env.template`). Guided start: `python main.py wizard`.

### SerpApi re-scrape (rich schema) — `serpapi_shopping.py`

A new backend that collects the organic Shopping tab with a **rich schema**: `product_id`
(100%), `rating`/`reviews` (~65–95%), `source`, `delivery`, `tag`. One search = one SERP (40
results). This is what enables *within-product* and *quality-adjusted* analysis.

```bash
cd scraper
echo "SERPAPI_KEY=your_key" >> .env
python serpapi_shopping.py --csv queries_5000.csv --locale IT --estimate   # dry-run estimate, $0
python serpapi_shopping.py --csv queries_5000.csv --locale IT              # real run -> results_serpapi.db
python serpapi_shopping.py --csv queries_5000.csv --locale IT --limit 100  # pilot
```
**Resumable** (it saves completed query_ids; a re-run resumes), with `--max-searches` as an
overrun cap. The 5,000 unique concepts on **a single locale** = 5,000 searches = Developer plan (~$75),
a clean market (one currency) and ~10× the current SERPs.

> **Note on the sponsored flag:** validated that SerpApi `google_shopping` returns **only
> the organic results** (no ads), and that shopping ads are volatile and not reliably exposed
> for IT/DE. So the organic dataset is *clean by construction* and the audit doesn't need them.

> **Current data limitations** (important when reading the results):
> 1. `rating`/`reviews_count` empty at ~98.6% → the ScraperAPI structured backend does not
>    return them; they only come from the Apify path (~1.4% of rows).
> 2. **Missing sponsored/organic flag** → the most direct variable of "Google bias"
>    is not captured by either backend (Apify returns only the organic results).
> 3. **Product id (`docid`/`catalogid`) present in the raw dumps but discarded during parsing** →
>    recoverable without re-scraping; enables *within-product* analysis.
> 4. Currency confounded with locale (EN=USD, DE/IT=EUR) → prices not comparable across markets.

---

## analysis/ — learning-to-rank audit

A model is trained to **reconstruct Google's ordering** from observable features, and two
variants are compared:

- **merit only**: price, keyword↔title relevance, title length, category, branded/generic;
- **merit + seller**: adds `is_amazon`, `is_giant`, `seller_freq_log`.

Model: **LightGBM `lambdarank`** grouped by SERP (`run_id`), evaluated with **NDCG@10** on
held-out SERPs, interpreted with **SHAP**. Relevance uses a multilingual semantic encoder
(MiniLM via `sentence-transformers`, or static `model2vec`; TF-IDF fallback).

### Usage
```bash
cd analysis
bash setup.sh                 # creates the 'bias' env (torch cu124 by default; TORCH_VARIANT=cpu for CPU)
bash launch_bias.sh           # opens the notebook
# or from the CLI:
bias/bin/python bias_ranking_audit.py --db ../results.db --country IT \
    --encoder sentence-transformers --model-path minilm_it --seeds 10
```
Generates: `bias_summary_<country>_<encoder>.csv` + 3 charts (NDCG, lift distribution, SHAP).
See `glossario_audit.md` for the non-technical explanation of the terms (merit, lift, NDCG, SHAP).

### Current results (IT market, 10 seeds)

| encoder | merit only | +seller | lift | is_amazon SHAP |
|---|---|---|---|---|
| tfidf | 0.449 | 0.512 | +0.062 | −0.144 |
| model2vec | 0.450 | 0.513 | +0.063 | −0.145 |
| sentence-transformers (MiniLM) | 0.442 | 0.510 | +0.068 | −0.139 |

**Reading:** the seller improves the reconstruction of the ordering (**lift ≈ +0.065**, stable), but it is
driven by seller **prevalence** (`seller_freq_log`), not by the Amazon identity — which is in fact
**penalized** (negative `is_amazon` SHAP). The result **does not change** going from TF-IDF to the
full MiniLM → the lift is not unmeasured relevance. **No evidence of pro-seller bias in the
observable organic ranking.** The modest NDCG (~0.49) indicates that much of what drives
Google's ordering is **unobservable** (sponsored, personalization, quality).

Figures in `analysis/figures/`.

---

## Next steps

1. **Recover `catalogid` from the raw dumps** (free) → *within-product* audit with product fixed effects.
2. **Sponsored flag** — the most important missing variable. Requires a SERP scraper that
   captures the *shopping ads* block (e.g. SerpApi `google_shopping`: exposes `tag`/`badge` and
   `inline_shopping_results`, plus `product_id` and rating). First validate at zero cost on the free
   plan with `analysis/validate_serpapi.py`, then a single re-scrape collects organic + sponsored
   + rating + product_id together.

   ```bash
   cd analysis
   # put SERPAPI_KEY=... in .env (free plan), then:
   python validate_serpapi.py                 # IT + DE, 3 keywords each
   python validate_serpapi.py --with-search   # also checks the ads block of the 'google' engine
   ```
   Prints sponsored/product_id/rating coverage per locale and saves the raw responses in
   `validation_samples/` for inspection.
3. "Quality-adjusted" rating and a quasi-experimental design (single locale, same keywords over time).
