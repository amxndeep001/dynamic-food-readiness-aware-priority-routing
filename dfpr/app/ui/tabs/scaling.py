"""Tab 6: Scalability & Ablation - plots from the experiment CSVs."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ui.runs import ROOT
from ui.theme import FACTOR_COLORS, explainer, method_color, method_label, show, style

FULL, QUICK = ROOT / "results", ROOT / "results_quick"
VARIANT_NAMES = {"no_u": "without urgency U", "no_f": "without readiness F", "no_w": "without waiting W",
                 "no_d": "without distance D", "no_c": "without traffic C", "no_r": "without rider wait R"}


def _find(name: str) -> tuple[pd.DataFrame | None, str]:
    for folder, label in [(FULL, "full experiment"), (QUICK, "quick reduced run")]:
        if (folder / name).exists():
            return pd.read_csv(folder / name), label
    return None, ""


def scaling_fig(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Cost vs waiting orders N (riders fixed)",
                                                        "Cost vs free riders R (orders fixed)"))
    for col, (sweep, x) in enumerate([("orders", "n_orders"), ("riders", "n_riders")], 1):
        d = df[df.sweep == sweep]
        for m in d.method.unique():
            s = d[d.method == m].sort_values(x)
            fig.add_trace(go.Scatter(x=s[x], y=s["total_ms"], mode="lines+markers", name=method_label(m),
                                     legendgroup=m, showlegend=col == 1,
                                     line=dict(color=method_color(m), width=3), marker=dict(size=9)), row=1, col=col)
        fig.update_xaxes(type="log", title_text=x.replace("n_", "number of "), row=1, col=col)
        fig.update_yaxes(type="log", title_text="ms per assignment" if col == 1 else None, row=1, col=col)
    style(fig, "Computation per assignment (decision + event updates), log-log", height=470)
    return fig


def ablation_fig(t: pd.DataFrame, scenario: str) -> go.Figure:
    d = t[t.scenario == scenario]
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Change in late or unserved orders (%-points)",
                                                        "Change in mean delivery time (min)"))
    for col, metric in enumerate(["late_pct", "avg_delivery_min"], 1):
        x = d[d.metric == metric]
        colors = [FACTOR_COLORS[v[-1].upper()] for v in x.variant]
        fig.add_trace(go.Bar(
            y=[VARIANT_NAMES.get(v, v) for v in x.variant], x=x.mean_diff, orientation="h",
            marker=dict(color=colors, line=dict(color="white", width=2)), showlegend=False,
            error_x=dict(type="data", symmetric=False, array=x.ci_high - x.mean_diff,
                         arrayminus=x.mean_diff - x.ci_low, color="#52514e"),
            hovertemplate="%{y}: %{x:+.2f}<extra></extra>"), row=1, col=col)
        fig.add_vline(x=0, line=dict(color="#52514e", width=2), row=1, col=col)
    fig.update_yaxes(autorange="reversed")
    style(fig, f"Ablation ({scenario}): tuned DFPR with one factor removed. Right of 0 = worse without it "
               "(bars: 95% CI of the paired difference)", height=430)
    return fig


def sensitivity_fig(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Late or unserved orders (%)", "Mean delivery time (min)"))
    for col, metric in enumerate(["late_pct", "avg_delivery_min"], 1):
        for m in df.method.unique():
            s = df[df.method == m].groupby("sigma")[metric].agg(["mean", "std", "count"])
            se = (s["std"] / np.sqrt(s["count"])).fillna(0)
            fig.add_trace(go.Scatter(x=s.index, y=s["mean"], mode="lines+markers", name=method_label(m), legendgroup=m,
                                     showlegend=col == 1, line=dict(color=method_color(m), width=3),
                                     error_y=dict(type="data", array=se, color=method_color(m), thickness=1)),
                          row=1, col=col)
        fig.update_xaxes(title_text="prep-time noise σ", row=1, col=col)
    style(fig, "Sensitivity to wrong cooking-time estimates (peak scenario; error bars: ±1 standard error)",
          height=450)
    return fig


def render() -> None:
    explainer(
        "Results of the batch experiments (many simulated days), not of the run in the sidebar. **Scaling:** how "
        "the computing cost grows with the number of waiting orders and free riders. **Ablation:** what happens "
        "when DFPR ignores one factor. **Sensitivity:** how methods cope when cooking-time estimates get worse."
    )
    sc, sc_src = _find("scaling.csv")
    ab, ab_src = _find("ablation_tests.csv")
    se, se_src = _find("sensitivity_runs.csv")
    if sc is None or ab is None or se is None:
        st.warning("Some experiment results are missing (results/*.csv).")
        if st.button("Run a quick reduced version of the experiments (about 2–3 minutes)", key="quick_exp"):
            with st.spinner("Running `main.py run-all --quick`…"):
                proc = subprocess.run([sys.executable, "main.py", "run-all", "--quick"], cwd=ROOT,
                                      capture_output=True, text=True)
            if proc.returncode == 0:
                st.success("Done. Results written to results_quick/ (reduced settings: few seeds, short days).")
                st.rerun()
            else:
                st.error("The quick run failed:\n\n" + proc.stderr[-2000:])
    if sc is not None:
        st.subheader("Scalability")
        st.caption(f"Source: scaling.csv ({sc_src}). Warm route cache; median of repeats.")
        show(scaling_fig(sc), "exp_scaling", "dfpr_scaling")
        st.caption("DFPR's cost grows roughly linearly with waiting orders (a free rider can change many orders' "
                   "candidate rider); Static priority stays almost flat (heap, O(log N)).")
    if ab is not None:
        st.subheader("Ablation")
        st.caption(f"Source: ablation_tests.csv ({ab_src}).")
        scen = st.radio("Scenario", sorted(ab.scenario.unique()), horizontal=True, key="abl_scen",
                        index=sorted(ab.scenario.unique()).index("peak") if "peak" in set(ab.scenario) else 0)
        show(ablation_fig(ab, scen), "exp_ablation", f"dfpr_ablation_{scen}")
    if se is not None:
        st.subheader("Sensitivity to prep-time noise")
        st.caption(f"Source: sensitivity_runs.csv ({se_src}).")
        show(sensitivity_fig(se), "exp_sensitivity", "dfpr_sensitivity")
