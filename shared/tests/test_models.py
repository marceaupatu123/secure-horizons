"""Tests de fumee des 15 modeles partages (shared.models).

Un test par modele : instanciation avec l'exemple VALIDE de `docs/CONTRACTS.md`,
puis verification qu'un exemple INVALIDE leve bien `pydantic.ValidationError`
(mauvais format d'adresse/hash, ratio hors [0,1], montant negatif/nul, ou champ
extra interdit).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from shared.models import (
    RATE_WAD_SCALE,
    AdminEvent,
    AdminEventKind,
    Alert,
    AlertSeed,
    AuditLogEntry,
    FreezeRequest,
    GhostTokenBurnEvent,
    GhostTokenMintEvent,
    GhostTokenRedemptionEvent,
    MintEvent,
    MintProvenanceSource,
    MintRequest,
    QuarantineRecord,
    ReleaseDecision,
    ResponseAction,
    RiskBeaconUpdate,
    SupplySnapshot,
    TransferEvent,
)

# --- Exemples VALIDES (repris des exemples JSON de docs/CONTRACTS.md) ---

# Mint observe en mode contrat protege (#104) : demande rattachee via SwapRequested.
MINT_EVENT: dict[str, Any] = {
    "tx_hash": "0x3f2a1b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f701",
    "log_index": 0,
    "block_number": 12345678,
    "chain_id": 43113,
    "observed_at": "2026-10-10T14:30:00Z",
    "recipient": "0x1111111111111111111111111111111111111111",
    "amount": 1000000000000000000,
    "request_id": 42,
    "depositor": "0x1111111111111111111111111111111111111111",
    "deposit_amount": 1000000,
    "rate_wad": 1000000000000000000,
    "provenance_source": "request",
    "claimed_minted": 1000000000000000000,
    "via_protected_path": True,
}

# Mint observe par un Transfer ERC-20 nu (hors mode protege) : demande inconnue.
MINT_EVENT_BARE: dict[str, Any] = {
    key: MINT_EVENT[key]
    for key in (
        "tx_hash", "log_index", "block_number", "chain_id", "observed_at",
        "recipient", "amount",
    )
}

TRANSFER_EVENT: dict[str, Any] = {
    "tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
    "log_index": 3,
    "block_number": 12345690,
    "chain_id": 43113,
    "observed_at": "2026-10-10T14:31:12Z",
    "sender": "0x1111111111111111111111111111111111111111",
    "recipient": "0x2222222222222222222222222222222222222222",
    "amount": 250000000000000000,
    "is_ghost": True,
}

ALERT: dict[str, Any] = {
    "alert_id": "a1f0c2e4-0001-4a2b-8c3d-5e6f70819203",
    "kind": "transfer",
    "severity": "critical",
    "created_at": "2026-10-10T14:31:20Z",
    "monitor_name": "rule_transfer",
    "subject_address": "0x2222222222222222222222222222222222222222",
    "source_tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
    "contamination_ratio": 0.87,
    "suspect_amount": 870000000000000000,
    "dispersion_score": 0.04,
    "volume_zscore": 6.2,
    "reason": "Volume eleve ET dispersion effondree : 2 destinations, adresses neuves",
    "seeds": [
        {
            "address": "0x2222222222222222222222222222222222222222",
            "suspect_amount": 870000000000000000,
            "contamination_ratio": 0.87,
        }
    ],
}

RESPONSE_ACTION: dict[str, Any] = {
    "action_id": "act-0001",
    "action_type": "delay",
    "status": "applied",
    "created_at": "2026-10-10T14:31:25Z",
    "expires_at": "2026-10-10T15:01:25Z",
    "perimeter_address": "0x2222222222222222222222222222222222222222",
    "triggering_alert_id": "a1f0c2e4-0001-4a2b-8c3d-5e6f70819203",
    "decision_id": None,
    "contamination_ratio": 0.87,
    "suspect_amount": 870000000000000000,
}

AUDIT_LOG_ENTRY: dict[str, Any] = {
    "entry_id": "audit-0001",
    "recorded_at": "2026-10-10T14:31:25Z",
    "actor": "monitor:rule_transfer",
    "event_type": "response_action",
    "subject_address": "0x2222222222222222222222222222222222222222",
    "related_action_id": "act-0001",
    "related_tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
    "payload": {"action_type": "delay", "window_minutes": "30"},
    "message": "Fenetre Ghost allongee a 30 min sur le perimetre suspect (auto-expirant)",
}

MINT_REQUEST: dict[str, Any] = {
    "request_id": 42,
    "requester": "0x3333333333333333333333333333333333333333",
    "deposit_token": "0x4444444444444444444444444444444444444444",
    "deposit_amount": 1000000000000000000,
    "created_at": "2026-10-10T14:29:50Z",
    "chain_id": 43113,
    "signature": "0xdeadbeefcafe0011223344556677889900aabbccddeeff",
}

QUARANTINE_RECORD: dict[str, Any] = {
    "record_id": "q-0001",
    "address": "0x2222222222222222222222222222222222222222",
    "status": "extended",
    "ghost_balance": 1000000000000000000,
    "contamination_ratio": 0.87,
    "suspect_amount": 870000000000000000,
    "window_opened_at": "2026-10-10T14:31:12Z",
    "window_expires_at": "2026-10-10T15:01:12Z",
    "chain_id": 43113,
}

FREEZE_REQUEST: dict[str, Any] = {
    "request_id": "fr-0001",
    "direction": "extend",
    "requested_by": "monitor:rule_transfer",
    "created_at": "2026-10-10T14:31:22Z",
    "perimeter_address": "0x2222222222222222222222222222222222222222",
    "triggering_alert_id": "a1f0c2e4-0001-4a2b-8c3d-5e6f70819203",
    "contamination_ratio": 0.87,
    "suspect_amount": 870000000000000000,
    "extend_minutes": 30,
}

RELEASE_DECISION: dict[str, Any] = {
    "decision_id": "rd-0001",
    "verdict": "confirm_destroy",
    "decided_at": "2026-10-10T14:45:00Z",
    "perimeter_address": "0x2222222222222222222222222222222222222222",
    "related_freeze_id": "fr-0001",
    "signers": [
        "0x5555555555555555555555555555555555555555",
        "0x6666666666666666666666666666666666666666",
    ],
    "threshold": 2,
    "burn_ratio": 0.87,
    "rationale": "Audit humain : lignage frauduleux confirme, destruction de la fraction suspecte",
}

RISK_BEACON_UPDATE: dict[str, Any] = {
    "beacon_id": "beacon-0001",
    "address": "0x2222222222222222222222222222222222222222",
    "risk_level": "elevated",
    "contamination_ratio": 0.87,
    "suspect_amount": 870000000000000000,
    "published_at": "2026-10-10T14:31:30Z",
    "window_expires_at": "2026-10-10T15:01:12Z",
    "chain_id": 43113,
}

GHOST_MINT_EVENT: dict[str, Any] = {
    "tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
    "log_index": 4,
    "block_number": 12345690,
    "chain_id": 43113,
    "minted_at": "2026-10-10T14:31:12Z",
    "recipient": "0x2222222222222222222222222222222222222222",
    "amount": 250000000000000000,
    "incoming_ratio": 0.87,
    "window_expires_at": "2026-10-10T14:41:12Z",
    "source_transfer_tx": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
}

GHOST_REDEMPTION_EVENT: dict[str, Any] = {
    "tx_hash": "0xaabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
    "log_index": 1,
    "block_number": 12345750,
    "chain_id": 43113,
    "redeemed_at": "2026-10-10T14:42:00Z",
    "holder": "0x7777777777777777777777777777777777777777",
    "ghost_amount": 500000000000000000,
    "token_amount": 499000000000000000,
    "fee_amount": 1000000000000000,
    "contamination_ratio": 0.01,
}

GHOST_BURN_EVENT: dict[str, Any] = {
    "tx_hash": "0xffeeddccbbaa00998877665544332211ffeeddccbbaa00998877665544332211",
    "log_index": 2,
    "block_number": 12345800,
    "chain_id": 43113,
    "burned_at": "2026-10-10T14:46:00Z",
    "address": "0x2222222222222222222222222222222222222222",
    "burned_amount": 870000000000000000,
    "contamination_ratio": 0.87,
    "suspect_amount": 870000000000000000,
    "decision_id": "rd-0001",
}


ADMIN_EVENT: dict[str, Any] = {
    "tx_hash": "0x5b6c7d8e9f00112233445566778899aabbccddeeff00112233445566778899aa",
    "log_index": 1,
    "block_number": 12345600,
    "chain_id": 43113,
    "observed_at": "2026-10-10T14:20:00Z",
    "contract_address": "0x5555555555555555555555555555555555555555",
    "kind": "role_granted",
    "subject_address": "0x6666666666666666666666666666666666666666",
    "actor": "0x7777777777777777777777777777777777777777",
    "role": "0x" + "00" * 32,
}

ADMIN_EVENT_RATE: dict[str, Any] = {
    **{k: v for k, v in ADMIN_EVENT.items() if k not in ("role", "actor")},
    "kind": "rate_changed",
    "old_rate_wad": 1000000000000000000,
    "new_rate_wad": 1002000000000000000,
}

SUPPLY_SNAPSHOT: dict[str, Any] = {
    "chain_id": 43113,
    "block_number": 12345700,
    "observed_at": "2026-10-10T14:35:00Z",
    "token_address": "0x8888888888888888888888888888888888888888",
    "total_supply": 900000000000000000000,
    "ghost_supply": 100000000000000000000,
    "collateral_value": 1000000000000000000000,
}


def _mutate(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Copie profonde de `base` avec champs remplaces/ajoutes."""
    data = copy.deepcopy(base)
    data.update(overrides)
    return data


