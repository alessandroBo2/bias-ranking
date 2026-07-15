# Student Guide — Product Scraper for Thesis

This guide takes you from installation to the full analysis,
step by step. Follow the order: each step verifies that the
previous one completed successfully.

---

## Before you start: what you need

| What | Where to get it |
|---|---|
| Python ≥ 3.10 | https://www.python.org/downloads/ |
| Apify account (already done) | https://console.apify.com |
| Anthropic account (already done) | https://console.anthropic.com |
| Your API keys | See §1 below |

**Estimated costs for the full thesis (400 queries × 3 languages):**
- Apify Starter plan: $49/month
- Credits for the queries: ~$130
- **Total: ~$179** — stays within the $200 budget

---

## Step 1 — Configure the API keys

The project uses two paid services. The keys go in the `.env` file
(already present in the folder, without values).

**APIFY_TOKEN:**
1. Go to https://console.apify.com
2. Click your avatar in the top right → **Settings**
3. **Integrations** tab → **API token** → copy the token

**ANTHROPIC_API_KEY:**
1. Go to https://console.anthropic.com
2. **API Keys** menu → **Create Key** → copy the key

Open the `.env` file with a text editor (Notepad is fine) and replace the placeholders:

```
APIFY_TOKEN=apify_api_put_your_token_here
ANTHROPIC_API_KEY=sk-ant-put_your_key_here
```

Save the file. **Never share this file with anyone.**

---

## Step 2 — Install the dependencies

Open a terminal in the project folder and run:

```bash
pip install -r requirements.txt
```

Wait for it to complete (1-3 minutes). If you see errors, try:
```bash
python -m pip install -r requirements.txt
```

---

## Step 3 — Verify the configuration

```bash
python -c "
from dotenv import load_dotenv; import os; load_dotenv()
at = os.environ.get('APIFY_TOKEN','')
ak = os.environ.get('ANTHROPIC_API_KEY','')
print('APIFY_TOKEN:', 'OK' if at.startswith('apify_api_') else 'MISSING or WRONG')
print('ANTHROPIC_API_KEY:', 'OK' if ak.startswith('sk-ant-') else 'MISSING or WRONG')
"
```

Two `OK` must appear. If `MISSING` appears, go back to Step 1.

---

## Step 4 — Open the GUI (recommended starting point)

```bash
python main.py gui
```

A window opens with two tabs:
- **🧙 Wizard** — to run the full pipeline
- **🔍 Explorer** — to explore the data already collected

Keep it open: you will use it for all the work.

---

## Step 5 — First test (small, cheap)

Before spending the $179 of the full run, do a test with a few queries.

In the GUI, **Wizard** tab, click **🚀 Start Wizard**. A terminal opens. Follow the instructions:

1. **Which CSV?** → choose `queries_pilot_100.csv`
2. **L1 category?** → `(all)`
3. **Query type?** → `(all)`
4. **How many queries?** → type `3`
5. **Languages?** → choose only `IT` (type `1`)
6. **Results per query?** → leave `20` (you cannot set less)
7. **Concurrency?** → leave `3`

The wizard shows the **cost estimate** before proceeding:
```
FREE tier cost:                   $1.23
BRONZE cost (Starter $49/month):  $0.32
```

Type `y` to confirm. The test takes 1-3 minutes.

**What to expect:** the wizard prints the products found, then automatically
generates analytics and bias and opens the dashboards in the browser.

---

## Step 6 — Explore the test data

In the GUI, **Explorer** tab, click **▶ Run Explorer**.
You will see an overview: how many products, by language, by category, top sellers.

Also try:
- Select language `IT` and re-run
- Type a keyword in the dedicated field and re-run

---

## Step 7 — Full thesis run

When you are ready (and have the Apify Starter plan active):

1. In the GUI → **🚀 Start Wizard**
2. CSV → `queries_400_stratified.csv`
3. Category → `(all)`
4. Type → `(all)`
5. How many queries → `400`
6. Languages → `IT`, `EN`, `DE` (all three, type `1,2,3`)
7. Results → `20`
8. Concurrency → `3`

The wizard shows the cost estimate (~$179). Read it carefully, then confirm.

**Estimated duration:** 3-5 hours. You can leave it running in the background.

At the end, the following open automatically in the browser:
- `output/dashboard.html` — general analytics
- `output/bias_dashboard.html` — bias analysis

---

## Step 8 — Analyzing the results

If you want to regenerate the analyses without re-running the scraping:

```bash
python main.py analytics   # regenerates the analytics dashboard
python main.py bias        # regenerates the bias dashboard
```

To explore the data in the terminal with filters:
```bash
python main.py explore                             # full overview
python main.py explore --lang IT                   # Italian data only
python main.py explore --keyword "running shoes"   # detail for one keyword
python main.py explore --runs                      # list of all Apify runs
```

---

## Step 9 — Claude's commentary (optional)

At the end, the wizard offers an automatic educational commentary by Claude
on the analysis results. It is saved in `output/report.md`.

You can also ask Claude directly:
```bash
python main.py ask "Analizza i risultati del mio dataset di bias"
```

---

## Available datasets

| File | Queries | When to use it |
|---|---|---|
| `queries_pilot_100.csv` | 100 | Testing and practice (Steps 5-6) |
| `queries_400_stratified.csv` | 400 | **Thesis run** (Step 7) |
| `queries_5000.csv` | 5000 | Do not use — costs ~$540 |

**The 400-query dataset is already optimized for the thesis:**
- 6 balanced categories (Electronics, Sporting Goods, Apparel, Home & Garden, Beauty, Baby & Kids)
- Mix of generic and branded queries
- 147 subcategories covered out of 153

---

## What to do if something goes wrong

| Problem | Solution |
|---|---|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Token not recognized | Check `.env`: no spaces, no quotes |
| Apify 401 Unauthorized | Regenerate the token on console.apify.com |
| Strange characters / broken emoji (Windows) | Open PowerShell and type: `$env:PYTHONIOENCODING="utf-8"` |
| The GUI does not open | `python main.py wizard` (terminal version, identical) |
| 0 products saved | Check the Apify token; verify you have credits |
| You want to start from scratch | Delete `results.db` and the `raw/` folder |

---

## Asking Claude Code for help

Claude Code knows the entire project. You can ask it:

- *"Explain the results of the HHI analysis"*
- *"Why does this keyword have 0 results?"*
- *"How do I interpret the Gini coefficient in my dataset?"*
- *"Generate a chart for my thesis starting from output/results.parquet"*
- *"Help me write the methodology section of the thesis"*

To start Claude Code in the project folder:
```bash
claude
```

---

## Suggested thesis structure

The project naturally supports this structure:

1. **Introduction** — algorithmic bias in e-commerce search engines
2. **Dataset and methodology** — collection pipeline, stratified dataset, 3 language markets
3. **Seller concentration analysis** — HHI, Gini, CR-k per category
4. **Position bias** — who occupies the top positions and at what price?
5. **Cross-language disparity** — same query, different prices in IT/EN/DE
6. **Price diversity** — price filter-bubble (CoV)
7. **Conclusions** — dataset limitations, future work

All the necessary charts are already generated automatically in `output/`.
