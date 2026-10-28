"""Trace recorder: schema, no effect on behaviour, geometric consistency, edge cases."""

from __future__ import annotations

import math

import pytest

from dispatch import make_dispatcher
from sim.config import load_config
from sim.orders import OrderSpec
from sim.recorder import Trace, record_run
from sim.simulator import run_simulation

SMALL = {"sim": {"start_hour": 11, "end_hour": 12.5, "drain_minutes": 60}, "riders": {"count": 6},
         "traffic": {"incident_rate_per_hour": 4}}
METHODS = ["dfpr", "nearest", "shortest_path", "static_priority", "nearest_time", "fifo"]
ORDER_STATES = {"placed", "assigned", "picked_up", "delivered", "late", "unserved"}
RIDER_STATES = {"idle", "to_restaurant", "waiting_at_restaurant", "to_customer"}


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config(overrides=SMALL)


@pytest.fixture(scope="module")
def traces(cfg) -> dict[str, Trace]:
    return {m: record_run(cfg, m, "peak", seed=4) for m in METHODS}


def outcome(orders) -> list[tuple]:
    return [(o["id"] if isinstance(o, dict) else o.id,) + tuple(
        (o[k] if isinstance(o, dict) else getattr(o, k))
        for k in ("rider_id", "assigned_at", "rider_arrived_at", "picked_at", "delivered_at", "distance_m"))
        for o in orders]


@pytest.mark.parametrize("method", METHODS)
def test_recording_does_not_change_behaviour(cfg, traces, method) -> None:
    plain = run_simulation(cfg, method, "peak", seed=4)
    assert outcome(plain.orders) == outcome(traces[method].orders)
    # Decision sequence: (time, chosen order, rider) in order.
    recorded = [(d["time"], d["chosen"]["order"], d["chosen"]["rider"]) for d in traces[method].decisions if d["chosen"]]
    by_assign = sorted((o.assigned_at, o.id, o.rider_id) for o in plain.orders if o.assigned_at is not None)
    assert sorted(recorded) == by_assign


@pytest.mark.parametrize("method", METHODS)
def test_ranking_explains_the_actual_choice(traces, method) -> None:
    decisions = [d for d in traces[method].decisions if d["chosen"]]
    assert decisions
    for d in decisions:
        top = d["candidates"][0]
        assert (top["order_id"], top["rider_id"]) == (d["chosen"]["order"], d["chosen"]["rider"])
        if d["runner_up"] is not None:
            assert d["runner_up"]["order_id"] != d["chosen"]["order"]
            assert d["runner_up"]["score"] <= top["score"] + 1e-12


def test_dfpr_breakdown_adds_up(traces) -> None:
    for d in traces["dfpr"].decisions:
        for c in d["candidates"]:
            assert set(c["factors"]) == set("UFWDCR")
            assert all(0.0 <= v <= 1.0 for v in c["factors"].values())
            assert sum(c["contributions"].values()) == pytest.approx(c["score"])


def test_schema_and_snapshots(traces) -> None:
    tr = traces["dfpr"]
    assert tr.meta["method"] == "dfpr" and tr.meta["weights"] is not None
    assert len(tr.coords) > 0 and len(tr.road_ends) == len(tr.initial_traffic)
    assert [e["time"] for e in tr.events] == sorted(e["time"] for e in tr.events)
    assert tr.decision_times() == sorted(tr.decision_times())
    for t in [tr.start, (tr.start + tr.end) / 2, tr.end, tr.end + 3600]:
        snap = tr.snapshot(t)
        assert set(snap) == {"time", "riders", "orders", "decision", "traffic"}
        assert len(snap["riders"]) == tr.meta["num_riders"]
        for r in snap["riders"]:
            assert r["status"] in RIDER_STATES and math.isfinite(r["x"]) and math.isfinite(r["y"])
        for o in snap["orders"]:
            assert o["state"] in ORDER_STATES
            assert {"est_ready", "actual_ready", "deadline", "placed_at"} <= set(o)
        assert len(snap["traffic"]) == len(tr.road_ends) and min(snap["traffic"]) >= 1.0
    # Heap operations are logged with the event that triggered them.
    ops = {h["op"] for h in tr.heap_ops}
    assert {"push", "update_key", "remove"} <= ops
    assert {h["trigger"] for h in tr.heap_ops} <= {"ORDER_PLACED", "FOOD_READY", "TRAFFIC_CHANGE", "RIDER_IDLE",
                                                   "DECISION", "RIDER_ARRIVED_RESTAURANT", "PICKUP", "DELIVERED"}
    sr = tr.sample_route
    assert sr["astar"]["cost"] == pytest.approx(sr["dijkstra"]["cost"])
    assert sr["astar"]["expanded"] <= sr["dijkstra"]["expanded"]
    assert tr.metrics["orders"] == len(tr.orders)


