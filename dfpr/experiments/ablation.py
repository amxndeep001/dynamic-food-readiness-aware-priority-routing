"""Experiment 4: ablation. Tuned DFPR with one weight set to 0 at a time.

Runs on the held-out seeds. For each variant we report the paired difference
(variant - full DFPR): a positive difference in late % or delivery time means
removing that factor *hurt*, i.e. the factor was helping.
"""

from __future__ import annotations

import pandas as pd

from dispatch.dfpr import FACTORS
from eval.stats import holm, paired_compare
from experiments.common import RunSpec, load_best_weights, results_dir, run_many, seeds
from sim.config import deep_merge

METRICS = ["late_pct", "avg_delivery_min", "p90_delivery_min", "food_wait_min", "rider_wait_min", "total_distance_km"]
FACTOR_NAMES = {"u": "urgency U", "f": "readiness F", "w": "waiting W", "d": "distance D", "c": "traffic C",
                "r": "rider wait R"}


def run(cfg: dict, base_overrides: dict | None = None) -> pd.DataFrame:
    base = base_overrides or {}
    exp = cfg["experiments"]
    weights = load_best_weights(cfg)
    variants = {"full": weights}
    for k in FACTORS:
        variants[f"no_{k}"] = {**weights, k: 0.0}
    specs = []
    for name, w in variants.items():
        ov = deep_merge(base, {"dfpr": {"weights": w, "weights_file": None}})
        for sc in exp["scenarios"]:
            for s in seeds(exp["test_seeds"]):
                specs.append(RunSpec("dfpr", sc, s, ov, {"variant": name}))
    print(f"Ablation: {len(specs)} runs")
    df = run_many(specs, exp["workers"], "ablation")
    out = results_dir(cfg)
    df.to_csv(out / "ablation_runs.csv", index=False)
    ablation_tests(df, [v for v in variants if v != "full"]).to_csv(out / "ablation_tests.csv", index=False)
    return df


def ablation_tests(df: pd.DataFrame, variants: list[str]) -> pd.DataFrame:
    """Paired tests of each variant against full DFPR; mean_diff = variant - full.

    Holm correction within each (scenario, metric) family of 6 variants.
    """
    rows = []
    for sc, g in df.groupby("scenario"):
        for metric in METRICS:
            piv = g.pivot_table(index="seed", columns="variant", values=metric)
            family = []
            for v in variants:
                r = paired_compare(piv[v].to_numpy(), piv["full"].to_numpy())
                family.append({"scenario": sc, "metric": metric, "variant": v, "n": r.n,
                               "variant_mean": piv[v].mean(), "full_mean": piv["full"].mean(),
                               "mean_diff": r.mean_diff, "ci_low": r.ci_low, "ci_high": r.ci_high,
                               "p_t": r.p_t, "p_wilcoxon": r.p_wilcoxon,
                               "variant_better": r.wins, "variant_worse": r.losses, "ties": r.ties})
            for row, adj in zip(family, holm([f["p_wilcoxon"] for f in family])):
                row["p_wilcoxon_holm"] = adj
            rows.extend(family)
    return pd.DataFrame(rows)
