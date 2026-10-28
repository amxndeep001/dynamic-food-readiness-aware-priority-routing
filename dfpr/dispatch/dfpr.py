"""DFPR: Dynamic Food-Readiness-Aware Priority Routing.

Score of eligible order i at time t, using its candidate rider (the idle rider
with the shortest traffic-aware travel time to the restaurant):

    P_i(t) = w_u*U + w_f*F + w_w*W - w_d*D - w_c*C - w_r*R

Notation (all times in seconds):
    tau_r, tau_c   traffic-aware travel time rider->restaurant, restaurant->customer
    free_r, free_c the same at free-flow speed (shortest free-flow time)
    dist_r, dist_c road distance (m) rider->restaurant, restaurant->customer
    a  = t + tau_r                         predicted rider arrival at the restaurant
    e  = ready_at                          if FOOD_READY has happened (observed), else
         max(placed + est_prep, t)         estimated ready time (it is not ready yet at t)
    d^ = max(a, e) + tau_c                 predicted delivery time

Normalisation to [0, 1], with clip(x) = min(1, max(0, x)) and H_* from config:
    U = clip(1 - (deadline - d^) / H_u)     urgency: 0 with >= H_u of slack, 1 if predicted late
    F = clip(1 - |e - a| / H_f)             readiness alignment: 1 when rider arrives as food is ready
    W = clip((t - placed) / H_w)            how long the order has been waiting
    D = clip((dist_r + dist_c) / D_max)     D_max = 2 * max road distance from any restaurant to any node
    C = clip((tau_r - free_r + tau_c - free_c) / C_max)   traffic delay on both legs
    R = clip(max(0, e - a) / H_r)           predicted rider waiting time at the restaurant

Dynamic updates (each one logged as a "recomputation" against its trigger):
    ORDER_PLACED    insert the order with a full score.
    FOOD_READY      e becomes the observed ready time -> rescore that one order.
    TRAFFIC_CHANGE  orders whose restaurant's shortest-path tree was invalidated
                    get their travel times, C, D and candidate rider recomputed.
    RIDER_IDLE      a new idle rider may be closer than an order's candidate;
                    only orders whose candidate changes are recomputed.
    ASSIGNMENT      the chosen rider stops being idle; orders that had that
                    rider as candidate get a new one.
    time passing    handled lazily at decision time (see below).

Lazy time refresh (why the heap still pays off)
-----------------------------------------------
Between events, scores drift only because t moves. Each time-dependent term
changes at a bounded rate: |dU/dt| <= 1/H_u, |dF/dt| <= 1/H_f, |dW/dt| <= 1/H_w,
|dR/dt| <= 1/H_r (D and C do not depend on t). So a score computed at time s
can be at most L * (t - s) higher at time t, where

    L = w_u/H_u + w_f/H_f + w_w/H_w + w_r/H_r.

The heap key is therefore stored as key_i = P_i(s_i) - L * s_i. Then
key_i + L*t is an *upper bound* on P_i(t), and ordering by key is ordering by
upper bound. At a decision we repeatedly look at the top entry: if it was
scored at the current time, its bound is exact and it beats every other
order's bound, so it is the true maximum. Otherwise we rescore it and update
its key (which can only go down) and look again. This gives the exact argmax
while usually rescoring only a few orders instead of all N.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dispatch.base import Candidate, Dispatcher, order_details
from ds.indexed_heap import IndexedMaxHeap
from sim.events import Event, EventType
from sim.orders import Order

if TYPE_CHECKING:
    from sim.simulator import SimView

FACTORS = ("u", "f", "w", "d", "c", "r")


def clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass(frozen=True)
class Weights:
    u: float = 1.0
    f: float = 1.0
    w: float = 1.0
    d: float = 1.0
    c: float = 1.0
    r: float = 1.0

    @classmethod
    def from_dict(cls, d: dict) -> Weights:
        return cls(**{k: float(d[k]) for k in FACTORS})

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class Normalization:
    """Scale constants (seconds / metres) that map each raw factor to [0, 1]."""

    urgency_horizon_s: float
    readiness_window_s: float
    wait_horizon_s: float
    delay_max_s: float
    rider_wait_max_s: float
    distance_max_m: float

    @classmethod
    def from_config(cls, cfg: dict, distance_max_m: float) -> Normalization:
        return cls(
            cfg["urgency_horizon_min"] * 60.0,
            cfg["readiness_window_min"] * 60.0,
            cfg["wait_horizon_min"] * 60.0,
            cfg["delay_max_min"] * 60.0,
            cfg["rider_wait_max_min"] * 60.0,
            distance_max_m,
        )

    def lipschitz(self, w: Weights) -> float:
        """Upper bound on how fast a score can change per second with no events."""
        return (
            abs(w.u) / self.urgency_horizon_s
            + abs(w.f) / self.readiness_window_s
            + abs(w.w) / self.wait_horizon_s
            + abs(w.r) / self.rider_wait_max_s
        )


@dataclass(frozen=True)
class RouteTerms:
    """The expensive, event-updated part of a score (shortest-path lookups)."""

    rider: int | None
    tau_r: float = 0.0
    free_r: float = 0.0
    dist_r: float = 0.0
    tau_c: float = 0.0
    free_c: float = 0.0
    dist_c: float = 0.0


@dataclass(frozen=True)
class Factors:
    U: float
    F: float
    W: float
    D: float
    C: float
    R: float


def compute_factors(order: Order, rt: RouteTerms, now: float, norm: Normalization) -> Factors:
    """Normalised factors for one order (formulas in the module docstring). O(1)."""
    a = now + rt.tau_r
    e = order.ready_at if order.ready_at is not None else max(order.est_ready_at, now)
    predicted_delivery = max(a, e) + rt.tau_c
    slack = order.deadline - predicted_delivery
    return Factors(
        U=clip01(1.0 - slack / norm.urgency_horizon_s),
        F=clip01(1.0 - abs(e - a) / norm.readiness_window_s),
        W=clip01((now - order.placed_at) / norm.wait_horizon_s),
        D=clip01((rt.dist_r + rt.dist_c) / norm.distance_max_m),
        C=clip01((rt.tau_r - rt.free_r + rt.tau_c - rt.free_c) / norm.delay_max_s),
        R=clip01(max(0.0, e - a) / norm.rider_wait_max_s),
    )


def combine(f: Factors, w: Weights) -> float:
    """P = w_u U + w_f F + w_w W - w_d D - w_c C - w_r R."""
    return w.u * f.U + w.f * f.F + w.w * f.W - w.d * f.D - w.c * f.C - w.r * f.R


class DFPR(Dispatcher):
    """Dynamic priority dispatcher backed by an indexed max-heap of eligible orders."""

    name = "dfpr"

    def __init__(self, weights: Weights, norm_cfg: dict) -> None:
        self.weights = weights
        self.norm_cfg = norm_cfg

    @classmethod
    def from_config(cls, cfg: dict) -> DFPR:
        """Weights come from ``dfpr.weights_file`` (tuned) if set, else ``dfpr.weights``."""
        dcfg = cfg["dfpr"]
        weights = dcfg["weights"]
        if dcfg.get("weights_file"):
            weights = json.loads(Path(dcfg["weights_file"]).read_text())["weights"]
        return cls(Weights.from_dict(weights), dcfg["normalization"])

    # ------------------------------------------------------------------ setup
    def reset(self, view: SimView) -> None:
        cache = view.router.cache
        # D_max: any rider->restaurant or restaurant->customer leg is at most
        # the largest distance from a restaurant to any node, so their sum is
        # at most twice that, which keeps D within [0, 1].
        ecc = max(max(cache.tree(r.node, "length").dist) for r in view.city.restaurants)
        self.norm = Normalization.from_config(self.norm_cfg, 2.0 * ecc)
        self.L = self.norm.lipschitz(self.weights)
        self.heap: IndexedMaxHeap[int] = IndexedMaxHeap()
        self.terms: dict[int, RouteTerms] = {}
        self.scored_at: dict[int, float] = {}
        self.by_rider: dict[int, set[int]] = {}  # candidate rider -> orders using it
        self.recomputations: Counter[str] = Counter()  # route-term recomputations per trigger
        self.rescores: Counter[str] = Counter()  # score-only recomputations per trigger
        self.trigger_counts: Counter[str] = Counter()
        self.lazy_refreshes = 0
        self.decisions = 0

    # ---------------------------------------------------------------- scoring
    def _route_terms(self, order: Order, rider: int | None, view: SimView) -> RouteTerms:
        cache = view.router.cache
        rest, cust = order.restaurant_node, order.customer_node
        t_time, t_free, t_len = cache.tree(rest, "time"), cache.tree(rest, "free_time"), cache.tree(rest, "length")
        if rider is None:
            return RouteTerms(None, tau_c=t_time.dist[cust], free_c=t_free.dist[cust], dist_c=t_len.dist[cust])
        node = view.riders[rider].node
        return RouteTerms(
            rider,
            t_time.dist[node], t_free.dist[node], t_len.dist[node],
            t_time.dist[cust], t_free.dist[cust], t_len.dist[cust],
        )

    def _best_idle_rider(self, order: Order, view: SimView, exclude: int | None = None) -> int | None:
        """Idle rider with the shortest traffic-aware travel time to the restaurant. O(R)."""
        dist = view.router.cache.tree(order.restaurant_node, "time").dist
        best, best_key = None, None
        for r in view.idle:
            if r == exclude:
                continue
            key = (dist[view.riders[r].node], r)
            if best_key is None or key < best_key:
                best, best_key = r, key
        return best

    def score(self, oid: int, view: SimView, now: float) -> float:
        """Exact score of an eligible order at time ``now`` from its cached route terms."""
        return combine(compute_factors(view.orders[oid], self.terms[oid], now, self.norm), self.weights)

    def _set_key(self, oid: int, view: SimView, now: float) -> None:
        key = self.score(oid, view, now) - self.L * now
        self.scored_at[oid] = now
        if oid in self.heap:
            self.heap.update_key(oid, key)
        else:
            self.heap.push(oid, key)

    def _recompute(self, oid: int, view: SimView, now: float, trigger: str,
                   rider: int | None = None, exclude: int | None = None) -> None:
        """Recompute route terms for one order, then rescore it.

        If ``rider`` is not given, the candidate is re-chosen as the nearest
        idle rider (ignoring ``exclude``). O(R + log N).
        """
        order = view.orders[oid]
        if rider is None:
            rider = self._best_idle_rider(order, view, exclude)
        old = self.terms.get(oid)
        if old is not None and old.rider is not None:
            self.by_rider[old.rider].discard(oid)
        if rider is not None:
            self.by_rider.setdefault(rider, set()).add(oid)
        self.terms[oid] = self._route_terms(order, rider, view)
        self._set_key(oid, view, now)
        self.recomputations[trigger] += 1

    # ----------------------------------------------------------------- events
    def on_event(self, event: Event, view: SimView) -> None:
        et, now = event.type, event.time
        self.trigger_counts[et.value] += 1

        if et == EventType.ORDER_PLACED:
            self._recompute(event.order_id, view, now, et.value)

        elif et == EventType.FOOD_READY:
            # Only e changed; travel times did not, so a rescore is enough.
            if event.order_id in self.heap:
                self._set_key(event.order_id, view, now)
                self.rescores[et.value] += 1

        elif et == EventType.TRAFFIC_CHANGE:
            stale = set(event.payload.invalidated_sources)
            if stale:
                for oid in list(self.heap.keys()):
                    if view.orders[oid].restaurant_node in stale:
                        self._recompute(oid, view, now, et.value)

        elif et == EventType.RIDER_IDLE:
            # The new rider replaces an order's candidate only if it is closer.
            r = event.rider_id
            node = view.riders[r].node
            cache = view.router.cache
            for oid in list(self.heap.keys()):
                cur = self.terms[oid].rider
                dist = cache.tree(view.orders[oid].restaurant_node, "time").dist
                if cur is None or (dist[node], r) < (dist[view.riders[cur].node], cur):
                    self._recompute(oid, view, now, et.value, rider=r)

    # --------------------------------------------------------------- decision
    def choose(self, now: float, view: SimView) -> tuple[int, int] | None:
        if not view.idle or not self.heap:
            return None
        self.decisions += 1
        # Lazy exact argmax (see module docstring): rescore the top until the
        # top entry is up to date; its bound is then exact and maximal.
        while True:
            oid, _ = self.heap.peek()
            if self.scored_at[oid] == now:
                break
            self._set_key(oid, view, now)
            self.lazy_refreshes += 1

        rider = self.terms[oid].rider
        assert rider is not None and rider in view.idle, "candidate rider must be idle"
        self.heap.remove(oid)
        self.by_rider[rider].discard(oid)
        del self.terms[oid], self.scored_at[oid]

        # The chosen rider is about to leave the idle pool.
        for other in list(self.by_rider.get(rider, ())):
            self._recompute(other, view, now, "ASSIGNMENT", exclude=rider)
        self.by_rider.pop(rider, None)
        self.trigger_counts["ASSIGNMENT"] += 1
        return rider, oid

    # -------------------------------------------------------------- explaining
    def rank(self, now: float, view: SimView) -> list[Candidate]:
        """Exact scores of all queued orders at ``now`` with per-factor breakdown.

        Read-only: uses the cached route terms and never touches heap keys, so
        calling it (as the demo recorder does) cannot change any decision.
        Order matches ``choose``: highest score first, ties to the older entry.
        """
        if not view.idle or not self.heap:
            return []
        w = self.weights
        out = []
        for oid in self.heap.keys():
            rt = self.terms[oid]
            f = compute_factors(view.orders[oid], rt, now, self.norm)
            contrib = {"U": w.u * f.U, "F": w.f * f.F, "W": w.w * f.W,
                       "D": -w.d * f.D, "C": -w.c * f.C, "R": -w.r * f.R}
            details = order_details(view, oid, now)
            details.update(
                rider_arrival_in=rt.tau_r,
                rider_wait=max(0.0, details["food_ready_in"] - rt.tau_r),
                food_wait=max(0.0, rt.tau_r - details["food_ready_in"]),
                traffic_delay=rt.tau_r - rt.free_r + rt.tau_c - rt.free_c,
                distance_m=rt.dist_r + rt.dist_c,
                delivery_leg=rt.tau_c,
            )
            score = combine(f, w)
            out.append(Candidate(oid, rt.rider, score, "DFPR priority score", score, "",
                                 factors=asdict(f), contributions=contrib, details=details))
        out.sort(key=lambda c: (-c.score, -self.heap.tiebreak(c.order_id)))
        return out

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        """Recomputation log: totals and average per triggering event."""
        per_event = {
            k: round((self.recomputations[k] + self.rescores[k]) / n, 3)
            for k, n in self.trigger_counts.items() if n
        }
        return {
            "weights": self.weights.as_dict(),
            "recomputations": dict(self.recomputations),
            "rescores": dict(self.rescores),
            "trigger_counts": dict(self.trigger_counts),
            "recomputations_per_event": per_event,
            "lazy_refreshes": self.lazy_refreshes,
            "decisions": self.decisions,
            "lazy_refreshes_per_decision": round(self.lazy_refreshes / max(self.decisions, 1), 3),
        }
