"""Rapport d'incident DORA (#15) branche sur le scenario B (#113). Aucun appel AWS."""

from __future__ import annotations

import pytest

from dashboard.demo import main as demo_main
from dashboard.scenarios import run_scenario
from dashboard.scenarios.real_report import (
    LLM_LIVE_ENV,
    MODE_OFFLINE,
    report_client,
)
from llm.demo import OFFLINE_TAG


def test_b_has_offline_incident_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LLM_LIVE_ENV, raising=False)
    variant = run_scenario("B", seed=20).variant("main")
    report = variant.incident_report
    assert report is not None
    assert MODE_OFFLINE in report and OFFLINE_TAG in report
    assert "Rapport d'incident" in report
    check = next(c for c in variant.checks if c.label == "rapport d'incident DORA")
    assert check.passed
    # Le rapport s'appuie sur les vraies actions de l'orchestrateur (#17).
    assert any(a.action_id in report for a in variant.dataset.actions)


def test_report_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LLM_LIVE_ENV, raising=False)
    first = run_scenario("B", seed=20).variant("main").incident_report
    second = run_scenario("B", seed=20).variant("main").incident_report
    assert first == second


def test_no_report_without_confirmed_alert() -> None:
    assert run_scenario("N1", seed=20).variant("main").incident_report is None


def test_live_mode_falls_back_offline_without_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LLM_LIVE_ENV, "1")
    for name in ("AWS_REGION", "BEDROCK_MODEL_ID", "FUJI_RPC_URL", "GUARDIAN_PRIVATE_KEY"):
        monkeypatch.delenv(name, raising=False)
    _, mode = report_client()
    assert mode.startswith(MODE_OFFLINE) and "LLM_LIVE=1" in mode


def test_cli_report_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv(LLM_LIVE_ENV, raising=False)
    assert demo_main(["run", "B", "--seed", "20", "--report"]) == 0
    assert "Rapport d'incident" in capsys.readouterr().out
    assert demo_main(["run", "N1", "--seed", "20", "--report"]) == 0
    assert "Aucun rapport d'incident" in capsys.readouterr().out



def test_quiet_warmup_restores_detection_logger_level() -> None:
    """La CLI masque le bruit du surveillant sans effet de bord global (autres tests)."""
    import logging

    from dashboard.demo import quiet_detection_warmup

    logger = logging.getLogger("detection")
    before = logger.level
    with quiet_detection_warmup():
        assert logger.level == logging.ERROR
    assert logger.level == before
    demo_main(["run", "N1", "--seed", "20"])
    assert logger.level == before
