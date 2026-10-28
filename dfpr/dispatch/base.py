"""Common interface for all dispatch rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sim.events import Event

if TYPE_CHECKING:
    from sim.simulator import SimView


@dataclass(frozen=True)
class Candidate:
    """One entry of a dispatcher's ranking at a decision (for explanations only).

    ``score`` is "higher = preferred" for every method; for cost-based rules it
    is the negated cost. ``value``/``unit`` hold the rule's own criterion in
    readable form (e.g. 850 m). ``factors``/``contributions`` are DFPR's raw
    normalised factors and their signed weighted contributions. ``details``
    holds times used by the plain-English explanation (seconds).
    """

    order_id: int
    rider_id: int | None
    score: float
    criterion: str
    value: float
    unit: str
    factors: dict[str, float] | None = None
    contributions: dict[str, float] | None = None
    details: dict[str, float] = field(default_factory=dict)


class Dispatcher(ABC):
    """A dispatch rule decides which idle rider takes which waiting order.

    The simulator calls:
      * ``reset(view)`` once before the run,
      * ``on_event(event, view)`` after it has applied each event to the state
        (dynamic methods such as DFPR update their internal scores here),
      * ``choose(now, view)`` at every decision point, repeatedly, until it
        returns None or there is no idle rider / eligible order left.

    ``view`` gives read access to the simulation state (orders, riders,
    eligible orders, idle riders, router). Dispatchers must not modify it;
    the simulator performs the assignment that ``choose`` returns.
    """

    name: str = "base"

    def reset(self, view: SimView) -> None:
        """Called once before the simulation starts."""

    def on_event(self, event: Event, view: SimView) -> None:
        """Called after each event has been applied to the simulation state."""

    @abstractmethod
    def choose(self, now: float, view: SimView) -> tuple[int, int] | None:
        """Return ``(rider_id, order_id)`` to assign now, or None to assign nothing."""

    def stats(self) -> dict:
        """Method-specific counters reported with the run (e.g. recomputations)."""
        return {}

    def rank(self, now: float, view: SimView) -> list[Candidate]:
        """Read-only ranking of the eligible orders, best first, for explanations.

        Used only by the trace recorder (demo app). It must not change any
        state that ``choose`` depends on, so recording cannot alter decisions.
        """
        return []


def order_details(view: SimView, oid: int, now: float) -> dict[str, float]:
    """Times every explanation can use: deadline slack and food status (seconds)."""
    o = view.orders[oid]
    ready = o.ready_at if o.ready_at is not None else max(o.est_ready_at, now)
    return {"time_to_deadline": o.deadline - now, "food_ready_in": max(0.0, ready - now),
            "food_ready": float(o.ready_at is not None), "waiting_for": now - o.placed_at}


def rider_details(view: SimView, oid: int, rider: int, now: float) -> dict[str, float]:
    """``order_details`` plus the rider's traffic-aware arrival and predicted wait (seconds)."""
    d = order_details(view, oid, now)
    eta = view.router.cache.distance(view.orders[oid].restaurant_node, view.riders[rider].node, "time")
    d["rider_arrival_in"] = eta
    d["rider_wait"] = max(0.0, d["food_ready_in"] - eta)
    d["food_wait"] = max(0.0, eta - d["food_ready_in"])
    return d


def rank_by_cost(view: SimView, now: float, rider: int, cost, criterion: str, unit: str) -> list[Candidate]:
    """Rank eligible orders for one rider by ``cost(order) -> float`` (lower = better),
    ties by placement time then id, exactly like the rider-centric baselines."""
    keyed = sorted(view.eligible, key=lambda o: (cost(o), view.orders[o].placed_at, o))
    return [Candidate(o, rider, -cost(o), criterion, cost(o), unit, details=rider_details(view, o, rider, now))
            for o in keyed]

# ---------------------------------------------------------------- shared helpers
#
# Distances are looked up in shortest-path trees rooted at *restaurants*.
# Roads are undirected and both directions share one traffic multiplier, so
# dist(rider -> restaurant) == dist(restaurant -> rider). There are only ~40
# restaurants, so their trees stay in the route cache and every lookup is O(1),
# whereas trees rooted at riders would change every time a rider moves.


def longest_idle_rider(view: SimView) -> int:
    """Idle rider who has been waiting longest (ties: lowest id). O(R)."""
    return min(view.idle, key=lambda r: (view.idle[r], r))


def nearest_idle_rider(view: SimView, restaurant: int, mode: str = "length") -> int:
    """Idle rider closest to ``restaurant`` by network cost (ties: lowest id). O(R)."""
    tree = view.router.cache.tree(restaurant, mode)
    return min(view.idle, key=lambda r: (tree.dist[view.riders[r].node], r))
