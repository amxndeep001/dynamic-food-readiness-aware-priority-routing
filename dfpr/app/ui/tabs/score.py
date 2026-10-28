"""Tab 2: Score Breakdown - what pushes each order up or down, and what-if weights."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dispatch.dfpr import Factors, Weights, combine
from sim.recorder import Trace
from ui.explain import clock
from ui.theme import FACTOR_COLORS, FACTOR_NAMES, explainer, method_label, show, style

FACTOR_KEYS = ["U", "F", "W", "D", "C", "R"]
SIGNS = {"U": 1, "F": 1, "W": 1, "D": -1, "C": -1, "R": -1}


def _decision_choice(trace: Trace) -> dict | None:
    decs = [i for i, d in enumerate(trace.decisions) if d["chosen"] and d["n_candidates"] >= 2]
    if not decs:
        return None
    live_t = trace.start + st.session_state.get("live_t_min", 0.0) * 60
    at_live = trace.decision_index_at(live_t)
    default = max([i for i in decs if at_live is not None and i <= at_live], default=decs[0])
    labels = {i: f"{clock(trace.decisions[i]['time'])} · #{trace.decisions[i]['chosen']['order']} chosen "
                 f"from {trace.decisions[i]['n_candidates']} waiting" for i in decs}
    i = st.selectbox("Decision to inspect (defaults to the one shown in Live Dispatch)", decs,
                     index=decs.index(default), format_func=labels.get, key=f"score_dec_{id(trace)}")
    return trace.decisions[i]


def breakdown_chart(dec: dict, top: int = 12) -> go.Figure:
    cands = dec["candidates"][:top]
    labels = [f"#{c['order_id']}" + (" (chosen)" if k == 0 else "") for k, c in enumerate(cands)]
    fig = go.Figure()
    for f in FACTOR_KEYS:
        fig.add_trace(go.Bar(y=labels, x=[c["contributions"][f] for c in cands], orientation="h",
                             name=FACTOR_NAMES[f], marker=dict(color=FACTOR_COLORS[f], line=dict(color="white", width=1)),
                             hovertemplate="%{y}: %{x:+.3f}<extra>" + FACTOR_NAMES[f] + "</extra>"))
    fig.add_trace(go.Scatter(y=labels, x=[c["score"] for c in cands], mode="markers", name="Total score P",
                             marker=dict(symbol="diamond", size=14, color="#0b0b0b", line=dict(color="white", width=1.5)),
                             hovertemplate="%{y}: P = %{x:.3f}<extra></extra>"))
    style(fig, f"Signed contribution of each factor at {clock(dec['time'])} (best order on top)",
          height=max(360, 46 * len(cands) + 160))
    fig.update_layout(barmode="relative")
    fig.update_yaxes(autorange="reversed", type="category")
    fig.update_xaxes(title="Contribution to P (right = pushes the order up, left = pushes it down)",
                     zeroline=True, zerolinecolor="#52514e", zerolinewidth=2)
    return fig


def what_if(dec: dict, run_w: dict) -> Weights:
    st.subheader("What if the weights were different?")
    st.caption("Moving a slider re-ranks this snapshot instantly with the same factor values. Candidate riders and "
               "travel times stay as they were; re-run the simulation to see the full effect over time.")
    key = "wi"
    if st.button("Reset to this run's weights", key="wi_reset"):
        for k in "ufwdcr":
            st.session_state[f"{key}_{k}"] = float(run_w[k])
    cols = st.columns(6)
    names = {"u": "w_u Urgency", "f": "w_f Readiness", "w": "w_w Waiting", "d": "w_d Distance", "c": "w_c Traffic",
             "r": "w_r Rider wait"}
    vals = {}
    for col, k in zip(cols, "ufwdcr"):
        st.session_state.setdefault(f"{key}_{k}", float(run_w[k]))
        vals[k] = col.slider(names[k], 0.0, 3.0, step=0.05, key=f"{key}_{k}")
    w = Weights(**vals)

    cands = dec["candidates"]
    new_scores = [combine(Factors(**c["factors"]), w) for c in cands]
    order = sorted(range(len(cands)), key=lambda i: -new_scores[i])
    new_rank = {i: r for r, i in enumerate(order, 1)}
    rows = []
    for i in order[:15]:
        c = cands[i]
        diff = (i + 1) - new_rank[i]
        arrow = f"↑ {diff}" if diff > 0 else f"↓ {-diff}" if diff < 0 else "="
        rows.append({"New rank": new_rank[i], "Order": f"#{c['order_id']}", "Change": arrow,
                     "New score": round(new_scores[i], 3), "Run rank": i + 1, "Run score": round(c["score"], 3)})
    df = pd.DataFrame(rows)

    def color(row):
        ch = row["Change"]
        bg = "#d9f0dc" if ch.startswith("↑") else "#fde2e1" if ch.startswith("↓") else ""
        return [f"background-color: {bg}" if bg else ""] * len(row)

    st.dataframe(df.style.apply(color, axis=1), hide_index=True, width="stretch")
    winner = cands[order[0]]["order_id"]
    if winner != cands[0]["order_id"]:
        st.warning(f"With these weights DFPR would pick **#{winner}** instead of #{cands[0]['order_id']}.")
    else:
        st.success(f"With these weights DFPR still picks **#{winner}**.")
    return w


def formula(dec: dict, w: Weights) -> None:
    st.subheader("The formula, filled in")
    ids = [c["order_id"] for c in dec["candidates"]]
    oid = st.selectbox("Order", ids, format_func=lambda o: f"#{o}", key=f"formula_{dec['time']}")
    c = next(c for c in dec["candidates"] if c["order_id"] == oid)
    f = c["factors"]
    st.latex(r"P_i(t) = w_u U_i + w_f F_i + w_w W_i - w_d D_i - w_c C_i - w_r R_i")
    terms = " ".join(
        f"{'+' if SIGNS[k] > 0 else '-'} {getattr(w, k.lower()):.2f}\\cdot{f[k]:.2f}" for k in FACTOR_KEYS
    ).lstrip("+ ")
    p = combine(Factors(**f), w)
    st.latex(rf"P_{{\#{oid}}} = {terms} = \mathbf{{{p:.3f}}}")
    st.caption("Factor values U, F, W, D, C, R are each normalised to [0, 1] (formulas in the README). "
               "Weights shown are the what-if sliders above.")


def render(trace: Trace) -> None:
    explainer(
        "DFPR gives every waiting order a score P built from six factors. Bars to the **right** push an order "
        "up the queue (urgent, food ready on time, waited long); bars to the **left** push it down (long trip, "
        "traffic delay, rider would wait at the restaurant). The black diamond is the total; the top order wins."
    )
    if trace.meta["method"] != "dfpr":
        st.info(f"This run uses **{method_label(trace.meta['method'])}**, which does not compute the DFPR score. "
                "Choose **DFPR** as the dispatch method in the sidebar (and press Run) to see score breakdowns.")
        return
    dec = _decision_choice(trace)
    if dec is None:
        st.info("No decision in this run had more than one waiting order, so there is nothing to compare. "
                "Try a busier preset such as *Lunch rush*.")
        return
    show(breakdown_chart(dec), "score_breakdown", "dfpr_score_breakdown")
    run_w = trace.meta["weights"] or {k: 1.0 for k in "ufwdcr"}
    if st.session_state.get("wi_run") != id(trace):  # new run: start the what-if from its weights
        st.session_state["wi_run"] = id(trace)
        for k in "ufwdcr":
            st.session_state[f"wi_{k}"] = float(run_w[k])
    w = what_if(dec, run_w)
    formula(dec, w)
