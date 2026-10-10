"""Tests du rapport d'incident pre-rempli (faux client Bedrock, aucun reseau)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError

from llm.client import REPORT_MAX_TOKENS, BedrockClient
from llm.prompts import SYSTEM_PROMPT_REPORT
from llm.report import (
    AI_NO_DECISION_LINE,
    PLACEHOLDER_PREFIX,
    REPORT_DISCLAIMER,
    REPORT_SECTIONS,
    build_incident_report,
)
from llm.tests.conftest import (
    ADDR_SUBJECT,
    FakeBedrockRuntime,
    RecordingRateLimiter,
    converse_response,
)
from shared.config import Settings
from shared.models import (
    Alert,
    AuditLogEntry,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
)

T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

NARRATIVE = {
    "description": "Description fictive.",
    "probable_cause": "Cause fictive.",
    "impact": "Impact fictif.",
    "mitigation": "Mitigation fictive.",
}


@pytest.fixture
def actions(alert: Alert) -> list[ResponseAction]:
    return [
        ResponseAction(
            action_id="ACT-DELAY",
            action_type=ResponseActionType.DELAY,
            status=ResponseActionStatus.APPLIED,
            created_at=T0 + timedelta(seconds=30),
            expires_at=T0 + timedelta(minutes=30),
            perimeter_address=ADDR_SUBJECT,
            triggering_alert_id=alert.alert_id,
        ),
        ResponseAction(
            action_id="ACT-DESTROY",
            action_type=ResponseActionType.DESTROY,
            status=ResponseActionStatus.APPLIED,
            created_at=T0 + timedelta(minutes=10),
            perimeter_address=ADDR_SUBJECT,
            triggering_alert_id=alert.alert_id,
            decision_id="DEC-1",
        ),
        ResponseAction(
            action_id="ACT-PAUSE",
            action_type=ResponseActionType.GLOBAL_PAUSE,
            status=ResponseActionStatus.PROPOSED,
            created_at=T0 + timedelta(minutes=12),
            triggering_alert_id=alert.alert_id,
        ),
    ]


@pytest.fixture
def audit_entries() -> list[AuditLogEntry]:
    # Volontairement hors ordre chronologique.
    return [
        AuditLogEntry(
            entry_id="AUD-2",
            recorded_at=T0 + timedelta(minutes=11),
            actor="multisig",
            event_type="destroy_confirmed",
            payload={"decision_id": "DEC-1"},
            message="Destruction confirmée (fictif)",
        ),
        AuditLogEntry(
            entry_id="AUD-1",
            recorded_at=T0 + timedelta(seconds=10),
            actor="monitor:rule_mint",
            event_type="alert_raised",
            payload={},
            message="Alerte levée (fictif)",
        ),
    ]


def _client(
    settings: Settings, limiter: RecordingRateLimiter, fake: FakeBedrockRuntime
) -> BedrockClient:
    return BedrockClient(settings, rate_limiter=limiter, client=fake)


def _ok_fake(events: list[str], text: str | None = None) -> FakeBedrockRuntime:
    return FakeBedrockRuntime(
        events, converse_response({"text": text if text is not None else json.dumps(NARRATIVE)})
    )


def test_deterministic_fields_and_single_llm_call(
    settings: Settings,
    limiter: RecordingRateLimiter,
    events: list[str],
    alert: Alert,
    actions: list[ResponseAction],
    audit_entries: list[AuditLogEntry],
) -> None:
    fake = _ok_fake(events)
    report = build_incident_report(
        alert, _client(settings, limiter, fake), actions, audit_entries, generated_at=T0
    )

    assert report.report_id == f"IR-{alert.alert_id}"
    assert report.incident_id == alert.alert_id
    assert report.detected_at == alert.created_at
    assert report.generated_at == T0
    assert report.kind == alert.kind
    assert report.severity == alert.severity
    assert report.suspect_amount == alert.suspect_amount
    assert report.seeds == alert.seeds
    assert report.total_seed_suspect_amount == sum(s.suspect_amount for s in alert.seeds)
    assert report.narrative_source == "llm"
    assert report.narrative.model_dump() == NARRATIVE

    assert events == ["wait", "converse"]
    call = fake.calls[0]
    assert call["system"] == [{"text": SYSTEM_PROMPT_REPORT}]
    assert call["inferenceConfig"]["maxTokens"] == REPORT_MAX_TOKENS


def test_timeline_sorted_and_complete(
    settings: Settings,
    limiter: RecordingRateLimiter,
    events: list[str],
    alert: Alert,
    actions: list[ResponseAction],
    audit_entries: list[AuditLogEntry],
) -> None:
    report = build_incident_report(
        alert, _client(settings, limiter, _ok_fake(events)), actions, audit_entries
    )
    times = [entry.at for entry in report.timeline]
    assert times == sorted(times)
    # alerte + 3 actions + 1 expiration (delay) + 2 entrees d'audit
    assert len(report.timeline) == 7
    assert report.timeline[0].event == "alerte créée"
    details = " ".join(entry.detail for entry in report.timeline)
    for expected in ("ACT-DELAY", "ACT-DESTROY", "ACT-PAUSE", "Destruction confirmée", "Alerte levée"):
        assert expected in details
    assert any("expiration prévue" in entry.event for entry in report.timeline)


def test_decisions_who_decided_what(
    settings: Settings,
    limiter: RecordingRateLimiter,
    events: list[str],
    alert: Alert,
    actions: list[ResponseAction],
) -> None:
    report = build_incident_report(alert, _client(settings, limiter, _ok_fake(events)), actions)
    by_id = {d.action_id: d.decided_by for d in report.decisions}
    assert "IA" in by_id["ACT-DELAY"]
    assert by_id["ACT-DESTROY"] == "multisig 2/3 (decision_id=DEC-1)"
    assert "non référencée" in by_id["ACT-PAUSE"]


def test_json_in_fences_accepted(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], alert: Alert
) -> None:
    fenced = "```json\n" + json.dumps(NARRATIVE) + "\n```"
    report = build_incident_report(alert, _client(settings, limiter, _ok_fake(events, fenced)))
    assert report.narrative_source == "llm"
    assert report.narrative.impact == NARRATIVE["impact"]


def test_markdown_rendering(
    settings: Settings,
    limiter: RecordingRateLimiter,
    events: list[str],
    alert: Alert,
    actions: list[ResponseAction],
    audit_entries: list[AuditLogEntry],
) -> None:
    report = build_incident_report(
        alert, _client(settings, limiter, _ok_fake(events)), actions, audit_entries
    )
    md = report.to_markdown()
    positions = [md.index(heading) for heading in REPORT_SECTIONS]
    assert positions == sorted(positions)
    assert REPORT_DISCLAIMER in md
    assert AI_NO_DECISION_LINE in md
    assert alert.alert_id in md
    assert str(alert.suspect_amount) in md
    for seed in alert.seeds:
        assert seed.address in md
    assert "rédaction IA — à relire" in md


def test_markdown_escapes_pipes(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], alert: Alert
) -> None:
    piped = alert.model_copy(update={"reason": "a | b"})
    md = build_incident_report(piped, _client(settings, limiter, _ok_fake(events))).to_markdown()
    assert "a \\| b" in md


def test_llm_error_gives_placeholder(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], alert: Alert
) -> None:
    error = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "Converse")
    fake = FakeBedrockRuntime(events, error=error)
    report = build_incident_report(alert, _client(settings, limiter, fake))

    assert report.narrative_source == "placeholder"
    for value in report.narrative.model_dump().values():
        assert value.startswith(PLACEHOLDER_PREFIX)
    assert report.incident_id == alert.alert_id
    assert report.suspect_amount == alert.suspect_amount
    assert len(fake.calls) == 1
    assert "rédaction IA — à relire" not in report.to_markdown()


@pytest.mark.parametrize("text", ["pas du JSON", '{"description": "seul champ"}'])
def test_bad_llm_answer_gives_placeholder(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], alert: Alert, text: str
) -> None:
    fake = _ok_fake(events, text)
    report = build_incident_report(alert, _client(settings, limiter, fake))
    assert report.narrative_source == "placeholder"
    assert report.narrative.description.startswith(PLACEHOLDER_PREFIX)
    assert len(fake.calls) == 1
