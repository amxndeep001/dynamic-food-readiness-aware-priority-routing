"""Sidebar: presets, simulation parameters, DFPR weights and the Run button."""

from __future__ import annotations

import streamlit as st

from ui.presets import BASE, PRESETS, preset_params
from ui.runs import tuned_weights
from ui.theme import method_label

METHODS = ["dfpr", "nearest", "shortest_path", "static_priority", "nearest_time", "fifo"]
CUSTOM = "Custom (use the controls below)"
WIDGETS = {"seed": "p_seed", "grid": "p_grid", "riders": "p_riders", "rate": "p_rate", "peak": "p_peak",
           "sigma": "p_sigma", "traffic": "p_traffic", "method": "p_method", "start_hour": "p_start",
           "hours": "p_hours"}
HIDDEN = ("incidents", "peaks", "scripted")
FACTOR_LABELS = {"u": "w_u  Urgency", "f": "w_f  Food readiness", "w": "w_w  Waiting time",
                 "d": "w_d  Distance", "c": "w_c  Traffic delay", "r": "w_r  Rider wait"}


def _load(params: dict) -> None:
    for k, key in WIDGETS.items():
        st.session_state[key] = params[k]
    st.session_state["p_hidden"] = {k: params.get(k) for k in HIDDEN}


def _reset_weights() -> None:
    for k, v in tuned_weights().items():
        st.session_state[f"w_{k}"] = round(v, 2)


def _on_preset() -> None:
    name = st.session_state["preset"]
    if name == CUSTOM:
        st.session_state["p_hidden"] = {k: None if k != "incidents" else [] for k in HIDDEN}
        return
    _load(preset_params(name))
    st.session_state["speed"] = PRESETS[name]["speed"]
    st.session_state["compare_with"] = PRESETS[name]["compare"]
    st.session_state["run_params"] = current_params()  # presets run with one click


def current_params() -> dict:
    p = {k: st.session_state[key] for k, key in WIDGETS.items()}
    p.update(st.session_state.get("p_hidden", {}))
    p["incidents"] = p.get("incidents") or []
    p["weights"] = {k: float(st.session_state[f"w_{k}"]) for k in "ufwdcr"}
    p["preset"] = st.session_state.get("preset", CUSTOM)
    return p


def init_state() -> None:
    """First page load: tuned weights and the 'Small and clear' preset, already run."""
    if "initialised" in st.session_state:
        return
    _reset_weights()
    st.session_state["preset"] = "Small and clear"
    _on_preset()
    st.session_state["initialised"] = True


def render() -> dict:
    init_state()
    sb = st.sidebar
    sb.header("Scenario")
    sb.selectbox("Presentation preset", list(PRESETS) + [CUSTOM], key="preset", on_change=_on_preset)
    name = st.session_state["preset"]
    if name in PRESETS:
        sb.caption(PRESETS[name]["caption"])

    sb.header("Simulation")
    sb.selectbox("Dispatch method", METHODS, key="p_method", format_func=method_label)
    c1, c2 = sb.columns(2)
    c1.number_input("Seed", 0, 10_000, key="p_seed")
    c2.number_input("Grid size", 6, 30, key="p_grid", help="City is an N x N street grid (200 m blocks)")
    c1.number_input("Riders", 1, 60, key="p_riders")
    c2.number_input("Orders / hour", 0.0, 200.0, step=5.0, key="p_rate")
    sb.toggle("Peak demand (x2.5 at lunch/dinner)", key="p_peak")
    sb.slider("Prep-time noise σ", 0.0, 0.8, step=0.05, key="p_sigma",
              help="How wrong the restaurants' cooking-time estimates are (lognormal noise)")
    sb.toggle("Traffic (time of day + jams)", key="p_traffic")
    c1, c2 = sb.columns(2)
    c1.number_input("Start hour", 0.0, 22.0, step=0.5, key="p_start")
    c2.number_input("Duration (h)", 0.5, 12.0, step=0.5, key="p_hours")

    sb.header("DFPR weights")
    sb.caption("Defaults are the weights tuned on development seeds (results/best_weights.json).")
    for k, label in FACTOR_LABELS.items():
        sb.slider(label, 0.0, 3.0, step=0.05, key=f"w_{k}")
    sb.button("Reset to tuned", on_click=_reset_weights, width="stretch")

    if sb.button("▶ Run simulation", type="primary", width="stretch", key="run_btn"):
        st.session_state["run_params"] = current_params()

    sb.header("Report")
    if sb.button("📁 Export run report", width="stretch", key="export_btn",
                 help="Saves metrics (JSON), orders/decisions/events (CSV) and every chart (HTML) to app_exports/"):
        st.session_state["do_export"] = True  # done at the end of the page, once all charts exist
    st.session_state["export_slot"] = sb.empty()
    return st.session_state["run_params"]


__all__ = ["render", "current_params", "METHODS", "BASE"]
