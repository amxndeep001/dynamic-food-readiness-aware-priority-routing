"""Dijkstra vs networkx, A* vs Dijkstra, and route-cache invalidation."""

import math
import random

import networkx as nx
import numpy as np
import pytest

from ds.graph import Graph
from ds.route_cache import RouteCache
from ds.shortest_path import INF, astar, dijkstra, path_cost, reconstruct_path
from sim.city import generate_grid_city
from sim.config import load_config


def random_graph(seed: int, n: int = 60, extra: int = 120) -> Graph:
    """Random connected graph: a random spanning tree plus extra roads.

    Road lengths are >= straight-line distance (as Graph requires) and speeds
    vary, so the three cost modes give genuinely different shortest paths.
    """
    rng = random.Random(seed)
    g = Graph([(rng.uniform(0, 5000), rng.uniform(0, 5000)) for _ in range(n)])
    seen: set[tuple[int, int]] = set()

    def add(u: int, v: int) -> None:
        if u == v or (min(u, v), max(u, v)) in seen:
            return
        seen.add((min(u, v), max(u, v)))
        g.add_road(u, v, g.euclid(u, v) * rng.uniform(1.0, 1.6) + 1.0, rng.uniform(5, 15))

    for v in range(1, n):
        add(v, rng.randrange(v))
    for _ in range(extra):
        add(rng.randrange(n), rng.randrange(n))
    for r in range(g.num_roads):
        g.set_traffic(r, rng.uniform(1.0, 3.0))
    return g


def to_networkx(g: Graph, mode: str) -> nx.Graph:
    cost = g.costs(mode)
    G = nx.Graph()
    G.add_nodes_from(range(g.num_nodes))
    for r, (u, v) in enumerate(g.road_ends):
        G.add_edge(u, v, weight=cost[r])
    return G


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("mode", ["length", "free_time", "time"])
def test_dijkstra_matches_networkx(seed: int, mode: str) -> None:
    g = random_graph(seed)
    G = to_networkx(g, mode)
    src = seed % g.num_nodes
    tree = dijkstra(g, src, mode)
    expected = nx.single_source_dijkstra_path_length(G, src)
    for v in range(g.num_nodes):
        assert tree.dist[v] == pytest.approx(expected[v], rel=1e-9, abs=1e-9)
        nodes, roads = reconstruct_path(tree, v)
        assert nodes[0] == src and nodes[-1] == v and len(nodes) == len(roads) + 1
        assert path_cost(g, roads, mode) == pytest.approx(tree.dist[v], rel=1e-9, abs=1e-9)


def test_unreachable_node() -> None:
    g = Graph([(0, 0), (100, 0), (500, 500)])
    g.add_road(0, 1, 100, 10)
    tree = dijkstra(g, 0, "length")
    assert tree.dist[2] == INF
    with pytest.raises(ValueError):
        reconstruct_path(tree, 2)
    with pytest.raises(ValueError):
        astar(g, 0, 2, "length")


def test_early_stop_target_is_exact() -> None:
    g = random_graph(3)
    full = dijkstra(g, 0, "time")
    for t in range(g.num_nodes):
        assert dijkstra(g, 0, "time", target=t).dist[t] == pytest.approx(full.dist[t])


@pytest.mark.parametrize("mode", ["length", "time"])
def test_astar_matches_dijkstra_on_city_with_traffic(mode: str) -> None:
    cfg = load_config()["city"]
    city = generate_grid_city(cfg, np.random.default_rng(1))
    g = city.graph
    rng = random.Random(7)
    for r in range(g.num_roads):
        g.set_traffic(r, rng.uniform(1.0, 3.0))
    for _ in range(200):
        s, t = rng.randrange(g.num_nodes), rng.randrange(g.num_nodes)
        cost, nodes, roads = astar(g, s, t, mode)
        assert cost == pytest.approx(dijkstra(g, s, mode).dist[t], rel=1e-9, abs=1e-9)
        assert nodes[0] == s and nodes[-1] == t
        assert path_cost(g, roads, mode) == pytest.approx(cost, rel=1e-9, abs=1e-9)


def test_astar_on_random_graphs() -> None:
    for seed in range(10):
        g = random_graph(seed)
        for t in range(0, g.num_nodes, 7):
            assert astar(g, 0, t)[0] == pytest.approx(dijkstra(g, 0).dist[t])


def test_graph_rejects_road_shorter_than_straight_line() -> None:
    g = Graph([(0, 0), (300, 400)])
    with pytest.raises(ValueError):
        g.add_road(0, 1, 499.0, 10)
    with pytest.raises(ValueError):
        g.set_traffic(g.add_road(0, 1, 500.0, 10), 0.5)


def test_route_cache_hits_and_misses() -> None:
    g = random_graph(1)
    cache = RouteCache(g)
    cache.distance(0, 5)
    cache.distance(0, 9)
    cache.distance(0, 9, "length")
    assert (cache.hits, cache.misses) == (1, 2)


@pytest.mark.parametrize("seed", range(5))
def test_route_cache_stays_correct_under_traffic_changes(seed: int) -> None:
    g = random_graph(seed)
    cache = RouteCache(g)
    rng = random.Random(seed)
    sources = list(range(0, g.num_nodes, 4))
    for _ in range(30):
        for s in sources:
            cache.tree(s, "time")
            cache.tree(s, "length")
        # Random batch of changes, some up, some down (never below 1).
        changes = {}
        for r in rng.sample(range(g.num_roads), 8):
            old = g.traffic[r]
            new = max(1.0, old * rng.uniform(0.5, 1.8))
            g.set_traffic(r, new)
            changes[r] = (old, new)
        cache.on_traffic_change(changes)
        for s in sources:
            fresh = dijkstra(g, s, "time").dist
            cached = cache.tree(s, "time").dist
            assert all(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9) for a, b in zip(fresh, cached))
    # Some trees must have survived, otherwise invalidation is just "clear all".
    assert cache.hits > len(sources) * 30
    assert cache.invalidations > 0
