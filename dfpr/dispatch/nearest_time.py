"""Control baseline: traffic-aware nearest pair."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dispatch.base import Candidate, Dispatcher, rider_details

if TYPE_CHECKING:
    from sim.simulator import SimView


class NearestTimePair(Dispatcher):
    """Assign the (idle rider, eligible order) pair with the shortest traffic-aware
    travel time from rider to restaurant.

    This is a stricter control for DFPR than ``NearestOrderFirst``. It uses the
    same information DFPR uses for routing (traffic-aware travel times from the
    restaurants' cached Dijkstra trees, invalidated on traffic changes) and the
    same rider choice (the nearest idle rider), but no priority score. Any
    remaining gap between this baseline and DFPR is due to the score itself.

    Cost per decision: O(N * R) lookups for N eligible orders and R idle riders.
    """

    name = "nearest_time"

    def choose(self, now: float, view: SimView) -> tuple[int, int] | None:
        if not view.idle or not view.eligible:
            return None
        cache = view.router.cache
        best, best_key = None, None
        for oid in view.eligible:
            o = view.orders[oid]
            dist = cache.tree(o.restaurant_node, "time").dist
            for r in view.idle:
                key = (dist[view.riders[r].node], o.placed_at, oid, r)
                if best_key is None or key < best_key:
                    best, best_key = (r, oid), key
        return best

    def rank(self, now: float, view: SimView) -> list[Candidate]:
        if not view.idle or not view.eligible:
            return []
        cache = view.router.cache
        keyed = []
        for oid in view.eligible:
            o = view.orders[oid]
            dist = cache.tree(o.restaurant_node, "time").dist
            r = min(view.idle, key=lambda r: (dist[view.riders[r].node], r))
            keyed.append(((dist[view.riders[r].node], o.placed_at, oid, r), oid, r))
        keyed.sort()
        return [Candidate(oid, r, -k[0], "traffic-aware travel time rider -> restaurant", k[0], "s",
                          details=rider_details(view, oid, r, now)) for k, oid, r in keyed]
