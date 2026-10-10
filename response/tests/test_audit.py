"""#19 : journal d'audit DORA (append-only, tracable, export JSONL)."""

from __future__ import annotations

from pathlib import Path

from response.__main__ import main, run_demo
from response.orchestrator import ResponseOrchestrator, ResponsePolicy
from response.tests.conftest import (
    GUARDIANS,
    SUSPECT,
    TX,
    FakeClock,
    make_alert,
    make_decision,
)
from shared.models import AuditLogEntry, ReleaseVerdict


def test_record_audit_returns_entry_and_appends(orchestrator: ResponseOrchestrator) -> None:
    action = orchestrator.handle_alert(make_alert())
    before = len(orchestrator.audit_log)

    entry = orchestrator.record_audit(action, actor="monitor:rule_transfer")

    assert isinstance(entry, AuditLogEntry)
    assert len(orchestrator.audit_log) == before + 1
    assert entry.related_action_id == action.action_id
    assert entry.subject_address == SUSPECT
    assert entry.related_tx_hash == TX
    assert entry.payload["action_type"] == "delay"
    assert entry.payload["status"] == "applied"
    assert entry.payload["triggering_alert_id"] == "alert-1"
    assert all(isinstance(v, str) for v in entry.payload.values())


def test_every_step_is_traced_with_actor(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_DESTROY, list(GUARDIANS[:2]), burn_ratio=0.87)
    )

    log = orchestrator.audit_log
    event_types = [e.event_type for e in log]
    assert event_types[0] == "alert_received"
    assert "freeze_request" in event_types
    assert "release_decision" in event_types
    assert {e.actor for e in log} >= {"monitor:rule_transfer", "multisig"}
    destroy = log[-1]
    assert destroy.payload["action_type"] == "destroy"
    assert destroy.payload["decision_id"] == "rd-1"


def test_rejected_decision_is_traced(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_DESTROY, list(GUARDIANS[:1]), burn_ratio=0.5)
    )

    last = orchestrator.audit_log[-1]
    assert last.payload["status"] == "rejected"
    assert "quorum" in last.message


def test_audit_log_cannot_be_mutated_from_outside(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    snapshot = orchestrator.audit_log
    snapshot[0].payload["severity"] = "tampered"

    assert orchestrator.audit_log[0].payload["severity"] == "critical"


def test_audit_jsonl_export(tmp_path: Path, clock: FakeClock) -> None:
    path = tmp_path / "audit.jsonl"
    orch = ResponseOrchestrator(
        ResponsePolicy(guardians=frozenset(GUARDIANS)), clock=clock, audit_path=path
    )
    orch.handle_alert(make_alert())

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(orch.audit_log)
    parsed = [AuditLogEntry.model_validate_json(line) for line in lines]
    assert [p.entry_id for p in parsed] == [e.entry_id for e in orch.audit_log]


def test_demo_runs_end_to_end(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    orch = run_demo()
    assert any(e.actor == "response:auto_expiry" for e in orch.audit_log)

    main(["--audit-jsonl", str(tmp_path / "demo.jsonl")])
    assert "Journal d'audit" in capsys.readouterr().out
    assert (tmp_path / "demo.jsonl").exists()
