"""Tests de la demo interactive animee (#148) : histoire tiree des vrais resultats A et B."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dashboard.demo import run_scenario_quietly
from dashboard.demo_data import DEMO_SEED
from dashboard.story import (
    JOURNAL_DETAIL_MAX_CHARS,
    JOURNAL_MAX_ENTRIES,
    build_story,
    render_story_html,
    story_json,
)

PAGE_PATH = str(Path(__file__).resolve().parents[1] / "pages" / "0_Demo_interactive.py")
FORBIDDEN_WORD = "prouv"  # cf. docs/CLAIMS.md


@pytest.fixture(scope="module")
def results():
    none = frozenset()
    return (run_scenario_quietly("A", seed=DEMO_SEED, disabled=none),
            run_scenario_quietly("B", seed=DEMO_SEED, disabled=none))


@pytest.fixture(scope="module")
def story(results):
    return build_story(*results)


def test_story_a_reprend_les_metriques_mesurees(results, story):
    result_a, _ = results
    assert story.seed == DEMO_SEED
    assert story.a.vulnerable_minted == result_a.metric("vulnerable", "minted").value
    assert story.a.vulnerable_loss == result_a.metric("vulnerable", "protocol_loss").value
    assert story.a.protected_loss == result_a.metric("protected", "protocol_loss").value
    assert story.a.deposit == result_a.metric("vulnerable", "collateral").value
    assert story.a.vulnerable_loss > 0 and story.a.protected_loss == 0


def test_story_b_reprend_les_metriques_mesurees(results, story):
    _, result_b = results
    main = result_b.variants[0].name
    assert story.b.protocol_loss == result_b.metric(main, "protocol_loss").value
    assert story.b.alert_count == result_b.metric(main, "alert_count").value
    assert story.b.detection_delay_seconds == pytest.approx(
        result_b.metric(main, "detection_delay_seconds").value)
    assert story.b.extended_window_minutes > story.b.normal_window_minutes
    assert 0 < len(story.b.journal) <= JOURNAL_MAX_ENTRIES
    assert all(len(line.detail) <= JOURNAL_DETAIL_MAX_CHARS for line in story.b.journal)


def test_build_story_refuse_un_scenario_inverse(results):
    result_a, result_b = results
    with pytest.raises(ValueError):
        build_story(result_b, result_a)


def test_html_contient_les_donnees_et_le_bandeau(story):
    html = render_story_html(story)
    assert "__STORY_JSON__" not in html
    assert story_json(story) in html
    assert "prefers-reduced-motion" in html
    assert FORBIDDEN_WORD not in html.lower()


def test_story_json_ne_peut_pas_fermer_le_script(story):
    hostile = story.model_copy(deep=True)
    hostile.b.journal[0].detail = "</script><img src=x onerror=alert(1)>"
    payload = story_json(hostile)
    assert "<" not in payload and ">" not in payload
    assert json.loads(payload)["b"]["journal"][0]["detail"].startswith("</script>")


def test_page_rejoue_et_affiche_le_composant(monkeypatch):
    from dashboard.scenarios import fuji_live

    def _offline(*_args, **_kwargs):
        raise ConnectionError("hors réseau en test")

    monkeypatch.setattr(fuji_live, "read_live_state", _offline)
    monkeypatch.setattr(fuji_live, "key_available", lambda: False)
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    assert at.session_state["story"].seed == DEMO_SEED
    assert FORBIDDEN_WORD not in " ".join(c.value for c in at.caption).lower()



def test_html_avec_rejeu_fuji(story):
    from dashboard.scenarios import fuji_live
    from dashboard.story import build_fuji_story

    run = fuji_live.load_run()
    if run is None:
        pytest.skip("aucun rejeu Fuji enregistré")
    html = render_story_html(story.model_copy(update={"fuji": build_fuji_story(run)}))
    assert run.transactions[0].tx_hash in html
    assert FORBIDDEN_WORD not in html.lower()
