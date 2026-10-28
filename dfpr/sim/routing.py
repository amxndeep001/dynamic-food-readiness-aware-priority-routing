"""Single router used for rider movement by every dispatcher.

All methods move riders with the same traffic-aware shortest paths (A* by
default, Dijkstra selectable), so differences between methods come from the
dispatch rule alone, never from routing quality.
"""

from __future__ import annotations

from dataclasses import dataclass

from ds.graph import Graph
from ds.route_cache import RouteCache
from ds.shortest_path import astar, dijkstra, reconstruct_path


@dataclass(frozen=True)
class Route:
    """A path as parallel lists: ``nodes`` (k+1 entries) and ``roads`` (k entries)."""

    nodes: list[int]
    roads: list[int]
    cost: float


class Router:
    """Movement routing plus cached network-distance queries for dispatchers."""

    def __init__(self, graph: Graph, algorithm: str = "astar") -> None:
        if algorithm not in ("astar", "dijkstra"):
            raise ValueError(f"unknown routing algorithm {algorithm!r}")
        self.graph = graph
        self.algorithm = algorithm
        self.cache = RouteCache(graph)
        self.route_calls = 0

    def route(self, src: int, dst: int) -> Route:
        """Fastest path under *current* traffic, for actually moving a rider."""
        self.route_calls += 1
        if self.algorithm == "astar":
            cost, nodes, roads = astar(self.graph, src, dst, "time")
        else:
            tree = dijkstra(self.graph, src, "time", target=dst)
            nodes, roads = reconstruct_path(tree, dst)
            cost = tree.dist[dst]
        return Route(nodes, roads, cost)

    def cost(self, src: int, dst: int, mode: str = "time") -> float:
        """Shortest-path cost from src to dst, served from the route cache."""
        return self.cache.distance(src, dst, mode)

    def on_traffic_change(self, changes: dict[int, tuple[float, float]]) -> list[int]:
        """Forward a traffic change to the cache; returns invalidated sources."""
        return self.cache.on_traffic_change(changes)
