"""Weighted road graph stored as an adjacency list.

Model
-----
* Nodes are intersections with planar coordinates in metres.
* A *road* is an undirected street segment with a length and a free-flow speed.
  It is stored as two directed ``Edge`` entries (one in each endpoint's list)
  that share the same ``road_id``, so traffic on a road affects both directions.
* Traffic is a per-road multiplier >= 1 on the free-flow travel time. Keeping it
  >= 1 means "traffic only ever slows you down", which is also what makes the
  A* heuristic (straight-line distance / max free-flow speed) admissible.

Three cost modes are supported everywhere:
    "length"     metres                      (traffic independent)
    "free_time"  seconds at free-flow speed  (traffic independent)
    "time"       free_time * traffic multiplier (changes over time)

Per-mode cost arrays are kept as plain lists indexed by road id so the inner
loop of Dijkstra does a single list lookup per edge.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import NamedTuple

COST_MODES = ("length", "free_time", "time")


class Edge(NamedTuple):
    """Directed half of a road: destination node and the shared road id."""

    to: int
    road_id: int


class Graph:
    """Undirected road network with per-road traffic multipliers."""

    def __init__(self, coords: list[tuple[float, float]]) -> None:
        self.coords: list[tuple[float, float]] = [(float(x), float(y)) for x, y in coords]
        self.adj: list[list[Edge]] = [[] for _ in self.coords]
        self.road_ends: list[tuple[int, int]] = []
        self.road_length: list[float] = []
        self.road_free_time: list[float] = []
        self.traffic: list[float] = []
        self._time_cost: list[float] = []  # free_time * traffic, kept in sync by set_traffic
        self._max_speed = 0.0

    # ------------------------------------------------------------ construction
    def add_road(self, u: int, v: int, length_m: float, speed_mps: float) -> int:
        """Add an undirected road and return its id.

        Raises ValueError if the length is shorter than the straight-line
        distance between the endpoints: such a road would break A*'s
        admissible heuristic (and is physically impossible).
        """
        if u == v:
            raise ValueError("self-loops are not allowed")
        if speed_mps <= 0 or length_m <= 0:
            raise ValueError("length and speed must be positive")
        if length_m < self.euclid(u, v) - 1e-6:
            raise ValueError(f"road {u}-{v} shorter than straight-line distance")
        rid = len(self.road_ends)
        self.road_ends.append((u, v))
        self.road_length.append(float(length_m))
        free_time = length_m / speed_mps
        self.road_free_time.append(free_time)
        self.traffic.append(1.0)
        self._time_cost.append(free_time)
        self._max_speed = max(self._max_speed, speed_mps)
        self.adj[u].append(Edge(v, rid))
        self.adj[v].append(Edge(u, rid))
        return rid

    # ----------------------------------------------------------------- queries
    @property
    def num_nodes(self) -> int:
        return len(self.coords)

    @property
    def num_roads(self) -> int:
        return len(self.road_ends)

    def euclid(self, u: int, v: int) -> float:
        """Straight-line distance between two nodes in metres."""
        (x1, y1), (x2, y2) = self.coords[u], self.coords[v]
        return math.hypot(x1 - x2, y1 - y2)

    def max_speed(self) -> float:
        """Fastest free-flow speed of any road (m/s); used by the A* heuristic."""
        return self._max_speed

    def costs(self, mode: str) -> list[float]:
        """Per-road cost list for ``mode`` (shared, do not mutate)."""
        if mode == "time":
            return self._time_cost
        if mode == "length":
            return self.road_length
        if mode == "free_time":
            return self.road_free_time
        raise ValueError(f"unknown cost mode {mode!r}")

    def road_between(self, u: int, v: int, mode: str = "time") -> int:
        """Id of the cheapest road joining u and v (raises KeyError if none)."""
        cost = self.costs(mode)
        best = None
        for e in self.adj[u]:
            if e.to == v and (best is None or cost[e.road_id] < cost[best]):
                best = e.road_id
        if best is None:
            raise KeyError(f"no road between {u} and {v}")
        return best

    def midpoint(self, road_id: int) -> tuple[float, float]:
        u, v = self.road_ends[road_id]
        (x1, y1), (x2, y2) = self.coords[u], self.coords[v]
        return (x1 + x2) / 2, (y1 + y2) / 2

    # ----------------------------------------------------------------- traffic
    def set_traffic(self, road_id: int, multiplier: float) -> None:
        """Set a road's traffic multiplier (must be >= 1, see module docstring)."""
        if multiplier < 1.0 - 1e-12:
            raise ValueError("traffic multiplier must be >= 1")
        self.traffic[road_id] = multiplier
        self._time_cost[road_id] = self.road_free_time[road_id] * multiplier

    # ------------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        """Serialisable edge-list form: nodes [id, x, y], edges [u, v, length_m, speed_mps]."""
        return {
            "nodes": [[i, x, y] for i, (x, y) in enumerate(self.coords)],
            "edges": [
                [u, v, self.road_length[r], self.road_length[r] / self.road_free_time[r]]
                for r, (u, v) in enumerate(self.road_ends)
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Graph:
        """Build a graph from the edge-list form. Node ids must be 0..n-1."""
        nodes = sorted(data["nodes"], key=lambda n: n[0])
        if [n[0] for n in nodes] != list(range(len(nodes))):
            raise ValueError("node ids must be the contiguous range 0..n-1")
        g = cls([(x, y) for _, x, y in nodes])
        for u, v, length_m, speed_mps in data["edges"]:
            g.add_road(int(u), int(v), float(length_m), float(speed_mps))
        return g

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict()))

    @classmethod
    def from_json(cls, path: str | Path) -> Graph:
        """Load a road network from a JSON edge list (lets a real map be swapped in)."""
        return cls.from_dict(json.loads(Path(path).read_text()))
