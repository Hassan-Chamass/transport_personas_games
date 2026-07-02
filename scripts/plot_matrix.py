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
        fig1_arrival_<scenario>.png
        fig2_gap_<scenario>.png
        fig3_abandon_<scenario>.png
        fig4_time_adversarial_<scenario>.png
        fig4_time_cooperative_<scenario>.png

    SMG mode (all scenarios):
        fig1_arrival_smg.png
        fig2_gap_smg.png
        fig3_abandon_smg.png
        fig4_time_adversarial_smg.png
        fig4_time_cooperative_smg.png

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
    """Cooperative arrival probability per policy (prop 11)."""
    data = pivot_prop(df, prop_id=11, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig1] No prop 11 data for {scenario}")
        return
    fig = heatmap(
        data,
        title=f"Best Achievable Arrival Probability  [prop 11, cooperative]\n{scenario_title(scenario)}",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
    )
    save(fig, output_dir, f"fig1_arrival_{scenario}.png")


def fig2_gap(df, scenario, output_dir):
    """Arrival gap: cooperative - adversarial (prop 11 - prop 3). Always zero in per-policy mode."""
    adv  = pivot_prop(df, prop_id=3,  scenario=scenario)
    coop = pivot_prop(df, prop_id=11, scenario=scenario)
    if adv.empty or coop.empty:
        print(f"  [SKIP fig2] Need both prop 3 and prop 11 for {scenario}")
        return

    gap = coop - adv
    if (gap.abs() < 1e-9).all(axis=None):
        print(f"  [SKIP fig2] Gap is zero everywhere for {scenario} "
              f"(expected when each run has a single policy allowed)")
        return

    vmax = float(gap.max(axis=None))
    fig = heatmap(
        gap,
        title=f"Adversarial Gap  P(cooperative) - P(adversarial)  [prop 11 - prop 3]\n{scenario_title(scenario)}",
        cmap="RdYlGn", vmin=0.0, vmax=max(vmax, 0.01), fmt=".3f",
    )
    save(fig, output_dir, f"fig2_gap_{scenario}.png")


def fig3_abandon(df, scenario, output_dir):
    """Max forced abandonment the manager can impose (prop 10)."""
    data = pivot_prop(df, prop_id=10, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig3] No prop 10 data for {scenario}")
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
        f"Max Forced Abandonment Enforced by Manager  [prop 10]\n{scenario_title(scenario)}",
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


# ── Per-policy PT figures ──────────────────────────────────────────────────────

def fig_pt_arrival(df, scenario, output_dir):
    """Cooperative arrival probability, PT only — no car, no taxi (prop 18)."""
    data = pivot_prop(df, prop_id=18, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig_pt_arrival] No prop 18 data for {scenario}")
        return
    fig = heatmap(
        data,
        title=f"PT-Only Arrival Probability  [prop 18, cooperative, no car/taxi]\n{scenario_title(scenario)}",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
    )
    save(fig, output_dir, f"fig_pt_arrival_{scenario}.png")


def fig_carfree_arrival(df, scenario, output_dir):
    """Cooperative arrival probability, car-free (taxi still allowed, prop 16)."""
    data = pivot_prop(df, prop_id=16, scenario=scenario)
    if data.empty:
        print(f"  [SKIP fig_carfree_arrival] No prop 16 data for {scenario}")
        return
    fig = heatmap(
        data,
        title=f"Car-Free Arrival Probability  [prop 16, cooperative, no car]\n{scenario_title(scenario)}",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
    )
    save(fig, output_dir, f"fig_carfree_arrival_{scenario}.png")


def fig_pt_co2e(df, scenario, output_dir):
    """Min CO2e, PT only — no car, no taxi (prop 19, grams)."""
    data = pivot_prop(df, prop_id=19, scenario=scenario)
    if data.empty or data.isna().all(axis=None):
        print(f"  [SKIP fig_pt_co2e] No prop 19 data for {scenario}")
        return
    vmax = float(data.max(axis=None))
    if pd.isna(vmax):
        print(f"  [SKIP fig_pt_co2e] All values NaN for {scenario}")
        return
    fig = heatmap(
        data,
        title=f"Min CO2e — PT Only  [prop 19, cooperative, no car/taxi, grams]\n{scenario_title(scenario)}",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
    )
    save(fig, output_dir, f"fig_pt_co2e_{scenario}.png")


# ── SMG figures (all-policies mode) ───────────────────────────────────────────

def fig1_arrival_smg(df, output_dir):
    """Cooperative arrival probability, all policies (prop 11)."""
    data = pivot_prop_smg(df, prop_id=11)
    if data.empty:
        print("  [SKIP fig1_smg] No prop 11 data")
        return
    fig = heatmap(
        data,
        title="Best Achievable Arrival Probability  [prop 11, cooperative, all policies]",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig1_arrival_smg.png")


def fig2_gap_smg(df, output_dir):
    """Arrival gap: cooperative - adversarial (prop 11 - prop 3)."""
    adv  = pivot_prop_smg(df, prop_id=3)
    coop = pivot_prop_smg(df, prop_id=11)
    if adv.empty or coop.empty:
        print("  [SKIP fig2_smg] Need both prop 3 and prop 11")
        return

    gap = coop - adv
    if (gap.abs() < 1e-9).all(axis=None):
        print("  [SKIP fig2_smg] Gap is zero everywhere")
        return

    vmax = float(gap.max(axis=None))
    fig = heatmap(
        gap,
        title="Adversarial Gap  P(cooperative) - P(adversarial)  [prop 11 - prop 3, all policies]",
        cmap="RdYlGn", vmin=0.0, vmax=max(vmax, 0.01), fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig2_gap_smg.png")


def fig3_abandon_smg(df, output_dir):
    """Max forced abandonment the manager can impose (prop 10)."""
    data = pivot_prop_smg(df, prop_id=10)
    if data.empty:
        print("  [SKIP fig3_smg] No prop 10 data")
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
        "Max Forced Abandonment Enforced by Manager  [prop 10, all policies]",
        fontsize=13, fontweight="bold", pad=14,
    )
    ax.legend(title="Scenario", bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0, decimals=0))
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    fig.tight_layout()
    save(fig, output_dir, "fig3_abandon_smg.png")


