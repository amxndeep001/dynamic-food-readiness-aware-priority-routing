"""Tab 3: Waiting Times - per-order timeline, distributions, waits over the day."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from sim.recorder import Trace
from ui.theme import FOOD_COOKING, explainer, show, style

DAY0 = pd.Timestamp("2026-01-01")
SEGMENTS = [
    ("Waiting for a rider", "#c9c7bf"),
    ("Rider driving to restaurant", "#9cc3ef"),
    ("Rider waits for food", "#e34948"),
    ("Food waits for rider", FOOD_COOKING),
    ("Delivering", "#008300"),
]


def _ts(s: float) -> pd.Timestamp:
    return DAY0 + pd.Timedelta(seconds=float(s))


def order_frame(trace: Trace) -> pd.DataFrame:
    rows = []
    for o in trace.orders:
        if o["picked_at"] is None:
            rw = fw = np.nan
        else:
            rw = max(0.0, o["actual_ready"] - o["rider_arrived_at"]) / 60
            fw = max(0.0, o["picked_at"] - o["actual_ready"]) / 60
        rows.append({**o, "rider_wait_min": rw, "food_wait_min": fw,
                     "delivery_min": (o["delivered_at"] - o["placed_at"]) / 60 if o["delivered_at"] else np.nan})
    return pd.DataFrame(rows)


def gantt(trace: Trace, orders: list[dict]) -> go.Figure:
    segs: dict[str, list[tuple[str, float, float]]] = {name: [] for name, _ in SEGMENTS}
    labels = []
    for o in orders:
        flag = " ⚠ late" if o["late"] else ""
        lab = f"#{o['id']} (rider {o['rider_id'] if o['rider_id'] is not None else '–'}){flag}"
        labels.append(lab)
        end = o["delivered_at"] or trace.meta["cutoff_s"]
        assigned = o["assigned_at"] if o["assigned_at"] is not None else end
        segs["Waiting for a rider"].append((lab, o["placed_at"], assigned))
        if o["rider_arrived_at"] is not None:
            segs["Rider driving to restaurant"].append((lab, o["assigned_at"], o["rider_arrived_at"]))
            if o["actual_ready"] > o["rider_arrived_at"]:
                segs["Rider waits for food"].append((lab, o["rider_arrived_at"], o["picked_at"] or end))
        if o["picked_at"] is not None:
            if o["actual_ready"] < o["rider_arrived_at"]:
                segs["Food waits for rider"].append((lab, o["actual_ready"], o["picked_at"]))
            if o["delivered_at"] is not None:
                segs["Delivering"].append((lab, o["picked_at"], o["delivered_at"]))
    fig = go.Figure()
    for name, color in SEGMENTS:
        s = segs[name]
        fig.add_trace(go.Bar(
            y=[x[0] for x in s] or [None], base=[_ts(x[1]) for x in s] or [None],
            x=[(x[2] - x[1]) * 1000 for x in s] or [None], orientation="h", name=name,
            marker=dict(color=color, line=dict(color="white", width=1)),
            hovertemplate="%{y}<br>" + name + ": %{customdata:.1f} min<extra></extra>",
            customdata=[(x[2] - x[1]) / 60 for x in s]))
    fig.add_trace(go.Scatter(y=labels, x=[_ts(o["deadline"]) for o in orders], mode="markers", name="Deadline",
                             marker=dict(symbol="line-ns", size=18, line=dict(width=3, color="#0b0b0b"))))
    fig.add_trace(go.Scatter(y=labels, x=[_ts(o["est_ready"]) for o in orders], mode="markers",
                             name="Estimated ready time", marker=dict(symbol="circle-open", size=11,
                                                                      color="#6250d6", line=dict(width=2))))
    style(fig, "Each order's life: placed → rider assigned → at restaurant → picked up → delivered",
          height=max(380, 30 * len(orders) + 180))
    fig.update_layout(barmode="overlay")
    fig.update_yaxes(autorange="reversed", type="category")
    fig.update_xaxes(type="date", tickformat="%H:%M", title="Time of day")
    return fig


def distributions(df: pd.DataFrame) -> tuple[go.Figure, go.Figure]:
    hist = make_subplots(rows=1, cols=3, subplot_titles=("Rider waits for food", "Food waits for rider",
                                                         "Delivery time (placed → delivered)"))
    for i, (col, color) in enumerate([("rider_wait_min", "#e34948"), ("food_wait_min", FOOD_COOKING),
                                      ("delivery_min", "#2a78d6")], 1):
        hist.add_trace(go.Histogram(x=df[col].dropna(), marker=dict(color=color, line=dict(color="white", width=1)),
                                    name=col.replace("_min", "").replace("_", " "), nbinsx=20), row=1, col=i)
        hist.update_xaxes(title_text="minutes", row=1, col=i)
    hist.update_yaxes(title_text="orders", row=1, col=1)
    style(hist, "How long people and food wait (all orders in this run)", height=380, legend=False)

    box = go.Figure()
    for col, name, color in [("rider_wait_min", "Rider waits for food", "#e34948"),
                             ("food_wait_min", "Food waits for rider", FOOD_COOKING),
                             ("delivery_min", "Delivery time", "#2a78d6")]:
        box.add_trace(go.Box(y=df[col].dropna(), name=name, marker_color=color, boxmean=True))
    style(box, "Spread of waiting times (box = middle 50%, line = median, dashed = mean)", height=380)
    box.update_yaxes(title="minutes")
    return hist, box


def over_time(df: pd.DataFrame, bucket_min: int = 15) -> go.Figure:
    """Two panels on one time axis: arrivals per hour (top) and average waits (bottom)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=("Orders arriving (per hour)", "Average waits of orders placed in that window"))
    b = (df.placed_at // (bucket_min * 60)) * bucket_min * 60
    g = df.assign(bucket=b).groupby("bucket")
    x = [_ts(v) for v in g.size().index]
    fig.add_trace(go.Bar(x=x, y=g.size().values * 60 / bucket_min, name="Arrival rate (orders/hour)",
                         marker=dict(color="#6250d6")), row=1, col=1)
    for col, name, color in [("delivery_min", "Mean delivery time", "#2a78d6"),
                             ("rider_wait_min", "Mean rider wait", "#e34948"),
                             ("food_wait_min", "Mean food wait", FOOD_COOKING)]:
        fig.add_trace(go.Scatter(x=x, y=g[col].mean().values, mode="lines+markers", name=name,
                                 line=dict(color=color, width=3), marker=dict(size=8)), row=2, col=1)
    style(fig, None, height=520)
    fig.update_yaxes(title_text="orders / hour", row=1, col=1)
    fig.update_yaxes(title_text="minutes", row=2, col=1)
    fig.update_xaxes(type="date", tickformat="%H:%M", row=2, col=1, title_text="Time the order was placed")
    return fig


def render(trace: Trace) -> None:
    explainer(
        "Where does the time go? Each bar is one order: **red** = the rider stands at the restaurant waiting for "
        "food (wasted rider time), **orange** = cooked food waits for the rider (it gets cold). DFPR tries to "
        "shrink both by sending riders so they arrive when the food is ready."
    )
    if not trace.orders:
        st.info("This run has no orders, so there are no waiting times to show.")
        return
    df = order_frame(trace)
    riders = sorted(int(r) for r in df.rider_id.dropna().unique())
    c1, c2 = st.columns([2, 1])
    pick = c1.multiselect("Show riders", riders, default=riders, format_func=lambda r: f"Rider {r}",
                          key=f"gantt_riders_{id(trace)}")
    sel = [o for o in trace.orders if o["rider_id"] in pick or (o["rider_id"] is None and len(pick) == len(riders))]
    n = len(sel)
    if n == 0:
        st.info("No orders for the selected riders.")
    else:
        lo, hi = (c2.slider("Orders shown (by order number)", 1, n, (1, min(n, 30)), key=f"gantt_rng_{id(trace)}")
                  if n > 1 else (1, 1))
        show(gantt(trace, sel[lo - 1:hi]), "waits_gantt", "dfpr_order_timeline")
    hist, box = distributions(df)
    show(hist, "waits_hist", "dfpr_wait_histograms")
    show(box, "waits_box", "dfpr_wait_boxplots")
    show(over_time(df), "waits_over_time", "dfpr_waits_over_time")
