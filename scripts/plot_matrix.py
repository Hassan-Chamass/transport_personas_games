"""
plot_matrix.py — Generate analysis figures from a matrix CSV exported by the webapp.

Usage:
    python plot_matrix.py path/to/results.csv
    python plot_matrix.py path/to/results.csv --scenario high_disruption
    python plot_matrix.py path/to/results.csv --output results/plots/

CSV formats supported:
    per-policy  policy column has values (ALLOW_NORMAL, etc.)
                -> one set of figures per scenario, personas x policies heatmaps
    smg         policy column is empty (all policies enabled simultaneously)
                -> one set of figures total, personas x scenarios heatmaps

Figures generated:
    Per-policy mode (per scenario):
        fig1_arrival_<scenario>.png      prop 9  — cooperative arrival probability
        fig2_gap_<scenario>.png          prop 9 - prop 3  — adversarial gap
        fig3_abandon_<scenario>.png      prop 8  — max forced abandonment
        fig4_time_adversarial_<scenario>.png  prop 4  — adversarial journey time

    SMG mode (all scenarios):
        fig1_arrival_smg.png             prop 9  — cooperative arrival probability
        fig2_gap_smg.png                 prop 9 - prop 3  — adversarial gap
        fig3_abandon_smg.png             prop 8  — max forced abandonment
        fig4_time_adversarial_smg.png    prop 4  — adversarial journey time
        fig4_time_cooperative_smg.png    prop 11 — cooperative journey time

    Per-policy mode, generalized-cost & manager-objective figures:
        fig5_gencost_<scenario>.png       prop 48 — best-response generalized cost
        fig5b_gencost_success_<scenario>.png  prop 48 / prop 9 — cost given success
        fig6_mode_choice_<scenario>.png   argmin of props 53-56 — chosen mode matrix
        fig7_revenue_net_<scenario>.png   prop 57 - prop 59 — net revenue ceiling
        fig8_scorecard_<scenario>.png/csv policy scorecard (DfT-segment-weighted)
        fig_time_success_<scenario>.png   prop 11 / prop 9 — E[time | success]
        fig_fare_success_<scenario>.png   prop 12 / prop 9 — fare given success (equity view)

    SMG mode extras:
        fig5_gencost_smg.png              prop 48 heatmap (personas x scenarios)
        fig_time_success_smg.png          prop 11 / prop 9

Dependencies:
    pip install pandas matplotlib seaborn --break-system-packages
"""

import argparse
from ast import Continue
import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from matplotlib.colors import ListedColormap
from pathlib import Path

# ── Display labels ─────────────────────────────────────────────────────────────

POLICY_ORDER = [
    "ALLOW_NORMAL",
    "ALLOW_HIGH_FREQ",
    "ALLOW_LOW_FARE",
    "ALLOW_ROAD_CHARGE",
    "ALLOW_ACCESSIBLE_SERVICE",
]

POLICY_LABELS = {
    "ALLOW_NORMAL":             "Normal",
    "ALLOW_HIGH_FREQ":          "High Freq",
    "ALLOW_LOW_FARE":           "Low Fare",
    "ALLOW_ROAD_CHARGE":        "Road Charge",
    "ALLOW_ACCESSIBLE_SERVICE": "Accessible\nService",
}

SCENARIO_LABELS = {
    "low_disruption":  "Low Disruption",
    "high_disruption": "High Disruption",
}

# Fixed persona order: most vulnerable first, car-dependent last.
# Edit this list to change ordering in all figures.
PERSONA_ORDER = [
    "elderly_no_car",
    "less_mobile",
    "young_low_income",
    "older_less_affluent",
    "young_family",
    "urban_professional",
    "suburban_family",
    "empty_nester",
    "heavy_car_user",
]

PERSONA_LABELS = {
    "elderly_no_car":      "Elderly (no car)",
    "less_mobile":         "Less Mobile",
    "young_low_income":    "Young Low Income",
    "older_less_affluent": "Older Less Affluent",
    "young_family":        "Young Family",
    "urban_professional":  "Urban Professional",
    "suburban_family":     "Suburban Family",
    "empty_nester":        "Empty Nester",
    "heavy_car_user":      "Heavy Car User",
}

