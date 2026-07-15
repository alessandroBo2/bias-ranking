# serp_dma — sponsored layer from general SERPs (DMA-paper data)

Tools to extract and use the shopping offers (PLA) from the general Google SERPs
collected in the style of Püplichhuisen & Sirries (SSRN 5185731, *"DMA in Effect and
(In)effective?"*) — e.g. the `Data_for_Alessandro` sample (DE market, April 3, 2024,
1,030 queries, 1,000 HTML SERPs).

It fills gap #2 of the main README: the **sponsored flag** and the
**CSS (comparison shopping service)** dimension that the ScraperAPI/Apify/SerpApi
backends do not capture on general SERPs.

## Structure of the source data

- `searchdatabase(.en).xlsx` — dictionary of the 27,507 DE keywords with
  category/subcategory taxonomy (input of the crawl, **not** parsed data).
- `overview query files/*.xlsx` — crawl logs: one row per query with presence
  flags (`su_google`, `blocked`, ...). No offer-level data.
- `raw html files/<timestamp>_google.html` — the saved SERPs: the offer level
  lives only here and is extracted by `parse_serp_ads.py`.

## Usage

```bash
pip install pandas beautifulsoup4 lxml openpyxl pyarrow
python parse_serp_ads.py \
    --html-dir     "<...>/Data_for_Alessandro/raw html files" \
    --overview-dir "<...>/Data_for_Alessandro/overview query files" \
    --db results_serp_dma.db --parquet serp_ads.parquet
```

Output: **`serp_ads`** table in SQLite. ~20,500 offers from 852 SERPs (~24 per SERP).

## Schema

Compatible with `products` where the concepts coincide, so the same features
of the audit (`log_price`, `rel`, `title_len`, `is_amazon`, `seller_freq_log`, ...)
can be built without modifications:

| column | notes |
|---|---|
| `run_id` | timestamp of the SERP = lambdarank group (one SERP = one group) |
| `keyword`, `query_original` | query (DE) |
| `category_l1`, `category_l2` | taxonomy from the searchdatabase |
| `position` | slot in the shopping unit (1 = most visible) |
| `title`, `price_value`, `currency`, `seller` | as in `products` |
| `language`, `query_type` | 'DE', 'generic' |
| `shipping_text`, `rating_count` | ad extension |
| `css_partner` | CSS that places the ad ("Google", "Producthero", ...) |
| `unit_variant` | `top` = classic Shopping Unit (≡ `su_google` flag), `top_pla_group` = new post-DMA element |
| `sponsored_unit` | 1 if classic Shopping Unit |

## Why a separate table and NOT a merge into `products`

`products` is the **organic ranking of the Shopping tab** (IT); `serp_ads` are
**sponsored auction slots on the general SERP** (DE, Apr 2024). Different ranking
mechanisms, market and period: a model trained on mixed rows learns a
mixture of two processes and the SHAP loses interpretability.

## How to use them for training

1. **Twin models (recommended)** — same feature set and same protocol
   as the audit (`analysis/bias_ranking_audit.py`), one model per layer;
   lift and SHAP are compared between organic and sponsored. For the sponsored layer
   add `is_google_css = (css_partner == 'Google')` to the platform features.
2. **Joint model (robustness only)** — concatenate the two layers with a `layer`
   feature; the groups (`run_id`) never mix the layers, so the group-split
   remains valid.

## Learning-to-rank audit on the sponsored layer

`audit_sponsored.py` replicates the protocol of `analysis/bias_ranking_audit.py`
(LambdaMART per SERP, held-out NDCG@10, 10 seeds) on the `serp_ads` table, with three
models: merit only → +seller → +CSS identity (`is_google_css`).

```bash
python audit_sponsored.py --db ../results_serp_dma.db --seeds 10
```

Results (10 seeds, TF-IDF):

| sample | seller lift | CSS lift | SHAP is_google_css | SHAP is_amazon |
|---|---|---|---|---|
| all units | +0.059 ± 0.008 | −0.003 ± 0.007 | +0.007 ± 0.007 | −0.218 ± 0.029 |
| classic SU (`top`) | +0.041 ± 0.011 | +0.003 ± 0.006 | −0.025 ± 0.015 | −0.109 ± 0.047 |
| new `top_pla_group` | +0.056 ± 0.011 | −0.001 ± 0.010 | **+0.065 ± 0.023** | −0.045 ± 0.068 |

**Reading.** As in the organic layer, the seller helps reconstruct the order (lift
+0.04/+0.06) but via prevalence (`seller_freq_log`), and Amazon is penalized even
in the sponsored slots. The Google-CSS identity **adds no predictive power**
beyond the seller (CSS lift ≈ 0): Google's descriptive advantage in position 1
(53.8%) is absorbed by seller composition and frequency. The only nuance: in the
new post-DMA element the SHAP contribution of `is_google_css` is positive
(+0.065) while in the classic SU it is ≈ 0/negative — consistent with Google's share in
position 1 being higher precisely there (60.7%).

*Methodological caveat (inherited from the protocol of `analysis/`)*: the
random/price baselines use `sklearn.ndcg_score` (linear gains) while the models report
LightGBM's internal NDCG (exponential label_gain) — compare the models with each
other, not with the baselines.

## Descriptive results on the sample (DE, 3/4/2024)

- Classic Shopping Unit in 45% of the SERPs; new `top_pla_group` in another 40%.
- **Google-CSS places 45.6% of the ads** (fragmented competitors: Producthero
  7.9%, Adference 7.6%, smec 5.1%, ...).
- **Google's positional advantage**: share in position 1 = 53.8% overall;
  60.7% in the new post-DMA element (vs 47.1% across all positions).
- Merchants: Temu and Shein dominate; **Amazon only 3.3%** — consistent with the
  organic audit (negative `is_amazon` SHAP).

**Limitations**: a single day, a single locale (DE), 2 categories out of 15 → descriptive
cross-section, no temporal panel.
