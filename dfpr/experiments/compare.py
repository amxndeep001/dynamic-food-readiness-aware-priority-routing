"""Experiment 2: main comparison on held-out seeds, with paired tests.

Every method runs on the same held-out seeds (default 100-129), never used in
tuning. DFPR uses the weights saved by ``tune.py``. Outputs:
    compare_runs.csv     one row per (method, scenario, seed)
    compare_summary.csv  mean and std per (scenario, method, metric)
    compare_tests.csv    paired DFPR-vs-other tests per (scenario, metric)
"""

from __future__ import annotations

import pandas as pd

from eval.stats import holm, paired_compare
from experiments.common import RunSpec, load_best_weights, results_dir, run_many, seeds
from sim.config import deep_merge

KEY_METRICS = [
    "late_pct", "avg_delivery_min", "p90_delivery_min", "food_wait_min", "rider_wait_min",
    "total_distance_km", "unserved", "peak_late_pct", "peak_avg_delivery_min", "peak_p90_delivery_min",
    "decision_mean_ms", "decision_max_ms", "update_ms_per_order",
]
TEST_METRICS = [
    "late_pct", "avg_delivery_min", "p90_delivery_min", "food_wait_min", "rider_wait_min",
    "total_distance_km", "peak_late_pct", "peak_avg_delivery_min",
]


def summarize(df: pd.DataFrame, group: list[str], metrics: list[str]) -> pd.DataFrame:
    agg = df.groupby(group)[metrics].agg(["mean", "std"])
    agg.columns = [f"{m}_{s}" for m, s in agg.columns]
    return agg.reset_index()


def paired_tests(df: pd.DataFrame, target: str, others: list[str], metrics: list[str],
                 by: str = "scenario", key: str = "method") -> pd.DataFrame:
    """Paired tests of ``target`` vs each of ``others`` (difference = target - other).

    Holm correction is applied within each (scenario, metric) family.
    """
    rows = []
    for group_val, g in df.groupby(by):
        for metric in metrics:
            piv = g.pivot_table(index="seed", columns=key, values=metric)
            family = []
            for other in others:
                if other not in piv or target not in piv:
                    continue
                pair = piv[[target, other]].dropna()
                r = paired_compare(pair[target].to_numpy(), pair[other].to_numpy())
                family.append({by: group_val, "metric": metric, "target": target, "other": other,
                               "n": r.n, "target_mean": pair[target].mean(), "other_mean": pair[other].mean(),
                               "mean_diff": r.mean_diff, "ci_low": r.ci_low, "ci_high": r.ci_high,
                               "p_t": r.p_t, "p_wilcoxon": r.p_wilcoxon,
                               "wins": r.wins, "losses": r.losses, "ties": r.ties})
            for row, adj in zip(family, holm([f["p_wilcoxon"] for f in family])):
                row["p_wilcoxon_holm"] = adj
            rows.extend(family)
    return pd.DataFrame(rows)


def run(cfg: dict, base_overrides: dict | None = None) -> pd.DataFrame:
    base = base_overrides or {}
    exp = cfg["experiments"]
    weights = load_best_weights(cfg)
    dfpr_ov = deep_merge(base, {"dfpr": {"weights": weights, "weights_file": None}})
    specs = [
        RunSpec(m, sc, s, dfpr_ov if m == "dfpr" else base)
        for m in exp["compare"]["methods"] for sc in exp["scenarios"] for s in seeds(exp["test_seeds"])
    ]
    print(f"Main comparison: {len(specs)} runs on held-out seeds {exp['test_seeds']}")
    df = run_many(specs, exp["workers"], "compare")
    out = results_dir(cfg)
    df.to_csv(out / "compare_runs.csv", index=False)
    summarize(df, ["scenario", "method"], KEY_METRICS).to_csv(out / "compare_summary.csv", index=False)
    others = [m for m in exp["compare"]["methods"] if m != "dfpr"]
    paired_tests(df, "dfpr", others, TEST_METRICS).to_csv(out / "compare_tests.csv", index=False)
    return df
