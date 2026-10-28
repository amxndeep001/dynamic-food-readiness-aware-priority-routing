"""Synthetic city: road network, restaurants and customer locations.

The default city is a grid (Manhattan-like local streets) with a few faster
diagonal arterials and some streets randomly closed, so shortest paths are not
trivially "go right then go up". A real map can be used instead by pointing
``city.map_file`` at a JSON edge list (see ``Graph.to_dict`` for the format,
optionally with "restaurants" and "clusters" keys).

The city is generated from its own fixed seed (``city.seed``), separate from the
per-run seed. That models one fixed city in which days (runs) differ only in
demand, prep noise, traffic and rider starts.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ds.graph import Graph

KMH = 1000 / 3600  # km/h -> m/s


@dataclass(frozen=True)
class Restaurant:
    """A restaurant at a graph node with a typical (mean) prep time in seconds."""

    id: int
    node: int
    mean_prep_s: float


@dataclass
class City:
    """Road graph plus where restaurants and customers are."""

    graph: Graph
    restaurants: list[Restaurant]
    cluster_centers: list[tuple[float, float]] = field(default_factory=list)
    cluster_sigma_m: float = 600.0
    cluster_frac: float = 0.0

    def __post_init__(self) -> None:
        self._xy = np.array(self.graph.coords)
        self._lo = self._xy.min(axis=0)
        self._hi = self._xy.max(axis=0)

    def nearest_node(self, x: float, y: float) -> int:
        """Node closest to a point (brute force O(V); only used while generating demand)."""
        d2 = (self._xy[:, 0] - x) ** 2 + (self._xy[:, 1] - y) ** 2
        return int(np.argmin(d2))

    def sample_customer_node(self, rng: np.random.Generator) -> int:
        """Customer location: Gaussian residential clusters mixed with uniform demand."""
        if self.cluster_centers and rng.random() < self.cluster_frac:
            cx, cy = self.cluster_centers[rng.integers(len(self.cluster_centers))]
            x, y = rng.normal(cx, self.cluster_sigma_m), rng.normal(cy, self.cluster_sigma_m)
        else:
            x, y = rng.uniform(self._lo[0], self._hi[0]), rng.uniform(self._lo[1], self._hi[1])
        x = float(np.clip(x, self._lo[0], self._hi[0]))
        y = float(np.clip(y, self._lo[1], self._hi[1]))
        return self.nearest_node(x, y)

    # ------------------------------------------------------------- persistence
    def to_json(self, path: str | Path) -> None:
        data = self.graph.to_dict()
        data["restaurants"] = [[r.node, r.mean_prep_s] for r in self.restaurants]
        data["clusters"] = [list(c) for c in self.cluster_centers]
        data["cluster_sigma_m"] = self.cluster_sigma_m
        data["cluster_frac"] = self.cluster_frac
        Path(path).write_text(json.dumps(data))

    @classmethod
    def from_json(cls, path: str | Path, cfg: dict) -> City:
        """Load a map. Missing restaurants/clusters are generated from ``cfg``."""
        data = json.loads(Path(path).read_text())
        graph = Graph.from_dict(data)
        rng = np.random.default_rng(cfg["seed"])
        if "restaurants" in data:
            restaurants = [Restaurant(i, int(n), float(p)) for i, (n, p) in enumerate(data["restaurants"])]
        else:
            restaurants = _place_restaurants(graph, cfg, rng)
        clusters = [tuple(c) for c in data.get("clusters", [])] or _cluster_centers(graph, cfg, rng)
        return cls(
            graph,
            restaurants,
            clusters,
            data.get("cluster_sigma_m", cfg["cluster_sigma_m"]),
            data.get("cluster_frac", cfg["cluster_frac"]),
        )


def build_city(cfg: dict) -> City:
    """Build the city described by the ``city`` config section."""
    if cfg.get("map_file"):
        return City.from_json(cfg["map_file"], cfg)
    return generate_grid_city(cfg, np.random.default_rng(cfg["seed"]))


def generate_grid_city(cfg: dict, rng: np.random.Generator) -> City:
    """Grid road network with diagonal arterials and a few closed streets.

    Node id = row * n + col, coordinates (col * spacing, row * spacing).
    """
    n = cfg["grid_size"]
    s = float(cfg["spacing_m"])
    coords = [(c * s, r * s) for r in range(n) for c in range(n)]
    nid = lambda r, c: r * n + c  # noqa: E731

    local: list[tuple[int, int]] = []
    for r in range(n):
        for c in range(n):
            if c + 1 < n:
                local.append((nid(r, c), nid(r, c + 1)))
            if r + 1 < n:
                local.append((nid(r, c), nid(r + 1, c)))

    arterial = _diagonal_arterials(n, cfg["num_arterials"], rng)

    # Close a fraction of local streets, but never one that would cut the city
    # in two: an unreachable customer would make the experiment meaningless.
    target = int(round(cfg["edge_removal_frac"] * len(local)))
    order = rng.permutation(len(local))
    kept = set(range(len(local)))
    removed = 0
    for i in order:
        if removed >= target:
            break
        kept.discard(int(i))
        if _connected(n * n, [local[j] for j in kept] + arterial):
            removed += 1
        else:
            kept.add(int(i))

    graph = Graph(coords)
    for j in sorted(kept):
        u, v = local[j]
        graph.add_road(u, v, s, cfg["local_speed_kmh"] * KMH)
    for u, v in arterial:
        graph.add_road(u, v, s * math.sqrt(2), cfg["arterial_speed_kmh"] * KMH)

    return City(
        graph,
        _place_restaurants(graph, cfg, rng),
        _cluster_centers(graph, cfg, rng),
        float(cfg["cluster_sigma_m"]),
        float(cfg["cluster_frac"]),
    )


def _diagonal_arterials(n: int, k: int, rng: np.random.Generator) -> list[tuple[int, int]]:
    """Segments of ``k`` distinct diagonal lines through the grid's central band."""
    candidates = [(+1, off) for off in range(-(n // 3), n // 3 + 1)]  # c - r = off
    candidates += [(-1, s) for s in range(n - 1 - n // 3, n - 1 + n // 3 + 1)]  # c + r = s
    picks = rng.choice(len(candidates), size=min(k, len(candidates)), replace=False)
    segs: set[tuple[int, int]] = set()
    for p in picks:
        direction, off = candidates[int(p)]
        for r in range(n - 1):
            c = r + off if direction == +1 else off - r
            c2 = c + direction
            if 0 <= c < n and 0 <= c2 < n:
                segs.add((r * n + c, (r + 1) * n + c2))
    return sorted(segs)


def _connected(num_nodes: int, edges: list[tuple[int, int]]) -> bool:
    adj: list[list[int]] = [[] for _ in range(num_nodes)]
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)
    seen = [False] * num_nodes
    seen[0] = True
    queue = deque([0])
    count = 1
    while queue:
        u = queue.popleft()
        for v in adj[u]:
            if not seen[v]:
                seen[v] = True
                count += 1
                queue.append(v)
    return count == num_nodes


def _place_restaurants(graph: Graph, cfg: dict, rng: np.random.Generator) -> list[Restaurant]:
    k = min(cfg["num_restaurants"], graph.num_nodes)
    nodes = rng.choice(graph.num_nodes, size=k, replace=False)
    lo, hi = cfg["prep_mean_min_range"]
    return [Restaurant(i, int(node), float(rng.uniform(lo, hi) * 60)) for i, node in enumerate(nodes)]


def _cluster_centers(graph: Graph, cfg: dict, rng: np.random.Generator) -> list[tuple[float, float]]:
    xy = np.array(graph.coords)
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    # Keep cluster centres away from the border so the Gaussian is not mostly clipped.
    margin = 0.15 * (hi - lo)
    return [
        (float(rng.uniform(lo[0] + margin[0], hi[0] - margin[0])), float(rng.uniform(lo[1] + margin[1], hi[1] - margin[1])))
        for _ in range(cfg["num_customer_clusters"])
    ]


def is_connected(graph: Graph) -> bool:
    """True if every node can reach every other node."""
    return _connected(graph.num_nodes, graph.road_ends)
