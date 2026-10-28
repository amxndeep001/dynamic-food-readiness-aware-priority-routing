"""Tab 5: Data Structures - the indexed heap step by step, Dijkstra vs A*, costs."""

from __future__ import annotations

import math
import time
from collections import Counter

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ds.graph import Graph
from ds.indexed_heap import IndexedMaxHeap
from ds.shortest_path import astar, dijkstra, reconstruct_path
from sim.recorder import Trace
from ui.explain import clock
from ui.theme import INK, explainer, show, style

EXAMPLE = [(101, 0.82), (102, 0.40), (103, 0.65), (104, 0.12), (105, 0.55), (106, 0.31), (107, 0.70)]


# --------------------------------------------------------------- heap demo
def _heap_from(entries: list[tuple[int, float]]) -> IndexedMaxHeap:
    """Rebuild a heap with exactly this array layout.

    Pushing a valid heap array in array order never triggers a swap (each
    parent is pushed earlier and is >= its children), so the layout is kept.
    """
    h: IndexedMaxHeap[int] = IndexedMaxHeap()
    for k, p in entries:
        h.push(k, p)
    return h


def _array(h: IndexedMaxHeap) -> list[tuple[int, float]]:
    return [(e[2], e[0]) for e in h._heap]


def run_operation(entries: list[tuple[int, float]], op: str, key: int, prio: float) -> list[dict]:
    """Run one operation on the real IndexedMaxHeap and record a frame per step (via its observer)."""
    h = _heap_from(entries)
    frames = [{"array": _array(h), "pos": dict(h._pos), "hl": [], "msg": "Starting heap."}]

    def observe(event: str, info: dict) -> None:
        arr = _array(h)
        if event == "push":
            frames.append({"array": arr, "pos": dict(h._pos), "hl": [info["index"]],
                           "msg": f"push(#{info['key']}, {info['priority']:.2f}): added at the end, index {info['index']}."})
        elif event == "pop_max":
            frames.append({"array": arr, "pos": dict(h._pos), "hl": [0],
                           "msg": f"pop_max(): the root #{info['key']} ({info['priority']:.2f}) is the maximum."})
        elif event == "update_key":
            frames.append({"array": arr, "pos": dict(h._pos), "hl": [info["index"]],
                           "msg": f"update_key(#{info['key']}): {info['old_priority']:.2f} → {info['priority']:.2f}; "
                                  f"found in O(1) through the position map (index {info['index']})."})
        elif event == "swap":
            i, j = info["i"], info["j"]
            frames.append({"array": arr, "pos": dict(h._pos), "hl": [i, j],
                           "msg": f"swap indices {i} ↔ {j} (and update both entries in the position map)."})
        elif event == "detach":
            frames.append({"array": arr, "pos": dict(h._pos), "hl": [],
                           "msg": f"Removed #{info['key']} from the end of the array, O(1)."})
        elif event == "done":
            frames.append({"array": arr, "pos": dict(h._pos), "hl": [], "msg": "Done: heap order restored."})

    h.observer = observe
    if op == "push":
        h.push(key, prio)
    elif op == "pop_max":
        h.pop_max()
    else:
        h.update_key(key, prio)
    h.observer = None
    h.check_invariants()
    return frames