# (modele, exemple valide, exemple invalide) — une entree par modele.
VALID_CASES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (MintEvent, MINT_EVENT),
    (MintEvent, MINT_EVENT_BARE),
    (TransferEvent, TRANSFER_EVENT),
    (Alert, ALERT),
    (ResponseAction, RESPONSE_ACTION),
    (AuditLogEntry, AUDIT_LOG_ENTRY),
    (MintRequest, MINT_REQUEST),
    (QuarantineRecord, QUARANTINE_RECORD),
    (FreezeRequest, FREEZE_REQUEST),
    (ReleaseDecision, RELEASE_DECISION),
    (RiskBeaconUpdate, RISK_BEACON_UPDATE),
    (GhostTokenMintEvent, GHOST_MINT_EVENT),
    (GhostTokenRedemptionEvent, GHOST_REDEMPTION_EVENT),
    (GhostTokenBurnEvent, GHOST_BURN_EVENT),
    (AdminEvent, ADMIN_EVENT),
    (AdminEvent, ADMIN_EVENT_RATE),
    (SupplySnapshot, SUPPLY_SNAPSHOT),
]


@pytest.mark.parametrize("model, example", VALID_CASES, ids=lambda v: getattr(v, "__name__", ""))
def test_valid_example_instantiates(model: type[BaseModel], example: dict[str, Any]) -> None:
    """L'exemple valide de CONTRACTS.md s'instancie sans erreur."""
    instance = model.model_validate(example)
    assert isinstance(instance, model)


