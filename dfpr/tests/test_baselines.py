"""Baseline dispatchers: hand-made decision cases plus full-run invariants."""

from __future__ import annotations

import pytest

from dispatch import METHODS, make_dispatcher
from dispatch.nearest import NearestOrderFirst
from dispatch.nearest_time import NearestTimePair
from dispatch.shortest_path_dispatch import ShortestPathDispatch
from dispatch.static_priority import StaticPriority
from ds.graph import Graph
from eval.invariants import check_invariants
from sim.city import City, Restaurant
from sim.config import load_config
from sim.events import Event, EventType
from sim.orders import Order
from sim.routing import Router
from sim.simulator import Rider, SimView, run_simulation

SMALL = {"sim": {"start_hour": 11, "end_hour": 14, "drain_minutes": 90}, "riders": {"count": 15}}


def toy_view() -> SimView:
    """Toy map where straight-line and road distance disagree.

    Nodes: 0 (0,0), 1 (100,0), 2 (0,1000), 3 (100,1000), 4 (300,0), 5 (300,500).
    Roads: 0-2 (1000 m), 2-3 (100 m), 3-1 (1000 m), 0-4 (300 m), 4-5 (500 m).

    From node 0, restaurant node 1 is 100 m away as the crow flies but 2100 m
    by road (0-2-3-1); restaurant node 4 is 300 m by road.
    """
    g = Graph([(0, 0), (100, 0), (0, 1000), (100, 1000), (300, 0), (300, 500)])
    g.add_road(0, 2, 1000, 10)
    g.add_road(2, 3, 100, 10)
    g.add_road(3, 1, 1000, 10)
    g.add_road(0, 4, 300, 10)
    g.add_road(4, 5, 500, 10)
    city = City(g, [Restaurant(0, 1, 600), Restaurant(1, 4, 600)])
    riders = {0: Rider(0, node=0)}
    return SimView(city, g, Router(g), {}, riders, {}, {0: 0.0}, 0.0, 3600.0)


def add_order(view: SimView, oid: int, restaurant: int, customer: int, placed: float = 0.0,
              deadline: float = 2400.0) -> None:
    view.orders[oid] = Order(oid, restaurant, customer, placed, 600.0, deadline)
    view.eligible[oid] = None


def test_nearest_uses_road_distance_not_straight_line() -> None:
    view = toy_view()
    add_order(view, 0, restaurant=1, customer=0)  # 100 m crow-flies, 2100 m by road
    add_order(view, 1, restaurant=4, customer=0)  # 300 m by road
    assert NearestOrderFirst().choose(0.0, view) == (0, 1)


def test_nearest_breaks_ties_by_placement_time() -> None:
    view = toy_view()
    add_order(view, 7, restaurant=4, customer=5, placed=50.0)
    add_order(view, 3, restaurant=4, customer=0, placed=10.0)
    assert NearestOrderFirst().choose(0.0, view) == (0, 3)


def test_shortest_path_minimises_total_length() -> None:
    view = toy_view()
    # Same restaurant (300 m away); customer at 0 adds 300 m, customer at 5 adds 500 m.
    add_order(view, 0, restaurant=4, customer=5)
    add_order(view, 1, restaurant=4, customer=0)
    assert ShortestPathDispatch().choose(0.0, view) == (0, 1)


def test_shortest_path_can_prefer_farther_restaurant() -> None:
    view = toy_view()
    view.riders[0].node = 2
    # Restaurant 4 is 1300 m away, then 1300 m back to customer 2: 2600 m total.
    # Restaurant 1 is 1100 m away, then 2100 m to customer 0: 3200 m total.
    add_order(view, 0, restaurant=1, customer=0)
    add_order(view, 1, restaurant=4, customer=2)
    assert NearestOrderFirst().choose(0.0, view) == (0, 0)
    assert ShortestPathDispatch().choose(0.0, view) == (0, 1)


def test_static_priority_is_edf_and_never_recomputed() -> None:
    view = toy_view()
    sp = StaticPriority()
    sp.reset(view)
    for oid, deadline in [(0, 3000.0), (1, 1000.0), (2, 2000.0)]:
        add_order(view, oid, restaurant=4, customer=0, deadline=deadline)
        sp.on_event(Event(0.0, EventType.ORDER_PLACED, order_id=oid), view)
    priorities = {oid: sp.heap.priority(oid) for oid in view.eligible}
    # Events that make DFPR recompute must leave the static ranking untouched.
    sp.on_event(Event(10.0, EventType.FOOD_READY, order_id=0), view)
    sp.on_event(Event(20.0, EventType.TRAFFIC_CHANGE), view)
    assert {oid: sp.heap.priority(oid) for oid in view.eligible} == priorities

    picked = []
    for _ in range(3):
        rider, oid = sp.choose(0.0, view)
        picked.append(oid)
        del view.eligible[oid]
    assert picked == [1, 2, 0]


def test_static_priority_sends_nearest_idle_rider() -> None:
    view = toy_view()
    view.riders[1] = Rider(1, node=5)  # 500 m from restaurant 4
    view.riders[0].node = 2  # 1300 m from restaurant 4
    view.idle[1] = 0.0
    sp = StaticPriority()
    sp.reset(view)
    add_order(view, 0, restaurant=4, customer=0)
    sp.on_event(Event(0.0, EventType.ORDER_PLACED, order_id=0), view)
    assert sp.choose(0.0, view) == (1, 0)


def test_nearest_time_uses_traffic_and_nearest_rider() -> None:
    view = toy_view()
    add_order(view, 0, restaurant=1, customer=0)  # 2100 m via 0-2-3-1: 210 s free-flow
    add_order(view, 1, restaurant=4, customer=0)  # 300 m: 30 s free-flow
    assert NearestTimePair().choose(0.0, view) == (0, 1)
    # A jam on road 0-4 (x10 -> 300 s) makes restaurant 1 the faster one to reach,
    # although it is still 7x farther in metres.
    view.graph.set_traffic(view.graph.road_between(0, 4), 10.0)
    view.router.cache.on_traffic_change({view.graph.road_between(0, 4): (1.0, 10.0)})
    assert NearestTimePair().choose(0.0, view) == (0, 0)
    assert NearestOrderFirst().choose(0.0, view) == (0, 1)
    # With a second idle rider standing at restaurant 4, that pair (0 s) wins.
    view.riders[1] = Rider(1, node=4)
    view.idle[1] = 5.0
    assert NearestTimePair().choose(0.0, view) == (1, 1)


@pytest.mark.parametrize("method", ["nearest", "shortest_path", "static_priority", "nearest_time"])
def test_baselines_full_run(method: str) -> None:
    cfg = load_config(overrides=SMALL)
    a = run_simulation(cfg, method, "peak", seed=2, record_trace=True)
    check_invariants(a)
    b = run_simulation(cfg, method, "peak", seed=2)
    assert [o.delivered_at for o in a.orders] == [o.delivered_at for o in b.orders]
    assert a.cache_stats["hits"] > 0  # distance queries are served from the cache


def test_registry_has_all_methods() -> None:
    cfg = load_config()
    for name in ("fifo", "nearest", "shortest_path", "static_priority"):
        assert make_dispatcher(name, cfg).name == name
    assert set(METHODS) >= {"nearest", "shortest_path", "static_priority"}
