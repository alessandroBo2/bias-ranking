# -*- coding: utf-8 -*-
import sys, os, sqlite3
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = r'C:\Users\cappu\Downloads\Bolla\for_ksenia'
os.makedirs(OUT, exist_ok=True)

con = sqlite3.connect(r'C:\Users\cappu\Downloads\Bolla\bias-ranking\results.db')
df = pd.read_sql("SELECT language, category_l1, seller FROM products WHERE seller IS NOT NULL AND seller != ''", con)
con.close()

def gini(counts):
    x = np.sort(np.asarray(counts, dtype=float))
    n = len(x)
    if n == 0 or x.sum() == 0: return np.nan
    cum = np.cumsum(x)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)

def hhi(counts):
    s = np.asarray(counts, dtype=float)
    sh = s / s.sum()
    return float((sh ** 2).sum())

rows = []
for lang, g in df.groupby('language'):
    c = g['seller'].value_counts()
    rows.append(dict(language=lang, market='ALL (pooled corpus)', n_listings=len(g),
                     n_sellers=len(c), gini=round(gini(c.values), 3), hhi=round(hhi(c.values), 4)))
    for cat, gc in g.groupby('category_l1'):
        cc = gc['seller'].value_counts()
        rows.append(dict(language=lang, market=f'category: {cat}', n_listings=len(gc),
                         n_sellers=len(cc), gini=round(gini(cc.values), 3), hhi=round(hhi(cc.values), 4)))
met = pd.DataFrame(rows)
met.to_csv(os.path.join(OUT, 'concentration_metrics.csv'), index=False, encoding='utf-8-sig')
print(met.to_string(index=False))

# Lorenz plot per language (pooled) + per-category HHI range annotation
fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), sharey=True)
for ax, lang in zip(axes, ['IT', 'DE', 'EN']):
    c = np.sort(df[df['language'] == lang]['seller'].value_counts().values)
    cumsellers = np.arange(1, len(c) + 1) / len(c)
    cumshare = np.cumsum(c) / c.sum()
    ax.plot(np.insert(cumsellers, 0, 0), np.insert(cumshare, 0, 0), lw=2, color='#4c78a8')
    ax.plot([0, 1], [0, 1], ls='--', color='#999', lw=1)
    sub = met[(met['language'] == lang)]
    all_row = sub[sub['market'].str.startswith('ALL')].iloc[0]
    cats = sub[~sub['market'].str.startswith('ALL')]
    ax.set_title(f"{lang} — Gini {all_row['gini']:.2f}, HHI {all_row['hhi']:.3f}\n"
                 f"per-category HHI: {cats['hhi'].min():.3f}–{cats['hhi'].max():.3f}")
    ax.set_xlabel('cumulative share of sellers')
axes[0].set_ylabel('cumulative share of listings')
fig.suptitle('Lorenz curves of seller visibility — organic Google Shopping listings', y=1.02)
plt.tight_layout()
plt.savefig(os.path.join(OUT, 'lorenz_gini_hhi.png'), dpi=130, bbox_inches='tight')
print('\nsaved: concentration_metrics.csv, lorenz_gini_hhi.png in', OUT)
