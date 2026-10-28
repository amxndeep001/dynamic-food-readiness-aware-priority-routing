"""Baseline 3: Static Priority (earliest deadline first)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dispatch.base import Candidate, Dispatcher, nearest_idle_rider, rider_details
from ds.indexed_heap import IndexedMaxHeap
from sim.events import Event, EventType

if TYPE_CHECKING:
    from sim.simulator import SimView


class StaticPriority(Dispatcher):
    """Earliest-deadline-first with a priority fixed when the order arrives.

    Each order is pushed into a max-heap with priority = -deadline when it is
    placed, and that priority is never recomputed, whatever happens to food
    readiness, traffic or rider positions. This is the "static" counterpart
    to DFPR. The top order goes to the idle rider nearest its restaurant.
    Without that, EDF would send arbitrary riders across the city.

    Cost per decision: O(log N) to pop the heap, plus O(R) to pick the rider.
    """

    name = "static_priority"

    def __init__(self) -> None:
        self.heap: IndexedMaxHeap[int] = IndexedMaxHeap()

    def reset(self, view: SimView) -> None:
        self.heap = IndexedMaxHeap()

    def on_event(self, event: Event, view: SimView) -> None:
        if event.type == EventType.ORDER_PLACED:
            self.heap.push(event.order_id, -view.orders[event.order_id].deadline)

    def choose(self, now: float, view: SimView) -> tuple[int, int] | None:
        if not view.idle or not self.heap:
            return None
        order_id, _ = self.heap.pop_max()
        # The heap holds exactly the eligible orders: pushed when placed,
        # popped only here, and the simulator always performs our choice.
        assert order_id in view.eligible
        rider = nearest_idle_rider(view, view.orders[order_id].restaurant_node)
        return rider, order_id

    def rank(self, now: float, view: SimView) -> list[Candidate]:
        if not view.idle or not self.heap:
            return []
        # Same order as the heap: latest deadline last; ties by insertion (= order id).
        oids = sorted(self.heap.keys(), key=lambda o: (view.orders[o].deadline, o))
        out = []
        for o in oids:
            rider = nearest_idle_rider(view, view.orders[o].restaurant_node)
            dl = view.orders[o].deadline
            out.append(Candidate(o, rider, -dl, "deadline (earliest first)", dl - now, "s",
                                 details=rider_details(view, o, rider, now)))
        return out
