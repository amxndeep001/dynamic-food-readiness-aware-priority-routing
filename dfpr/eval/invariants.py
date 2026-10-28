"""Sanity checks that must hold for every simulation run, whatever the dispatcher.

Used by the tests and run on every experiment result, so a bug in a dispatcher
or the simulator cannot silently produce impossible numbers.
"""

from __future__ import annotations

import math
from collections import Counter

from sim.orders import OrderStatus
from sim.simulator import SimResult


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


def check_invariants(result: SimResult) -> None:
    """Raise AssertionError if the run violates any physical or bookkeeping rule."""
    assert len(result.orders) == len(result.specs), "some orders were never placed"
    counts = Counter(o.status for o in result.orders)
    assert set(counts) <= {OrderStatus.DELIVERED, OrderStatus.UNSERVED}, f"unfinished statuses: {counts}"

    for o in result.orders:
        true_ready = result.true_ready_at[o.id]
        if o.ready_at is not None:
            assert _close(o.ready_at, true_ready), f"order {o.id}: ready_at differs from truth"
        if o.picked_at is not None:
            assert o.picked_at >= true_ready - 1e-9, f"order {o.id} picked up before food was ready"
            assert o.picked_at >= o.rider_arrived_at >= o.assigned_at >= o.placed_at, f"order {o.id}: bad timeline"
            # Pickup happens exactly when the later of rider and food arrives.
            assert _close(o.picked_at, max(o.rider_arrived_at, true_ready)), f"order {o.id}: late pickup"
        if o.status == OrderStatus.DELIVERED:
            assert o.delivered_at >= o.picked_at, f"order {o.id} delivered before pickup"

    if not result.trace:
        return
    times = [t for t, *_ in result.trace]
    assert times == sorted(times), "events processed out of time order"
    pickups = Counter(oid for _, et, oid, _ in result.trace if et == "PICKUP")
    delivers = Counter(oid for _, et, oid, _ in result.trace if et == "DELIVERED")
    assert all(c == 1 for c in pickups.values()), "an order was picked up twice"
    assert all(c == 1 for c in delivers.values()), "an order was delivered twice"
    assert set(delivers) == {o.id for o in result.orders if o.status == OrderStatus.DELIVERED}

    # Capacity 1: between a rider's pickup and the matching delivery there is
    # no other pickup by that rider.
    holding: dict[int, int] = {}
    for _, et, oid, rid in result.trace:
        if et == "PICKUP":
            assert rid not in holding, f"rider {rid} carrying two orders"
            holding[rid] = oid
        elif et == "DELIVERED":
            assert holding.pop(rid) == oid, f"rider {rid} delivered an order it was not carrying"