# Pour chaque modele : un exemple invalide qui doit lever ValidationError.
INVALID_CASES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    # Hash tx trop court -> echec pattern.
    (MintEvent, _mutate(MINT_EVENT, tx_hash="0xdeadbeef")),
    # Adresse mal formee (destinataire).
    (TransferEvent, _mutate(TRANSFER_EVENT, recipient="0x1234")),
    # Ratio hors [0, 1].
    (Alert, _mutate(ALERT, contamination_ratio=1.5)),
    # Graine avec ratio hors [0, 1] -> AlertSeed invalide, propage l'erreur.
    (
        Alert,
        _mutate(
            ALERT,
            seeds=[
                {
                    "address": "0x2222222222222222222222222222222222222222",
                    "suspect_amount": 870000000000000000,
                    "contamination_ratio": 1.5,
                }
            ],
        ),
    ),
    # Champ extra interdit.
    (ResponseAction, _mutate(RESPONSE_ACTION, unexpected="x")),
    # Payload du mauvais type (doit etre dict[str, str]).
    (AuditLogEntry, _mutate(AUDIT_LOG_ENTRY, payload="pas-un-dict")),
    # Montant de depot nul (gt=0 attendu).
    (MintRequest, _mutate(MINT_REQUEST, deposit_amount=0)),
    # Montant absolu suspect negatif.
    (QuarantineRecord, _mutate(QUARANTINE_RECORD, suspect_amount=-1)),
    # Enum de direction invalide.
    (FreezeRequest, _mutate(FREEZE_REQUEST, direction="speedup")),
    # Liste de signataires vide (min_length=1).
    (ReleaseDecision, _mutate(RELEASE_DECISION, signers=[])),
    # Ratio hors [0, 1].
    (RiskBeaconUpdate, _mutate(RISK_BEACON_UPDATE, contamination_ratio=-0.1)),
    # incoming_ratio hors [0, 1].
    (GhostTokenMintEvent, _mutate(GHOST_MINT_EVENT, incoming_ratio=2.0)),
    # ghost_amount nul (gt=0 attendu).
    (GhostTokenRedemptionEvent, _mutate(GHOST_REDEMPTION_EVENT, ghost_amount=0)),
    # Adresse mal formee.
    (GhostTokenBurnEvent, _mutate(GHOST_BURN_EVENT, address="0xzzzz")),
    # Role bytes32 mal forme.
    (AdminEvent, _mutate(ADMIN_EVENT, role="0x00")),
    # Offre negative.
    (SupplySnapshot, _mutate(SUPPLY_SNAPSHOT, total_supply=-1)),
]


