"""Tests du branchement contrat protege -> detection (#104). Donnees FICTIVES."""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction

from detection.detector import RuleBasedMonitor
from detection.inputs import AdminAnnouncement, AdminEventKind
from detection.pipeline import DetectionPipeline, run_live
from detection.provenance import (
    correlator_context_provider,
    mint_context_from_provenance,
    rate_from_wad,
)
from monitor.config import MonitorConfig
from monitor.listener import ChainListener
from monitor.tests.test_protected import (
    ALICE,
    ATTACKER,
    BOB,
    FIXED_NOW,
    MINTER,
    TOKEN,
    WAD,
    ZERO,
    FakeEth,
    FakeWeb3,
    role_granted,
    swap_completed,
    swap_requested,
    transfer,
)
from monitor.protected import MintProvenance, event_topic
from shared.models import Alert, AlertSeverity

_TOTAL_SUPPLY = "0x" + f"{10**30:064x}"


class _SupplyEth(FakeEth):
    def call(self, transaction):  # type: ignore[no-untyped-def]
        return _TOTAL_SUPPLY


def _run(logs, monitor: RuleBasedMonitor | None = None) -> list[Alert]:  # type: ignore[no-untyped-def]
    alerts: list[Alert] = []
    pipeline = DetectionPipeline(monitor or RuleBasedMonitor(), alerts.append)
    config = MonitorConfig(
        rpc_url=None, token_address=TOKEN, minter_address=MINTER, start_block=0
    )
    listener = ChainListener(
        config,
        FakeWeb3(_SupplyEth(logs, 50)),
        sleep=lambda _: None,
        now=lambda: FIXED_NOW,
    )
    run_live(pipeline, config, listener, max_polls=1, now=lambda: FIXED_NOW)
    return alerts


def test_rate_from_wad_convertit_6_vers_18_decimales() -> None:
    # 1 USDC (1e6 base units) a 1:1 -> 1e18 base units mintees.
    assert Fraction(10**6) * rate_from_wad(WAD) == 10**18


