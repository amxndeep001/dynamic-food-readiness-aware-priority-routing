"""Simulator determinism and invariants."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dispatch.base import Dispatcher
from dispatch.fifo import FifoDispatcher
from ds.graph import Graph
from eval.invariants import check_invariants
from ds.shortest_path import dijkstra
from sim.city import City, Restaurant, build_city
from sim.config import load_config
from sim.orders import OrderSpec, OrderStatus
from sim.simulator import SimResult, Simulator, run_simulation
from sim.traffic import TrafficUpdate

# A short day keeps the tests fast while still covering the lunch peak.
SMALL = {"sim": {"start_hour": 11, "end_hour": 14, "drain_minutes": 90}, "riders": {"count": 15}}


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config(overrides=SMALL)


class NewestFirstDispatcher(Dispatcher):
    """Deliberately different rule, used to check that the world does not depend on the dispatcher."""

    name = "newest"

    def choose(self, now, view):
        if not view.idle or not view.eligible:
            return None
        return max(view.idle), max(view.eligible, key=lambda o: view.orders[o].placed_at)


@pytest.fixture(scope="module")
def fifo_peak(cfg: dict) -> SimResult:
    return run_simulation(cfg, FifoDispatcher(), "peak", seed=1, record_trace=True)


def comparable(result: SimResult) -> list:
    """Per-order records, which must be identical for identical inputs."""
    return [(o.id, o.status, o.rider_id, o.assigned_at, o.rider_arrived_at, o.picked_at, o.delivered_at,
             o.distance_m) for o in result.orders]


def test_same_seed_same_result(cfg: dict, fifo_peak: SimResult) -> None:
    again = run_simulation(cfg, FifoDispatcher(), "peak", seed=1, record_trace=True)
    assert comparable(again) == comparable(fifo_peak)
    assert again.trace == fifo_peak.trace
    assert again.rider_distance_m == fifo_peak.rider_distance_m


def test_different_seed_different_world(cfg: dict, fifo_peak: SimResult) -> None:
    other = run_simulation(cfg, FifoDispatcher(), "peak", seed=2)
    assert other.specs != fifo_peak.specs


def test_world_is_independent_of_dispatcher(cfg: dict, fifo_peak: SimResult) -> None:
    other = run_simulation(cfg, NewestFirstDispatcher(), "peak", seed=1)
    assert other.specs == fifo_peak.specs  # orders + true prep times
    assert other.traffic_schedule == fifo_peak.traffic_schedule
    assert other.rider_starts == fifo_peak.rider_starts
    # ... but the outcome differs, otherwise this test proves nothing.
    assert comparable(other) != comparable(fifo_peak)


def test_invariants_peak(fifo_peak: SimResult) -> None:
    check_invariants(fifo_peak)
    assert sum(o.status == OrderStatus.DELIVERED for o in fifo_peak.orders) > 0


def test_invariants_normal_and_other_dispatcher(cfg: dict) -> None:
    check_invariants(run_simulation(cfg, FifoDispatcher(), "normal", seed=4, record_trace=True))
    check_invariants(run_simulation(cfg, NewestFirstDispatcher(), "peak", seed=4, record_trace=True))


def test_dijkstra_routing_option(cfg: dict) -> None:
    alt = load_config(overrides={**SMALL, "routing": {"algorithm": "dijkstra"}})
    a = run_simulation(cfg, FifoDispatcher(), "normal", seed=3)
    b = run_simulation(alt, FifoDispatcher(), "normal", seed=3)
    # Same optimal costs; paths may differ only on exact ties.
    da = [o.delivered_at for o in a.orders]
    db = [o.delivered_at for o in b.orders]
    assert da == pytest.approx(db)


def test_overload_counts_unserved(cfg: dict) -> None:
    stress = load_config(overrides={**SMALL, "riders": {"count": 2}, "sim": {**SMALL["sim"], "drain_minutes": 10}})
    result = run_simulation(stress, FifoDispatcher(), "peak", seed=0, record_trace=True)
    check_invariants(result)
    assert sum(o.status == OrderStatus.UNSERVED for o in result.orders) > 0


def test_travel_never_faster_than_free_flow(cfg: dict, fifo_peak: SimResult) -> None:
    """Traffic multipliers are >= 1, so every delivery leg takes at least free-flow time."""
    g = build_city(cfg["city"]).graph
    for o in fifo_peak.orders:
        if o.status == OrderStatus.DELIVERED:
            free = dijkstra(g, o.restaurant_node, "free_time").dist[o.customer_node]
            assert o.delivered_at - o.picked_at >= free - 1e-6


def test_no_traffic_means_exact_free_flow_legs(cfg: dict) -> None:
    calm = load_config(overrides={**SMALL, "traffic": {"tod_profile": [[0, 1.0], [24, 1.0]], "incident_rate_per_hour": 0}})
    result = run_simulation(calm, FifoDispatcher(), "normal", seed=0)
    g = build_city(calm["city"]).graph
    for o in result.orders:
        if o.status == OrderStatus.DELIVERED:
            free = dijkstra(g, o.restaurant_node, "free_time").dist[o.customer_node]
            assert o.delivered_at - o.picked_at == pytest.approx(free)


def test_traffic_change_retimes_moving_rider_exactly(cfg: dict) -> None:
    """Hand-computed case on a 3-node line 0 -- 1 -- 2 (100 m roads at 10 m/s = 10 s each).

    t=0   rider at node 0 is sent to the restaurant at node 2 (expected arrival t=20).
    t=5   traffic: road 0 x2, road 1 x3. Half of road 0 is left -> 0.5 * 20 = 10 s,
          so node 1 at t=15, then road 1 takes 30 s -> arrival t=45.
          The old arrival event at t=20 must be ignored as stale.
    t=60  food ready -> pickup; the way back takes 30 + 20 = 50 s -> delivered at t=110.
    """
    g = Graph([(0, 0), (100, 0), (200, 0)])
    g.add_road(0, 1, 100, 10)
    g.add_road(1, 2, 100, 10)
    city = City(g, [Restaurant(0, 2, 60.0)])
    spec = OrderSpec(0, restaurant_node=2, customer_node=0, placed_at=0.0, est_prep_s=60.0,
                     actual_prep_s=60.0, deadline=1000.0)
    traffic = SimpleNamespace(schedule=[TrafficUpdate(5.0, {0: 2.0, 1: 3.0})])
    sim = Simulator(cfg, city, [spec], traffic, [0], FifoDispatcher(), 0.0, 100.0, record_trace=True)
    result = sim.run()
    o = result.orders[0]
    assert o.rider_arrived_at == pytest.approx(45.0)
    assert o.picked_at == pytest.approx(60.0)
    assert o.delivered_at == pytest.approx(110.0)
    assert o.distance_m == pytest.approx(400.0)
    assert result.event_counts["RIDER_ARRIVED_RESTAURANT"] == 1
