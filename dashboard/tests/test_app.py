"""Test de fumee de l'app Streamlit via AppTest (sans navigateur)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.demo_data import generate_demo_dataset
from dashboard.view_model import PerimeterState, compute_summary

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")
FORBIDDEN_WORD = "prouv"  # couvre toutes les formes du mot (cf. docs/CLAIMS.md)


def _run() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def _metric_value(at: AppTest, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


def test_app_renders() -> None:
    at = _run()
    assert not at.exception
    assert "Crypto-Secure" in at.title[0].value
    assert any("synthétiques" in i.value for i in at.info)
    assert len(at.metric) >= 4
    assert len(at.dataframe) >= 4


def test_slider_updates_metrics_from_computation() -> None:
    at = _run()
    slider = at.slider(key="sim_offset")
    offset = slider.max
    slider.set_value(offset).run()
    assert not at.exception
    d = generate_demo_dataset()
    expected = compute_summary(d, d.reference_time + timedelta(minutes=offset))
    assert _metric_value(at, "Périmètres retardés") == str(
        expected.perimeter_count_by_state[PerimeterState.DELAYED.value]
    )


def test_no_forbidden_wording() -> None:
    at = _run()
    texts = [e.value for group in (at.title, at.header, at.subheader, at.markdown,
                                   at.caption, at.info) for e in group]
    assert all(FORBIDDEN_WORD not in t.lower() for t in texts)
