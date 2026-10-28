"""Traffic model: time-of-day congestion plus random local incidents.

The effective multiplier on road r at time t is

    m_r(t) = tod(t) * product of factors of incidents active on r at t

where ``tod`` is a piecewise-linear profile (evaluated in fixed steps, e.g.
every 15 min, so it changes in discrete jumps) and each incident slows all
roads whose midpoint lies within a radius of a random centre node. Every term
is >= 1, so m_r(t) >= 1 (traffic only slows travel).

The whole schedule is generated up front from the run's traffic RNG. Every
dispatcher therefore experiences exactly the same traffic, regardless of what
it does. The simulator turns each ``TrafficUpdate`` into a TRAFFIC_CHANGE event.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ds.graph import Graph

HOUR = 3600.0


@dataclass(frozen=True)
class Incident:
    start: float
    end: float
    factor: float
    roads: frozenset[int]


@dataclass(frozen=True)
class TrafficUpdate:
    """New absolute multipliers for the roads that changed at ``time``."""

    time: float
    multipliers: dict[int, float]


def apply_update(graph: Graph, update: TrafficUpdate) -> dict[int, tuple[float, float]]:
    """Write an update into the graph; return ``{road: (old, new)}`` for the cache."""
    changes: dict[int, tuple[float, float]] = {}
    for road, new in update.multipliers.items():
        old = graph.traffic[road]
        if new != old:
            graph.set_traffic(road, new)
            changes[road] = (old, new)
    return changes


class TrafficModel:
    """Pre-computed traffic schedule over ``[start_s, end_s]``."""

    def __init__(self, cfg: dict, graph: Graph, rng: np.random.Generator, start_s: float, end_s: float) -> None:
        self.cfg = cfg
        self.start_s = start_s
        self.end_s = end_s
        profile = cfg["tod_profile"]
        self._prof_h = np.array([p[0] for p in profile], dtype=float)
        self._prof_m = np.array([p[1] for p in profile], dtype=float)
        self.step_s = cfg["step_minutes"] * 60.0
        self.incidents = self._generate_incidents(graph, rng)
        self.schedule = self._build_schedule(graph.num_roads)

    def tod(self, t: float) -> float:
        """Time-of-day multiplier, held constant within each step (>= 1)."""
        step_start = self.start_s + np.floor((t - self.start_s) / self.step_s) * self.step_s
        hour = (step_start / HOUR) % 24
        return max(1.0, float(np.interp(hour, self._prof_h, self._prof_m)))

    def _generate_incidents(self, graph: Graph, rng: np.random.Generator) -> list[Incident]:
        cfg = self.cfg
        rate = cfg["incident_rate_per_hour"] / HOUR
        mids = np.array([graph.midpoint(r) for r in range(graph.num_roads)])
        incidents: list[Incident] = []
        t = self.start_s
        while rate > 0:
            t += rng.exponential(1.0 / rate)
            if t >= self.end_s:
                break
            centre = graph.coords[int(rng.integers(graph.num_nodes))]
            d = np.hypot(mids[:, 0] - centre[0], mids[:, 1] - centre[1])
            roads = frozenset(int(r) for r in np.nonzero(d <= cfg["incident_radius_m"])[0])
            factor = float(rng.uniform(*cfg["incident_factor_range"]))
            duration = float(rng.uniform(*cfg["incident_duration_min_range"])) * 60.0
            incidents.append(Incident(t, min(t + duration, self.end_s), factor, roads))

        # Optional fixed incidents (used by demo presets), drawn after the random
        # ones so they never change the random stream:
        # [start_hour, end_hour, x_frac, y_frac, radius_m, factor], where x/y are
        # fractions of the city's bounding box (0 = left/bottom, 1 = right/top).
        xy = np.array(graph.coords)
        lo, hi = xy.min(axis=0), xy.max(axis=0)
        for start_h, end_h, fx, fy, radius, factor in cfg.get("scripted_incidents", []):
            cx, cy = lo[0] + fx * (hi[0] - lo[0]), lo[1] + fy * (hi[1] - lo[1])
            d = np.hypot(mids[:, 0] - cx, mids[:, 1] - cy)
            roads = frozenset(int(r) for r in np.nonzero(d <= radius)[0])
            start, end = max(start_h * HOUR, self.start_s), min(end_h * HOUR, self.end_s)
            if start < end and roads:
                incidents.append(Incident(start, end, float(factor), roads))
        return incidents

    def _multipliers_at(self, t: float, num_roads: int) -> np.ndarray:
        m = np.full(num_roads, self.tod(t))
        for inc in self.incidents:
            if inc.start <= t < inc.end:
                m[list(inc.roads)] *= inc.factor
        return m

    def _build_schedule(self, num_roads: int) -> list[TrafficUpdate]:
        # Every instant at which some multiplier may change.
        times = set(np.arange(self.start_s, self.end_s, self.step_s).tolist())
        for inc in self.incidents:
            times.update((inc.start, inc.end))
        times = sorted(t for t in times if self.start_s <= t < self.end_s)

        schedule: list[TrafficUpdate] = []
        prev = np.ones(num_roads)
        for t in times:
            cur = self._multipliers_at(t, num_roads)
            changed = np.nonzero(np.abs(cur - prev) > 1e-12)[0]
            if len(changed) or not schedule:
                schedule.append(TrafficUpdate(float(t), {int(r): float(cur[r]) for r in changed}))
            prev = cur
        return schedule