# DfT segment sizes (Meet the Personas pack, June 2023) — midpoints of the
# published ranges (11-20% -> 15.5 | 6-10% -> 8 | "5% or less" -> 5).
# Used as population weights for aggregated metrics; normalized at use.
SEGMENT_WEIGHTS = {
    "less_mobile":         15.5,   # Segment 1
    "young_family":        15.5,   # Segment 2
    "older_less_affluent":  8.0,   # Segment 3
    "empty_nester":        15.5,   # Segment 4
    "suburban_family":     15.5,   # Segment 5
    "heavy_car_user":      15.5,   # Segment 6
    "elderly_no_car":       5.0,   # Segment 7
    "urban_professional":   8.0,   # Segment 8
    "young_low_income":     5.0,   # Segment 9
}
WEIGHTS_DISPLAY = {PERSONA_LABELS.get(k, k): v for k, v in SEGMENT_WEIGHTS.items()}

# Mode-conditioned generalized-cost props (argmin = the persona's chosen mode)
MODE_PROPS = [(53, "Car"), (54, "PT"), (55, "Taxi"), (56, "Walk/Bike")]
MODE_COLOR_LIST = ["#d9534f", "#5cb85c", "#f0ad4e", "#5bc0de"]   # Car, PT, Taxi, Walk/Bike

# ── Data loading ───────────────────────────────────────────────────────────────

def load(csv_path):
    df = pd.read_csv(csv_path)
    # Convert boolean strings to numeric before coercion (props 23-52)
    df["result"] = df["result"].replace({"true": "1", "false": "0"})
    df["result"] = pd.to_numeric(df["result"], errors="coerce")
    # Replace Infinity (e.g. prop 19 when no car/taxi path exists)
    df["result"] = df["result"].replace([float("inf"), float("-inf")], float("nan"))
    return df


def detect_mode(df):
    """Return 'smg' if policy column is empty (all-policies run), else 'per_policy'."""
    if "policy" not in df.columns:
        return "smg"
    non_empty = df["policy"].dropna().astype(str).str.strip()
    if non_empty.empty or (non_empty == "").all():
        return "smg"
    return "per_policy"


# ── Pivot helpers ──────────────────────────────────────────────────────────────

def pivot_prop(df, prop_id, scenario):
    """Per-policy mode: personas x policies DataFrame for a given prop and scenario."""
    sub = df[(df["prop_index"] == prop_id) & (df["scenario"] == scenario)]
    if sub.empty:
        return pd.DataFrame()

    p = sub.pivot_table(index="persona", columns="policy", values="result", aggfunc="first")

    ordered_cols = [c for c in POLICY_ORDER if c in p.columns]
    p = p[ordered_cols]
    p.rename(columns=POLICY_LABELS, inplace=True)

    ordered_rows = [r for r in PERSONA_ORDER if r in p.index]
    remaining    = [r for r in p.index if r not in PERSONA_ORDER]
    p = p.loc[ordered_rows + remaining]
    p.rename(index=PERSONA_LABELS, inplace=True)

    return p


def pivot_prop_smg(df, prop_id):
    """SMG mode: personas x scenarios DataFrame for a given prop."""
    sub = df[df["prop_index"] == prop_id]
    if sub.empty:
        return pd.DataFrame()

    p = sub.pivot_table(index="persona", columns="scenario", values="result", aggfunc="first")

    ordered_rows = [r for r in PERSONA_ORDER if r in p.index]
    remaining    = [r for r in p.index if r not in PERSONA_ORDER]
    p = p.loc[ordered_rows + remaining]
    p.rename(index=PERSONA_LABELS, inplace=True)
    p.rename(columns=SCENARIO_LABELS, inplace=True)

    return p


# ── Shared helpers ─────────────────────────────────────────────────────────────

