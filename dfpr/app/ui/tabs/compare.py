"""Tab 4: Method Comparison - same world, different dispatch rules."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from sim.recorder import Trace
from ui.explain import clock
from ui.map_view import map_figure
from ui.runs import ROOT, get_trace
from ui.sidebar import METHODS
from ui.theme import explainer, method_color, method_label, show, style

# (metric key, label, unit); lower is better for every one of them.
METRICS = [
    ("avg_delivery_min", "Mean delivery time", "min"),
    ("p90_delivery_min", "p90 delivery time", "min"),
    ("late_pct", "Late or unserved", "%"),
    ("food_wait_min", "Food waits for rider", "min"),
    ("rider_wait_min", "Rider waits for food", "min"),
    ("total_distance_km", "Total distance", "km"),
    ("decision_mean_ms", "Decision time", "ms"),
]
RESULTS = ROOT / "results"


def metric_bars(rows: dict[str, dict], title: str, errors: dict[str, dict] | None = None) -> go.Figure:
    methods = list(rows)
    fig = make_subplots(rows=2, cols=4, subplot_titles=[f"{lab} ({u})" for _, lab, u in METRICS],
                        vertical_spacing=0.16, horizontal_spacing=0.06)
    for i, (key, _, _) in enumerate(METRICS):
        r, c = divmod(i, 4)
        for m in methods:
            fig.add_trace(go.Bar(
                x=[method_label(m)], y=[rows[m].get(key, np.nan)], name=method_label(m), legendgroup=m,
                showlegend=(i == 0), marker=dict(color=method_color(m), line=dict(color="white", width=2)),
                error_y=dict(type="data", array=[errors[m].get(key, 0)], color="#52514e", thickness=1.5)
                if errors else None,
                hovertemplate=f"{method_label(m)}: %{{y:.2f}}<extra></extra>"), row=r + 1, col=c + 1)
        fig.update_xaxes(showticklabels=False, row=r + 1, col=c + 1)
    style(fig, title, height=600)
    fig.update_layout(bargap=0.15)
    return fig


def radar(rows: dict[str, dict]) -> go.Figure:
    """Each metric as best / value (all metrics are lower-is-better): 1 = best of the
    methods shown, 0.5 = twice the best value. Works for any number of methods."""
    keys = [k for k, _, _ in METRICS]
    labels = [lab for _, lab, _ in METRICS]
    vals = {k: np.array([rows[m].get(k, np.nan) for m in rows], dtype=float) for k in keys}
    fig = go.Figure()
    for j, m in enumerate(rows):
        r = []
        for k in keys:
            best, v = np.nanmin(vals[k]), vals[k][j]
            r.append(1.0 if v <= 0 or v == best else float(max(best, 0.0) / v))
        fig.add_trace(go.Scatterpolar(r=r + r[:1], theta=labels + labels[:1], name=method_label(m),
                                      line=dict(color=method_color(m), width=3), fill="toself", opacity=0.5))
    style(fig, "Relative performance in this run (edge = best of the methods shown; 0.5 = twice as large as the best)",
          height=560)
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 1], tickvals=[0.25, 0.5, 0.75, 1.0],
                                                 tickfont=dict(size=11)), bgcolor="#fcfcfb",
                                 domain=dict(y=[0.08, 0.92])))
    return fig


def honest_summary(rows: dict[str, dict]) -> list[str]:
    """Where DFPR wins and loses against each other method in this run, from the numbers."""
    if "dfpr" not in rows:
        return ["DFPR is not among the selected methods, so there is nothing to summarise about it."]
    out = []
    for m in rows:
        if m == "dfpr":
            continue
        wins, losses, ties = [], [], []
        for key, lab, unit in METRICS:
            a, b = rows["dfpr"].get(key), rows[m].get(key)
            if a is None or b is None or np.isnan(a) or np.isnan(b):
                continue
            diff = a - b
            tol = 0.005 * max(abs(a), abs(b), 1e-9)
            item = f"{lab.lower()} ({diff:+.2f} {unit})"
            (ties if abs(diff) <= tol else wins if diff < 0 else losses).append(item)
        out.append(f"**vs {method_label(m)}:** DFPR better on {', '.join(wins) or 'nothing'}; "
                   f"worse on {', '.join(losses) or 'nothing'}"
                   + (f"; equal on {', '.join(ties)}" if ties else "") + ".")
    return out


def held_out_section(methods: list[str]) -> None:
    path = RESULTS / "compare_runs.csv"
    if not path.exists():
        st.caption("No multi-seed results found (results/compare_runs.csv). Run `py -3.13 main.py run-all` to add them.")
        return
    df = pd.read_csv(path)
    scen = st.radio("Scenario of the main experiment", sorted(df.scenario.unique()), horizontal=True,
                    index=sorted(df.scenario.unique()).index("peak") if "peak" in set(df.scenario) else 0)
    g = df[(df.scenario == scen) & df.method.isin(methods)]
    if g.empty:
        st.caption("None of the selected methods are in the multi-seed results.")
        return
    order = [m for m in methods if m in set(g.method)]
    mean = {m: g[g.method == m].mean(numeric_only=True).to_dict() for m in order}
    std = {m: g[g.method == m].std(numeric_only=True).to_dict() for m in order}
    n = g.seed.nunique()
    show(metric_bars(mean, f"Held-out seeds {g.seed.min()}–{g.seed.max()} ({n} simulated days, {scen} scenario): "
                           "mean ± std", std), "cmp_heldout", f"dfpr_heldout_{scen}")
    tests = RESULTS / "compare_tests.csv"
    if tests.exists() and "dfpr" in order:
        t = pd.read_csv(tests)
        t = t[(t.scenario == scen) & t.other.isin(order)]
        lines = []
        for other, tt in t.groupby("other"):
            sig = tt[tt.p_wilcoxon_holm < 0.05]
            better = [f"{r.metric} ({r.mean_diff:+.2f})" for r in sig.itertuples() if r.mean_diff < 0]
            worse = [f"{r.metric} ({r.mean_diff:+.2f})" for r in sig.itertuples() if r.mean_diff > 0]
            ns = [r.metric for r in tt.itertuples() if r.p_wilcoxon_holm >= 0.05]
            lines.append(f"**vs {method_label(other)}:** significantly better on {', '.join(better) or 'nothing'}; "
                         f"significantly worse on {', '.join(worse) or 'nothing'}"
                         + (f"; no significant difference on {', '.join(ns)}" if ns else "") + ".")
        st.markdown("**Multi-seed result (paired Wilcoxon tests, Holm-corrected, p < 0.05):**")
        for line in lines:
            st.markdown("- " + line)


def render(trace: Trace, params: dict) -> None:
    explainer(
        "Every method is run on **exactly the same simulated period**: same orders, same cooking times, same "
        "traffic, same rider start points. Only the dispatch rule differs, so any difference comes from the rule. "
        "Numbers from one run can be luck; the multi-seed chart further down averages 30 held-out days."
    )
    default = ["dfpr", st.session_state.get("compare_with", "nearest")]
    picked = st.multiselect("Methods to compare (2–4)", METHODS, default=list(dict.fromkeys(default)),
                            format_func=method_label, max_selections=4, key="cmp_methods")
    if len(picked) < 2:
        st.info("Pick at least two methods.")
        return
    with st.spinner("Running the selected methods on the same simulated period (cached after the first time)…"):
        traces = {m: (trace if m == trace.meta["method"] else get_trace(params, m)) for m in picked}
    rows = {m: tr.metrics for m, tr in traces.items()}
    if not any(rows.values()):
        st.info("This run has no orders, so there is nothing to compare.")
        return

    # Honest banner first.
    if "dfpr" in rows:
        lost = [m for m in rows if m != "dfpr" and rows["dfpr"]["avg_delivery_min"] > rows[m]["avg_delivery_min"]]
        if lost:
            st.markdown(f"<div class='banner-loss'>In this run DFPR did <b>not</b> have the lowest mean delivery time: "
                        f"{', '.join(method_label(m) for m in lost)} did better.</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='banner-win'>In this run DFPR had the lowest mean delivery time of the methods "
                        "shown. Check the other metrics below: it does not win everywhere.</div>",
                        unsafe_allow_html=True)

    st.subheader("Side-by-side replay")
    a, b = st.columns(2)
    left = a.selectbox("Left map", picked, index=0, format_func=method_label, key="cmp_left")
    right = b.selectbox("Right map", picked, index=1, format_func=method_label, key="cmp_right")
    end = max(traces[left].end, traces[right].end)
    start = trace.start
    m = st.slider("Shared time (minutes since start)", 0.0, max(1.0, round((end - start) / 60, 1)), step=0.5,
                  key="cmp_min")
    t = start + m * 60
    for col, meth in [(a, left), (b, right)]:
        with col:
            tr = traces[meth]
            done = sum(1 for o in tr.orders if o["delivered_at"] is not None and o["delivered_at"] <= t)
            late = sum(1 for o in tr.orders if o["delivered_at"] is not None and o["delivered_at"] <= t and o["late"])
            fig = map_figure(tr, t, title=f"{method_label(meth)} at {clock(t)}: {done} delivered, {late} late",
                             height=520, legend=False)
            show(fig, f"cmp_map_{meth}", f"dfpr_compare_map_{meth}")
    st.caption("Map colours are the same as in Live Dispatch (riders: grey idle, blue to restaurant, red waiting "
               "for food, green delivering).")

    st.subheader("This run")
    show(metric_bars(rows, "One simulated period (single seed, not significance-tested). Lower is better."),
         "cmp_bars", "dfpr_compare_this_run")
    c1, c2 = st.columns([1.1, 1])
    with c1:
        show(radar(rows), "cmp_radar", "dfpr_compare_radar")
    with c2:
        st.markdown("**Where DFPR wins and loses in this run** (computed from the numbers, single run):")
        for line in honest_summary(rows):
            st.markdown("- " + line)

    st.subheader("Main experiment: many simulated days")
    held_out_section(picked)
