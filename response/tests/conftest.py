"""Fixtures communes aux tests du module response (donnees FICTIVES)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest

from response.orchestrator import ResponseOrchestrator, ResponsePolicy
from shared.models import (
    Alert,
    AlertKind,
    AlertSeed,
    AlertSeverity,
    FreezeDirection,
    FreezeRequest,
    ReleaseDecision,
    ReleaseVerdict,
)

GUARDIANS = (
    "0x5555555555555555555555555555555555555555",
    "0x6666666666666666666666666666666666666666",
    "0x7777777777777777777777777777777777777777",
)
OUTSIDER = "0x9999999999999999999999999999999999999999"
SUSPECT = "0x2222222222222222222222222222222222222222"
SEED = "0x3333333333333333333333333333333333333333"
TX = "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778"
START = datetime(2026, 10, 10, 14, 30, tzinfo=timezone.utc)


class FakeClock:
    """Horloge manuelle (UTC)."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: float) -> None:
        self.now += timedelta(minutes=minutes)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_orchestrator(clock: FakeClock) -> Callable[..., ResponseOrchestrator]:
    def _make(**policy_overrides: object) -> ResponseOrchestrator:
        counter = iter(range(1, 100_000))
        policy = ResponsePolicy(guardians=frozenset(GUARDIANS), **policy_overrides)  # type: ignore[arg-type]
        return ResponseOrchestrator(
            policy,
            clock=clock,
            id_factory=lambda prefix: f"{prefix}-{next(counter)}",
        )

    return _make


@pytest.fixture
def orchestrator(make_orchestrator: Callable[..., ResponseOrchestrator]) -> ResponseOrchestrator:
    return make_orchestrator()


def make_alert(
    severity: AlertSeverity = AlertSeverity.CRITICAL,
    subject: str = SUSPECT,
    seeds: list[AlertSeed] | None = None,
    alert_id: str = "alert-1",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        kind=AlertKind.TRANSFER,
        severity=severity,
        created_at=START,
        monitor_name="rule_transfer",
        subject_address=subject,
        source_tx_hash=TX,
        contamination_ratio=0.87,
        suspect_amount=870,
        reason="Volume eleve ET dispersion effondree (fictif)",
        seeds=seeds or [],
    )


def make_freeze(
    direction: FreezeDirection = FreezeDirection.EXTEND,
    extend_minutes: int | None = 30,
    requested_by: str = "monitor:rule_transfer",
    request_id: str = "fr-1",
    perimeter: str = SUSPECT,
) -> FreezeRequest:
    return FreezeRequest(
        request_id=request_id,
        direction=direction,
        requested_by=requested_by,
        created_at=START,
        perimeter_address=perimeter,
        triggering_alert_id="alert-1",
        contamination_ratio=0.87,
        suspect_amount=870,
        extend_minutes=extend_minutes if direction is FreezeDirection.EXTEND else None,
    )


def make_decision(
    verdict: ReleaseVerdict,
    signers: list[str],
    perimeter: str | None = SUSPECT,
    burn_ratio: float | None = None,
    related_freeze_id: str | None = None,
    threshold: int = 1,
    decision_id: str = "rd-1",
) -> ReleaseDecision:
    return ReleaseDecision(
        decision_id=decision_id,
        verdict=verdict,
        decided_at=START,
        perimeter_address=perimeter,
        related_freeze_id=related_freeze_id,
        signers=signers,
        threshold=threshold,
        burn_ratio=burn_ratio,
        rationale="Decision fictive de test",
    )
