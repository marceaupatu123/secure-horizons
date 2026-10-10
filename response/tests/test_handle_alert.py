"""#17 : orchestration de la reponse graduee (alerte -> retard auto-expirant)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from response.orchestrator import PerimeterState, ResponseOrchestrator, ResponsePolicy
from response.tests.conftest import GUARDIANS, SEED, START, SUSPECT, FakeClock, make_alert
from shared.models import (
    AlertSeed,
    AlertSeverity,
    ResponseActionStatus,
    ResponseActionType,
)


def test_critical_alert_applies_auto_expiring_delay(orchestrator: ResponseOrchestrator) -> None:
    action = orchestrator.handle_alert(make_alert(AlertSeverity.CRITICAL))

    assert action.action_type is ResponseActionType.DELAY
    assert action.status is ResponseActionStatus.APPLIED
    assert action.expires_at == START + timedelta(minutes=60)
    assert action.triggering_alert_id == "alert-1"
    assert action.decision_id is None
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.DELAYED
    assert orchestrator.is_conversion_suspended(SUSPECT)


def test_alert_never_destroys_nor_pauses(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert(AlertSeverity.CRITICAL))

    types = {a.action_type for a in orchestrator.actions}
    assert types == {ResponseActionType.DELAY}
    assert not orchestrator.global_pause_active


def test_info_alert_only_proposes(orchestrator: ResponseOrchestrator) -> None:
    action = orchestrator.handle_alert(make_alert(AlertSeverity.INFO))

    assert action.action_type is ResponseActionType.DELAY
    assert action.status is ResponseActionStatus.PROPOSED
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.NORMAL
    assert not orchestrator.is_conversion_suspended(SUSPECT)


def test_severity_threshold_is_configurable(make_orchestrator) -> None:  # type: ignore[no-untyped-def]
    orch = make_orchestrator(auto_delay_min_severity=AlertSeverity.CRITICAL)

    assert orch.handle_alert(make_alert(AlertSeverity.WARNING)).status is ResponseActionStatus.PROPOSED


def test_seeds_are_each_delayed_with_their_own_suspicion(
    orchestrator: ResponseOrchestrator,
) -> None:
    seed = AlertSeed(address=SEED, suspect_amount=120, contamination_ratio=0.3)
    subject_action = orchestrator.handle_alert(make_alert(seeds=[seed]))

    assert subject_action.perimeter_address == SUSPECT
    seed_delay = orchestrator.active_delay(SEED)
    assert seed_delay is not None
    assert seed_delay.contamination_ratio == 0.3
    assert seed_delay.suspect_amount == 120


def test_silence_returns_to_normal(orchestrator: ResponseOrchestrator, clock: FakeClock) -> None:
    orchestrator.handle_alert(make_alert())
    clock.advance(60)

    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.NORMAL
    assert not orchestrator.is_conversion_suspended(SUSPECT)
    (delay,) = orchestrator.actions
    assert delay.status is ResponseActionStatus.EXPIRED
    assert orchestrator.audit_log[-1].actor == "response:auto_expiry"


def test_address_case_does_not_split_perimeters(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert(subject="0x" + "ab" * 20))

    assert orchestrator.perimeter_state("0x" + "AB" * 20) is PerimeterState.DELAYED


def test_policy_rejects_impossible_quorum() -> None:
    with pytest.raises(ValueError):
        ResponsePolicy(guardians=frozenset(GUARDIANS), perimeter_quorum=4)
    with pytest.raises(ValueError):
        ResponsePolicy(guardians=frozenset())


def test_policy_global_quorum_defaults_to_unanimity() -> None:
    assert ResponsePolicy(guardians=frozenset(GUARDIANS)).required_global_quorum == 3


def test_naive_clock_is_refused() -> None:
    orch = ResponseOrchestrator(
        ResponsePolicy(guardians=frozenset(GUARDIANS)),
        clock=lambda: START.replace(tzinfo=None),
    )
    with pytest.raises(ValueError):
        orch.handle_alert(make_alert())
