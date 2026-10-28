"""Per-run metrics computed from a ``SimResult``.

Definitions (times in minutes; "lower is better" for every metric):
    avg_delivery_min   mean (delivered_at - placed_at) over delivered orders
    p90_delivery_min   90th percentile of the same
    late_pct           % of all orders that were delivered after their deadline
                       OR never delivered (an unserved order is a late order)
    late_count         the number of such orders
    unserved           orders not delivered by end + drain time
    total_distance_km  distance travelled by all riders
    food_wait_min      mean (picked_at - true ready time): food waiting for the rider
    rider_wait_min     mean max(0, true ready time - rider arrival): rider waiting for food
    decision_mean_ms / decision_max_ms   wall time per dispatcher.choose() call
    update_ms_per_order  dispatcher on_event() time / number of orders (DFPR's
                         dynamic updates happen here, so this is part of its cost)
    peak_*             the same delivery metrics restricted to orders *placed*
                       inside the peak windows (config ``metrics.peak_windows``)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sim.simulator import SimResult

HOUR = 3600.0
LOWER_IS_BETTER = True  # true for every metric below


def _delivery_metrics(df: pd.DataFrame, prefix: str = "") -> dict[str, float]:
    n = len(df)
    done = df[df.status == "DELIVERED"]
    minutes = (done.delivered_at - done.placed_at) / 60.0
    late = int((done.delivered_at > done.deadline).sum() + (df.status == "UNSERVED").sum())
    return {
        f"{prefix}orders": n,
        f"{prefix}avg_delivery_min": float(minutes.mean()) if len(done) else float("nan"),
        f"{prefix}p90_delivery_min": float(np.percentile(minutes, 90)) if len(done) else float("nan"),
        f"{prefix}late_count": late,
        f"{prefix}late_pct": 100.0 * late / n if n else float("nan"),
    }


def compute_metrics(result: SimResult, peak_windows: list[list[float]]) -> dict[str, float]:
    """All metrics for one run, as a flat dict (one row of a results table)."""
    df = result.to_frame()
    out: dict[str, float] = _delivery_metrics(df)
    out["unserved"] = int((df.status == "UNSERVED").sum())
    out["total_distance_km"] = sum(result.rider_distance_m) / 1000.0

    picked = df[df.picked_at.notna()]
    out["food_wait_min"] = float(((picked.picked_at - picked.true_ready_at) / 60.0).mean())
    arrived = df[df.rider_arrived_at.notna()]
    out["rider_wait_min"] = float(((arrived.true_ready_at - arrived.rider_arrived_at).clip(lower=0) / 60.0).mean())

    dec = np.array([d.seconds for d in result.decisions]) * 1000.0
    out["decisions"] = len(dec)
    out["decision_mean_ms"] = float(dec.mean()) if len(dec) else 0.0
    out["decision_max_ms"] = float(dec.max()) if len(dec) else 0.0
    out["update_ms_per_order"] = 1000.0 * sum(result.update_seconds.values()) / max(len(df), 1)

    hours = df.placed_at / HOUR
    in_peak = np.zeros(len(df), dtype=bool)
    for start, end in peak_windows:
        in_peak |= (hours >= start) & (hours < end)
    out.update(_delivery_metrics(df[in_peak], prefix="peak_"))

    stats = result.dispatcher_stats
    if "recomputations" in stats:
        out["recomputations_total"] = sum(stats["recomputations"].values()) + sum(stats["rescores"].values())
        out["lazy_refreshes"] = stats["lazy_refreshes"]
    out["cache_hits"] = result.cache_stats["hits"]
    out["cache_misses"] = result.cache_stats["misses"]
    out["wall_time_s"] = result.wall_time_s
    return out
