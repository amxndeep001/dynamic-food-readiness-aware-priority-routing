"""City generation, JSON round trip, traffic schedule, router."""

import numpy as np
import pytest

from ds.graph import Graph
from sim.city import City, build_city, is_connected
from sim.config import load_config, make_rngs
from sim.routing import Router
from sim.traffic import TrafficModel, apply_update

START, END = 10 * 3600.0, 22 * 3600.0


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


@pytest.fixture(scope="module")
def city(cfg: dict) -> City:
    return build_city(cfg["city"])


def test_city_is_connected_and_has_expected_shape(city: City, cfg: dict) -> None:
    c = cfg["city"]
    g = city.graph
    n = c["grid_size"]
    assert g.num_nodes == n * n
    assert is_connected(g)
    full_local = 2 * n * (n - 1)
    local = sum(1 for r in range(g.num_roads) if g.road_length[r] == c["spacing_m"])
    arterial = g.num_roads - local
    assert local == full_local - round(c["edge_removal_frac"] * full_local)
    assert arterial > 0
    assert len(city.restaurants) == c["num_restaurants"]
    assert len({r.node for r in city.restaurants}) == c["num_restaurants"]


def test_city_is_deterministic(cfg: dict) -> None:
    a, b = build_city(cfg["city"]), build_city(cfg["city"])
    assert a.graph.to_dict() == b.graph.to_dict()
    assert a.restaurants == b.restaurants
    other = build_city({**cfg["city"], "seed": 99})
    assert other.graph.to_dict() != a.graph.to_dict()


def test_json_round_trip(city: City, cfg: dict, tmp_path) -> None:
    path = tmp_path / "city.json"
    city.to_json(path)
    loaded = build_city({**cfg["city"], "map_file": str(path)})
    assert loaded.graph.to_dict() == city.graph.to_dict()
    assert loaded.restaurants == city.restaurants
    assert loaded.cluster_centers == city.cluster_centers

    # A bare edge list (a "real map") also loads; restaurants get generated.
    bare = tmp_path / "edges.json"
    city.graph.to_json(bare)
    assert Graph.from_json(bare).to_dict() == city.graph.to_dict()
    assert len(build_city({**cfg["city"], "map_file": str(bare)}).restaurants) == cfg["city"]["num_restaurants"]


def test_customer_sampling_returns_valid_nodes(city: City) -> None:
    rng = np.random.default_rng(0)
    nodes = [city.sample_customer_node(rng) for _ in range(500)]
    assert all(0 <= v < city.graph.num_nodes for v in nodes)
    assert len(set(nodes)) > 50  # spread out, not all piled on one node


def make_traffic(cfg: dict, city: City, seed: int) -> TrafficModel:
    return TrafficModel(cfg["traffic"], city.graph, make_rngs(seed)["traffic"], START, END)


def test_traffic_schedule_is_deterministic_and_valid(cfg: dict, city: City) -> None:
    a, b = make_traffic(cfg, city, 5), make_traffic(cfg, city, 5)
    assert a.schedule == b.schedule
    assert make_traffic(cfg, city, 6).schedule != a.schedule
    times = [u.time for u in a.schedule]
    assert times == sorted(times) and times[0] == START and times[-1] < END
    assert all(m >= 1.0 for u in a.schedule for m in u.multipliers.values())
    assert len(a.incidents) > 0


def test_traffic_peaks_are_slower(cfg: dict, city: City) -> None:
    t = make_traffic(cfg, city, 0)
    assert t.tod(10.5 * 3600) == pytest.approx(1.0)
    assert t.tod(12.5 * 3600) > 1.2
    assert t.tod(19.5 * 3600) > t.tod(16 * 3600)


def test_replaying_schedule_matches_direct_evaluation(cfg: dict, city: City) -> None:
    g = Graph.from_dict(city.graph.to_dict())
    t = make_traffic(cfg, city, 3)
    for upd in t.schedule:
        apply_update(g, upd)
        expected = t._multipliers_at(upd.time, g.num_roads)
        assert np.allclose(g.traffic, expected)


def test_router_astar_and_dijkstra_agree(city: City) -> None:
    g = Graph.from_dict(city.graph.to_dict())
    rng = np.random.default_rng(1)
    for r in range(g.num_roads):
        g.set_traffic(r, float(rng.uniform(1, 2.5)))
    ra, rd = Router(g, "astar"), Router(g, "dijkstra")
    for _ in range(50):
        s, d = (int(x) for x in rng.integers(g.num_nodes, size=2))
        a, b = ra.route(s, d), rd.route(s, d)
        assert a.cost == pytest.approx(b.cost)
        assert a.cost == pytest.approx(ra.cost(s, d))
