# LightGBM-reduced

LightGBM/LambdaMART bias audit on the **first (reduced) scraping dataset** (`results.db`, ~53k rows,
IT/EN/DE) — the version where `rating`/`reviews` are largely missing and there is no sponsored flag.
A richer SerpApi re-scrape is used in later iterations (see the repo root README).

## Files
- `bias_ranking_audit.py` — CLI audit (baselines, merit vs merit+seller, multi-seed, SHAP, CSV, figures).
- `bias_ranking_audit.ipynb` — narrated notebook (GPU test, offline model option, 3 figures, CSV).
- `setup.sh` / `launch_bias.sh` — environment setup and launcher.
- `figures/` — example figures (full MiniLM, IT).

## Quick start
```bash
bash setup.sh                 # creates the 'bias' env (TORCH_VARIANT=cpu for CPU-only)
bash launch_bias.sh           # opens the notebook
# or CLI:
bias/bin/python bias_ranking_audit.py --db results.db --country IT \
    --encoder sentence-transformers --model-path minilm_it --seeds 10
```
Put `results.db` (and optionally `minilm_it/`) in this folder. Outputs:
`bias_summary_<country>_<encoder>.csv` + 3 PNGs (NDCG, lift distribution, SHAP).

## Result (IT, 10 seeds)
| encoder | merit only | +seller | lift | is_amazon SHAP |
|---|---|---|---|---|
| tfidf | 0.449 | 0.512 | +0.062 | −0.144 |
| model2vec | 0.450 | 0.513 | +0.063 | −0.145 |
| sentence-transformers | 0.442 | 0.510 | +0.068 | −0.139 |

The seller improves the reconstruction (**lift ≈ +0.065**, stable), but it is driven by seller
**prevalence** (`seller_freq_log`), not by Amazon identity — which is **penalised** (negative SHAP).
The result does **not** change from TF-IDF to full MiniLM. **No evidence of pro-seller bias in the
observable organic ranking.** The modest NDCG (~0.49) means much of what drives Google's order is
**unobservable** (sponsored, personalisation, quality).
