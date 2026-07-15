# -*- coding: utf-8 -*-
r"""Event study + rollout DiD across the DMA event (5 waves).

Inputs (from build_panel.py --dta ... and build_gsrp_panel.py):
  panel_outcomes.csv  — SU outcomes per query x wave (balanced panel)
  gsrp_panel.csv      — page-level outcomes + rollout cohort per query x wave

Outputs (in --out-dir):
  event_study_means.csv  — per-wave means, balanced queries
  event_study_diffs.csv  — within-query paired differences vs the 2023 baseline
  did_results.csv        — rollout DiD (treated: cohort w5; controls: not-yet-treated, cohort w6)
  event_study.png        — two-panel event-series figure

The DiD replicates the source study's identification: queries first switched
to the new design in CW5-2024 (treated) against queries not yet switched in
CW5 (first switched in CW6), outcome change CW4 -> CW5, so rollout selection
common to both groups is differenced out. SEs from query-level deltas.
"""
import argparse
import os

import numpy as np
import pandas as pd

SU_OUTCOMES = ["su_present", "google_css_share", "google_css_first_slot",
               "rival_css_present", "n_css_partners"]
GSRP_OUTCOMES = ["new_design", "pv_present", "pw_present", "pv_first", "pw_first",
                 "css_top10", "css_top3", "css_organic"]


def paired_diffs(df, outcomes, base_wave):
    waves = [w for w in sorted(df["wave"].unique()) if w != base_wave]
    base = df[df["wave"] == base_wave].set_index("keyword")
    rows = []
    for w in waves:
        cur = df[df["wave"] == w].set_index("keyword")
        for oc in outcomes:
            both = pd.concat([base[oc].rename("pre"), cur[oc].rename("post")],
                             axis=1).dropna().astype(float)
            if not len(both):
                continue
            d = both["post"] - both["pre"]
            se = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else np.nan
            rows.append(dict(wave=w, outcome=oc, n=len(both),
                             base_mean=both["pre"].mean(), wave_mean=both["post"].mean(),
                             diff=d.mean(), se=se,
                             t=(d.mean() / se) if se and se > 0 else np.nan))
    return pd.DataFrame(rows)


def did(gsrp, su, outcome_frames):
    """Treated: cohort 2024w05. Controls: cohort 2024w06 (not yet treated in w5)."""
    coh = gsrp.drop_duplicates("keyword")[["keyword", "cohort"]]
    treated = set(coh.loc[coh["cohort"] == "2024w05", "keyword"])
    control = set(coh.loc[coh["cohort"] == "2024w06", "keyword"])
    rows = []
    for name, (df, outcomes) in outcome_frames.items():
        w4 = df[df["wave"] == "2024w04"].set_index("keyword")
        w5 = df[df["wave"] == "2024w05"].set_index("keyword")
        for oc in outcomes:
            delta = (w5[oc].astype(float) - w4[oc].astype(float)).dropna()
            dt, dc = delta[delta.index.isin(treated)], delta[delta.index.isin(control)]
            if len(dt) < 10 or len(dc) < 10:
                continue
            est = dt.mean() - dc.mean()
            se = np.sqrt(dt.var(ddof=1) / len(dt) + dc.var(ddof=1) / len(dc))
            rows.append(dict(dataset=name, outcome=oc, n_treated=len(dt), n_control=len(dc),
                             delta_treated=dt.mean(), delta_control=dc.mean(),
                             did=est, se=se, t=est / se if se > 0 else np.nan))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--panel-dir", default="panel5")
    a = ap.parse_args()
    su = pd.read_csv(os.path.join(a.panel_dir, "panel_outcomes.csv"))
    gsrp = pd.read_csv(os.path.join(a.panel_dir, "gsrp_panel.csv"))

    # balanced GSRP queries (present in all waves)
    waves = sorted(gsrp["wave"].unique())
    sets = [set(gsrp.loc[gsrp["wave"] == w, "keyword"]) for w in waves]
    g_bal = gsrp[gsrp["keyword"].isin(set.intersection(*sets))]

    means = pd.concat([
        su.groupby("wave")[SU_OUTCOMES].mean().add_prefix("su:"),
        g_bal.groupby("wave")[GSRP_OUTCOMES].mean().add_prefix("gsrp:"),
    ], axis=1).round(4)
    means.to_csv(os.path.join(a.panel_dir, "event_study_means.csv"), encoding="utf-8-sig")
    print("=== per-wave means (balanced queries) ===")
    print(means.to_string())

    diffs = pd.concat([paired_diffs(su, SU_OUTCOMES, "2023w24"),
                       paired_diffs(g_bal, GSRP_OUTCOMES, "2023w24")], ignore_index=True)
    diffs.round(4).to_csv(os.path.join(a.panel_dir, "event_study_diffs.csv"),
                          index=False, encoding="utf-8-sig")

    d = did(gsrp, su, {"gsrp": (g_bal, GSRP_OUTCOMES), "su": (su, SU_OUTCOMES)})
    d.round(4).to_csv(os.path.join(a.panel_dir, "did_results.csv"),
                      index=False, encoding="utf-8-sig")
    print("\n=== rollout DiD (treated w5 vs not-yet-treated w6; change w4->w5) ===")
    print(d.round(4).to_string(index=False))

    # figure
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = sorted(su["wave"].unique())
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    for oc, lab in [("su_present", "classic SU present"),
                    ("google_css_share", "Google-CSS share (SU)"),
                    ("google_css_first_slot", "Google-CSS first slot (SU)")]:
        axes[0].plot(order, su.groupby("wave")[oc].mean().reindex(order), marker="o", label=lab)
    for oc, lab in [("new_design", "new page design"),
                    ("pv_present", "Product Viewer present"),
                    ("pw_present", "Product Websites present")]:
        axes[0].plot(order, g_bal.groupby("wave")[oc].mean().reindex(order),
                     marker="s", ls="--", label=lab)
    axes[0].set_title("Surfaces across the DMA event"); axes[0].legend(fontsize=8)
    axes[0].axvline(1.5, color="#999", lw=1, ls=":")
    for oc, lab in [("css_top10", "rival-CSS links in top-10"),
                    ("css_top3", "rival-CSS links in top-3"),
                    ("css_organic", "rival-CSS organic links")]:
        axes[1].plot(order, g_bal.groupby("wave")[oc].mean().reindex(order), marker="o", label=lab)
    axes[1].set_title("Rival-CSS visibility on the page"); axes[1].legend(fontsize=8)
    axes[1].axvline(1.5, color="#999", lw=1, ls=":")
    for ax in axes:
        ax.set_xticks(range(len(order))); ax.set_xticklabels(order, rotation=20)
    plt.tight_layout()
    plt.savefig(os.path.join(a.panel_dir, "event_study.png"), dpi=130, bbox_inches="tight")
    print(f"\n-> event_study_means.csv, event_study_diffs.csv, did_results.csv, event_study.png")


if __name__ == "__main__":
    main()
