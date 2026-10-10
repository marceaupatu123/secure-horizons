"""Test de fumee de la page Streamlit « Scénarios de démo » (#47) via AppTest."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.scenarios import SIMULATION_LABEL, run_scenario

PAGE_PATH = str(Path(__file__).resolve().parents[1] / "pages" / "1_Scenarios_de_demo.py")
FORBIDDEN_WORD = "prouv"  # couvre toutes les formes du mot (cf. docs/CLAIMS.md)


def _run() -> AppTest:
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    return at


def _launch(at: AppTest, scenario_id: str) -> AppTest:
    at.selectbox(key="scenario_id").set_value(scenario_id)
    at.button(key="run_scenario").click().run()
    return at


def _texts(at: AppTest) -> list[str]:
    groups = (at.title, at.header, at.subheader, at.markdown, at.caption, at.info, at.warning)
    return [e.value for group in groups for e in group]


def test_page_renders() -> None:
    at = _run()
    assert not at.exception
    assert len(at.dataframe) >= 1


def test_scenario_a_side_by_side() -> None:
    at = _launch(_run(), "A")
    assert not at.exception
    labels = {v.label for v in run_scenario("A").variants}
    assert len(labels) >= 2
    assert labels <= {s.value for s in at.subheader}
    assert any(SIMULATION_LABEL in c.value for c in at.caption)


def test_scenario_n1() -> None:
    at = _launch(_run(), "N1")
    assert not at.exception
    assert not at.warning


def test_disabled_optional_scenario() -> None:
    at = _run()
    at.checkbox(key="enable_C").uncheck().run()
    at = _launch(at, "C")
    assert not at.exception
    assert any("désactivé" in w.value for w in at.warning)


def test_no_forbidden_wording() -> None:
    at = _launch(_run(), "B")
    assert all(FORBIDDEN_WORD not in t.lower() for t in _texts(at))
