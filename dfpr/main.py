"""Command-line entry point.

Single run:
    py -3.13 main.py --method dfpr --scenario peak --seed 3

Experiments (results in results/):
    py -3.13 main.py run-all            tune -> compare -> scaling -> ablation -> sensitivity -> plots -> report
    py -3.13 main.py tune | compare | scaling | ablation | sensitivity | plots | report
    py -3.13 main.py run-all --quick    tiny version of everything (results_quick/), to check the pipeline
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from dispatch import METHODS
from sim.config import load_config
from sim.simulator import run_simulation

TUNED_WEIGHTS = Path(__file__).resolve().parent / "results" / "best_weights.json"
COMMANDS = ["run", "run-all", "tune", "compare", "scaling", "ablation", "sensitivity", "plots", "report"]

# Shrinks every experiment so the whole pipeline runs in a couple of minutes.
QUICK = {
    "sim": {"start_hour": 11, "end_hour": 14, "drain_minutes": 60},
    "experiments": {
        "results_dir": "results_quick",
        "dev_seeds": [0, 2],
        "test_seeds": [100, 104],
        "tuning": {"n_random": 3, "n_refine": 2, "refine_top": 1},
        "scaling": {"orders": [10, 50], "riders": [5, 20], "assignments": 5, "repeats": 1},
        "sensitivity": {"sigmas": [0.0, 0.3], "n_seeds": 4},
    },
}


def summarize(result) -> str:
    df = result.to_frame()
    done = df[df.status == "DELIVERED"]
    delivery_min = (done.delivered_at - done.placed_at) / 60
    late = (done.delivered_at > done.deadline).sum() + (df.status == "UNSERVED").sum()
    dt = np.array([d.seconds for d in result.decisions]) * 1000
    lines = [
        f"method={result.method} scenario={result.scenario} seed={result.seed}",
        f"orders={len(df)} delivered={len(done)} unserved={(df.status == 'UNSERVED').sum()}",
        f"mean delivery time={delivery_min.mean():.1f} min  p90={np.percentile(delivery_min, 90):.1f} min",
        f"late or unserved={late} ({100 * late / max(len(df), 1):.1f}% of orders)",
        f"total distance={sum(result.rider_distance_m) / 1000:.1f} km",
        f"decisions={len(dt)}  mean={dt.mean():.3f} ms  max={dt.max():.3f} ms",
        f"dispatcher event-update time={1000 * sum(result.update_seconds.values()):.1f} ms total",
        f"route cache={result.cache_stats}",
        f"events={result.event_counts}",
        f"wall time={result.wall_time_s:.2f} s",
    ]
    stats = result.dispatcher_stats
    if "weights" in stats:
        lines.insert(1, "weights=" + ", ".join(f"{k}={v:g}" for k, v in stats["weights"].items()))
    if "recomputations_per_event" in stats:
        lines.append(f"recomputations per triggering event={stats['recomputations_per_event']}")
        lines.append(f"lazy refreshes per decision={stats['lazy_refreshes_per_decision']}")
    return "\n".join(lines)


def run_experiments(command: str, cfg: dict) -> None:
    # Imported lazily so a single simulation run does not load matplotlib.
    from experiments import ablation, compare, plots, report, scaling, sensitivity, tune
    from experiments.common import results_dir

    # Worker processes rebuild the config from these overrides, so passing the
    # full config means a custom --config file reaches every run.
    base = {k: v for k, v in cfg.items() if k != "experiments"}
    steps = {
        "tune": lambda: tune.run(cfg, base),
        "compare": lambda: compare.run(cfg, base),
        "scaling": lambda: scaling.run(cfg, base),
        "ablation": lambda: ablation.run(cfg, base),
        "sensitivity": lambda: sensitivity.run(cfg, base),
        "plots": lambda: print("plots:", *map(str, plots.make_all(results_dir(cfg), cfg["experiments"]["compare"]["methods"])),
                               sep="\n  "),
        "report": lambda: print("report:", report.build(results_dir(cfg), cfg)),
    }
    order = list(steps) if command == "run-all" else [command]
    for step in order:
        t0 = time.perf_counter()
        print(f"=== {step} ===", flush=True)
        steps[step]()
        print(f"=== {step} done in {time.perf_counter() - t0:.0f}s ===", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="DFPR food-delivery dispatch simulator and experiments")
    parser.add_argument("command", nargs="?", default="run", choices=COMMANDS)
    parser.add_argument("--method", default="dfpr", choices=sorted(METHODS))
    parser.add_argument("--scenario", default="normal", choices=["normal", "peak"])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--config", default=None, help="path to a JSON config (default: config/default.json)")
    parser.add_argument("--quick", action="store_true", help="tiny experiment settings, written to results_quick/")
    args = parser.parse_args()

    cfg = load_config(args.config, QUICK if args.quick else None)
    if args.command == "run":
        # A single DFPR run uses the tuned weights once `tune` has produced them.
        tuned = TUNED_WEIGHTS
        if args.method == "dfpr" and not cfg["dfpr"].get("weights_file") and tuned.exists():
            cfg["dfpr"]["weights_file"] = str(tuned)
        print(summarize(run_simulation(cfg, args.method, args.scenario, args.seed)))
    else:
        run_experiments(args.command, cfg)


if __name__ == "__main__":
    main()
