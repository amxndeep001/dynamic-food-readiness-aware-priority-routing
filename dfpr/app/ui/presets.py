"""One-click presentation scenarios.

Each preset is just a set of simulator parameters (and, for "Readiness
matters", a scripted set of orders). Nothing is tuned to make DFPR look good:
the app shows the real outcome of each run, including when DFPR does worse.
"""

from __future__ import annotations

from ds.shortest_path import dijkstra
from sim.city import build_city
from sim.orders import OrderSpec

BASE = {
    "seed": 7, "grid": 25, "riders": 18, "rate": 40.0, "peak": False, "sigma": 0.3, "traffic": True,
    "method": "dfpr", "start_hour": 11.0, "hours": 3.0, "incidents": [], "peaks": None, "scripted": None,
}

PRESETS: dict[str, dict] = {
    "Small and clear": {
        "params": {"grid": 8, "riders": 3, "rate": 16.0, "start_hour": 12.0, "hours": 1.0, "traffic": False,
                   "seed": 3},
        "compare": "nearest",
        "speed": 30,
        "caption": "3 riders, about 15 orders in one hour, an 8x8 city and no traffic. Step through decisions one at a "
                   "time: watch the priority queue on the right and read *why* each order goes first.",
    },
    "Readiness matters": {
        "params": {"grid": 10, "riders": 2, "rate": 0.0, "start_hour": 12.0, "hours": 1.0, "traffic": False,
                   "sigma": 0.0, "scripted": "readiness"},
        "compare": "nearest",
        "speed": 30,
        "caption": "A constructed situation: each rider stands next to a restaurant whose food needs 14 more "
                   "minutes, while another restaurant a bit farther away has food ready in 2 minutes. "
                   "Nearest-first sends the rider to the close one to wait. Watch what DFPR does, then "
                   "compare both methods in the *Method Comparison* tab.",
    },
    "Lunch rush": {
        "params": {"peak": True, "peaks": [[12, 14, 2.5]], "start_hour": 11.0, "hours": 3.5},
        "compare": "static_priority",
        "speed": 300,
        "caption": "The full city at lunch: demand jumps to 2.5x at 12:00-14:00 with 18 riders. Watch the queue "
                   "grow, riders turn red (waiting for food) and the late counter. This is the setting of the "
                   "main experiment.",
    },
    "Traffic jam": {
        "params": {"riders": 14, "start_hour": 12.0, "hours": 2.0,
                   "incidents": [[12.5, 13.25, 0.5, 0.5, 1300, 3.0]]},
        "compare": "nearest",
        "speed": 120,
        "caption": "At 12:30 a heavy jam (x3 travel time) covers the city centre for 45 minutes. Roads turn "
                   "red, riders inside it slow down (they do not re-route), and DFPR re-scores the orders whose "
                   "routes changed (see heap updates triggered by TRAFFIC_CHANGE in the Data Structures tab). "
                   "Whether that actually helps here is shown in Method Comparison.",
    },
}


def preset_params(name: str) -> dict:
    return {**BASE, **PRESETS[name]["params"]}


# ----------------------------------------------------------- scripted world
def scripted_world(name: str, cfg: dict) -> tuple[list[OrderSpec], list[int]]:
    """Orders and rider starts for a scripted preset, built on the real city."""
    if name != "readiness":
        raise ValueError(f"unknown scripted world {name!r}")
    city = build_city(cfg["city"])
    g = city.graph
    # Orders arrive at the very start: the simulator processes ORDER_PLACED
    # before the riders' first RIDER_IDLE at the same instant, so each rider
    # really faces the choice between all waiting orders.
    t0 = cfg["sim"]["start_hour"] * 3600
    trees = {r.node: dijkstra(g, r.node, "length") for r in city.restaurants}

    # Pairs (slow restaurant A, ready restaurant B) 500-1200 m apart, disjoint.
    pairs: list[tuple[int, int]] = []
    used: set[int] = set()
    nodes = sorted(trees)
    for a in nodes:
        for b in nodes:
            if a == b or a in used or b in used:
                continue
            if 500 <= trees[a].dist[b] <= 1200:
                pairs.append((a, b))
                used.update((a, b))
                break
        if len(pairs) == int(cfg["riders"]["count"]):
            break

    specs: list[OrderSpec] = []
    starts: list[int] = []
    for k, (a, b) in enumerate(pairs):
        # Rider starts one block from A, on the side away from B.
        nbrs = [e.to for e in g.adj[a]]
        starts.append(max(nbrs, key=lambda v: (trees[b].dist[v], -v)))

        def customer(r: int) -> int:
            return min(range(g.num_nodes), key=lambda v: (abs(trees[r].dist[v] - 1000), v))

        specs.append(OrderSpec(2 * k, a, customer(a), t0, 14 * 60.0, 14 * 60.0, t0 + 35 * 60.0))
        specs.append(OrderSpec(2 * k + 1, b, customer(b), t0, 2 * 60.0, 2 * 60.0, t0 + 35 * 60.0))
    # Extra riders (if the slider asks for more) start at the first restaurant pair's far side.
    while len(starts) < int(cfg["riders"]["count"]):
        starts.append(nodes[len(starts) % len(nodes)])
    return specs, starts
