# Schema mapping — temporal shopping-unit data → repo schema

Real data drop (verified 15 Jul 2026): a single Stata file
`shopping unit data/final_2023_24.dta` (~716 MB, 448,992 rows), containing —
despite the name — **only ISO week 24 of 2023** (13–14 June 2023, pre-DMA
baseline): 23,742 queries, one row per PLA slot plus one placeholder row per
query when no shopping unit was shown. Categories are already included
(no external `queries_for_merge` file needed). The 2024 waves (CW4/5/6/14)
announced by the authors are **not in this drop** and must be requested;
`build_panel.py --dta` ingests them unchanged once they arrive.

## Columns (real names → repo schema, applied by `build_panel.py`)

| source column | repo schema | notes |
|---|---|---|
| `year`, `week` | `wave` | e.g. `2023w24` |
| `time` | `run_id` | SERP identifier (timestamp) |
| `query` | `keyword` | same universe as `searchdatabase.xlsx` (27,507 keywords) |
| `category`, `subcategory` | `category_l1`, `category_l2` | already merged in the file |
| `d_su` | `su_present` | 1 = classic Shopping Unit shown for the query |
| `totalplas` | `total_plas` | number of PLAs in the unit |
| `positioninsu` | `position` | NaN on placeholder rows; kept only if ≤ 16 |
| `merchantlink` / `merchantname` | `seller` / `seller_name` | lowercased during cleaning |
| `cssname` (+ `csslink`) | `css_partner` | lowercased; Google identified by `^google` prefix |
| `d_css_pla` | `d_css_pla` | authors' CSS-PLA flag, kept as-is |
| `price`, `pricebefore` | `price_value` | German-formatted strings, literal `'NA'` → NaN |
| `rating`, `totalratings` | `rating`, `rating_count` | |
| `productname`, `productlink` | — | not needed by the audit; dropped to keep the panel slim |

## Replicated cleaning (for comparability with the authors)

1. `position <= 16`
2. lowercase of `cssname` and `merchantlink`
3. literal `'NA'` strings converted to missing
4. placeholder rows (no SU) are excluded from the offers table but **kept**
   for query-level presence, so `su_present` and the balanced panel are
   computed on all executed queries

## Outcomes per (query × wave)

| outcome | definition |
|---|---|
| `su_present` | classic Shopping Unit shown |
| `google_css_share` | share of PLAs with CSS = Google |
| `google_css_first_slot` | CSS = Google in the minimum-position slot |
| `rival_css_present` | at least one PLA from a rival CSS |
| `n_css_partners` | distinct CSSs in the unit |
| `median_price` | median PLA price |

## Two-wave pre/post (implemented: `prepost_2023_2024.py`)

Until the authors' 2024 waves arrive, the post-DMA wave is our parsed
sample of 3 April 2024 (= ISO week 14, `serp_ads` table), restricted to the
**classic unit** and positions ≤ 16 so both waves measure the same construct.
All 852 sampled queries are present in the 2023 baseline (same universe).
Documented caveat: the two waves come from different collection instruments;
the pipeline re-runs unchanged on the authors' 2024 files when available.

## Pre-specified design (thesis, §3.7)

With ≥ 2 authors' waves in 2024: difference-in-differences on the balanced
panel, treatment = rollout cohort, *not-yet-treated* controls, errors
clustered by query. With the current two waves: paired within-query
pre/post differences (see `prepost_2023_2024.py`).
