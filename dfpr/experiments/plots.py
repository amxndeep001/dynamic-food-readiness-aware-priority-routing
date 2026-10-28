"""Plots from the experiment CSVs (results/plots/*.png).

Style: each method keeps one fixed colour in every chart, the grid and axes
are kept light, every chart has a legend or names its single series, and
error bars are always labelled with what they show.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from experiments.ablation import FACTOR_NAMES  # noqa: E402
from experiments.common import COLORS, LABELS  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"

METRIC_LABELS = {
    "late_pct": "Late or unserved orders (%)",
    "avg_delivery_min": "Mean delivery time (min)",
    "p90_delivery_min": "p90 delivery time (min)",
    "food_wait_min": "Food waiting for rider (min)",
    "rider_wait_min": "Rider waiting for food (min)",
    "total_distance_km": "Total rider distance (km)",
}


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "xtick.color": INK_2, "ytick.color": INK_2, "text.color": INK,
        "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "font.size": 9, "axes.titlesize": 10, "legend.frameon": False,
    })


def compare_bars(runs: pd.DataFrame, methods: list[str], out: Path) -> list[Path]:
    """One figure per scenario: small multiples of the main metrics, mean +- std over seeds."""
    _style()
    paths = []
    for scenario, g in runs.groupby("scenario"):
        fig, axes = plt.subplots(2, 3, figsize=(12, 6.2))
        present = [m for m in methods if m in set(g.method)]
        for ax, (metric, label) in zip(axes.flat, METRIC_LABELS.items()):
            stats = g.groupby("method")[metric].agg(["mean", "std"]).reindex(present)
            x = np.arange(len(present))
            ax.bar(x, stats["mean"], width=0.72, color=[COLORS[m] for m in present],
                   edgecolor=SURFACE, linewidth=2, yerr=stats["std"], capsize=3,
                   error_kw={"elinewidth": 1, "ecolor": INK_2})
            ax.set_title(label)
            ax.set_xticks([])
            ax.grid(axis="x", visible=False)
        handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[m]) for m in present]
        fig.legend(handles, [LABELS[m] for m in present], loc="lower center", ncol=len(present))
        n = g.seed.nunique()
        fig.suptitle(f"{scenario.capitalize()} scenario: mean over {n} held-out seeds (error bars: ±1 std across seeds)",
                     color=INK)
        fig.tight_layout(rect=(0, 0.06, 1, 0.95))
        path = out / f"compare_{scenario}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(path)
    return paths


def scaling_lines(df: pd.DataFrame, out: Path) -> Path:
    _style()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, sweep, xcol, xlabel in [
        (axes[0], "orders", "n_orders", "Eligible orders N (riders fixed)"),
        (axes[1], "riders", "n_riders", "Idle riders R (orders fixed)"),
    ]:
        d = df[df.sweep == sweep]
        for m in [m for m in COLORS if m in set(d.method)]:
            s = d[d.method == m].sort_values(xcol)
            ax.plot(s[xcol], s["total_ms"], marker="o", markersize=5, linewidth=2, color=COLORS[m], label=LABELS[m])
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("ms per assignment (decision + event updates)")
        fixed = f"R = {int(d.n_riders.iloc[0])}" if sweep == "orders" else f"N = {int(d.n_orders.iloc[0])}"
        ax.set_title(f"Cost vs {sweep} ({fixed})")
    axes[0].legend()
    fig.suptitle("Computational cost per assignment (median of repeats, warm route cache)", color=INK)
    fig.tight_layout()
    path = out / "scaling.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def ablation_bars(tests: pd.DataFrame, out: Path) -> Path:
    """Paired difference (variant - full DFPR) with 95% CI, per scenario."""
    _style()
    metrics = ["late_pct", "avg_delivery_min"]
    scenarios = sorted(tests.scenario.unique())
    fig, axes = plt.subplots(len(scenarios), len(metrics), figsize=(11, 3.4 * len(scenarios)), squeeze=False)
    for i, sc in enumerate(scenarios):
        for j, metric in enumerate(metrics):
            ax = axes[i][j]
            d = tests[(tests.scenario == sc) & (tests.metric == metric)]
            y = np.arange(len(d))
            ax.barh(y, d.mean_diff, height=0.6, color=COLORS["dfpr"], edgecolor=SURFACE, linewidth=2)
            ax.errorbar(d.mean_diff, y, xerr=[d.mean_diff - d.ci_low, d.ci_high - d.mean_diff],
                        fmt="none", ecolor=INK_2, elinewidth=1, capsize=3)
            ax.axvline(0, color=INK_2, linewidth=1)
            ax.set_yticks(y, [f"without {FACTOR_NAMES[v[3:]]}" for v in d.variant])
            ax.invert_yaxis()
            ax.grid(axis="y", visible=False)
            ax.set_xlabel(f"Change in {METRIC_LABELS[metric].lower()} vs full DFPR")
            ax.set_title(f"{sc.capitalize()}: {METRIC_LABELS[metric]}")
    fig.suptitle("Ablation: removing one factor (weight = 0). Right of 0 = worse without it. Bars: 95% CI of paired difference",
                 color=INK)
    fig.tight_layout()
    path = out / "ablation.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def sensitivity_lines(runs: pd.DataFrame, out: Path) -> Path:
    _style()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, metric in zip(axes, ["late_pct", "avg_delivery_min"]):
        for m in [m for m in COLORS if m in set(runs.method)]:
            s = runs[runs.method == m].groupby("sigma")[metric].agg(["mean", "std", "count"])
            se = s["std"] / np.sqrt(s["count"])
            ax.plot(s.index, s["mean"], marker="o", markersize=5, linewidth=2, color=COLORS[m], label=LABELS[m])
            ax.fill_between(s.index, s["mean"] - se, s["mean"] + se, color=COLORS[m], alpha=0.12, linewidth=0)
        ax.set_xlabel("Prep-time noise σ (lognormal)")
        ax.set_title(METRIC_LABELS[metric])
    axes[0].legend()
    n = runs.seed.nunique()
    fig.suptitle(f"Sensitivity to prep-time noise, peak scenario, {n} held-out seeds (bands: ±1 standard error)",
                 color=INK)
    fig.tight_layout()
    path = out / "sensitivity.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def tuning_scatter(cands: pd.DataFrame, out: Path) -> Path:
    _style()
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    for stage, color in [("random", COLORS["nearest"]), ("refine", COLORS["static_priority"])]:
        d = cands[cands.stage == stage]
        ax.scatter(d.avg_delivery_min, d.late_pct, s=36, color=color, edgecolor=SURFACE, linewidth=1.5,
                   label=f"{stage} candidates")
    best = cands.iloc[0]
    eq = cands[cands.candidate == 0].iloc[0]
    ax.scatter([eq.avg_delivery_min], [eq.late_pct], s=90, color=COLORS["dfpr_untuned"], edgecolor=SURFACE,
               linewidth=1.5, label="equal weights", zorder=3)
    ax.scatter([best.avg_delivery_min], [best.late_pct], s=260, marker="*", color=COLORS["dfpr"],
               edgecolor=SURFACE, linewidth=1, label="selected (lowest objective)", zorder=4)
    ax.set_xlabel("Mean delivery time (min), dev seeds")
    ax.set_ylabel("Late or unserved (%), dev seeds")
    ax.set_title("Weight tuning on development seeds (both scenarios pooled)")
    ax.legend()
    fig.tight_layout()
    path = out / "tuning.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def make_all(results: Path, methods: list[str]) -> list[Path]:
    plots = results / "plots"
    plots.mkdir(exist_ok=True)
    made = []
    if (results / "compare_runs.csv").exists():
        made += compare_bars(pd.read_csv(results / "compare_runs.csv"), methods, plots)
    if (results / "scaling.csv").exists():
        made.append(scaling_lines(pd.read_csv(results / "scaling.csv"), plots))
    if (results / "ablation_tests.csv").exists():
        made.append(ablation_bars(pd.read_csv(results / "ablation_tests.csv"), plots))
    if (results / "sensitivity_runs.csv").exists():
        made.append(sensitivity_lines(pd.read_csv(results / "sensitivity_runs.csv"), plots))
    if (results / "tuning_candidates.csv").exists():
        made.append(tuning_scatter(pd.read_csv(results / "tuning_candidates.csv"), plots))
    return made
