"""Build results/summary.md from the experiment CSVs.

Tables and the factual "who wins where" statements are generated from the
data. The interpretation section is read from results/interpretation.md, which
is written by hand *after* looking at the results, so regenerating the tables
never overwrites it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from experiments.ablation import FACTOR_NAMES
from experiments.common import LABELS
from experiments.plots import METRIC_LABELS

ALPHA = 0.05


def _fmt(x: float, digits: int = 2) -> str:
    return "n/a" if pd.isna(x) else f"{x:.{digits}f}"


def _p(x: float) -> str:
    return "n/a" if pd.isna(x) else ("<0.001" if x < 0.001 else f"{x:.3f}")


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _verdict(row: pd.Series) -> str:
    if row.p_wilcoxon_holm >= ALPHA:
        return "no significant difference"
    return "**DFPR better**" if row.mean_diff < 0 else "**DFPR worse**"


def build(results: Path, cfg: dict) -> Path:
    exp = cfg["experiments"]
    parts = ["# DFPR experiment results", ""]
    parts.append(
        "All numbers below are produced by `python main.py run-all` and read back from the CSV files in "
        "this folder. For every metric, **lower is better**. *Late* means delivered after the deadline "
        "**or never delivered**. Tests are paired by seed (every method sees the same orders, prep times, "
        f"traffic and rider starts). p-values: exact Wilcoxon signed-rank test, Holm-corrected within each "
        f"(scenario, metric) family; significance threshold {ALPHA}. The paired t-test p-value and the 95% CI "
        "of the mean difference are also reported in `compare_tests.csv`."
    )
    parts.append("")

    # ---------------------------------------------------------------- setup
    parts += ["## 1. Setup", ""]
    rows = [
        ["City", f"{cfg['city']['grid_size']}x{cfg['city']['grid_size']} grid, {cfg['city']['spacing_m']} m blocks, "
                 f"{cfg['city']['num_arterials']} arterials, {cfg['city']['num_restaurants']} restaurants"],
        ["Day", f"{cfg['sim']['start_hour']}:00-{cfg['sim']['end_hour']}:00 + {cfg['sim']['drain_minutes']} min drain"],
        ["Demand", f"{cfg['demand']['base_rate_per_hour']} orders/h; peak scenario x"
                   f"{cfg['demand']['scenarios']['peak']['peaks'][0][2]} at "
                   + ", ".join(f"{a}-{b}h" for a, b, _ in cfg['demand']['scenarios']['peak']['peaks'])],
        ["Riders", f"{cfg['riders']['count']} (capacity {cfg['riders']['capacity']})"],
        ["Prep noise", f"lognormal sigma = {cfg['demand']['prep_noise_sigma']}"],
        ["Dev seeds (tuning)", f"{exp['dev_seeds'][0]}-{exp['dev_seeds'][1] - 1}"],
        ["Held-out seeds (evaluation)", f"{exp['test_seeds'][0]}-{exp['test_seeds'][1] - 1}"],
    ]
    parts += [_md_table(["Parameter", "Value"], rows), ""]

    # --------------------------------------------------------------- tuning
    bw = results / "best_weights.json"
    if bw.exists():
        best = json.loads(bw.read_text())
        cands = pd.read_csv(results / "tuning_candidates.csv")
        parts += ["## 2. Weight tuning (development seeds only)", ""]
        obj = " + ".join(f"{c} x {m}" for m, c in best["objective_definition"].items())
        parts.append(f"Objective (lower is better): mean over dev runs of `{obj}`. "
                     f"{best['candidates_evaluated']} candidates evaluated on both scenarios.")
        parts.append("")
        rows = []
        for _, r in cands.head(5).iterrows():
            rows.append([str(int(r.candidate)), r.stage] + [_fmt(r[f"w_{k}"]) for k in "ufwdcr"]
                        + [_fmt(r.objective, 3), _fmt(r.late_pct), _fmt(r.avg_delivery_min)])
        eq = cands[cands.candidate == 0].iloc[0]
        rows.append(["0 (equal)", eq.stage] + [_fmt(eq[f"w_{k}"]) for k in "ufwdcr"]
                    + [_fmt(eq.objective, 3), _fmt(eq.late_pct), _fmt(eq.avg_delivery_min)])
        parts += [_md_table(["Candidate", "Stage", "w_u", "w_f", "w_w", "w_d", "w_c", "w_r", "Objective",
                             "Late %", "Mean delivery"], rows), ""]
        parts += ["![tuning](plots/tuning.png)", ""]

    # ----------------------------------------------------------- comparison
    if (results / "compare_runs.csv").exists():
        runs = pd.read_csv(results / "compare_runs.csv")
        tests = pd.read_csv(results / "compare_tests.csv")
        methods = [m for m in exp["compare"]["methods"] if m in set(runs.method)]
        parts += ["## 3. Main comparison (held-out seeds)", ""]
        for sc in exp["scenarios"]:
            g = runs[runs.scenario == sc]
            parts += [f"### {sc.capitalize()} scenario: mean ± std over {g.seed.nunique()} seeds", ""]
            cols = ["late_pct", "avg_delivery_min", "p90_delivery_min", "food_wait_min", "rider_wait_min",
                    "total_distance_km", "unserved", "peak_late_pct", "peak_avg_delivery_min"]
            names = ["Late %", "Mean delivery (min)", "p90 (min)", "Food wait (min)", "Rider wait (min)",
                     "Distance (km)", "Unserved", "Peak-window late %", "Peak-window mean (min)"]
            rows = []
            for m in methods:
                d = g[g.method == m]
                rows.append([LABELS[m]] + [f"{d[c].mean():.2f} ± {d[c].std():.2f}" for c in cols])
            parts += [_md_table(["Method"] + names, rows), ""]
            parts += [f"![compare {sc}](plots/compare_{sc}.png)", ""]

            parts += [f"**Paired tests, DFPR (tuned) vs each method, {sc} scenario** "
                      "(difference = DFPR - other; negative = DFPR lower = better)", ""]
            t = tests[tests.scenario == sc]
            rows = []
            for _, r in t.iterrows():
                rows.append([METRIC_LABELS.get(r.metric, r.metric), LABELS[r.other], _fmt(r.mean_diff),
                             f"[{_fmt(r.ci_low)}, {_fmt(r.ci_high)}]", f"{r.wins}/{r.losses}/{r.ties}",
                             _p(r.p_wilcoxon_holm), _verdict(r)])
            parts += [_md_table(["Metric", "vs", "Mean diff", "95% CI", "DFPR W/L/T", "p (Holm)", "Verdict"], rows), ""]

        # Computation
        parts += ["### Computation cost (held-out runs, both scenarios)", ""]
        rows = []
        for m in methods:
            d = runs[runs.method == m]
            rows.append([LABELS[m], _fmt(d.decision_mean_ms.mean(), 3), _fmt(d.decision_max_ms.max(), 2),
                         _fmt(d.update_ms_per_order.mean(), 3), _fmt(d.wall_time_s.mean(), 2)])
        parts += [_md_table(["Method", "Mean decision (ms)", "Max decision (ms)", "Event updates per order (ms)",
                             "Wall time per run (s)"], rows), ""]

    # -------------------------------------------------------------- scaling
    if (results / "scaling.csv").exists():
        sc_df = pd.read_csv(results / "scaling.csv")
        parts += ["## 4. Scaling (microbenchmark)", ""]
        for sweep, col in [("orders", "n_orders"), ("riders", "n_riders")]:
            d = sc_df[sc_df.sweep == sweep]
            piv = d.pivot_table(index=col, columns="method", values="total_ms")
            ms = [m for m in LABELS if m in piv.columns]
            rows = [[str(int(i))] + [_fmt(piv.loc[i, m], 3) for m in ms] for i in piv.index]
            fixed = f"riders fixed at {int(d.n_riders.iloc[0])}" if sweep == "orders" else \
                f"orders fixed at {int(d.n_orders.iloc[0])}"
            parts += [f"ms per assignment (decision + event updates) vs {sweep}, {fixed}:", ""]
            parts += [_md_table([col] + [LABELS[m] for m in ms], rows), ""]
        parts += ["![scaling](plots/scaling.png)", ""]

    # ------------------------------------------------------------- ablation
    if (results / "ablation_tests.csv").exists():
        ab = pd.read_csv(results / "ablation_tests.csv")
        parts += ["## 5. Ablation (tuned DFPR with one weight set to 0, held-out seeds)", ""]
        parts.append("Difference = variant - full DFPR. Positive = worse without the factor (the factor helps).")
        parts.append("")
        for sc in exp["scenarios"]:
            rows = []
            for metric in ["late_pct", "avg_delivery_min", "food_wait_min", "rider_wait_min", "total_distance_km"]:
                d = ab[(ab.scenario == sc) & (ab.metric == metric)]
                rows.append([METRIC_LABELS[metric]] + [
                    f"{_fmt(r.mean_diff)} (p={_p(r.p_wilcoxon_holm)})" for _, r in d.iterrows()])
            variants = ab[(ab.scenario == sc) & (ab.metric == "late_pct")].variant
            parts += [f"**{sc.capitalize()} scenario**", ""]
            parts += [_md_table(["Metric"] + [f"without {FACTOR_NAMES[v[3:]]}" for v in variants], rows), ""]
        parts += ["![ablation](plots/ablation.png)", ""]

    # ---------------------------------------------------------- sensitivity
    if (results / "sensitivity_runs.csv").exists():
        se = pd.read_csv(results / "sensitivity_runs.csv")
        st = pd.read_csv(results / "sensitivity_tests.csv")
        parts += ["## 6. Sensitivity to prep-time noise (peak scenario)", ""]
        for metric in ["late_pct", "avg_delivery_min"]:
            piv = se.pivot_table(index="sigma", columns="method", values=metric, aggfunc="mean")
            ms = [m for m in LABELS if m in piv.columns]
            rows = [[_fmt(s)] + [_fmt(piv.loc[s, m]) for m in ms] for s in piv.index]
            parts += [f"Mean {METRIC_LABELS[metric].lower()}:", ""]
            parts += [_md_table(["sigma"] + [LABELS[m] for m in ms], rows), ""]
        rows = []
        for _, r in st[st.metric == "late_pct"].iterrows():
            rows.append([_fmt(r.sigma), LABELS[r.other], _fmt(r.mean_diff), f"{r.wins}/{r.losses}/{r.ties}",
                         _p(r.p_wilcoxon_holm), _verdict(r)])
        parts += ["Paired tests on late % (DFPR - other):", ""]
        parts += [_md_table(["sigma", "vs", "Mean diff", "DFPR W/L/T", "p (Holm)", "Verdict"], rows), ""]
        parts += ["![sensitivity](plots/sensitivity.png)", ""]

    # ------------------------------------------------------- interpretation
    interp = results / "interpretation.md"
    parts += ["## 7. Interpretation", ""]
    parts.append(interp.read_text(encoding="utf-8") if interp.exists()
                 else "_Not written yet: add results/interpretation.md after reviewing the numbers._")
    path = results / "summary.md"
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path