@pytest.mark.parametrize("method", ["dfpr", "nearest"])
def test_rider_positions_match_pickups_and_deliveries(traces, method) -> None:
    """Interpolated legs (including traffic re-timing) put riders exactly where they should be."""
    tr = traces[method]
    for o in tr.orders:
        if o["delivered_at"] is None:
            continue
        r = o["rider_id"]
        x, y, _ = tr.rider_position(r, o["picked_at"])
        assert (x, y) == pytest.approx(tr.coords[o["restaurant_node"]], abs=1e-6)
        x, y, _ = tr.rider_position(r, o["delivered_at"])
        assert (x, y) == pytest.approx(tr.coords[o["customer_node"]], abs=1e-6)
    assert any(leg["start"] < leg["end"] for leg in tr.legs)


def test_zero_orders(cfg) -> None:
    tr = record_run(cfg, "dfpr", "normal", seed=0, specs=[])
    assert tr.orders == [] and tr.decisions == []
    snap = tr.snapshot(tr.start + 600)
    assert snap["orders"] == [] and snap["decision"] is None
    assert all(r["status"] == "idle" for r in snap["riders"])


def test_order_never_ready_and_busy_riders(cfg) -> None:
    t0 = cfg["sim"]["start_hour"] * 3600
    specs = [
        # Food takes far longer than the whole day: picked up never, ends unserved.
        OrderSpec(0, restaurant_node=10, customer_node=20, placed_at=t0 + 60, est_prep_s=600,
                  actual_prep_s=10 * 3600, deadline=t0 + 60 + 2400),
        # Several more orders than riders, so riders are all busy for a while.
        *[OrderSpec(i, restaurant_node=10 + i, customer_node=300 + i, placed_at=t0 + 120, est_prep_s=300,
                    actual_prep_s=300, deadline=t0 + 2520) for i in range(1, 6)],
    ]
    for method in ["dfpr", "static_priority", "nearest"]:
        tr = record_run(cfg, method, "normal", seed=0, specs=specs, rider_starts=[0, 5])
        final = tr.snapshot(tr.meta["cutoff_s"] + 1)
        states = {o["id"]: o["state"] for o in final["orders"]}
        assert states[0] == "unserved"
        assert all(states[i] in {"delivered", "late"} for i in range(1, 6))
        # A moment when both riders are busy and orders still wait: queue is not empty but no decision is made.
        assert all(len(d["idle_riders"]) >= 1 for d in tr.decisions)


def test_dispatchers_rank_empty_when_nothing_to_do(cfg) -> None:
    from sim.city import build_city
    from sim.routing import Router
    from sim.simulator import Rider, SimView

    city = build_city(cfg["city"])
    view = SimView(city, city.graph, Router(city.graph), {}, {0: Rider(0, 0)}, {}, {}, 0.0, 3600.0)
    for m in METHODS:
        d = make_dispatcher(m, cfg)
        d.reset(view)
        assert d.rank(0.0, view) == []
