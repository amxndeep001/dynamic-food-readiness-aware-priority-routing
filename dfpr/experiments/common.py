"""Shared helpers for experiments: run specs, parallel execution, paths."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from eval.invariants import check_invariants
from eval.metrics import compute_metrics
from sim.config import deep_merge, load_config
from sim.simulator import run_simulation

ROOT = Path(__file__).resolve().parent.parent
EQUAL_WEIGHTS = {k: 1.0 for k in "ufwdcr"}

# Display names and a fixed colour per method (colour follows the method, in
# every chart). Hex values are slots of the validated reference palette.
LABELS = {
    "dfpr": "DFPR (tuned)",
    "static_priority": "Static priority (EDF)",
    "nearest": "Nearest order first",
    "nearest_time": "Nearest pair (traffic-aware)",
    "shortest_path": "Shortest-path dispatch",
    "fifo": "FIFO (reference)",
    "dfpr_untuned": "DFPR (equal weights)",
}
COLORS = {
    "dfpr": "#2a78d6",
    "static_priority": "#eb6834",
    "nearest": "#1baf7a",
    "nearest_time": "#008300",
    "shortest_path": "#eda100",
    "fifo": "#e87ba4",
    "dfpr_untuned": "#6250d6",
}


@dataclass(frozen=True)
class RunSpec:
    """One simulation run: method, scenario, seed and config overrides.

    ``method`` may be "dfpr_untuned", which is DFPR with equal weights.
    ``tags`` are copied into the output row (e.g. candidate id, ablated factor).
    """

    method: str
    scenario: str
    seed: int
    overrides: dict = field(default_factory=dict, hash=False)
    tags: dict = field(default_factory=dict, hash=False)


def results_dir(cfg: dict) -> Path:
    path = ROOT / cfg["experiments"]["results_dir"]
    (path / "plots").mkdir(parents=True, exist_ok=True)
    return path


def seeds(span: list[int]) -> list[int]:
    return list(range(span[0], span[1]))


def load_best_weights(cfg: dict) -> dict[str, float]:
    path = results_dir(cfg) / "best_weights.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `python main.py tune` first")
    return json.loads(path.read_text())["weights"]


def run_one(spec: RunSpec) -> dict:
    """Run one simulation, verify its invariants and return its metrics row."""
    cfg = load_config(overrides=spec.overrides)
    method = spec.method
    if method == "dfpr_untuned":
        cfg = deep_merge(cfg, {"dfpr": {"weights": EQUAL_WEIGHTS, "weights_file": None}})
        method = "dfpr"
    result = run_simulation(cfg, method, spec.scenario, spec.seed)
    check_invariants(result)  # an impossible run must never reach a results table
    row = {"method": spec.method, "scenario": spec.scenario, "seed": spec.seed, **spec.tags}
    row.update(compute_metrics(result, cfg["metrics"]["peak_windows"]))
    return row


def run_many(specs: list[RunSpec], workers: int | None = None, label: str = "runs") -> pd.DataFrame:
    """Run specs in parallel processes (results are independent of scheduling)."""
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, row in enumerate(ex.map(run_one, specs, chunksize=1), 1):
            rows.append(row)
            if i % max(1, len(specs) // 10) == 0 or i == len(specs):
                print(f"  [{label}] {i}/{len(specs)} runs  ({time.perf_counter() - t0:.0f}s)", flush=True)
    return pd.DataFrame(rows)