def tree_figure(frame: dict) -> go.Figure:
    arr = frame["array"]
    n = len(arr)
    xs, ys = [], []
    for i in range(n):
        level = int(math.log2(i + 1))
        pos = i - (2 ** level - 1)
        xs.append((pos + 0.5) / 2 ** level)
        ys.append(-level)
    fig = go.Figure()
    ex, ey = [], []
    for i in range(1, n):
        p = (i - 1) // 2
        ex += [xs[p], xs[i], None]
        ey += [ys[p], ys[i], None]
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(color="#b5b3ab", width=2), hoverinfo="skip",
                             name="parent → child"))
    colors = ["#eb6834" if i in frame["hl"] else "#2a78d6" for i in range(n)]
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=[f"#{k}<br>{p:.2f}" for k, p in arr], textfont=dict(color="white", size=13),
        marker=dict(size=58, color=colors, line=dict(color="white", width=2)), name="node (order, priority)",
        hovertext=[f"index {i}: order #{k}, priority {p:.3f}" for i, (k, p) in enumerate(arr)], hoverinfo="text"))
    fig.add_trace(go.Scatter(x=[x for x in xs], y=[y - 0.32 for y in ys], mode="text",
                             text=[f"[{i}]" for i in range(n)], textfont=dict(size=12, color="#52514e"),
                             hoverinfo="skip", name="array index"))
    style(fig, "Binary max-heap as a tree (orange = involved in this step)", height=430)
    fig.update_xaxes(visible=False, range=[-0.05, 1.05])
    fig.update_yaxes(visible=False, range=[min(ys, default=0) - 0.7, 0.6])
    return fig


def heap_section(trace: Trace) -> None:
    st.subheader("Indexed binary max-heap, one step at a time")
    st.caption("This is the real `ds/indexed_heap.py` running; every swap is captured through its observer hook.")
    dec = None
    if trace.meta["method"] == "dfpr":
        i = trace.decision_index_at(trace.start + st.session_state.get("live_t_min", 0.0) * 60)
        if i is not None and trace.decisions[i]["n_candidates"] >= 2:
            dec = trace.decisions[i]
    c = st.columns([2, 1, 1, 1, 1])
    source = c[0].radio("Start from", ["Small example (7 orders)", "DFPR queue at the Live Dispatch time"]
                        if dec else ["Small example (7 orders)"], horizontal=True, key="heap_src")
    if source.startswith("DFPR") and dec:
        entries = [(cd["order_id"], round(cd["score"], 3)) for cd in dec["candidates"][:15]]
        entries = _array(_heap_from(sorted(entries, key=lambda e: -e[1])))
    else:
        entries = list(EXAMPLE)
        h = IndexedMaxHeap()
        for k, p in entries:
            h.push(k, p)
        entries = _array(h)
    op = c[1].selectbox("Operation", ["push", "pop_max", "update_key"], key="heap_op")
    keys = [k for k, _ in entries]
    if op == "push":
        key = c[2].number_input("New order id", value=max(keys, default=100) + 1, step=1, key="heap_key_new")
    elif op == "update_key":
        key = c[2].selectbox("Order", keys, index=len(keys) - 1 if keys else 0, key="heap_key_upd")
    else:
        key = None
    prio = c[3].number_input("Priority", value=0.95, step=0.05, format="%.2f", key="heap_prio") if op != "pop_max" else 0.0
    if op == "pop_max" and not entries:
        st.info("The heap is empty: pop_max would raise an error.")
        return
    frames = run_operation(entries, op, int(key) if key is not None else 0, float(prio))
    sig = (tuple(entries), op, key, prio)
    if st.session_state.get("heap_sig") != sig:
        st.session_state["heap_sig"] = sig
        st.session_state["heap_step"] = 0
    b = st.columns([1, 1, 4])
    if b[0].button("◀ Previous step", key="heap_prev"):
        st.session_state["heap_step"] = max(0, st.session_state["heap_step"] - 1)
    if b[1].button("Next step ▶", key="heap_next"):
        st.session_state["heap_step"] = min(len(frames) - 1, st.session_state["heap_step"] + 1)
    k = st.session_state["heap_step"]
    b[2].markdown(f"**Step {k} of {len(frames) - 1}:** {frames[k]['msg']}")
    frame = frames[k]
    left, right = st.columns([2, 1])
    with left:
        show(tree_figure(frame), "heap_tree", "dfpr_heap_tree")
    with right:
        st.markdown("**Array view** (what is really stored)")
        arr = pd.DataFrame([{"index": i, "order": f"#{kk}", "priority": round(p, 3)} for i, (kk, p) in
                            enumerate(frame["array"])])

        def hl(row):
            return ["background-color: #fde3d6" if row["index"] in frame["hl"] else ""] * len(row)

        st.dataframe(arr.style.apply(hl, axis=1), hide_index=True, width="stretch", height=300)
        st.markdown("**Position map** (order → index, makes update_key O(log n))")
        st.dataframe(pd.DataFrame([{"order": f"#{kk}", "index": v} for kk, v in sorted(frame["pos"].items())]),
                     hide_index=True, width="stretch", height=220)