@pytest.mark.parametrize(
    "model, bad_example", INVALID_CASES, ids=lambda v: getattr(v, "__name__", "")
)
def test_invalid_example_raises(model: type[BaseModel], bad_example: dict[str, Any]) -> None:
    """L'exemple invalide leve bien pydantic.ValidationError."""
    with pytest.raises(ValidationError):
        model.model_validate(bad_example)


def test_extra_field_forbidden_on_every_model() -> None:
    """Aucun modele ne tolere un champ hors schema (extra='forbid')."""
    for model, example in VALID_CASES:
        with pytest.raises(ValidationError):
            model.model_validate(_mutate(example, champ_inconnu="x"))


# --- #79 : request_id optionnel, pas de collision avec la demande n°0 ---


def test_mint_event_request_id_defaults_to_none_when_absent() -> None:
    """Un MintEvent sans request_id vaut None (observation ERC-20 nue), jamais 0.

    Decision #79 (OPEN_ANSWERS §79) : un Transfer ERC-20 ne porte pas l'id de
    demande ; l'ancienne sentinelle 0 entrait en collision avec la vraie
    demande n°0 (les demandes sont numerotees a partir de 0).
    """
    payload = {k: v for k, v in MINT_EVENT_BARE.items() if k != "request_id"}
    event = MintEvent.model_validate(payload)
    assert event.request_id is None


def test_mint_event_request_id_zero_is_a_real_request_not_a_sentinel() -> None:
    """request_id=0 reste une vraie demande valide (pas une sentinelle)."""
    event = MintEvent.model_validate(_mutate(MINT_EVENT, request_id=0))
    assert event.request_id == 0


def test_mint_event_request_id_rejects_negative() -> None:
    """request_id reste >= 0 quand il est fourni (ge=0)."""
    with pytest.raises(ValidationError):
        MintEvent.model_validate(_mutate(MINT_EVENT, request_id=-1))


# --- #104 : revision groupee (provenance du mint, administration, offre) ---


def test_mint_event_bare_erc20_has_no_request_fields() -> None:
    """Hors mode protege, les champs de demande valent None (inconnu)."""
    event = MintEvent.model_validate(MINT_EVENT_BARE)
    assert event.depositor is None
    assert event.deposit_amount is None
    assert event.rate_wad is None
    assert event.provenance_source is None
    assert event.claimed_minted is None
    assert event.via_protected_path is None


def test_mint_event_legacy_request_id_alone_stays_valid() -> None:
    """Retrocompatible : un MintEvent avec seulement request_id reste valide."""
    event = MintEvent.model_validate(_mutate(MINT_EVENT_BARE, request_id=7))
    assert event.request_id == 7
    assert event.provenance_source is None


