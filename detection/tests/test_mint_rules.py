"""Tests du surveillant de mint a regles (#11, OPEN_ANSWERS §1).

Donnees fictives uniquement. Aucun appel reseau / LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction

from detection.detector import RuleBasedMonitor
from detection.inputs import (
    AdminAnnouncement,
    AdminEvent,
    AdminEventKind,
    MintContext,
)
from shared.models import AlertKind, AlertSeverity, MintEvent

UNIT = 10**6  # base units par token (fictif)
RECIPIENT = "0x" + "a1" * 20
NEW_IMPL = "0x" + "b2" * 20
MINT_TX = "0x" + "c3" * 32
ADMIN_TX = "0x" + "d4" * 32
RATE = Fraction(1)


def _mint(amount: int) -> MintEvent:
    return MintEvent(
        tx_hash=MINT_TX,
        log_index=0,
        block_number=1,
        chain_id=43113,
        observed_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        recipient=RECIPIENT,
        amount=amount,
        request_id=0,  # sentinelle #9 : ne doit pas etre utilisee
    )


def _consistent_context(deposit: int, minted: int, **overrides: object) -> MintContext:
    """Contexte coherent : offre +minted, collateral suffisant, oracle aligne."""
    values: dict[str, object] = {
        "deposit_amount": deposit,
        "rate": RATE,
        "reference_rate": RATE,
        "total_supply_before": 1_000 * UNIT,
        "total_supply_after": 1_000 * UNIT + minted,
        "collateral_value": 1_000 * UNIT + minted,
    }
    values.update(overrides)
    return MintContext(**values)  # type: ignore[arg-type]


def test_legit_big_mint_no_alert() -> None:
    minted = 80_000_000 * UNIT
    alert = RuleBasedMonitor().check_mint(
        _mint(minted), _consistent_context(minted, minted)
    )
    assert alert is None


def test_mint_within_fee_epsilon_no_alert() -> None:
    deposit = 1_000_000 * UNIT
    minted = deposit - deposit // 2000  # 0,05 % de frais < epsilon provisoire
    alert = RuleBasedMonitor().check_mint(
        _mint(minted), _consistent_context(deposit, minted)
    )
    assert alert is None


def test_resolv_like_mint_alerts_on_i1() -> None:
    deposit = 200_000 * UNIT
    minted = 80_000_000 * UNIT
    alert = RuleBasedMonitor().check_mint(
        _mint(minted), _consistent_context(deposit, minted)
    )
    assert alert is not None
    assert alert.kind is AlertKind.MINT
    assert alert.severity is AlertSeverity.CRITICAL
    assert "I1" in alert.reason
    assert "retarder" in alert.reason
    assert alert.subject_address == RECIPIENT
    assert alert.source_tx_hash == MINT_TX
    assert alert.suspect_amount == minted - deposit
    assert len(alert.seeds) == 1
    assert alert.seeds[0].address == RECIPIENT
    assert alert.seeds[0].suspect_amount == minted - deposit
    assert alert.contamination_ratio == (minted - deposit) / minted


def test_supply_drift_alerts_on_i5() -> None:
    minted = 1_000 * UNIT
    context = _consistent_context(
        minted,
        minted,
        total_supply_after=1_000 * UNIT + 2 * minted,
        collateral_value=10_000 * UNIT,
    )
    alert = RuleBasedMonitor().check_mint(_mint(minted), context)
    assert alert is not None
    assert "I5" in alert.reason
    assert "I1" not in alert.reason
    assert alert.severity is AlertSeverity.CRITICAL
    assert alert.seeds == []  # derive non attribuable a une adresse


def test_i5_accounts_for_burns() -> None:
    minted = 1_000 * UNIT
    burned = 300 * UNIT
    context = _consistent_context(
        minted,
        minted,
        total_supply_after=1_000 * UNIT + minted - burned,
        interval_burned_total=burned,
    )
    assert RuleBasedMonitor().check_mint(_mint(minted), context) is None


def test_collateral_breach_alerts_on_i6() -> None:
    minted = 1_000 * UNIT
    context = _consistent_context(minted, minted, collateral_value=500 * UNIT)
    alert = RuleBasedMonitor().check_mint(_mint(minted), context)
    assert alert is not None
    assert "I6" in alert.reason
    assert alert.severity is AlertSeverity.CRITICAL


def test_unannounced_admin_event_alerts() -> None:
    minted = 1_000 * UNIT
    upgrade = AdminEvent(
        kind=AdminEventKind.UPGRADED, subject_address=NEW_IMPL, tx_hash=ADMIN_TX
    )
    context = _consistent_context(minted, minted, admin_events=(upgrade,))
    alert = RuleBasedMonitor().check_mint(_mint(minted), context)
    assert alert is not None
    assert "upgraded" in alert.reason
    assert alert.severity is AlertSeverity.WARNING


def test_announced_admin_event_no_alert() -> None:
    minted = 1_000 * UNIT
    upgrade = AdminEvent(
        kind=AdminEventKind.UPGRADED, subject_address=NEW_IMPL, tx_hash=ADMIN_TX
    )
    monitor = RuleBasedMonitor(
        announced_admin_changes=[
            # casse differente : la comparaison d'adresses ignore la casse
            AdminAnnouncement(
                kind=AdminEventKind.UPGRADED,
                subject_address="0x" + NEW_IMPL[2:].upper(),
            )
        ]
    )
    context = _consistent_context(minted, minted, admin_events=(upgrade,))
    assert monitor.check_mint(_mint(minted), context) is None


def test_oracle_deviation_alerts_with_seed() -> None:
    deposit = 1_000 * UNIT
    manipulated_rate = Fraction(2)
    minted = deposit * 2  # I1 tient avec le mauvais taux
    context = _consistent_context(deposit, minted, rate=manipulated_rate)
    alert = RuleBasedMonitor().check_mint(_mint(minted), context)
    assert alert is not None
    assert "oracle" in alert.reason
    assert "I1" not in alert.reason
    assert alert.seeds[0].suspect_amount == minted - deposit


def test_no_context_no_alert() -> None:
    assert RuleBasedMonitor().check_mint(_mint(80_000_000 * UNIT)) is None


# --- I3 : destinataire = deposant (#91) ---

ATTACKER = "0x" + "e5" * 20


def test_i3_recipient_is_requester_no_alert() -> None:
    minted = 1_000 * UNIT
    context = _consistent_context(minted, minted, requester=RECIPIENT.upper().replace("0X", "0x"))
    assert RuleBasedMonitor().check_mint(_mint(minted), context) is None


def test_i3_diverted_one_to_one_mint_alerts() -> None:
    """Scenario B : demande d'une victime mintee a 1:1 vers une autre adresse.
    I1, I5, I6 et l'oracle sont respectes ; seul I3 le voit."""
    minted = 1_000 * UNIT
    context = _consistent_context(minted, minted, requester=ATTACKER)
    alert = RuleBasedMonitor().check_mint(_mint(minted), context)
    assert alert is not None
    assert alert.kind == AlertKind.MINT
    assert "I3 viole" in alert.reason
    assert alert.suspect_amount == minted
    assert alert.contamination_ratio == 1.0
    assert [s.address for s in alert.seeds] == [RECIPIENT]


def test_i3_skipped_without_requester() -> None:
    minted = 1_000 * UNIT
    assert RuleBasedMonitor().check_mint(_mint(minted), _consistent_context(minted, minted)) is None


def test_i3_invalid_requester_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="requester"):
        MintContext(requester="pas-une-adresse")
