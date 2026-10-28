"""Dijkstra and A* on ``Graph``, both using our own ``MinHeap``.

Both use *lazy deletion*: instead of a decrease-key operation, a node is pushed
again whenever its tentative distance improves, and stale heap entries
(whose distance is larger than the best known one) are skipped when popped.
The heap therefore holds at most O(E) entries, giving O((V + E) log V) time.

Cost modes ("length", "free_time", "time") are described in ``ds/graph.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ds.graph import Graph
from ds.min_heap import MinHeap

INF = math.inf


@dataclass
class ShortestPathTree:
    """Result of single-source Dijkstra.

    ``dist[v]`` is the shortest cost from ``source`` to v (INF if unreachable).
    ``parent[v]`` / ``parent_road[v]`` describe the last hop on that path
    (-1 for the source and unreachable nodes). If Dijkstra was stopped early at
    a target, only nodes settled before the target have final distances.
    """

    source: int
    mode: str
    dist: list[float]
    parent: list[int]
    parent_road: list[int]

    def roads_used(self) -> set[int]:
        """Set of road ids that appear in the tree (used for cache invalidation)."""
        return {r for r in self.parent_road if r >= 0}


def dijkstra(graph: Graph, source: int, mode: str = "time", target: int | None = None,
             visit_order: list[int] | None = None) -> ShortestPathTree:
    """Single-source shortest paths from ``source``. O((V + E) log V).

    If ``target`` is given, the search stops as soon as the target is settled.
    If ``visit_order`` is a list, settled nodes are appended to it in order
    (used by the demo app to visualise the search; off by default).
    """
    n = graph.num_nodes
    cost = graph.costs(mode)
    dist = [INF] * n
    parent = [-1] * n
    parent_road = [-1] * n
    settled = [False] * n
    dist[source] = 0.0
    frontier: MinHeap[int] = MinHeap()
    frontier.push(0.0, source)

    while frontier:
        d, u = frontier.pop()
        if settled[u]:
            continue  # stale entry left behind by lazy deletion
        settled[u] = True
        if visit_order is not None:
            visit_order.append(u)
        if u == target:
            break
        for to, rid in graph.adj[u]:
            nd = d + cost[rid]
            if nd < dist[to]:
                dist[to] = nd
                parent[to] = u
                parent_road[to] = rid
                frontier.push(nd, to)

    return ShortestPathTree(source, mode, dist, parent, parent_road)


def reconstruct_path(tree: ShortestPathTree, target: int) -> tuple[list[int], list[int]]:
    """Return ``(nodes, roads)`` from the tree's source to ``target``.

    ``nodes`` has one more element than ``roads``. Raises ValueError if the
    target is unreachable.
    """
    if tree.dist[target] == INF:
        raise ValueError(f"node {target} unreachable from {tree.source}")
    nodes = [target]
    roads: list[int] = []
    v = target
    while v != tree.source:
        roads.append(tree.parent_road[v])
        v = tree.parent[v]
        nodes.append(v)
    nodes.reverse()
    roads.reverse()
    return nodes, roads


def astar(graph: Graph, source: int, target: int, mode: str = "time",
          visit_order: list[int] | None = None) -> tuple[float, list[int], list[int]]:
    """Point-to-point shortest path with A*. Returns ``(cost, nodes, roads)``.

    Heuristic h(v) = straight-line distance(v, target), divided by the maximum
    free-flow speed for the time-based modes. It never overestimates because
    every road is at least as long as the straight line between its endpoints,
    no road is faster than the max speed, and traffic multipliers are >= 1.
    An admissible + consistent heuristic means the first time we settle the
    target, its cost is optimal (same answer as Dijkstra, fewer nodes explored).
    """
    cost = graph.costs(mode)
    scale = 1.0 if mode == "length" else 1.0 / graph.max_speed()
    tx, ty = graph.coords[target]

    def h(v: int) -> float:
        x, y = graph.coords[v]
        return math.hypot(x - tx, y - ty) * scale

    n = graph.num_nodes
    g = [INF] * n
    parent = [-1] * n
    parent_road = [-1] * n
    closed = [False] * n
    g[source] = 0.0
    frontier: MinHeap[int] = MinHeap()
    frontier.push(h(source), source)

    while frontier:
        _, u = frontier.pop()
        if closed[u]:
            continue
        closed[u] = True
        if visit_order is not None:
            visit_order.append(u)
        if u == target:
            tree = ShortestPathTree(source, mode, g, parent, parent_road)
            nodes, roads = reconstruct_path(tree, target)
            return g[target], nodes, roads
        for to, rid in graph.adj[u]:
            ng = g[u] + cost[rid]
            if ng < g[to]:
                g[to] = ng
                parent[to] = u
                parent_road[to] = rid
                frontier.push(ng + h(to), to)

    raise ValueError(f"node {target} unreachable from {source}")


def path_cost(graph: Graph, roads: list[int], mode: str = "time") -> float:
    """Total cost of a path given as a list of road ids."""
    cost = graph.costs(mode)
    return sum(cost[r] for r in roads)