def test_mint_event_protected_example_carries_provenance() -> None:
    """L'exemple de CONTRACTS.md porte la demande rattachee (I1, I3)."""
    event = MintEvent.model_validate(MINT_EVENT)
    assert event.provenance_source is MintProvenanceSource.REQUEST
    assert event.via_protected_path is True
    # I1 recalculable cote consommateur : depot (6 dec.) x 1e12 x taux / 1e18.
    assert event.deposit_amount is not None and event.rate_wad is not None
    assert event.deposit_amount * 10**12 * event.rate_wad // RATE_WAD_SCALE == event.amount


def test_mint_event_unexpected_path_carries_no_request() -> None:
    """Mint sans provenance (I4) : via_protected_path=False, aucune demande."""
    event = MintEvent.model_validate(_mutate(MINT_EVENT_BARE, via_protected_path=False))
    assert event.via_protected_path is False
    with pytest.raises(ValidationError):
        MintEvent.model_validate(
            _mutate(MINT_EVENT_BARE, via_protected_path=False, request_id=3)
        )


@pytest.mark.parametrize(
    "overrides",
    [
        # Champ de demande sans provenance_source.
        {"provenance_source": None, "via_protected_path": None},
        # provenance_source sans chemin protege.
        {"via_protected_path": None},
        {"via_protected_path": False},
        # provenance_source sans request_id ni deposant.
        {"request_id": None},
        {"depositor": None},
        # Valeur hors enum.
        {"provenance_source": "guess"},
        # Bornes.
        {"deposit_amount": 0},
        {"rate_wad": 0},
        {"claimed_minted": -1},
    ],
)
def test_mint_event_rejects_incoherent_provenance(overrides: dict[str, Any]) -> None:
    """Les champs de demande ne viennent que des evenements du minter."""
    with pytest.raises(ValidationError):
        MintEvent.model_validate(_mutate(MINT_EVENT, **overrides))


def test_mint_event_protected_path_requires_provenance() -> None:
    """via_protected_path=True sans provenance_source est incoherent."""
    with pytest.raises(ValidationError):
        MintEvent.model_validate(_mutate(MINT_EVENT_BARE, via_protected_path=True))


def test_admin_event_kinds_match_detection_list() -> None:
    """L'enum partage couvre les 5 types de detection.inputs.AdminEventKind."""
    assert {kind.value for kind in AdminEventKind} == {
        "upgraded", "role_granted", "role_revoked", "rate_changed", "oracle_changed",
    }


@pytest.mark.parametrize(
    "payload",
    [
        # Role exige pour role_granted.
        _mutate(ADMIN_EVENT, role=None),
        # Role interdit hors evenement de role.
        _mutate(ADMIN_EVENT_RATE, role="0x" + "00" * 32),
        # rate_changed exige les deux taux.
        _mutate(ADMIN_EVENT_RATE, new_rate_wad=None),
        # Taux interdits hors rate_changed.
        _mutate(ADMIN_EVENT, old_rate_wad=1, new_rate_wad=2),
        # Taux nul.
        _mutate(ADMIN_EVENT_RATE, old_rate_wad=0),
    ],
)
def test_admin_event_kind_specific_fields(payload: dict[str, Any]) -> None:
    """Chaque champ type n'est porte que par le type d'evenement qui l'emet."""
    with pytest.raises(ValidationError):
        AdminEvent.model_validate(payload)


def test_admin_event_upgrade_needs_no_extra_field() -> None:
    """Un upgrade ne porte ni role ni taux."""
    payload = {k: v for k, v in ADMIN_EVENT.items() if k not in ("role", "actor")}
    event = AdminEvent.model_validate(_mutate(payload, kind="upgraded"))
    assert event.kind is AdminEventKind.UPGRADED
    assert event.role is None and event.old_rate_wad is None


def test_supply_snapshot_optional_reads() -> None:
    """Ghost et collateral sont optionnels (non deployes ou non lus)."""
    payload = {
        k: v for k, v in SUPPLY_SNAPSHOT.items() if k not in ("ghost_supply", "collateral_value")
    }
    snapshot = SupplySnapshot.model_validate(payload)
    assert snapshot.ghost_supply is None
    assert snapshot.collateral_value is None
