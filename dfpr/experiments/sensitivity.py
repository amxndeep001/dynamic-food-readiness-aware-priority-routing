"""Experiment 5: sensitivity to prep-time noise.

actual_prep = est_prep * exp(sigma * Z - sigma^2 / 2). Z comes from its own
RNG stream, so for a given seed every sigma sees the same orders and the same
Z values; only the size of the estimation error changes (a paired design).
DFPR keeps the weights tuned at the default sigma; it is not re-tuned per sigma.
"""

from __future__ import annotations

import pandas as pd

from experiments.common import RunSpec, load_best_weights, results_dir, run_many, seeds
from experiments.compare import paired_tests, summarize
from sim.config import deep_merge

METRICS = ["late_pct", "avg_delivery_min", "food_wait_min", "rider_wait_min", "total_distance_km"]


def run(cfg: dict, base_overrides: dict | None = None) -> pd.DataFrame:
    base = base_overrides or {}
    exp = cfg["experiments"]
    scfg = exp["sensitivity"]
    weights = load_best_weights(cfg)
    test_seeds = seeds(exp["test_seeds"])[: scfg["n_seeds"]]
    specs = []
    for sigma in scfg["sigmas"]:
        ov = deep_merge(base, {"demand": {"prep_noise_sigma": sigma}})
        dfpr_ov = deep_merge(ov, {"dfpr": {"weights": weights, "weights_file": None}})
        for m in scfg["methods"]:
            for s in test_seeds:
                specs.append(RunSpec(m, scfg["scenario"], s, dfpr_ov if m == "dfpr" else ov, {"sigma": sigma}))
    print(f"Sensitivity: {len(specs)} runs")
    df = run_many(specs, exp["workers"], "sensitivity")
    out = results_dir(cfg)
    df.to_csv(out / "sensitivity_runs.csv", index=False)
    summarize(df, ["sigma", "method"], METRICS).to_csv(out / "sensitivity_summary.csv", index=False)
    others = [m for m in scfg["methods"] if m != "dfpr"]
    paired_tests(df, "dfpr", others, ["late_pct", "avg_delivery_min"], by="sigma").to_csv(
        out / "sensitivity_tests.csv", index=False)
    return df
