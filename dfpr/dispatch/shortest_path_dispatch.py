"""Baseline 2: Shortest-Path Dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dispatch.base import Candidate, Dispatcher, longest_idle_rider, rank_by_cost

if TYPE_CHECKING:
    from sim.simulator import SimView


class ShortestPathDispatch(Dispatcher):
    """The idle rider takes the order with the smallest total free-flow path length.

    Total length = road distance(rider -> restaurant) + road distance(restaurant -> customer).

    Note: Dijkstra only *finds paths*; it does not say which order a rider
    should take. A "shortest path" baseline therefore still needs a dispatch
    rule, and the rule here is "minimum total path length". It ignores
    deadlines, food readiness and traffic. Both legs come from the
    restaurant's cached Dijkstra tree (length mode, so never invalidated).

    Cost per decision: O(R + N), with O(1) distance lookups.
    """

    name = "shortest_path"

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
            tree = cache.tree(o.restaurant_node, self.mode)
            return tree.dist[node] + tree.dist[o.customer_node], o.placed_at, oid

        return rider, min(view.eligible, key=key)

    def rank(self, now: float, view: SimView) -> list[Candidate]:
        if not view.idle or not view.eligible:
            return []
        rider = longest_idle_rider(view)
        node = view.riders[rider].node
        cache = view.router.cache

        def total(oid: int) -> float:
            tree = cache.tree(view.orders[oid].restaurant_node, self.mode)
            return tree.dist[node] + tree.dist[view.orders[oid].customer_node]

        return rank_by_cost(view, now, rider, total, "total path rider -> restaurant -> customer", "m")
