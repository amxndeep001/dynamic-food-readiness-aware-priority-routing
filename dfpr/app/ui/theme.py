"""Colours, fonts and Plotly styling shared by every tab (projector-friendly)."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from experiments.common import COLORS as METHOD_COLORS
from experiments.common import LABELS as METHOD_LABELS

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
ROAD_FREE = "#cfcdc6"

FONT = dict(family="Inter, Segoe UI, Arial, sans-serif", size=16, color=INK)

# Rider status: one colour each, never reused for methods within the same chart.
RIDER_COLORS = {
    "idle": "#8a8880",
    "to_restaurant": "#2a78d6",
    "waiting_at_restaurant": "#e34948",
    "to_customer": "#008300",
}
RIDER_LABELS = {
    "idle": "Idle (free)",
    "to_restaurant": "Going to restaurant",
    "waiting_at_restaurant": "Waiting for food",
    "to_customer": "Delivering",
}
FOOD_READY = "#1baf7a"
FOOD_COOKING = "#eb6834"

# Traffic multiplier bins for road colouring (green -> red), with legend labels.
TRAFFIC_BINS = [
    (1.0, 1.1, "#9fd8a8", "Free flow"),
    (1.1, 1.3, "#d6d36a", "Light traffic"),
    (1.3, 1.6, "#f0a33a", "Slow (x1.3-1.6)"),
    (1.6, 2.2, "#e2572f", "Heavy (x1.6-2.2)"),
    (2.2, 99.0, "#9e1b1b", "Jam (>x2.2)"),
]

# DFPR factors: sign shown in the label; colours from the categorical palette.
FACTOR_COLORS = {"U": "#2a78d6", "F": "#1baf7a", "W": "#6250d6", "D": "#eda100", "C": "#e87ba4", "R": "#e34948"}
FACTOR_NAMES = {
    "U": "Urgency (+)",
    "F": "Food readiness (+)",
    "W": "Waiting time (+)",
    "D": "Distance (−)",
    "C": "Traffic delay (−)",
    "R": "Rider wait (−)",
}

PLOTLY_CONFIG = {
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "scale": 2, "filename": "dfpr_chart"},
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}


def method_color(m: str) -> str:
    return METHOD_COLORS.get(m, "#52514e")


def method_label(m: str) -> str:
    return METHOD_LABELS.get(m, m)


def style(fig: go.Figure, title: str | None = None, height: int = 420, legend: bool = True) -> go.Figure:
    """Apply the shared look: large fonts, light grid, legend on top."""
    # Title sits at the very top of the figure, the legend in its own row just
    # above the plot area, so the two never overlap.
    top = (55 if title else 15) + (45 if legend else 0)
    fig.update_layout(
        title=dict(text=title, font=dict(size=20), x=0.0, xanchor="left", y=0.99, yanchor="top",
                   yref="container") if title else None,
        height=height,
        font=FONT,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        margin=dict(l=10, r=10, t=top, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=15)),
        showlegend=legend,
        hoverlabel=dict(font_size=15),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, automargin=True)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, automargin=True)
    return fig


def show(fig: go.Figure, key: str, filename: str | None = None) -> None:
    """Render a chart; its toolbar camera icon downloads a 2x PNG."""
    cfg = dict(PLOTLY_CONFIG)
    cfg["toImageButtonOptions"] = {**cfg["toImageButtonOptions"], "filename": filename or key}
    st.plotly_chart(fig, key=key, config=cfg, theme=None, width="stretch")
    st.session_state.setdefault("_figures", {})[key] = fig  # collected for "Export run report"


CSS = """
<style>
html, body, [class*="css"] { font-size: 18px; }
.block-container { padding-top: 1.2rem; max-width: 100%; }
h1 { font-size: 2.0rem !important; margin-bottom: 0 !important; }
h2, h3 { font-size: 1.45rem !important; }
[data-testid="stMetricValue"] { font-size: 2.0rem; }
[data-testid="stMetricLabel"] p { font-size: 1.0rem; }
.dfpr-sub { color: #52514e; font-size: 1.05rem; margin-top: 0.1rem; }
.why-card { border-left: 6px solid #2a78d6; background: #f3f6fb; padding: 0.8rem 1rem;
            border-radius: 6px; font-size: 1.05rem; line-height: 1.45; color: #0b0b0b; }
.why-card.baseline { border-left-color: #eb6834; background: #fdf4ef; }
.event-log { font-size: 0.95rem; line-height: 1.5; max-height: 330px; overflow-y: auto; color: #0b0b0b; }
.banner-loss { border-left: 6px solid #e34948; background: #fdf0f0; padding: 0.6rem 1rem; border-radius: 6px; }
.banner-win { border-left: 6px solid #008300; background: #eef7ee; padding: 0.6rem 1rem; border-radius: 6px; }
</style>
"""


def apply_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def explainer(text: str) -> None:
    """The 'What am I looking at?' box at the top of every tab."""
    with st.expander("ℹ️ What am I looking at?", expanded=False):
        st.markdown(text)
