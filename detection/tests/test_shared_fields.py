"""#104 : detection lit les champs partages de `shared/` (#135).

`MintContext` construit depuis le `MintEvent` (sans correlateur, donc aussi en
REPLAY d'un JSONL) et `AdminEvent` partage accepte. Donnees FICTIVES.
"""

from __future__ import annotations

from datetime import datetime, timezone

from detection.detector import RuleBasedMonitor
from detection.inputs import AdminAnnouncement, AdminEventKind
from detection.pipeline import DetectionPipeline, parse_replay_line, run_replay
from detection.provenance import (
    admin_detail,
    admin_event_from_shared,
    mint_context_from_event,
    rate_from_wad,
)
from monitor.protected import event_topic
from shared.models import AdminEvent, Alert, AlertSeverity, MintEvent, MintProvenanceSource
from shared.models import AdminEventKind as SharedKind

ALICE = "0x" + "a1" * 20
BOB = "0x" + "b0" * 20
ATTACKER = "0x" + "ee" * 20
MINTER = "0x" + "22" * 20
WAD = 10**18
T0 = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)
SERVICE_ROLE = event_topic("SERVICE_ROLE")


def _mint(recipient: str, amount: int, **fields: object) -> MintEvent:
    return MintEvent(
        tx_hash="0x" + "cd" * 32,
        log_index=0,
        block_number=11,
        chain_id=43113,
        observed_at=T0,
        recipient=recipient,
        amount=amount,
        **fields,  # type: ignore[arg-type]
    )


def _protected(recipient: str, amount: int, deposit: int, depositor: str = ALICE) -> MintEvent:
    return _mint(
        recipient,
        amount,
        request_id=7,
        depositor=depositor,
        deposit_amount=deposit,
        rate_wad=WAD,
        provenance_source=MintProvenanceSource.REQUEST,
        claimed_minted=amount,
        via_protected_path=True,
    )


def _admin(kind: SharedKind, **fields: object) -> AdminEvent:
    return AdminEvent(
        tx_hash="0x" + "ef" * 32,
        log_index=0,
        block_number=5,
        chain_id=43113,
        observed_at=T0,
        contract_address=MINTER,
        kind=kind,
        subject_address=ATTACKER,
        **fields,  # type: ignore[arg-type]
    )


def _replay(lines: list[str], monitor: RuleBasedMonitor | None = None) -> tuple[list[Alert], int]:
    alerts: list[Alert] = []
    pipeline = DetectionPipeline(monitor or RuleBasedMonitor(), alerts.append)
    summary = run_replay(lines, pipeline, initial_supply=10**30)
    return alerts, summary.admins


# ------------------------------------------------------------ MintContext


def test_contexte_none_si_non_verifie() -> None:
    assert mint_context_from_event(_mint(ALICE, 1)) is None


def test_contexte_path_unexpected_si_hors_chemin() -> None:
    ctx = mint_context_from_event(_mint(ATTACKER, 1, via_protected_path=False))
    assert ctx is not None and ctx.path_unexpected is True


def test_contexte_complet_si_rattache() -> None:
    ctx = mint_context_from_event(_protected(ALICE, 10**18, 1_000_000))
    assert ctx is not None and ctx.path_unexpected is False
    assert ctx.deposit_amount == 1_000_000
    assert ctx.rate == rate_from_wad(WAD)
    assert ctx.requester == ALICE


# ------------------------------------------------------------ REPLAY sans correlateur


def test_replay_mint_honnete_aucune_alerte() -> None:
    alerts, _ = _replay([_protected(ALICE, 10**18, 1_000_000).model_dump_json()])
    assert alerts == []


def test_replay_mint_gonfle_vers_un_tiers_leve_i1_et_i3() -> None:
    """Avant #104, ce JSONL ne levait rien : le replay n'avait aucun contexte."""
    line = _protected(ATTACKER, 400 * 10**18, 1_000_000).model_dump_json()
    (alert,) = _replay([line])[0]
    assert alert.severity == AlertSeverity.CRITICAL
    assert "I1 viole" in alert.reason and "I3 viole" in alert.reason


def test_replay_mint_hors_chemin_leve_i4() -> None:
    line = _mint(ATTACKER, 10**24, via_protected_path=False).model_dump_json()
    (alert,) = _replay([line])[0]
    assert alert.severity == AlertSeverity.CRITICAL and "I4 viole" in alert.reason


def test_replay_mint_erc20_nu_reste_non_verifie() -> None:
    alerts, _ = _replay([_mint(ATTACKER, 10**24).model_dump_json()])
    assert alerts == []


# ------------------------------------------------------------ AdminEvent partage


def test_parse_replay_line_lit_un_admin_event() -> None:
    event = _admin(SharedKind.ROLE_GRANTED, role=SERVICE_ROLE, actor=BOB)
    assert parse_replay_line(event.model_dump_json()) == event


def test_replay_role_non_annonce_alerte() -> None:
    line = _admin(SharedKind.ROLE_GRANTED, role=SERVICE_ROLE, actor=BOB).model_dump_json()
    alerts, admins = _replay([line])
    assert admins == 1
    (alert,) = alerts
    assert "role_granted" in alert.reason and "SERVICE_ROLE" in alert.reason


def test_replay_role_annonce_silencieux() -> None:
    monitor = RuleBasedMonitor(
        announced_admin_changes=[
            AdminAnnouncement(kind=AdminEventKind.ROLE_GRANTED, subject_address=ATTACKER)
        ]
    )
    line = _admin(SharedKind.ROLE_GRANTED, role=SERVICE_ROLE, actor=BOB).model_dump_json()
    alerts, admins = _replay([line], monitor)
    assert alerts == [] and admins == 1


def test_admin_event_partage_vers_detection() -> None:
    rate = _admin(SharedKind.RATE_CHANGED, old_rate_wad=WAD, new_rate_wad=10**36)
    converted = admin_event_from_shared(rate)
    assert converted.kind is AdminEventKind.RATE_CHANGED
    assert converted.subject_address == ATTACKER
    assert admin_detail(rate) == f"taux {WAD} -> {10**36} (x 1e18)"
    unknown_role = "0x" + "99" * 32
    role = _admin(SharedKind.ROLE_REVOKED, role=unknown_role, actor=BOB)
    assert admin_detail(role) == f"role {unknown_role} par {BOB}"
