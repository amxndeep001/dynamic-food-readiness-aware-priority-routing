"""Turning sidebar parameters into a config, and cached recorded runs.

All simulation logic lives in the existing packages (sim/, dispatch/); this
module only builds a config dict and calls ``sim.recorder.record_run``.

Traces are cached with ``st.cache_resource`` (keyed on the parameters):
playback re-renders several times a second, and ``st.cache_data`` would
deep-copy a multi-MB trace on every access. Traces are read-only, so sharing
one object is safe.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from sim.config import deep_merge, load_config
from sim.recorder import Trace, record_run

ROOT = Path(__file__).resolve().parents[2]
TUNED_FILE = ROOT / "results" / "best_weights.json"
EQUAL = {k: 1.0 for k in "ufwdcr"}


def tuned_weights() -> dict[str, float]:
    """Weights from tuning (results/best_weights.json), or equal weights if absent."""
    try:
        return {k: float(v) for k, v in json.loads(TUNED_FILE.read_text())["weights"].items()}
    except (OSError, KeyError, ValueError):
        return dict(EQUAL)


def build_config(p: dict) -> dict:
    """Config for one run from the (JSON-serialisable) parameter dict ``p``."""
    grid = int(p["grid"])
    n_rest = max(3, min(40, round(grid * grid * 0.064)))
    overrides = {
        "city": {"grid_size": grid, "num_restaurants": n_rest, "cluster_sigma_m": 600 * grid / 25},
        "riders": {"count": int(p["riders"])},
        "demand": {"base_rate_per_hour": float(p["rate"]), "prep_noise_sigma": float(p["sigma"])},
        "sim": {"start_hour": float(p["start_hour"]), "end_hour": float(p["start_hour"]) + float(p["hours"]),
                "drain_minutes": 90},
        "dfpr": {"weights": dict(p["weights"]), "weights_file": None},
    }
    traffic: dict = {"scripted_incidents": p.get("incidents", [])}
    if not p["traffic"]:
        traffic.update(tod_profile=[[0, 1.0], [24, 1.0]], incident_rate_per_hour=0, scripted_incidents=[])
    overrides["traffic"] = traffic
    if p.get("peaks") is not None:
        overrides["demand"]["scenarios"] = {"peak": {"peaks": p["peaks"]}}
    return deep_merge(load_config(), overrides)


def run_key(p: dict, method: str | None = None) -> str:
    q = dict(p)
    if method is not None:
        q["method"] = method
    return json.dumps(q, sort_keys=True)


@st.cache_resource(show_spinner=False, max_entries=40)
def _cached_trace(key: str) -> Trace:
    p = json.loads(key)
    cfg = build_config(p)
    specs = rider_starts = None
    if p.get("scripted"):
        from ui.presets import scripted_world  # local import: presets import this module

        specs, rider_starts = scripted_world(p["scripted"], cfg)
    return record_run(cfg, p["method"], "peak" if p["peak"] else "normal", int(p["seed"]),
                      specs=specs, rider_starts=rider_starts)


def get_trace(p: dict, method: str | None = None) -> Trace:
    """Recorded run for parameters ``p`` (optionally with another method)."""
    return _cached_trace(run_key(p, method))
