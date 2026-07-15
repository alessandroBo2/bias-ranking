# Schema mapping — temporal data (Paul's format) → repo schema

The shared temporal runs (one 2023 pre-DMA week + CW4, CW5, CW6, CW14 of 2024,
at the shopping-unit and page-element level, Stata `.dta` files) use column names different
from our `serp_ads` schema. `build_panel.py` applies this mapping; **update it here and
in the `SCHEMA_MAPPING` constant of the script** after inspecting the real files.

## Columns

| Paul's format (expected) | repo schema | notes |
|---|---|---|
| `cssname` | `css_partner` | lowercased during cleaning; Google identified by the `google` prefix |
| `merchantlink` / `merchant` | `seller` | lowercased during cleaning |
| `position` / `pos` | `position` | only positions ≤ 16 kept (authors' cleaning) |
| `query` | `keyword` | merge key with `queries_for_merge.dta` |
| `time` / `timestamp` | `run_id` | identifies the SERP |
| `price` | `price_value` | |
| (element column, to verify) | `unit_variant` | candidates: `element`, `unittype`; exists only in post-redesign runs |

## Replicated cleaning (for comparability with the authors)

1. `position <= 16`
2. lowercase of `cssname` and `merchantlink`
3. merge of the categories from `queries_for_merge.dta` on the query key; unmerged
   rows are **not silently discarded**: they are counted per wave in
   `attrition_report.csv`

## Outcomes per (query × wave) — defined to be computable in both regimes

| outcome | definition | regime |
|---|---|---|
| `google_css_share` | share of offers with CSS = Google | all waves |
| `google_css_first_slot` | CSS = Google in the slot at the minimum position | all waves |
| `rival_css_present` | at least one offer with a rival CSS | all waves |
| `n_css_partners` | number of distinct CSSs on the SERP | all waves |
| `new_element_present` | the new post-redesign element is present | 2024 waves only (NA in 2023) |

The 2023 run contains neither the new element nor (probably) the same container
structure: for this reason the main outcomes are defined on the classic Shopping Unit,
always observable, and the metrics of the new element are populated only where the
variant exists — the DMA event is thus not confounded with a change of definition.

## Pre-specified design (thesis, §3.7)

Difference-in-differences on the balanced panel (queries present in all waves),
treatment = rollout cohort (first wave in which the query shows the new design),
*not-yet-treated* controls; outcomes as above. Errors clustered by query.
