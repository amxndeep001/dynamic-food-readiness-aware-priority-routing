"""Cache of single-source shortest-path trees with traffic-aware invalidation.

Dispatchers repeatedly ask "how far is restaurant r from node x?". Running a
full Dijkstra from each restaurant / rider node once and reusing the tree turns
those queries into O(1) lookups. The cache is keyed by ``(source, mode)``.

Trees for "length" and "free_time" never go stale (they ignore traffic).
For "time" trees we invalidate only those that a traffic change could affect:

* A road got **slower**: distances can only change if the tree actually uses
  that road. Trees that do not use it keep exactly the same paths and costs.
* A road (u, v) got **faster**: distances can only change if the road now
  offers a shortcut, i.e. dist[u] + new_cost < dist[v] (or the reverse).
  This check is complete: if no changed road gives a shortcut, the old
  distances still satisfy every edge's triangle inequality, so they are still
  the shortest distances.
"""

from __future__ import annotations

from dataclasses import dataclass

from ds.graph import Graph
from ds.shortest_path import INF, ShortestPathTree, dijkstra, reconstruct_path


@dataclass
class _Entry:
    tree: ShortestPathTree
    roads: set[int]


class RouteCache:
    """Memoises Dijkstra trees per (source, mode) and counts hits / misses."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self._entries: dict[tuple[int, str], _Entry] = {}
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    def __len__(self) -> int:
        return len(self._entries)

    def tree(self, source: int, mode: str = "time") -> ShortestPathTree:
        """Shortest-path tree from ``source`` (computed on a miss)."""
        key = (source, mode)
        entry = self._entries.get(key)
        if entry is not None:
            self.hits += 1
            return entry.tree
        self.misses += 1
        t = dijkstra(self.graph, source, mode)
        self._entries[key] = _Entry(t, t.roads_used())
        return t

    def distance(self, source: int, target: int, mode: str = "time") -> float:
        """Shortest cost from source to target in the given mode."""
        return self.tree(source, mode).dist[target]

    def path(self, source: int, target: int, mode: str = "time") -> tuple[list[int], list[int]]:
        """``(nodes, roads)`` of the shortest path from source to target."""
        return reconstruct_path(self.tree(source, mode), target)

    def on_traffic_change(self, changes: dict[int, tuple[float, float]]) -> list[int]:
        """Invalidate "time" trees affected by traffic changes.

        ``changes`` maps road_id -> (old_multiplier, new_multiplier). The graph
        must already hold the new multipliers. Returns the source nodes whose
        trees were dropped, so callers can recompute only what depends on them.
        """
        slower = {r for r, (old, new) in changes.items() if new > old}
        faster = [r for r, (old, new) in changes.items() if new < old]
        cost = self.graph.costs("time")
        dropped: list[int] = []
        for key in list(self._entries):
            source, mode = key
            if mode != "time":
                continue
            entry = self._entries[key]
            if self._affected(entry, slower, faster, cost):
                del self._entries[key]
                dropped.append(source)
        self.invalidations += len(dropped)
        return dropped

    def _affected(self, entry: _Entry, slower: set[int], faster: list[int], cost: list[float]) -> bool:
        if not slower.isdisjoint(entry.roads):
            return True
        dist = entry.tree.dist
        for r in faster:
            u, v = self.graph.road_ends[r]
            c = cost[r]
            # A tiny tolerance avoids invalidating on floating-point ties.
            if dist[u] != INF and dist[u] + c < dist[v] - 1e-9:
                return True
            if dist[v] != INF and dist[v] + c < dist[u] - 1e-9:
                return True
        return False

    def clear(self) -> None:
        self._entries.clear()
