"""Experiment 1: tune DFPR's six weights on development seeds only.

Two-stage random search:
  1. ``n_random`` weight vectors drawn uniformly from ``weight_range``^6, plus
     the equal-weights vector (1, ..., 1) as a reference point;
  2. ``n_refine`` perturbations of the ``refine_top`` best candidates
     (each weight multiplied by exp(N(0, refine_sigma))).

Objective (configurable): mean over dev runs (both scenarios, all dev seeds) of
    sum_k coef_k * metric_k     default: late_pct + avg_delivery_min
Lower is better. Held-out test seeds are never touched here.

Note: multiplying all weights by the same positive constant does not change
any ranking, so the search effectively explores 5 dimensions, not 6.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dispatch.dfpr import FACTORS
from experiments.common import EQUAL_WEIGHTS, RunSpec, results_dir, run_many, seeds
from sim.config import deep_merge


def objective_column(df: pd.DataFrame, coefs: dict[str, float]) -> pd.Series:
    return sum(c * df[m] for m, c in coefs.items())


def _specs(cands: dict[int, dict], cfg: dict, base: dict, stage: str) -> list[RunSpec]:
    exp = cfg["experiments"]
    specs = []
    for cid, w in cands.items():
        ov = deep_merge(base, {"dfpr": {"weights": w, "weights_file": None}})
        tags = {"candidate": cid, "stage": stage, **{f"w_{k}": w[k] for k in FACTORS}}
        for sc in exp["scenarios"]:
            for s in seeds(exp["dev_seeds"]):
                specs.append(RunSpec("dfpr", sc, s, ov, tags))
    return specs


def _score(df: pd.DataFrame, coefs: dict) -> pd.DataFrame:
    df = df.assign(objective=objective_column(df, coefs))
    cols = ["candidate", "stage"] + [f"w_{k}" for k in FACTORS]
    return (df.groupby(cols, as_index=False)
              .agg(objective=("objective", "mean"), late_pct=("late_pct", "mean"),
                   avg_delivery_min=("avg_delivery_min", "mean"), runs=("seed", "count"))
              .sort_values(["objective", "candidate"]))


def run(cfg: dict, base_overrides: dict | None = None) -> dict:
    base = base_overrides or {}
    tcfg = cfg["experiments"]["tuning"]
    lo, hi = tcfg["weight_range"]
    rng = np.random.default_rng(tcfg["rng_seed"])
    out = results_dir(cfg)

    cands = {0: dict(EQUAL_WEIGHTS)}
    for i in range(1, tcfg["n_random"] + 1):
        cands[i] = {k: round(float(rng.uniform(lo, hi)), 4) for k in FACTORS}
    print(f"Tuning stage 1: {len(cands)} candidates")
    runs1 = run_many(_specs(cands, cfg, base, "random"), cfg["experiments"]["workers"], "tune-1")
    table = _score(runs1, tcfg["objective"])

    top = table.head(tcfg["refine_top"]).candidate.tolist()
    refine: dict[int, dict] = {}
    next_id = max(cands) + 1
    for j in range(tcfg["n_refine"]):
        parent = cands[top[j % len(top)]]
        refine[next_id] = {k: round(float(np.clip(parent[k] * np.exp(rng.normal(0, tcfg["refine_sigma"])), lo, hi)), 4)
                           for k in FACTORS}
        next_id += 1
    runs = runs1
    if refine:
        print(f"Tuning stage 2: {len(refine)} refinements of candidates {top}")
        runs2 = run_many(_specs(refine, cfg, base, "refine"), cfg["experiments"]["workers"], "tune-2")
        runs = pd.concat([runs1, runs2], ignore_index=True)
        table = _score(runs, tcfg["objective"])

    best = table.iloc[0]
    weights = {k: float(best[f"w_{k}"]) for k in FACTORS}
    equal = table[table.candidate == 0].iloc[0]
    payload = {
        "weights": weights,
        "candidate": int(best.candidate),
        "objective": float(best.objective),
        "objective_definition": tcfg["objective"],
        "equal_weights_objective": float(equal.objective),
        "dev_seeds": cfg["experiments"]["dev_seeds"],
        "scenarios": cfg["experiments"]["scenarios"],
        "candidates_evaluated": int(len(table)),
    }
    runs.to_csv(out / "tuning_runs.csv", index=False)
    table.to_csv(out / "tuning_candidates.csv", index=False)
    (out / "best_weights.json").write_text(json.dumps(payload, indent=2))
    print(f"Best weights {weights} objective {best.objective:.3f} (equal weights: {equal.objective:.3f})")
    return payload
