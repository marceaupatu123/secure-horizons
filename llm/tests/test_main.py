"""Tests du point d'entree `python -m llm` et de la demo hors ligne (aucun AWS)."""

from __future__ import annotations

from typing import Any

import pytest

from llm.__main__ import is_live_mode, main, offline_settings
from llm.demo import (
    OfflineConverseStub,
    fictive_actions,
    fictive_alert,
    fictive_audit_entries,
)
from llm.prompts import SYSTEM_PROMPT_EXPLAIN, SYSTEM_PROMPT_REPORT
from llm.report import REPORT_SECTIONS, IncidentNarrative


@pytest.mark.parametrize(
    ("argv", "env", "expected"),
    [
        ([], {}, False),
        (["--live"], {}, True),
        ([], {"LLM_LIVE": "1"}, True),
        ([], {"LLM_LIVE": "0"}, False),
    ],
)
def test_is_live_mode(argv: list[str], env: dict[str, str], expected: bool) -> None:
    assert is_live_mode(argv, env) is expected


def test_offline_settings_defaults() -> None:
    settings = offline_settings({})
    assert settings.aws_region == "us-east-1"
    assert settings.bedrock_model_id


def test_main_offline_never_calls_aws(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("boto3.client ne doit pas être appelé hors ligne")

    monkeypatch.setattr("llm.client.boto3.client", forbidden)
    monkeypatch.setattr("llm.client.RateLimiter.wait", lambda self: None)
    monkeypatch.delenv("LLM_LIVE", raising=False)

    assert main([]) == 0
    out = capsys.readouterr().out
    assert "hors ligne" in out
    assert "# Rapport d'incident" in out
    for heading in REPORT_SECTIONS:
        assert heading in out
    assert "À compléter" not in out


def test_offline_stub_answers() -> None:
    stub = OfflineConverseStub()
    report = stub.converse(system=[{"text": SYSTEM_PROMPT_REPORT}], messages=[])
    narrative = IncidentNarrative.model_validate_json(
        report["output"]["message"]["content"][0]["text"]
    )
    assert narrative.description
    explain = stub.converse(system=[{"text": SYSTEM_PROMPT_EXPLAIN}], messages=[])
    assert "ne décide rien" in explain["output"]["message"]["content"][0]["text"]


def test_fictive_data_is_consistent() -> None:
    alert = fictive_alert()
    assert all(a.triggering_alert_id == alert.alert_id for a in fictive_actions(alert))
    assert len(fictive_audit_entries(alert)) == 2
