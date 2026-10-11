"""Friction locale : part de l'offre en fenetre allongee (`real_pipeline.delayed_supply_share`)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dashboard.scenarios import run_scenario
from dashboard.scenarios.real_pipeline import delayed_supply_share, holdings_at
from shared.models import (
    MintEvent,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    TransferEvent,
)

T0 = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
A, B, C = (f"0x{i:040x}" for i in (1, 2, 3))


def _tx(i: int) -> str:
    return f"0x{i:064x}"


def _events() -> list:
    return [
        MintEvent(tx_hash=_tx(1), log_index=0, block_number=1, chain_id=43113,
                  observed_at=T0, recipient=A, amount=100, request_id=0),
        TransferEvent(tx_hash=_tx(2), log_index=0, block_number=2, chain_id=43113,
                      observed_at=T0 + timedelta(minutes=1), sender=A, recipient=B, amount=40,
                      is_ghost=True),
        TransferEvent(tx_hash=_tx(3), log_index=0, block_number=3, chain_id=43113,
                      observed_at=T0 + timedelta(minutes=2), sender=B, recipient=C, amount=10,
                      is_ghost=True),
    ]


def _delay(address: str, start: datetime, minutes: int = 60) -> ResponseAction:
    return ResponseAction(action_id=f"act-{address[-1]}", action_type=ResponseActionType.DELAY,
                          status=ResponseActionStatus.EXPIRED, created_at=start,
                          expires_at=start + timedelta(minutes=minutes),
                          perimeter_address=address)


def test_holdings_follow_events() -> None:
    balances, minted = holdings_at(_events(), T0 + timedelta(minutes=5))
    assert minted == 100
    assert balances == {A.lower(): 60, B.lower(): 30, C.lower(): 10}


def test_share_is_peak_over_overlapping_delays() -> None:
    events = _events()
    later = T0 + timedelta(minutes=5)
    # Offre = 900 initiale + 100 mintee ; B (30) puis B + C (40) retardes ensemble.
    actions = [_delay(B, later), _delay(C, later + timedelta(minutes=1))]
    assert delayed_supply_share(events, actions, initial_supply=900) == 40 / 1000


def test_no_delay_gives_none() -> None:
    assert delayed_supply_share(_events(), [], initial_supply=900) is None


def test_scenarios_report_delayed_share() -> None:
    attack = run_scenario("B", seed=20).metric("main", "delayed_supply_share").value
    false_alert = run_scenario("N3", seed=20).metric("main", "delayed_supply_share").value
    assert attack is not None and 0 < attack < 100
    assert false_alert is not None and 0 < false_alert < 100