# ------------------------------------------------------- Dijkstra vs A*
def _graph_at(trace: Trace, t: float) -> Graph:
    """The run's road graph with the traffic in force at time t.

    Free-flow times are copied exactly (speed = length / free time), so the
    "time" costs both algorithms minimise are the simulator's own.
    """
    g = Graph(trace.coords)
    for (u, v), ft in zip(trace.road_ends, trace.road_free_time):
        length = g.euclid(u, v)
        g.add_road(u, v, max(length, 1e-6), max(length, 1e-6) / ft)
    for r, m in enumerate(trace.traffic_at(t)):
        g.set_traffic(r, float(m))
    return g


def search_figure(trace: Trace, visits: list[int], path: list[int], title: str) -> go.Figure:
    xy = np.array(trace.coords)
    ends = np.array(trace.road_ends)
    rx = np.column_stack([xy[ends[:, 0], 0], xy[ends[:, 1], 0], np.full(len(ends), np.nan)]).ravel()
    ry = np.column_stack([xy[ends[:, 0], 1], xy[ends[:, 1], 1], np.full(len(ends), np.nan)]).ravel()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rx, y=ry, mode="lines", line=dict(color="#e4e3df", width=2), hoverinfo="skip",
                             name="road"))
    fig.add_trace(go.Scatter(
        x=xy[visits, 0], y=xy[visits, 1], mode="markers", name="expanded node (colour = visit order)",
        marker=dict(size=9, color=list(range(len(visits))), colorscale="Blues", cmin=-len(visits) * 0.25,
                    colorbar=dict(title="visit #", thickness=12, len=0.6), line=dict(width=0)),
        hovertext=[f"node {v}: visited #{i + 1}" for i, v in enumerate(visits)], hoverinfo="text"))
    fig.add_trace(go.Scatter(x=xy[path, 0], y=xy[path, 1], mode="lines", line=dict(color=INK, width=5),
                             name="shortest path"))
    fig.add_trace(go.Scatter(x=[xy[path[0], 0], xy[path[-1], 0]], y=[xy[path[0], 1], xy[path[-1], 1]],
                             mode="markers+text", text=["S", "T"], textfont=dict(color="white", size=14),
                             marker=dict(size=26, color=["#008300", "#e34948"]), name="start / target"))
    style(fig, title, height=520)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    return fig


def search_section(trace: Trace) -> None:
    st.subheader("Dijkstra vs A* on this city (traffic-aware travel time)")
    t = trace.start + st.session_state.get("live_t_min", 0.0) * 60
    n = len(trace.coords)
    sr = trace.sample_route or {}
    c = st.columns(3)
    s = c[0].number_input("Start node", 0, n - 1, value=int(sr.get("source", 0)), key="sp_src")
    tg = c[1].number_input("Target node", 0, n - 1, value=int(sr.get("target", n - 1)), key="sp_dst")
    c[2].markdown(f"Traffic as at **{clock(t)}** (the Live Dispatch time).")
    g = _graph_at(trace, t)
    vd, va = [], []
    t0 = time.perf_counter()
    tree = dijkstra(g, int(s), "time", target=int(tg), visit_order=vd)
    td = 1000 * (time.perf_counter() - t0)
    t0 = time.perf_counter()
    cost_a, path_a, _ = astar(g, int(s), int(tg), "time", visit_order=va)
    ta = 1000 * (time.perf_counter() - t0)
    path_d, _ = reconstruct_path(tree, int(tg))
    m = st.columns(4)
    m[0].metric("Dijkstra: nodes expanded", len(vd))
    m[1].metric("A*: nodes expanded", len(va), delta=f"{len(va) - len(vd)}", delta_color="inverse")
    m[2].metric("Travel time (both)", f"{tree.dist[int(tg)] / 60:.1f} min",
                help="A* returns the same optimal cost because its heuristic never overestimates")
    m[3].metric("Time taken", f"{td:.2f} ms vs {ta:.2f} ms")
    if abs(cost_a - tree.dist[int(tg)]) > 1e-6:
        st.error("A* and Dijkstra disagree, which should never happen.")
    a, b = st.columns(2)
    with a:
        show(search_figure(trace, vd, path_d, f"Dijkstra: explores in all directions ({len(vd)} nodes)"),
             "sp_dijkstra", "dfpr_dijkstra")
    with b:
        show(search_figure(trace, va, path_a, f"A*: guided towards the target ({len(va)} nodes)"),
             "sp_astar", "dfpr_astar")


