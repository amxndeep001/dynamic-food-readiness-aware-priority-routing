"""DFPR interactive demo.

    streamlit run app/app.py          (from the dfpr/ folder)

The app only *replays* simulations: every run is computed once by the real
simulator and dispatchers (sim/, dispatch/) with a TraceRecorder attached,
cached, and then played back.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st  # noqa: E402

st.set_page_config(page_title="DFPR demo", page_icon="🛵", layout="wide", initial_sidebar_state="expanded")

from ui import export, runs, sidebar, theme  # noqa: E402
from ui.presets import PRESETS  # noqa: E402
from ui.tabs import compare, ds, live, scaling, score, waits  # noqa: E402

TITLE = "Dynamic Food-Readiness-Aware Priority Routing (DFPR)"
MEMBERS = "Simar Bhatia (26MCS0020) · Yash Mohadikar (26MCS0037) · Amandeep Singh Bhatti (26MCS0046)"


def header() -> None:
    st.title(f"🛵 {TITLE}")
    st.markdown(f"<div class='dfpr-sub'><b>Data Structures Project</b> · {MEMBERS}</div>", unsafe_allow_html=True)


def main() -> None:
    theme.apply_css()
    params = sidebar.render()
    header()
    preset = params.get("preset")
    if preset in PRESETS:
        st.info(f"**Preset: {preset}.** {PRESETS[preset]['caption']}")

    with st.spinner("Simulating (first run of these settings only; results are cached)…"):
        trace = runs.get_trace(params)
    st.session_state["_figures"] = {}

    names = ["🗺️ Live Dispatch", "📊 Score Breakdown", "⏱️ Waiting Times", "⚖️ Method Comparison",
             "🌳 Data Structures", "📈 Scalability & Ablation"]
    tabs = st.tabs(names)
    with tabs[0]:
        live.render(trace, params)
    with tabs[1]:
        score.render(trace)
    with tabs[2]:
        waits.render(trace)
    with tabs[3]:
        compare.render(trace, params)
    with tabs[4]:
        ds.render(trace)
    with tabs[5]:
        scaling.render()

    if st.session_state.pop("do_export", False):
        folder, n, pngs = export.export_report(trace, params, st.session_state.get("_figures", {}))
        note = "" if pngs else " PNG files need the optional 'kaleido' package; use each chart's camera icon instead."
        st.session_state["export_slot"].success(f"Saved {n} charts + metrics to `{folder}`.{note}")


main()
