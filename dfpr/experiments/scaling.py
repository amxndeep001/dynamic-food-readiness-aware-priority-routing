"""Experiment 3: computational cost vs number of active orders and riders.

A full simulation cannot hold, say, 800 orders waiting at once in a stable way,
so this is a controlled microbenchmark on the real city graph:

  1. put N eligible orders and R idle riders into a state view;
  2. repeat ``assignments`` times: advance the clock 30 s, call choose()
     (timed as *decision* cost), perform the assignment, then place one new
     order and return the rider as idle at a random node, delivering the
     ORDER_PLACED and RIDER_IDLE events to the dispatcher (timed as *update*
     cost). N and R therefore stay constant.

Shortest-path trees for all restaurants are computed before timing starts, so
the numbers measure the dispatch rule itself, not one-off Dijkstra runs. (The
cost of Dijkstra re-runs after traffic changes is measured in the full
simulations instead: ``update_ms_per_order`` in compare_runs.csv.)

Runs in a single process, sequentially, so timings are not disturbed by
parallel work.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from dispatch import make_dispatcher
from experiments.common import results_dir
from sim.city import build_city
from sim.config import deep_merge
from sim.events import Event, EventType
from sim.orders import Order
from sim.routing import Router
from sim.simulator import Rider, SimView

T0 = 12 * 3600.0


def _bench(cfg: dict, city, method: str, n_orders: int, n_riders: int, assignments: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    g = city.graph
    router = Router(g)
    for r in city.restaurants:  # warm cache
        for mode in ("time", "free_time", "length"):
            router.cache.tree(r.node, mode)
    riders = {i: Rider(i, int(rng.integers(g.num_nodes))) for i in range(n_riders)}
    view = SimView(city, g, router, {}, riders, {}, {i: T0 for i in riders}, T0, T0 + 4 * 3600)
    disp = make_dispatcher(method, cfg)
    disp.reset(view)

    next_id = 0
    now = T0

    def place(t: float) -> float:
        nonlocal next_id
        rest = city.restaurants[int(rng.integers(len(city.restaurants)))]
        oid = next_id
        next_id += 1
        placed = t - float(rng.uniform(0, 900))  # orders of mixed age
        view.orders[oid] = Order(oid, rest.node, int(rng.integers(g.num_nodes)), placed, rest.mean_prep_s,
                                 placed + float(rng.uniform(35, 45)) * 60)
        view.eligible[oid] = None
        t0 = time.perf_counter()
        disp.on_event(Event(t, EventType.ORDER_PLACED, order_id=oid), view)
        return time.perf_counter() - t0

    for _ in range(n_orders):
        place(now)

    dec, upd = [], []
    for _ in range(assignments):
        now += 30.0
        t0 = time.perf_counter()
        rider, oid = disp.choose(now, view)
        dec.append(time.perf_counter() - t0)
        del view.idle[rider], view.eligible[oid]
        u = place(now)
        riders[rider].node = int(rng.integers(g.num_nodes))
        view.idle[rider] = now
        t0 = time.perf_counter()
        disp.on_event(Event(now, EventType.RIDER_IDLE, rider_id=rider), view)
        upd.append(u + time.perf_counter() - t0)
    return {"decision_ms": 1000 * float(np.mean(dec)), "update_ms": 1000 * float(np.mean(upd))}


def run(cfg: dict, base_overrides: dict | None = None) -> pd.DataFrame:
    scfg = cfg["experiments"]["scaling"]
    run_cfg = cfg
    # DFPR's cost does not depend on weight values, but use the tuned ones if present.
    weights_file = results_dir(cfg) / "best_weights.json"
    if weights_file.exists():
        run_cfg = deep_merge(run_cfg, {"dfpr": {"weights_file": str(weights_file)}})
    city = build_city(run_cfg["city"])
    grid = [("orders", n, scfg["fixed_riders"]) for n in scfg["orders"]]
    grid += [("riders", scfg["fixed_orders"], r) for r in scfg["riders"]]
    rows = []
    for sweep, n, r in grid:
        for method in scfg["methods"]:
            reps = [_bench(run_cfg, city, method, n, r, scfg["assignments"], seed) for seed in range(scfg["repeats"])]
            row = {"sweep": sweep, "method": method, "n_orders": n, "n_riders": r,
                   "decision_ms": float(np.median([x["decision_ms"] for x in reps])),
                   "update_ms": float(np.median([x["update_ms"] for x in reps]))}
            row["total_ms"] = row["decision_ms"] + row["update_ms"]
            rows.append(row)
        print(f"  [scaling] {sweep}: N={n} R={r} done", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(results_dir(cfg) / "scaling.csv", index=False)
    return df
