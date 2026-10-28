"""Smoke tests for the Streamlit demo: every preset renders every tab without errors."""

from __future__ import annotations

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
pytest.importorskip("plotly")

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
PRESETS = ["Small and clear", "Readiness matters", "Lunch rush", "Traffic jam"]


def run_app(preset: str | None = None):
    at = st_testing.AppTest.from_file(APP, default_timeout=240)
    at.run()
    if preset is not None:
        at.sidebar.selectbox(key="preset").set_value(preset)
        at.run()
    return at


def assert_clean(at) -> None:
    assert not at.exception, [e.message for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_default_load_renders() -> None:
    at = run_app()
    assert_clean(at)
    assert "Dynamic Food-Readiness-Aware Priority Routing" in at.title[0].value
    assert len(at.tabs) == 6


@pytest.mark.parametrize("preset", PRESETS)
def test_presets_render(preset: str) -> None:
    assert_clean(run_app(preset))


@pytest.mark.parametrize("method", ["nearest", "static_priority", "fifo"])
def test_baseline_methods_render(method: str) -> None:
    at = run_app()
    at.sidebar.selectbox(key="p_method").set_value(method)
    at.sidebar.button(key="run_btn").click()
    at.run()
    assert_clean(at)


def test_zero_orders_renders() -> None:
    at = run_app()
    at.sidebar.number_input(key="p_rate").set_value(0.0)
    at.sidebar.button(key="run_btn").click()
    at.run()
    assert_clean(at)


def test_export_report(tmp_path, monkeypatch) -> None:
    import sys
    sys.path.insert(0, str(Path(APP).parent))
    import ui.export as export_mod

    monkeypatch.setattr(export_mod, "ROOT", tmp_path)
    at = run_app()
    at.sidebar.button(key="export_btn").click()
    at.run()
    assert_clean(at)
    folders = list((tmp_path / "app_exports").iterdir())
    assert len(folders) == 1
    names = {p.name for p in folders[0].iterdir()}
    assert {"metrics.json", "orders.csv", "decisions.csv", "events.csv", "heap_ops.csv", "charts"} <= names
    assert any((folders[0] / "charts").glob("*.html"))