def save(fig, output_dir, filename):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    fig.savefig(path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


def heatmap(data, title, cmap,
            vmin, vmax, fmt=".3f",
            xlabel="Policy",
            figsize=(9, 5)):
    fig, ax = plt.subplots(figsize=figsize)
    sns.heatmap(
        data, ax=ax,
        cmap=cmap, vmin=vmin, vmax=vmax,
        annot=True, fmt=fmt,
        linewidths=0.5, linecolor="#dddddd",
        cbar_kws={"shrink": 0.8},
    )
    ax.set_title(title, fontsize=13, pad=14, fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=11, labelpad=8)
    ax.set_ylabel("Persona", fontsize=11, labelpad=8)
    ax.tick_params(axis="x", rotation=30, labelsize=9)
    ax.tick_params(axis="y", rotation=0,  labelsize=9)
    fig.tight_layout()
    return fig


def scenario_title(scenario):
    return scenario.replace("_", " ").title()


# ── Per-policy figures ─────────────────────────────────────────────────────────

def fig1_arrival(df, scenario, output_dir):
    """Cooperative arrival probability per policy (prop 9)."""
    data = pivot_prop(df, prop_id=9, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig1] No prop 9 data for {scenario}")
        return
    fig = heatmap(
        data,
        title=f"Best Achievable Arrival Probability  [prop 9, cooperative]\n{scenario_title(scenario)}",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
    )
    save(fig, output_dir, f"fig1_arrival_{scenario}.png")


def fig2_gap(df, scenario, output_dir):
    """Arrival gap: cooperative - adversarial (prop 9 - prop 3). Always zero in per-policy mode."""
    adv  = pivot_prop(df, prop_id=3, scenario=scenario)
    coop = pivot_prop(df, prop_id=9, scenario=scenario)
    if adv.empty or coop.empty:
        print(f"  [SKIP fig2] Need both prop 3 and prop 9 for {scenario}")
        return

    gap = coop - adv
    if (gap.abs() < 1e-9).all(axis=None):
        print(f"  [SKIP fig2] Gap is zero everywhere for {scenario} "
              f"(expected when each run has a single policy allowed)")
        return

    vmax = float(gap.max(axis=None))
    fig = heatmap(
        gap,
        title=f"Adversarial Gap  P(cooperative) - P(adversarial)  [prop 9 - prop 3]\n{scenario_title(scenario)}",
        cmap="RdYlGn", vmin=0.0, vmax=max(vmax, 0.01), fmt=".3f",
    )
    save(fig, output_dir, f"fig2_gap_{scenario}.png")


def fig3_abandon(df, scenario, output_dir):
    """Max forced abandonment the manager can impose (prop 8)."""
    data = pivot_prop(df, prop_id=8, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig3] No prop 8 data for {scenario}")
        return

    n_personas = len(data)
    n_policies = len(data.columns)
    bar_width   = 0.14
    x           = list(range(n_personas))
    colors      = sns.color_palette("Set2", n_policies)

    fig, ax = plt.subplots(figsize=(max(10, n_personas * 1.3), 5))

    for i, policy in enumerate(data.columns):
        offsets = [xi + (i - n_policies / 2 + 0.5) * bar_width for xi in x]
        ax.bar(offsets, data[policy], width=bar_width,
               label=policy, color=colors[i], edgecolor="white", linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(data.index, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("P(forced abandonment)", fontsize=11)
    ax.set_ylim(0, 1)
    ax.set_title(
        f"Max Forced Abandonment Enforced by Manager  [prop 8]\n{scenario_title(scenario)}",
        fontsize=13, fontweight="bold", pad=14,
    )
    ax.legend(title="Policy", bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0, decimals=0))
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    fig.tight_layout()
    save(fig, output_dir, f"fig3_abandon_{scenario}.png")


def fig4_time(df, scenario, output_dir):
    """Adversarial expected journey time in minutes (prop 4)."""
    data = pivot_prop(df, prop_id=4, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig4] No prop 4 data for {scenario}")
        return
    vmax = float(data.max(axis=None))
    fig = heatmap(
        data,
        title=f"Expected Journey Time - Adversarial  [prop 4, minutes]\n{scenario_title(scenario)}",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
    )
    save(fig, output_dir, f"fig4_time_adversarial_{scenario}.png")


# ── Generalized-cost & manager-objective figures (per-policy mode) ────────────

def _weighted_mean(series):
    """Mean over personas weighted by DfT segment sizes (NaN-safe)."""
    s = series.dropna()
    if s.empty:
        return float("nan")
    w = pd.Series({k: WEIGHTS_DISPLAY.get(k, 1.0) for k in s.index})
    return float((s * w).sum() / w.sum())


def fig5_gencost(df, scenario, output_dir):
    """Best-response generalized cost per policy (prop 48, equivalent pence)."""
    data = pivot_prop(df, prop_id=48, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig5] No prop 48 data for {scenario}")
        return
    vmax = float(data.max(axis=None))
    fig = heatmap(
        data,
        title=f"Generalized Cost of Best Response  [prop 48, equivalent pence]\n{scenario_title(scenario)}",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
    )
    save(fig, output_dir, f"fig5_gencost_{scenario}.png")


def fig5b_gencost_success(df, scenario, output_dir):
    """Generalized cost conditioned on success: prop 48 / prop 9.
    Removes the free-abandonment bias (abandoned journeys accrue almost no
    cost and drag the raw expectation down). NaN when P(arrival) < 0.05."""
    p48 = pivot_prop(df, prop_id=48, scenario=scenario)
    p9  = pivot_prop(df, prop_id=9,  scenario=scenario)
    if p48.empty or p9.empty:
        print(f"  [SKIP fig5b] Need props 48 and 9 for {scenario}")
        return
    gc = (p48 / p9.reindex(index=p48.index, columns=p48.columns)).where(p9 > 0.05)
    vmax = float(gc.max(axis=None))
    if pd.isna(vmax):
        print(f"  [SKIP fig5b] All values NaN for {scenario}")
        return
    fig = heatmap(
        gc,
        title=f"Generalized Cost Given Success  [prop 48 / prop 9, equivalent pence]\n{scenario_title(scenario)}",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
    )
    save(fig, output_dir, f"fig5b_gencost_success_{scenario}.png")


def fig6_mode_choice(df, scenario, output_dir):
    """Chosen mode per (persona, policy): argmin of mode-conditioned props 53-56."""
    pivots = {}
    for prop_id, label in MODE_PROPS:
        p = pivot_prop(df, prop_id=prop_id, scenario=scenario)
        if not p.empty:
            pivots[label] = p
    if len(pivots) < 2:
        print(f"  [SKIP fig6] Need props 53-56 data for {scenario}")
        return

    # Align all pivots on the same index/columns
    idx  = list(pivots[next(iter(pivots))].index)
    cols = list(pivots[next(iter(pivots))].columns)
    for label in pivots:
        pivots[label] = pivots[label].reindex(index=idx, columns=cols)

    mode_labels = [label for _, label in MODE_PROPS if label in pivots]
    codes  = pd.DataFrame(float("nan"), index=idx, columns=cols)
    annots = pd.DataFrame("",           index=idx, columns=cols)
    for r in idx:
        for c in cols:
            vals = {label: pivots[label].loc[r, c] for label in mode_labels}
            vals = {k: v for k, v in vals.items() if pd.notna(v)}
            if not vals:
                annots.loc[r, c] = "stuck"
                continue
            best = min(vals, key=vals.get)
            codes.loc[r, c]  = mode_labels.index(best)
            annots.loc[r, c] = f"{best}\n{vals[best]:.0f}p"

    fig, ax = plt.subplots(figsize=(9, 5))
    sns.heatmap(
        codes, ax=ax,
        cmap=ListedColormap(MODE_COLOR_LIST[:len(mode_labels)]),
        vmin=-0.5, vmax=len(mode_labels) - 0.5,
        annot=annots, fmt="",
        linewidths=0.5, linecolor="#dddddd",
        cbar=False, annot_kws={"fontsize": 8},
    )
    ax.set_facecolor("#bbbbbb")   # NaN cells (infeasible everywhere) show grey
    ax.set_title(
        f"Chosen Mode of the Rational Persona  [argmin of props 53-56]\n{scenario_title(scenario)}",
        fontsize=13, pad=14, fontweight="bold",
    )
    ax.set_xlabel("Policy", fontsize=11, labelpad=8)
    ax.set_ylabel("Persona", fontsize=11, labelpad=8)
    ax.tick_params(axis="x", rotation=30, labelsize=9)
    ax.tick_params(axis="y", rotation=0,  labelsize=9)
    fig.tight_layout()
    save(fig, output_dir, f"fig6_mode_choice_{scenario}.png")


def fig7_revenue_net(df, scenario, output_dir):
    """Net revenue ceiling per policy: prop 57 (revenue max) - prop 59 (policy spend)."""
    rev  = pivot_prop(df, prop_id=57, scenario=scenario)
    cost = pivot_prop(df, prop_id=59, scenario=scenario)
    if rev.empty:
        print(f"  [SKIP fig7] No prop 57 data for {scenario}")
        return
    net = rev - cost.reindex(index=rev.index, columns=rev.columns).fillna(0) if not cost.empty else rev
    vmin = min(0.0, float(net.min(axis=None)))
    vmax = float(net.max(axis=None))
    fig = heatmap(
        net,
        title=f"Net Revenue Ceiling  [prop 57 - prop 59, pence per traveller]\n{scenario_title(scenario)}",
        cmap="RdYlGn", vmin=vmin, vmax=vmax, fmt=".0f",
    )
    save(fig, output_dir, f"fig7_revenue_net_{scenario}.png")


def fig8_scorecard(df, scenario, output_dir):
    """Policy scorecard: DfT-segment-weighted aggregates per policy (PNG + CSV)."""
    p9  = pivot_prop(df, 9,  scenario)
    p11 = pivot_prop(df, 11, scenario)
    p48 = pivot_prop(df, 48, scenario)
    p57 = pivot_prop(df, 57, scenario)
    p59 = pivot_prop(df, 59, scenario)
    if p48.empty:
        print(f"  [SKIP fig8] No prop 48 data for {scenario}")
        return

    rows = []
    for pol in p48.columns:
        row = {"policy": pol,
               "avg_gen_cost":   _weighted_mean(p48[pol]),
               "worst_gen_cost": float(p48[pol].max())}
        if not p9.empty:
            row["avg_arrival"] = _weighted_mean(p9[pol])
            if not p11.empty:
                ts = (p11[pol] / p9[pol]).where(p9[pol] > 0.05)
                row["avg_time_success"] = _weighted_mean(ts)
        if not p57.empty:
            net = p57[pol]
            if not p59.empty:
                net = net - p59[pol].reindex(p57.index).fillna(0)
            row["net_revenue_ceiling"] = _weighted_mean(net)
        rows.append(row)

    sc = pd.DataFrame(rows).set_index("policy")
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, f"scorecard_{scenario}.csv")
    sc.to_csv(csv_path, float_format="%.2f")
    print(f"  Saved: {csv_path}")

    fig, ax = plt.subplots(figsize=(max(8, 2 + 1.8 * len(sc.columns)), 1.2 + 0.5 * len(sc)))
    ax.axis("off")
    table = ax.table(
        cellText=[[f"{v:.1f}" if pd.notna(v) else "—" for v in r] for r in sc.values],
        rowLabels=list(sc.index), colLabels=list(sc.columns),
        loc="center", cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.4)
    ax.set_title(
        f"Policy Scorecard (DfT-segment-weighted)\n{scenario_title(scenario)}",
        fontsize=13, fontweight="bold", pad=20,
    )
    fig.tight_layout()
    save(fig, output_dir, f"fig8_scorecard_{scenario}.png")


def fig_time_success(df, scenario, output_dir):
    """E[time | success] = prop 11 / prop 9 (NaN when P(arrival) < 0.05)."""
    p9  = pivot_prop(df, 9,  scenario)
    p11 = pivot_prop(df, 11, scenario)
    if p9.empty or p11.empty:
        print(f"  [SKIP fig_time_success] Need props 9 and 11 for {scenario}")
        return
    ts = (p11 / p9).where(p9 > 0.05)
    vmax = float(ts.max(axis=None))
    if pd.isna(vmax):
        print(f"  [SKIP fig_time_success] All values NaN for {scenario}")
        return
    fig = heatmap(
        ts,
        title=f"Expected Journey Time Given Success  [prop 11 / prop 9, minutes]\n{scenario_title(scenario)}",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
    )
    save(fig, output_dir, f"fig_time_success_{scenario}.png")


def fig_fare_success(df, scenario, output_dir):
    """Fare given success: prop 12 / prop 9 (equity view — actual pence paid,
    no gencost weight assumptions). Same success-conditioning as fig5b/fig_time_success
    to dodge the free-abandonment bias (NaN when P(arrival) < 0.05)."""
    p12 = pivot_prop(df, prop_id=12, scenario=scenario)
    p9  = pivot_prop(df, prop_id=9,  scenario=scenario)
    if p12.empty or p9.empty:
        print(f"  [SKIP fig_fare_success] Need props 12 and 9 for {scenario}")
        return
    fare = (p12 / p9.reindex(index=p12.index, columns=p12.columns)).where(p9 > 0.05)
    vmax = float(fare.max(axis=None))
    if pd.isna(vmax):
        print(f"  [SKIP fig_fare_success] All values NaN for {scenario}")
        return
    fig = heatmap(
        fare,
        title=f"Fare Given Success  [prop 12 / prop 9, pence]\n{scenario_title(scenario)}",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
    )
    save(fig, output_dir, f"fig_fare_success_{scenario}.png")


# ── SMG figures (all-policies mode) ───────────────────────────────────────────

def fig1_arrival_smg(df, output_dir):
    """Cooperative arrival probability, all policies (prop 9)."""
    data = pivot_prop_smg(df, prop_id=9)
    if data.empty:
        print("  [SKIP fig1_smg] No prop 9 data")
        return
    fig = heatmap(
        data,
        title="Best Achievable Arrival Probability  [prop 9, cooperative, all policies]",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig1_arrival_smg.png")


def fig2_gap_smg(df, output_dir):
    """Arrival gap: cooperative - adversarial (prop 9 - prop 3)."""
    adv  = pivot_prop_smg(df, prop_id=3)
    coop = pivot_prop_smg(df, prop_id=9)
    if adv.empty or coop.empty:
        print("  [SKIP fig2_smg] Need both prop 3 and prop 9")
        return

    gap = coop - adv
    if (gap.abs() < 1e-9).all(axis=None):
        print("  [SKIP fig2_smg] Gap is zero everywhere")
        return

    vmax = float(gap.max(axis=None))
    fig = heatmap(
        gap,
        title="Adversarial Gap  P(cooperative) - P(adversarial)  [prop 9 - prop 3, all policies]",
        cmap="RdYlGn", vmin=0.0, vmax=max(vmax, 0.01), fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig2_gap_smg.png")


def fig3_abandon_smg(df, output_dir):
    """Max forced abandonment the manager can impose (prop 8)."""
    data = pivot_prop_smg(df, prop_id=8)
    if data.empty:
        print("  [SKIP fig3_smg] No prop 8 data")
        return

    n_personas  = len(data)
    n_scenarios = len(data.columns)
    bar_width   = 0.3
    x           = list(range(n_personas))
    colors      = sns.color_palette("Set2", n_scenarios)

    fig, ax = plt.subplots(figsize=(max(10, n_personas * 1.3), 5))

    for i, scenario in enumerate(data.columns):
        offsets = [xi + (i - n_scenarios / 2 + 0.5) * bar_width for xi in x]
        ax.bar(offsets, data[scenario], width=bar_width,
               label=scenario, color=colors[i], edgecolor="white", linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(data.index, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("P(forced abandonment)", fontsize=11)
    ax.set_ylim(0, 1)
    ax.set_title(
        "Max Forced Abandonment Enforced by Manager  [prop 8, all policies]",
        fontsize=13, fontweight="bold", pad=14,
    )
    ax.legend(title="Scenario", bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0, decimals=0))
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    fig.tight_layout()
    save(fig, output_dir, "fig3_abandon_smg.png")


def fig5_gencost_smg(df, output_dir):
    """Best-response generalized cost (prop 48), personas x scenarios."""
    data = pivot_prop_smg(df, prop_id=48)
    if data.empty:
        print("  [SKIP fig5_smg] No prop 48 data")
        return
    vmax = float(data.max(axis=None))
    fig = heatmap(
        data,
        title="Generalized Cost of Best Response  [prop 48, equivalent pence, all policies]",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig5_gencost_smg.png")


def fig_time_success_smg(df, output_dir):
    """E[time | success] = prop 11 / prop 9, personas x scenarios."""
    p9  = pivot_prop_smg(df, prop_id=9)
    p11 = pivot_prop_smg(df, prop_id=11)
    if p9.empty or p11.empty:
        print("  [SKIP fig_time_success_smg] Need props 9 and 11")
        return
    ts = (p11 / p9).where(p9 > 0.05)
    vmax = float(ts.max(axis=None))
    if pd.isna(vmax):
        print("  [SKIP fig_time_success_smg] All values NaN")
        return
    fig = heatmap(
        ts,
        title="Expected Journey Time Given Success  [prop 11 / prop 9, minutes, all policies]",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig_time_success_smg.png")


def fig4_time_smg(df, output_dir):
    """Adversarial (prop 4) and cooperative (prop 11) journey time in minutes."""
    specs = [
        (4,  "adversarial", "Adversarial"),
        (11, "cooperative", "Cooperative"),
    ]
    for prop_id, tag, label in specs:
        data = pivot_prop_smg(df, prop_id=prop_id)
        if data.empty:
            print(f"  [SKIP fig4_smg {tag}] No prop {prop_id} data")
            continue
        vmax = float(data.max(axis=None))
        if pd.isna(vmax):
            print(f"  [SKIP fig4_smg {tag}] All values are NaN for prop {prop_id}")
            continue
        fig = heatmap(
            data,
            title=f"Expected Journey Time - {label}  [prop {prop_id}, minutes, all policies]",
            cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
            xlabel="Scenario", figsize=(6, 5),
        )
        save(fig, output_dir, f"fig4_time_{tag}_smg.png")


# ── Main ───────────────────────────────────────────────────────────────────────

FIGURE_FUNCS_PER_POLICY = [
    fig1_arrival, fig2_gap, fig3_abandon, fig4_time,
    fig5_gencost, fig5b_gencost_success, fig6_mode_choice, fig7_revenue_net,
    fig8_scorecard, fig_time_success, fig_fare_success,
]
FIGURE_FUNCS_SMG = [
    fig1_arrival_smg, fig2_gap_smg, fig3_abandon_smg, fig4_time_smg,
    fig5_gencost_smg, fig_time_success_smg,
]


def main():
    parser = argparse.ArgumentParser(
        description="Generate analysis figures from a matrix CSV (webapp export)."
    )
    parser.add_argument("csv",        help="Path to the matrix CSV file")
    parser.add_argument("--scenario", nargs="+", help="Filter to specific scenario(s). Default: all.")
    parser.add_argument("--output",   default=None,
                        help="Output directory for figures. Default: <csv_dir>/plots/")
    parser.add_argument("--pt-only",  action="store_true",
                        help="Subfolder figures under pt_only/ to distinguish PT-only runs.")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"Error: file not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    df         = load(args.csv)
    mode       = detect_mode(df)
    output_dir = args.output or str(Path(args.csv).parent / "plots")
    if args.pt_only:
        output_dir = os.path.join(output_dir, "pt_only")

    print(f"CSV      : {args.csv}")
    print(f"Mode     : {mode}")
    print(f"Output   : {output_dir}")

    if mode == "smg":
        if args.scenario:
            df = df[df["scenario"].isin(args.scenario)]
        print("\n-- SMG (all-policies) --")
        for fn in FIGURE_FUNCS_SMG:
            fn(df, output_dir)
    else:
        scenarios = args.scenario or sorted(df["scenario"].dropna().unique().tolist())
        print(f"Scenarios: {scenarios}")
        for scenario in scenarios:
            print(f"\n-- {scenario} --")
            for fn in FIGURE_FUNCS_PER_POLICY:
                fn(df, scenario, output_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
