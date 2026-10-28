"""Plotly city map for one moment of a recorded run."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from sim.recorder import Trace
from ui.theme import FOOD_COOKING, FOOD_READY, INK, RIDER_COLORS, RIDER_LABELS, TRAFFIC_BINS, style

WAITING_STATES = {"placed", "assigned"}
ACTIVE_STATES = {"placed", "assigned", "picked_up"}


def _road_xy(trace: Trace) -> tuple[np.ndarray, np.ndarray]:
    """(n_roads, 2) arrays of x and y end points, cached on the trace object."""
    if not hasattr(trace, "_road_xy_cache"):
        c = np.array(trace.coords)
        ends = np.array(trace.road_ends)
        trace._road_xy_cache = (c[ends, 0], c[ends, 1])
    return trace._road_xy_cache


def _segments(xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Many line segments as one trace: x1, x2, NaN, x1, x2, NaN, ..."""
    n = len(xs)
    gap = np.full((n, 1), np.nan)
    return np.hstack([xs, gap]).ravel(), np.hstack([ys, gap]).ravel()


def map_figure(trace: Trace, t: float, title: str | None = None, height: int = 640,
               legend: bool = True, highlight_order: int | None = None) -> go.Figure:
    snap = trace.snapshot(t)
    fig = go.Figure()

    # Roads, coloured by the traffic multiplier in force at time t.
    rx, ry = _road_xy(trace)
    mult = np.asarray(snap["traffic"])
    for lo, hi, color, label in TRAFFIC_BINS:
        mask = (mult >= lo) & (mult < hi)
        x, y = _segments(rx[mask], ry[mask]) if mask.any() else ([None], [None])
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=color, width=3 if lo < 1.1 else 5),
                                 name=f"Road: {label}", hoverinfo="skip", legendgroup="roads",
                                 legendgrouptitle_text="Traffic" if lo == 1.0 else None))

    orders = snap["orders"]
    # Customers of orders not yet delivered.
    cust = [o for o in orders if o["state"] in ACTIVE_STATES]
    if cust:
        fig.add_trace(go.Scatter(
            x=[trace.coords[o["customer_node"]][0] for o in cust],
            y=[trace.coords[o["customer_node"]][1] for o in cust],
            mode="markers", marker=dict(symbol="diamond", size=12, color="#6250d6", line=dict(color="white", width=1)),
            name="Customer waiting", text=[f"Customer of #{o['id']}" for o in cust], hoverinfo="text"))

    # Restaurants, with a badge for orders still waiting there.
    rest_x = [trace.coords[r["node"]][0] for r in trace.restaurants]
    rest_y = [trace.coords[r["node"]][1] for r in trace.restaurants]
    fig.add_trace(go.Scatter(
        x=rest_x, y=rest_y, mode="markers+text", text=[f"R{r['id']}" for r in trace.restaurants],
        textposition="bottom center", textfont=dict(size=12, color=INK),
        marker=dict(symbol="square", size=16, color="#3d3a35", line=dict(color="white", width=1.5)),
        name="Restaurant", hovertext=[f"Restaurant R{r['id']}<br>typical prep {r['mean_prep_s'] / 60:.0f} min"
                                      for r in trace.restaurants], hoverinfo="text"))
    waiting: dict[int, list[dict]] = {}
    for o in orders:
        if o["state"] in WAITING_STATES:
            waiting.setdefault(o["restaurant_node"], []).append(o)
    for ready, color, label in [(True, FOOD_READY, "Order waiting: food ready"),
                                (False, FOOD_COOKING, "Order waiting: still cooking")]:
        pts = [(node, os_) for node, os_ in waiting.items() if any(o["food_ready"] for o in os_) == ready]
        off = 0.35 * (trace.coords[1][0] - trace.coords[0][0]) if len(trace.coords) > 1 else 50
        fig.add_trace(go.Scatter(
            x=[trace.coords[n][0] + off for n, _ in pts] or [None],
            y=[trace.coords[n][1] + off for n, _ in pts] or [None],
            mode="markers+text", text=[str(len(os_)) for _, os_ in pts],
            textfont=dict(size=11, color="white"),
            marker=dict(symbol="circle", size=20, color=color, line=dict(color="white", width=1.5)),
            name=label,
            hovertext=["<br>".join(f"#{o['id']}: {'ready' if o['food_ready'] else 'cooking'}" for o in os_)
                       for _, os_ in pts], hoverinfo="text"))

    # Rider routes (remaining part) and riders.
    for status, dash in [("to_restaurant", "dash"), ("to_customer", "solid")]:
        xs, ys = [], []
        for r in snap["riders"]:
            if r["status"] == status and len(r["route"]) > 1:
                xs += [p[0] for p in r["route"]] + [None]
                ys += [p[1] for p in r["route"]] + [None]
        fig.add_trace(go.Scatter(x=xs or [None], y=ys or [None], mode="lines", hoverinfo="skip",
                                 line=dict(color=RIDER_COLORS[status], width=4, dash=dash),
                                 name=f"Route: {RIDER_LABELS[status].lower()}"))
    for status, color in RIDER_COLORS.items():
        rs = [r for r in snap["riders"] if r["status"] == status]
        fig.add_trace(go.Scatter(
            x=[r["x"] for r in rs] or [None], y=[r["y"] for r in rs] or [None], mode="markers+text",
            text=[str(r["id"]) for r in rs], textfont=dict(size=13, color="white"),
            marker=dict(size=26, color=color, line=dict(color="white", width=2)),
            name=f"Rider: {RIDER_LABELS[status]}",
            hovertext=[f"Rider {r['id']}: {RIDER_LABELS[status]}" + (f" (order #{r['order']})" if r["order"] is not None else "")
                       for r in rs], hoverinfo="text"))

    if highlight_order is not None:
        o = next((o for o in orders if o["id"] == highlight_order), None)
        if o is not None:
            x, y = trace.coords[o["restaurant_node"]]
            fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers", name=f"Chosen order #{o['id']}",
                                     marker=dict(symbol="square-open", size=34, color="#0b0b0b", line=dict(width=3))))

    style(fig, title, height=height, legend=legend)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(legend=dict(orientation="v", y=1, x=1.01, xanchor="left", yanchor="top",
                                  font=dict(size=13), groupclick="toggleitem"),
                      margin=dict(l=5, r=5, t=50 if title else 10, b=5), uirevision="map")
    return fig
