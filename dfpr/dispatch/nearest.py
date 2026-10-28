"""Baseline 1: Nearest Order First."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dispatch.base import Candidate, Dispatcher, longest_idle_rider, rank_by_cost

if TYPE_CHECKING:
    from sim.simulator import SimView


class NearestOrderFirst(Dispatcher):
    """The idle rider takes the eligible order whose restaurant is closest.

    "Closest" is network (road) distance in metres, not straight-line
    distance. When several riders are idle, the one idle longest chooses first.
    Ties are broken by order placement time, then order id.

    Cost per decision: O(R + N) for R idle riders and N eligible orders, with
    O(1) distance lookups from cached restaurant trees.
    """

    name = "nearest"

    def __init__(self, mode: str = "length") -> None:
        self.mode = mode

    def choose(self, now: float, view: SimView) -> tuple[int, int] | None:
        if not view.idle or not view.eligible:
            return None
        rider = longest_idle_rider(view)
        node = view.riders[rider].node
        cache = view.router.cache

        def key(oid: int) -> tuple[float, float, int]:
            o = view.orders[oid]
            return cache.distance(o.restaurant_node, node, self.mode), o.placed_at, oid

        return rider, min(view.eligible, key=key)

    def rank(self, now: float, view: SimView) -> list[Candidate]:
        if not view.idle or not view.eligible:
            return []
        rider = longest_idle_rider(view)
        node = view.riders[rider].node
        cache = view.router.cache
        return rank_by_cost(view, now, rider,
                            lambda o: cache.distance(view.orders[o].restaurant_node, node, self.mode),
                            "road distance from rider to restaurant", "m")
