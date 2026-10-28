"""Trivial first-come-first-served dispatcher (sanity reference, not a baseline)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dispatch.base import Candidate, Dispatcher, rank_by_cost

if TYPE_CHECKING:
    from sim.simulator import SimView


class FifoDispatcher(Dispatcher):
    """The longest-idle rider takes the oldest waiting order.

    Ignores location entirely, so it is a floor that any sensible rule should
    beat. O(R + N) per decision for R idle riders and N eligible orders.
    """

    name = "fifo"

    def choose(self, now: float, view: SimView) -> tuple[int, int] | None:
        if not view.idle or not view.eligible:
            return None
        rider = min(view.idle, key=lambda r: (view.idle[r], r))
        order = min(view.eligible, key=lambda o: (view.orders[o].placed_at, o))
        return rider, order

    def rank(self, now: float, view: SimView) -> list[Candidate]:
        if not view.idle or not view.eligible:
            return []
        rider = min(view.idle, key=lambda r: (view.idle[r], r))
        return rank_by_cost(view, now, rider, lambda o: view.orders[o].placed_at, "placement time", "s")
