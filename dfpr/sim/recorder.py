"""Optional trace recorder used by the demo app to replay a simulation.

The recorder is passed to ``Simulator(recorder=...)``; experiments never pass
one, so they run exactly as before. It only *observes*: dispatchers' read-only
``rank()`` explains each decision, and an observer on the indexed heap logs its
operations.

Rather than copying the whole state at every time step (huge), the recorder is
*event-sourced*: it logs what changed and when (rider movement legs, status
changes, traffic updates, order timestamps). ``Trace.snapshot(t)`` rebuilds the
exact state at any time t from those logs, which is what the UI plays back.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import time
from dataclasses import dataclass, field

import numpy as np

from ds.indexed_heap import IndexedMaxHeap
from ds.shortest_path import astar, dijkstra, reconstruct_path
from eval.metrics import compute_metrics
from sim.events import Event, EventType

STATUS_NAMES = {
    "IDLE": "idle",
    "TO_RESTAURANT": "to_restaurant",
    "WAITING": "waiting_at_restaurant",
    "TO_CUSTOMER": "to_customer",
}
HEAP_OPS = ("push", "pop_max", "update_key", "remove")
MAX_CANDIDATES = 50  # per decision; enough for the UI, keeps traces small


def _clock(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600 % 24:02d}:{t // 60 % 60:02d}"


@dataclass
class Trace:
    """Everything the demo app needs to replay one run. Picklable (for caching)."""

    meta: dict
    coords: list[tuple[float, float]]
    road_ends: list[tuple[int, int]]
    road_free_time: list[float]
    restaurants: list[dict]  # id, node, mean_prep_s
    rider_starts: list[int]
    initial_traffic: list[float]
    traffic_updates: list[tuple[float, dict[int, float]]]
    orders: list[dict]
    legs: list[dict]
    status_log: list[tuple[float, int, str, int | None]]
    events: list[dict]
    decisions: list[dict]
    heap_ops: list[dict]
    sample_route: dict
    metrics: dict
    dispatcher_stats: dict
    cache_stats: dict
    event_counts: dict
    _traffic_cache: list = field(default_factory=list, repr=False)

    # ------------------------------------------------------------- time axis
    @property
    def start(self) -> float:
        return self.meta["start_s"]

    @property
    def end(self) -> float:
        """Last moment anything happened (delivery or end of the order window)."""
        return self.meta["last_event_s"]

    def decision_times(self) -> list[float]:
        return [d["time"] for d in self.decisions]

    def decision_index_at(self, t: float) -> int | None:
        """Index of the latest decision at or before t (None if none yet)."""
        i = bisect.bisect_right(self.decision_times(), t) - 1
        return i if i >= 0 else None

    # --------------------------------------------------------------- traffic
    def traffic_at(self, t: float) -> np.ndarray:
        """Per-road multipliers in force at time t."""
        if not self._traffic_cache:
            cur = np.array(self.initial_traffic, dtype=float)
            self._traffic_cache.append((-math.inf, cur.copy()))
            for when, changes in self.traffic_updates:
                for road, m in changes.items():
                    cur[road] = m
                self._traffic_cache.append((when, cur.copy()))
        times = [c[0] for c in self._traffic_cache]
        return self._traffic_cache[bisect.bisect_right(times, t) - 1][1]

    # ---------------------------------------------------------------- riders
    def rider_position(self, rider: int, t: float) -> tuple[float, float, list[tuple[float, float]]]:
        """(x, y, remaining route points) of a rider at time t."""
        legs = [leg for leg in self.legs if leg["rider"] == rider and leg["start"] <= t]
        if not legs:
            x, y = self.coords[self.rider_starts[rider]]
            return x, y, []
        leg = legs[-1]
        if t >= leg["end"]:
            return leg["xs"][-1], leg["ys"][-1], []
        x = float(np.interp(t, leg["times"], leg["xs"]))
        y = float(np.interp(t, leg["times"], leg["ys"]))
        k = bisect.bisect_right(leg["times"], t)
        return x, y, [(x, y)] + list(zip(leg["xs"][k:], leg["ys"][k:]))

    def rider_status(self, rider: int, t: float) -> tuple[str, int | None]:
        last = ("idle", None)
        for when, rid, status, order in self.status_log:
            if when > t:
                break
            if rid == rider:
                last = (status, order)
        return last

    # ---------------------------------------------------------------- orders
    @staticmethod
    def order_state(o: dict, t: float) -> str:
        """placed / assigned / picked_up / delivered / late / unserved (or 'future')."""
        if o["placed_at"] > t:
            return "future"
        if o["delivered_at"] is not None and o["delivered_at"] <= t:
            return "late" if o["delivered_at"] > o["deadline"] else "delivered"
        if o["delivered_at"] is None and t >= o["cutoff_s"]:
            return "unserved"
        if o["picked_at"] is not None and o["picked_at"] <= t:
            return "picked_up"
        if o["assigned_at"] is not None and o["assigned_at"] <= t:
            return "assigned"
        return "placed"

    def snapshot(self, t: float) -> dict:
        """The full state at time t, rebuilt from the logs."""
        riders = []
        for rid in range(len(self.rider_starts)):
            x, y, route = self.rider_position(rid, t)
            status, order = self.rider_status(rid, t)
            riders.append({"id": rid, "x": x, "y": y, "status": status, "order": order, "route": route})
        orders = []
        for o in self.orders:
            state = self.order_state(o, t)
            if state == "future":
                continue
            orders.append({**o, "state": state, "food_ready": o["actual_ready"] <= t})
        di = self.decision_index_at(t)
        return {
            "time": t,
            "riders": riders,
            "orders": orders,
            "decision": self.decisions[di] if di is not None else None,
            "traffic": self.traffic_at(t),
        }

    def events_until(self, t: float, n: int = 15) -> list[dict]:
        i = bisect.bisect_right([e["time"] for e in self.events], t)
        return self.events[max(0, i - n): i]


class TraceRecorder:
    """Collects a ``Trace`` while a ``Simulator`` runs (see module docstring)."""

    def __init__(self, sample_route: bool = True) -> None:
        self.want_sample_route = sample_route
        self.trace: Trace | None = None
        self.legs: list[dict] = []
        self._open_leg: dict[int, int] = {}
        self.status_log: list[tuple[float, int, str, int | None]] = []
        self._last_status: dict[int, tuple[str, int | None]] = {}
        self.events: list[dict] = []
        self.decisions: list[dict] = []
        self.heap_ops: list[dict] = []
        self.traffic_updates: list[tuple[float, dict[int, float]]] = []
        self.trigger = "START"
        self._heap: IndexedMaxHeap | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self, sim) -> None:
        self.sim = sim
        g = sim.graph
        self.coords = list(g.coords)
        self.initial_traffic = list(g.traffic)
        self.rest_id = {r.node: r.id for r in sim.city.restaurants}
        heap = getattr(sim.dispatcher, "heap", None)
        if isinstance(heap, IndexedMaxHeap):
            heap.observer = self._heap_op
            self._heap = heap

    def finish(self, sim, result) -> None:
        if self._heap is not None:
            self._heap.observer = None
        g = sim.graph
        cutoff = sim.cutoff_s
        orders = []
        for o in result.orders:
            spec = sim._specs[o.id]
            orders.append({
                "id": o.id,
                "restaurant": self.rest_id.get(o.restaurant_node, -1),
                "restaurant_node": o.restaurant_node,
                "customer_node": o.customer_node,
                "placed_at": o.placed_at,
                "est_ready": o.placed_at + spec.est_prep_s,
                "actual_ready": o.placed_at + spec.actual_prep_s,  # unknown to dispatchers until FOOD_READY
                "deadline": o.deadline,
                "assigned_at": o.assigned_at,
                "rider_id": o.rider_id,
                "rider_arrived_at": o.rider_arrived_at,
                "picked_at": o.picked_at,
                "delivered_at": o.delivered_at,
                "distance_m": o.distance_m,
                "status": o.status.value,
                "late": o.delivered_at is None or o.delivered_at > o.deadline,
                "cutoff_s": cutoff,
            })
        times = [e["time"] for e in self.events] or [sim.start_s]
        meta = {
            "method": sim.dispatcher.name,
            "start_s": sim.start_s,
            "end_s": sim.end_s,
            "cutoff_s": cutoff,
            "last_event_s": max(times[-1], sim.start_s),
            "num_riders": len(sim.riders),
            "weights": result.dispatcher_stats.get("weights"),
        }
        self.trace = Trace(
            meta=meta,
            coords=self.coords,
            road_ends=list(g.road_ends),
            road_free_time=list(g.road_free_time),
            restaurants=[{"id": r.id, "node": r.node, "mean_prep_s": r.mean_prep_s} for r in sim.city.restaurants],
            rider_starts=list(sim.rider_starts),
            initial_traffic=self.initial_traffic,
            traffic_updates=self.traffic_updates,
            orders=orders,
            legs=self.legs,
            status_log=self.status_log,
            events=self.events,
            decisions=self.decisions,
            heap_ops=self.heap_ops,
            sample_route=self._sample_route(sim) if self.want_sample_route else {},
            metrics=compute_metrics(result, sim.cfg["metrics"]["peak_windows"]) if result.orders else {},
            dispatcher_stats=result.dispatcher_stats,
            cache_stats=result.cache_stats,
            event_counts=result.event_counts,
        )

    # ---------------------------------------------------------------- events
    def on_event(self, sim, ev: Event) -> None:
        self.trigger = ev.type.value
        text = self._describe(sim, ev)
        self.events.append({"time": ev.time, "type": ev.type.value, "order": ev.order_id,
                            "rider": ev.rider_id, "text": text})
        if ev.type == EventType.TRAFFIC_CHANGE and ev.payload is not None:
            changes = ev.payload.changes
            if changes:
                self.traffic_updates.append((ev.time, {r: new for r, (_, new) in changes.items()}))

    def after_step(self, sim) -> None:
        """Log rider status changes (after an event and the decisions it caused)."""
        for rid, r in sim.riders.items():
            st = (STATUS_NAMES[r.status.name], r.orders[0] if r.orders else None)
            if self._last_status.get(rid) != st:
                self._last_status[rid] = st
                self.status_log.append((sim.now, rid, st[0], st[1]))

    def _describe(self, sim, ev: Event) -> str:
        et, oid, rid = ev.type, ev.order_id, ev.rider_id
        o = sim.orders.get(oid) if oid is not None else None
        if et == EventType.ORDER_PLACED:
            return f"Order #{oid} placed at restaurant R{self.rest_id.get(o.restaurant_node, '?')} (due {_clock(o.deadline)})"
        if et == EventType.FOOD_READY:
            return f"Food ready for order #{oid}"
        if et == EventType.RIDER_ARRIVED_RESTAURANT:
            wait = "" if o.ready_at is not None else " (food not ready: rider waits)"
            return f"Rider {rid} reached the restaurant for #{oid}{wait}"
        if et == EventType.PICKUP:
            return f"Rider {rid} picked up #{oid}"
        if et == EventType.DELIVERED:
            mins = (o.delivered_at - o.placed_at) / 60
            late = f", LATE by {(o.delivered_at - o.deadline) / 60:.0f} min" if o.delivered_at > o.deadline else ""
            return f"Order #{oid} delivered by rider {rid} after {mins:.0f} min{late}"
        if et == EventType.RIDER_IDLE:
            return f"Rider {rid} is free"
        if et == EventType.TRAFFIC_CHANGE:
            changes = ev.payload.changes if ev.payload is not None else {}
            up = sum(1 for old, new in changes.values() if new > old)
            down = len(changes) - up
            if not changes:
                return "Traffic check: no change"
            if up and not down:
                return f"Traffic got worse on {up} roads"
            if down and not up:
                return f"Traffic cleared on {down} roads"
            return f"Traffic changed: {up} roads slower, {down} faster"
        return et.value

    # -------------------------------------------------------------- decisions
    def before_choose(self, sim) -> list:
        self.trigger = "DECISION"
        return sim.dispatcher.rank(sim.now, sim.view)

    def after_choose(self, sim, ranked: list, choice: tuple[int, int] | None) -> None:
        cands = [dataclasses.asdict(c) for c in ranked[:MAX_CANDIDATES]]
        runner = None
        if choice is not None:
            runner = next((c for c in cands if c["order_id"] != choice[1]), None)
        self.decisions.append({
            "time": sim.now,
            "method": sim.dispatcher.name,
            "idle_riders": list(sim.idle),
            "n_eligible": len(sim.eligible),
            "chosen": {"rider": choice[0], "order": choice[1]} if choice else None,
            "runner_up": runner,
            "candidates": cands,
            "n_candidates": len(ranked),
        })

    def _heap_op(self, op: str, info: dict) -> None:
        if op in HEAP_OPS:
            self.heap_ops.append({"time": self.sim.now, "op": op, "order": info["key"],
                                  "priority": info["priority"], "trigger": self.trigger})

    # ---------------------------------------------------------------- legs
    def on_leg(self, sim, rider) -> None:
        self._close(rider.id, sim.now)
        nodes = list(rider.route_nodes)
        self._open(rider, nodes, [self.coords[n] for n in nodes], list(rider.node_times))

    def on_retime(self, sim, rider, i: int, frac: float) -> None:
        """Traffic changed mid-trip: cut the old leg at now, continue from the exact position."""
        now = sim.now
        (x1, y1), (x2, y2) = self.coords[rider.route_nodes[i]], self.coords[rider.route_nodes[i + 1]]
        pos = (x2 - frac * (x2 - x1), y2 - frac * (y2 - y1))
        self._close(rider.id, now, pos)
        nodes = list(rider.route_nodes[i + 1:])
        self._open(rider, nodes, [pos] + [self.coords[n] for n in nodes], [now] + list(rider.node_times[i + 1:]),
                   first_node=rider.route_nodes[i])

    def _open(self, rider, nodes, points, times, first_node=None) -> None:
        self._open_leg[rider.id] = len(self.legs)
        self.legs.append({
            "rider": rider.id,
            "order": rider.orders[0] if rider.orders else None,
            "status": STATUS_NAMES[rider.status.name],
            "start": times[0],
            "end": times[-1],
            "xs": [p[0] for p in points],
            "ys": [p[1] for p in points],
            "times": times,
            "nodes": ([first_node] if first_node is not None else []) + nodes,
        })

    def _close(self, rider_id: int, now: float, pos: tuple[float, float] | None = None) -> None:
        idx = self._open_leg.pop(rider_id, None)
        if idx is None:
            return
        leg = self.legs[idx]
        if leg["end"] <= now:
            return
        keep = [k for k, t in enumerate(leg["times"]) if t < now]
        if pos is None:
            pos = (float(np.interp(now, leg["times"], leg["xs"])), float(np.interp(now, leg["times"], leg["ys"])))
        leg["xs"] = [leg["xs"][k] for k in keep] + [pos[0]]
        leg["ys"] = [leg["ys"][k] for k in keep] + [pos[1]]
        leg["times"] = [leg["times"][k] for k in keep] + [now]
        leg["end"] = now

    # --------------------------------------------------------- sample route
    def _sample_route(self, sim) -> dict:
        """Dijkstra vs A* on one long route (restaurant -> farthest node), current traffic."""
        g = sim.graph
        if not sim.city.restaurants or g.num_nodes < 2:
            return {}
        src = sim.city.restaurants[0].node
        dst = max(range(g.num_nodes), key=lambda v: g.euclid(src, v))
        out = {"source": src, "target": dst}
        for name, fn in [("dijkstra", lambda vo: dijkstra(g, src, "time", target=dst, visit_order=vo)),
                         ("astar", lambda vo: astar(g, src, dst, "time", visit_order=vo))]:
            visits: list[int] = []
            t0 = time.perf_counter()
            res = fn(visits)
            ms = 1000 * (time.perf_counter() - t0)
            if name == "dijkstra":
                nodes, _ = reconstruct_path(res, dst)
                cost = res.dist[dst]
            else:
                cost, nodes, _ = res
            out[name] = {"visits": visits, "path": nodes, "cost": cost, "expanded": len(visits), "ms": ms}
        return out


def record_run(cfg: dict, dispatcher, scenario: str = "normal", seed: int = 0,
               specs=None, rider_starts=None, sample_route: bool = True) -> Trace:
    """Run one simulation with a recorder attached and return its ``Trace``."""
    from sim.simulator import run_simulation  # local import: simulator does not depend on this module

    rec = TraceRecorder(sample_route=sample_route)
    run_simulation(cfg, dispatcher, scenario, seed, recorder=rec, specs=specs, rider_starts=rider_starts)
    return rec.trace