# ------------------------------------------------------------- complexity
COMPLEXITY = pd.DataFrame([
    ["Indexed max-heap: push / pop_max / update_key / remove", "O(log n)", "position map key → index finds any order in O(1)"],
    ["Indexed max-heap: peek / contains / priority", "O(1)", ""],
    ["Min-heap (event queue): push / pop", "O(log n)", "FIFO tie-break on insertion counter"],
    ["Dijkstra (one source)", "O((V + E) log V)", "lazy deletion; stops early at a target"],
    ["A* (point to point)", "O((V + E) log V) worst case", "admissible straight-line heuristic"],
    ["Route-cache lookup", "O(1) hit / one Dijkstra miss", "trees rooted at restaurants"],
    ["Order / rider status lookup", "O(1)", "hash maps (Python dict)"],
    ["Decision: Nearest / Shortest path / FIFO", "O(N + R)", ""],
    ["Decision: Static priority (EDF)", "O(log N + R)", ""],
    ["Decision: DFPR", "O(k log N + m(R + log N))", "k lazy refreshes, m orders whose candidate rider was taken"],
], columns=["Operation", "Complexity", "Note"])


def cost_section(trace: Trace) -> None:
    st.subheader("Complexity, and what this run actually did")
    left, right = st.columns([1.3, 1])
    left.dataframe(COMPLEXITY, hide_index=True, width="stretch", height=400)
    with right:
        ops = Counter(h["op"] for h in trace.heap_ops)
        cache = trace.cache_stats
        total = cache["hits"] + cache["misses"]
        st.markdown("**Measured in this run**")
        lines = ["- Heap operations: " + (", ".join(f"{k} {v}" for k, v in ops.items()) or "none (method has no heap)")]
        if total:
            lines.append(f"- Route cache: {cache['hits']:,} hits, {cache['misses']:,} misses "
                         f"(hit rate {100 * cache['hits'] / total:.1f}%), {cache['invalidations']:,} trees "
                         "invalidated by traffic")
        else:
            lines.append("- Route cache: not used")
        st.markdown("\n".join(lines))
        if trace.metrics:
            st.markdown(f"- Decisions: {trace.metrics['decisions']}, mean {trace.metrics['decision_mean_ms']:.3f} ms, "
                        f"max {trace.metrics['decision_max_ms']:.2f} ms")
        per = trace.dispatcher_stats.get("recomputations_per_event")
        if per:
            st.markdown("**DFPR score recomputations per triggering event**")
            st.dataframe(pd.DataFrame([{"event": k, "avg recomputations": v} for k, v in per.items()]),
                         hide_index=True, width="stretch")
        if trace.heap_ops:
            by = pd.DataFrame(trace.heap_ops).groupby(["trigger", "op"]).size().unstack(fill_value=0)
            st.markdown("**Heap operations by triggering event**")
            st.dataframe(by, width="stretch")


def render(trace: Trace) -> None:
    explainer(
        "The data structures that make DFPR fast. **Top:** the indexed max-heap that holds the waiting orders; "
        "step through an operation and watch the swaps in the tree, the array and the position map. **Middle:** "
        "Dijkstra vs A* finding the same route; A* explores fewer nodes. **Bottom:** Big-O costs and real counts."
    )
    heap_section(trace)
    search_section(trace)
    cost_section(trace)
