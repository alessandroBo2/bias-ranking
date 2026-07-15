# Glossary of the Google Shopping bias audit
*Explanation of the terms for a non-technical (marketing) audience.*

---

## The idea in one sentence
We train a model to **guess the order in which Google arranged the products** on the page,
using only observable characteristics. If, to guess well, it needs to know *who the seller is*
(and price and relevance are not enough), then the seller "weighs" beyond merit: that is where we
look for a possible bias.

---

## The terms

**Merit** — The characteristics that should *legitimately* explain a good position:
relevance of the title to the search, price, quality/length of the title, category, branded or
generic search. It is the measurable "why you deserve to rank high".

**Merit only** — The model that gets **only** the merit characteristics. It does not know who sells
the product. It has to reconstruct Google's order with its hands tied.

**Merit + seller** — The exact same model, but it additionally knows **who sells**: whether it is
Amazon, whether it is a retail "giant", and how often that seller appears in the data (prevalence).

**NDCG@10** — The score of how well the model guessed the order, focusing on the **first 10**
results (the ones that matter). It goes roughly from 0 to 1: higher = more faithful reconstruction.
*Caution:* it is not a percentage of "correct answers", and the chance line is not 0 but ~0.40
(see random baseline). The useful range therefore goes from ~0.40 (random) to 1.0 (perfect).

**Lift** — The **increase** obtained by adding a lever (the same concept as uplift in marketing).
Here = how much the NDCG rises when moving from "merit only" to "merit + seller".
In our IT data the lift is **≈ +0.065**, stable. It means: knowing who the seller is helps
reconstruct the order *beyond* what price and relevance already explain.

**Baseline (random / price ascending)** — Two reference "rulers". *Random* = random order
(~0.40). *Price ascending* = cheapest first (~0.389). They serve to show that the "merit" model
(~0.43) learns something real, and that **Google does not sort by price** (sorting by price does
worse than chance).

**SHAP** — *SHapley Additive exPlanations.* A method that explains, **for every single product**,
how much and in which direction each characteristic pushed it in the ranking. It is based on the
*Shapley values*, a concept from game theory (Lloyd Shapley, Nobel laureate in economics) that
splits a team result among its members in a fair way. In practice it decomposes a product's final
score into many "+" and "−", one for each lever.

---

## How to read the SHAP plot (beeswarm)

- **Vertical axis**: the variables, ordered from the **most important (top)** to the least.
- **Horizontal axis**: the SHAP value. **Right = pushes up** in the ranking, **left = pushes
  down**. The line at zero = no effect.
- **Each dot is a product** (one row of the dataset).
- **Color** = value of the characteristic: **red = high, blue = low**.

Combining color and position you can read the *rule* the model learned. In our plots:

- `seller_freq_log` (seller prevalence) — **the strongest lever**: the red dots (seller that
  appears often) sit on the right → the more prevalent, the more it gets pushed up.
- `is_amazon` (binary: red = it is Amazon) — the red dots sit **on the left** (≈ −0.14):
  **being Amazon pushes down**, not up → no pro-Amazon favoritism.
- `log_price` — a high price (red) leans slightly left → a small push downward.
- `rel` (relevance) — small effect and low in the list → textual relevance matters little for
  Google's order.

---

## The conclusion in two lines
The model that knows the seller reconstructs Google's order better (**lift ≈ +0.065**), but that
advantage comes from the seller's **prevalence** (market structure), not from being Amazon — which
actually turns out to be penalized. The result does not change between TF-IDF and MiniLM. **No
evidence of pro-seller bias in the observable organic ranking.**

> Why an NDCG of "only" ~0.49 is perfectly fine: if price, relevance and seller were enough to
> reconstruct the order almost perfectly, it would mean the order is all there. Failing to do so
> means that much of what drives the ranking is **unobservable** (sponsored placement,
> personalization, quality) — exactly the limitation of the data: the **sponsored flag** and the
> **ratings** are missing. The audit says "no evident bias in the measurable organic ranking",
> not "Google is neutral".