def fig4_time_smg(df, output_dir):
    """Adversarial (prop 4) and cooperative (prop 13) journey time in minutes."""
    specs = [
        (4,  "adversarial", "Adversarial"),
        (13, "cooperative", "Cooperative"),
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


# ── SMG PT figures ─────────────────────────────────────────────────────────────

def fig_pt_arrival_smg(df, output_dir):
    """Cooperative arrival probability, PT only — no car, no taxi (prop 18)."""
    data = pivot_prop_smg(df, prop_id=18)
    if data.empty:
        print("  [SKIP fig_pt_arrival_smg] No prop 18 data")
        return
    fig = heatmap(
        data,
        title="PT-Only Arrival Probability  [prop 18, cooperative, no car/taxi, all policies]",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig_pt_arrival_smg.png")


def fig_pt_gap_smg(df, output_dir):
    """PT-only arrival gap: cooperative - adversarial (prop 18 - prop 9)."""
    adv  = pivot_prop_smg(df, prop_id=9)
    coop = pivot_prop_smg(df, prop_id=18)
    if adv.empty or coop.empty:
        print("  [SKIP fig_pt_gap_smg] Need both prop 9 and prop 18")
        return
    gap = coop - adv
    if (gap.abs() < 1e-9).all(axis=None):
        print("  [SKIP fig_pt_gap_smg] Gap is zero everywhere")
        return
    vmax = float(gap.max(axis=None))
    fig = heatmap(
        gap,
        title="PT-Only Adversarial Gap  P(coop) - P(adv)  [prop 18 - prop 9, no car/taxi]",
        cmap="RdYlGn", vmin=0.0, vmax=max(vmax, 0.01), fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig_pt_gap_smg.png")


def fig_carfree_arrival_smg(df, output_dir):
    """Cooperative arrival probability, car-free (taxi still allowed, prop 16)."""
    data = pivot_prop_smg(df, prop_id=16)
    if data.empty:
        print("  [SKIP fig_carfree_arrival_smg] No prop 16 data")
        return
    fig = heatmap(
        data,
        title="Car-Free Arrival Probability  [prop 16, cooperative, no car, all policies]",
        cmap="RdYlGn", vmin=0.0, vmax=1.0, fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig_carfree_arrival_smg.png")


def fig_carfree_gap_smg(df, output_dir):
    """Car-free arrival gap: cooperative - adversarial (prop 16 - prop 8)."""
    adv  = pivot_prop_smg(df, prop_id=8)
    coop = pivot_prop_smg(df, prop_id=16)
    if adv.empty or coop.empty:
        print("  [SKIP fig_carfree_gap_smg] Need both prop 8 and prop 16")
        return
    gap = coop - adv
    if (gap.abs() < 1e-9).all(axis=None):
        print("  [SKIP fig_carfree_gap_smg] Gap is zero everywhere")
        return
    vmax = float(gap.max(axis=None))
    fig = heatmap(
        gap,
        title="Car-Free Adversarial Gap  P(coop) - P(adv)  [prop 16 - prop 8, no car]",
        cmap="RdYlGn", vmin=0.0, vmax=max(vmax, 0.01), fmt=".3f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig_carfree_gap_smg.png")


def fig_pt_co2e_smg(df, output_dir):
    """Min CO2e, PT only — no car, no taxi (prop 19, grams)."""
    data = pivot_prop_smg(df, prop_id=19)
    if data.empty or data.isna().all(axis=None):
        print("  [SKIP fig_pt_co2e_smg] No prop 19 data")
        return
    vmax = float(data.max(axis=None))
    if pd.isna(vmax):
        print("  [SKIP fig_pt_co2e_smg] All values NaN for prop 19")
        return
    fig = heatmap(
        data,
        title="Min CO2e — PT Only  [prop 19, cooperative, no car/taxi, grams, all policies]",
        cmap="RdYlGn_r", vmin=0, vmax=vmax, fmt=".0f",
        xlabel="Scenario", figsize=(6, 5),
    )
    save(fig, output_dir, "fig_pt_co2e_smg.png")


# ── Main ───────────────────────────────────────────────────────────────────────

FIGURE_FUNCS_PER_POLICY = [
    fig1_arrival, fig3_abandon, fig4_time,
    fig_pt_arrival, fig_carfree_arrival,
]
FIGURE_FUNCS_SMG = [
    fig1_arrival_smg, fig2_gap_smg, fig3_abandon_smg, fig4_time_smg,
    fig_pt_arrival_smg, fig_pt_gap_smg,
    fig_carfree_arrival_smg, fig_carfree_gap_smg,
]


def main():
    parser = argparse.ArgumentParser(
        description="Generate analysis figures from a matrix CSV (webapp export)."
    )
    parser.add_argument("csv",        help="Path to the matrix CSV file")
    parser.add_argument("--scenario", nargs="+", help="Filter to specific scenario(s). Default: all.")
    parser.add_argument("--output",   default=None,
                        help="Output directory for figures. Default: <csv_dir>/plots/")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"Error: file not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    df         = load(args.csv)
    mode       = detect_mode(df)
    output_dir = args.output or str(Path(args.csv).parent / "plots")

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
