"""Tests de fumee des 13 modeles partages (shared.models).

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
    MintRequest,
    QuarantineRecord,
    ReleaseDecision,
    ResponseAction,
    RiskBeaconUpdate,
    SupplySnapshot,
    TransferEvent,
)

# --- Exemples VALIDES (repris des exemples JSON de docs/CONTRACTS.md) ---

MINT_EVENT: dict[str, Any] = {
    "tx_hash": "0x3f2a1b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f701",
    "log_index": 0,
    "block_number": 12345678,
    "chain_id": 43113,
    "observed_at": "2026-10-10T14:30:00Z",
    "recipient": "0x1111111111111111111111111111111111111111",
    "amount": 1000000000000000000,
    "request_id": 42,
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
    "tx_hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    "log_index": 0,
    "block_number": 12345600,
    "chain_id": 43113,
    "observed_at": "2026-10-10T14:20:00Z",
    "contract_address": "0x8888888888888888888888888888888888888888",
    "kind": "role_granted",
    "subject_address": "0x9999999999999999999999999999999999999999",
    "actor": "0x3333333333333333333333333333333333333333",
    "details": {
        "role": "0x" + "ab" * 32,
    },
}

SUPPLY_SNAPSHOT: dict[str, Any] = {
    "chain_id": 43113,
    "block_number": 12345700,
    "observed_at": "2026-10-10T14:35:00Z",
    "token_address": "0x8888888888888888888888888888888888888888",
    "total_supply": 1000000000000000000000,
    "ghost_supply": 250000000000000000000,
    "collateral_value": 1250000000000000000000,
}

# MintEvent issu de `SwapCompleted` : champs de la demande renseignes (#79).
MINT_EVENT_FULL: dict[str, Any] = {
    **MINT_EVENT,
    "depositor": "0x1111111111111111111111111111111111111111",
    "deposit_amount": 1000000,
    "rate_wad": 10**12 * RATE_WAD_SCALE,
    "token_address": "0x8888888888888888888888888888888888888888",
}


def _mutate(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Copie profonde de `base` avec champs remplaces/ajoutes."""
    data = copy.deepcopy(base)
    data.update(overrides)
    return data


# (modele, exemple valide, exemple invalide) — une entree par modele.
VALID_CASES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (MintEvent, MINT_EVENT),
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
    (SupplySnapshot, SUPPLY_SNAPSHOT),
    (MintEvent, MINT_EVENT_FULL),
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
    # Enum d'evenement admin inconnu.
    (AdminEvent, _mutate(ADMIN_EVENT, kind="minted")),
    # Details du mauvais type (dict[str, str] attendu).
    (AdminEvent, _mutate(ADMIN_EVENT, details={"old_rate": 1})),
    # Offre negative.
    (SupplySnapshot, _mutate(SUPPLY_SNAPSHOT, total_supply=-1)),
    # request_id negatif : None pour « inconnu », jamais de sentinelle.
    (MintEvent, _mutate(MINT_EVENT, request_id=-1)),
    # Depot nul (gt=0 attendu quand il est connu).
    (MintEvent, _mutate(MINT_EVENT_FULL, deposit_amount=0)),
    # Taux nul (gt=0 attendu quand il est connu).
    (MintEvent, _mutate(MINT_EVENT_FULL, rate_wad=0)),
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


def test_mint_event_request_fields_default_to_unknown() -> None:
    """Un mint vu par un `Transfer` ERC-20 n'a pas de demande : None, pas 0 (#79)."""
    data = copy.deepcopy(MINT_EVENT)
    del data["request_id"]
    event = MintEvent.model_validate(data)
    assert event.request_id is None
    assert event.depositor is None
    assert event.deposit_amount is None
    assert event.rate_wad is None
    assert event.token_address is None


def test_mint_event_rate_wad_scale() -> None:
    """rate_wad / RATE_WAD_SCALE = base units mintees par base unit deposee."""
    event = MintEvent.model_validate(MINT_EVENT_FULL)
    assert event.rate_wad is not None and event.deposit_amount is not None
    assert event.deposit_amount * event.rate_wad // RATE_WAD_SCALE == event.amount


def test_admin_event_kinds_cover_repo_contracts() -> None:
    """Les evenements admin emis par les contrats du depot ont leur valeur d'enum."""
    assert {k.value for k in AdminEventKind} >= {
        "upgraded",
        "role_granted",
        "role_revoked",
        "rate_changed",
        "oracle_changed",
    }


def test_transfer_event_token_address_optional() -> None:
    """token_address est optionnel (compatibilite des producteurs existants)."""
    assert TransferEvent.model_validate(TRANSFER_EVENT).token_address is None
    event = TransferEvent.model_validate(
        _mutate(TRANSFER_EVENT, token_address="0x8888888888888888888888888888888888888888")
    )
    assert event.token_address == "0x8888888888888888888888888888888888888888"
