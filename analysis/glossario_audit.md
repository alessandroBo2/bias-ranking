# Glossary of the Google Shopping bias audit
*Explanation of the terms for a non-technical (marketing) audience.*

---

## The idea in one sentence
We train a model to **guess the order in which Google arranged the products** on the page,
using only observable characteristics. If, to guess well, it needs to know *who the seller is*
(and price and relevance are not enough), then the seller "weighs" beyond merit: that's where we
look for a possible bias.

---

## The terms

**Merit** — The characteristics that *legitimately* should explain a good position:
relevance of the title to the search, price, title quality/length, category, branded or generic
search. It's the measurable "why you deserve to be at the top".

**Merit only** — The model we give **only** the merit characteristics. It doesn't know who sells the
product. It has to reconstruct Google's order with its hands tied.

**Merit + seller** — The exact same model, but it also knows **who sells**: whether it's Amazon, whether
it's a retail "giant", and how often that seller appears in the data (prevalence).

**NDCG@10** — The score for how well the model guessed the order, focusing on the **top 10**
results (the ones that matter). It runs roughly from 0 to 1: higher = more faithful reconstruction.
*Note:* it is not a percentage of "correct answers", and the chance line is not 0 but ~0.40
(see the random baseline). The useful range therefore goes from ~0.40 (random) to 1.0 (perfect).

**Lift** — The **increase** obtained by adding a lever (same concept as uplift in marketing).
Here = how much NDCG rises going from "merit only" to "merit + seller".
In our IT data the lift is **≈ +0.065**, stable. It means: knowing who the seller is helps
reconstruct the order *beyond* what price and relevance already explain.

**Baseline (random / ascending price)** — Two reference "rulers". *Random* = random order
(~0.40). *Ascending price* = from cheapest (~0.389). They serve to show that the "merit" model
(~0.43) learns something real, and that **Google does not order by price** (ordering by price does
worse than random).

**SHAP** — *SHapley Additive exPlanations.* A method that explains, **for each single product**, how
much and in which direction each characteristic pushed it up the ranking. It is based on *Shapley
values*, a concept from game theory (Lloyd Shapley, Nobel laureate in economics) that fairly
distributes a team result among its members. In practice it decomposes a product's final score
into many "+" and "−", one per lever.

---

## How to read the SHAP chart (beeswarm)

- **Vertical axis**: the variables, ordered from the **most important (at the top)** to the least.
- **Horizontal axis**: the SHAP value. **Right = pushes up** the ranking, **left = pushes
  down**. The line at zero = no effect.
- **Each dot is a product** (a row of the dataset).
- **Color** = value of the characteristic: **red = high, blue = low**.

Combining color and position you can read the *rule* the model learned. In our charts:

- `seller_freq_log` (seller prevalence) — **the strongest lever**: the red dots (a seller that
  appears often) are on the right → the more prevalent, the more it is pushed up.
- `is_amazon` (binary: red = is Amazon) — the red dots are **on the left** (≈ −0.14):
  **being Amazon pushes down**, not up → no pro-Amazon favoritism.
- `log_price` — high price (red) tends slightly to the left → small push downward.
- `rel` (relevance) — small effect and low in the list → textual relevance counts little for
  Google's order.

---

## The conclusion in two lines
The model that knows the seller reconstructs Google's order better (**lift ≈ +0.065**), but that
advantage comes from the seller's **prevalence** (market structure), not from being Amazon — which
is in fact penalized. The result does not change between TF-IDF and MiniLM. **No evidence of
pro-seller bias in the observable organic ranking.**

> Why NDCG is "only" ~0.49 and that's perfectly fine: if price, relevance and seller were enough to
> reconstruct the order almost perfectly, it would mean the order is entirely there. Not managing it
> means that much of what moves the ranking is **unobservable** (sponsored, personalization,
> quality) — exactly the data limit: the **sponsored flag** and the **ratings** are missing.
> The audit says "no evident bias in the measurable organic ranking", not "Google is neutral".