def test_mint_honnete_ne_leve_aucune_alerte() -> None:
    logs = [
        swap_requested(0, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        transfer(ZERO, ALICE, 10**18, block=11, index=0, tx=2),
        swap_completed(0, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
    ]
    assert _run(logs) == []


def test_mint_gonfle_vers_un_tiers_leve_i1_et_i3() -> None:
    """Resolv rejoue contre un contrat qui ment : depot 1 USDC, 400 minte ailleurs."""
    logs = [
        swap_requested(3, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        transfer(ZERO, ATTACKER, 400 * 10**18, block=11, index=0, tx=2),
        swap_completed(3, ALICE, ATTACKER, 400_000_000, 400 * 10**18, WAD, block=11, index=1, tx=2),
    ]
    (alert,) = _run(logs)
    assert alert.severity == AlertSeverity.CRITICAL
    assert "I1 viole" in alert.reason and "I3 viole" in alert.reason
    assert alert.subject_address.lower() == ATTACKER


def test_mint_hors_chemin_prevu_leve_i4() -> None:
    logs = [transfer(ZERO, ATTACKER, 10**24, block=11, index=0, tx=9)]
    (alert,) = _run(logs)
    assert alert.severity == AlertSeverity.CRITICAL
    assert "I4 viole" in alert.reason
    assert alert.suspect_amount == 10**24
    assert alert.seeds and alert.seeds[0].suspect_amount == 10**24


def test_role_accorde_non_annonce_alerte_immediatement() -> None:
    logs = [role_granted(event_topic("SERVICE_ROLE"), ATTACKER, BOB, block=5, index=0, tx=1)]
    (alert,) = _run(logs)
    assert "role_granted" in alert.reason and "SERVICE_ROLE" in alert.reason
    assert alert.suspect_amount == 0 and alert.seeds == []


def test_role_annonce_ne_leve_pas_d_alerte() -> None:
    monitor = RuleBasedMonitor(
        announced_admin_changes=[
            AdminAnnouncement(kind=AdminEventKind.ROLE_GRANTED, subject_address=ATTACKER)
        ]
    )
    logs = [role_granted(event_topic("SERVICE_ROLE"), ATTACKER, BOB, block=5, index=0, tx=1)]
    assert _run(logs, monitor) == []


def test_provenance_absente_donne_path_unexpected() -> None:
    assert mint_context_from_provenance(None).path_unexpected is True
    ctx = mint_context_from_provenance(
        MintProvenance(
            request_id=1,
            depositor=ALICE,
            deposit_amount=5,
            rate_wad=WAD,
            source="request",
            claimed_minted=5 * 10**12,
        )
    )
    assert ctx.path_unexpected is False and ctx.deposit_amount == 5


def test_provider_mint_inconnu_rend_none() -> None:
    from monitor.protected import MintCorrelator
    from shared.models import MintEvent

    provider = correlator_context_provider(MintCorrelator())
    event = MintEvent(
        tx_hash="0x" + "ab" * 32,
        log_index=0,
        block_number=1,
        chain_id=43113,
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        recipient=ALICE,
        amount=1,
        request_id=None,
    )
    assert provider(event) is None


# ------------------------------------------------------------ mode Ghost (#8)


def _run_ghost(logs) -> list[Alert]:  # type: ignore[no-untyped-def]
    from monitor.tests.test_protected import GHOST

    alerts: list[Alert] = []
    pipeline = DetectionPipeline(RuleBasedMonitor(), alerts.append)
    config = MonitorConfig(
        rpc_url=None,
        token_address=TOKEN,
        minter_address=MINTER,
        ghost_address=GHOST,
        start_block=0,
    )
    listener = ChainListener(
        config,
        FakeWeb3(_SupplyEth(logs, 50)),
        sleep=lambda _: None,
        now=lambda: FIXED_NOW,
    )
    run_live(pipeline, config, listener, max_polls=1, now=lambda: FIXED_NOW)
    return alerts


def test_ghost_mint_honnete_et_conversion_ne_levent_aucune_alerte() -> None:
    """Sans le mode Ghost, la conversion serait un faux positif I4 critique."""
    from monitor.protected import ISSUE_KIND_MINT
    from monitor.tests.test_protected import ghost_converted, ghost_issued

    logs = [
        swap_requested(0, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        ghost_issued(ALICE, MINTER, 0, 10**18, ISSUE_KIND_MINT, block=11, index=0, tx=2),
        swap_completed(0, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
        ghost_converted(ALICE, 10**18, 99 * 10**16, 10**16, block=20, index=0, tx=3),
        transfer(ZERO, ALICE, 99 * 10**16, block=20, index=1, tx=3),
    ]
    assert _run_ghost(logs) == []


def test_ghost_mint_gonfle_leve_i1_et_i3() -> None:
    """Resolv avec le Ghost : depot 1 USDC, 400 de Ghost emis a l'attaquant."""
    from monitor.protected import ISSUE_KIND_MINT
    from monitor.tests.test_protected import ghost_issued

    logs = [
        swap_requested(3, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        ghost_issued(ATTACKER, MINTER, 3, 400 * 10**18, ISSUE_KIND_MINT, block=11, index=0, tx=2),
        swap_completed(3, ALICE, ATTACKER, 400_000_000, 400 * 10**18, WAD, block=11, index=1, tx=2),
    ]
    reasons = " | ".join(a.reason for a in _run_ghost(logs))
    assert "I1" in reasons and "I3" in reasons


def test_ghost_m_minte_hors_conversion_leve_i4() -> None:
    logs = [transfer(ZERO, ATTACKER, 10**24, block=11, index=0, tx=9)]
    (alert,) = _run_ghost(logs)
    assert alert.severity == AlertSeverity.CRITICAL
    assert "I4 viole" in alert.reason
