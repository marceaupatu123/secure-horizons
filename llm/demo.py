"""Donnees fictives et faux client Bedrock pour la demo hors ligne de `python -m llm`.

Aucun appel reseau : `OfflineConverseStub` imite la forme d'une reponse
Converse. Ses textes ne contiennent aucun chiffre : ils renvoient aux faits
deterministes du rapport.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from llm.prompts import SYSTEM_PROMPT_REPORT
from shared.models import (
    Alert,
    AlertKind,
    AlertSeed,
    AlertSeverity,
    AuditLogEntry,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
)

_T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
_ADDR_ATTACKER = "0x" + "aa" * 20
_ADDR_RELAY = "0x" + "bb" * 20
_TX_MINT = "0x" + "cd" * 32

OFFLINE_TAG = "[démo hors ligne]"


def fictive_alert() -> Alert:
    """Alerte de mint anormal entierement fictive."""
    return Alert(
        alert_id="DEMO-ALERT-0001",
        kind=AlertKind.MINT,
        severity=AlertSeverity.CRITICAL,
        created_at=_T0,
        monitor_name="rule_mint",
        subject_address=_ADDR_ATTACKER,
        source_tx_hash=_TX_MINT,
        contamination_ratio=1.0,
        suspect_amount=5_000_000_000_000,
        dispersion_score=0.05,
        volume_zscore=12.0,
        reason="Mint sans dépôt on-chain correspondant (scénario fictif)",
        seeds=[
            AlertSeed(
                address=_ADDR_ATTACKER, suspect_amount=4_000_000_000_000, contamination_ratio=1.0
            ),
            AlertSeed(
                address=_ADDR_RELAY, suspect_amount=1_000_000_000_000, contamination_ratio=1.0
            ),
        ],
    )


def fictive_actions(alert: Alert) -> list[ResponseAction]:
    """Un retard pose par le surveillant/IA puis une destruction multisig (fictifs)."""
    return [
        ResponseAction(
            action_id="DEMO-ACT-DELAY",
            action_type=ResponseActionType.DELAY,
            status=ResponseActionStatus.APPLIED,
            created_at=alert.created_at + timedelta(seconds=5),
            expires_at=alert.created_at + timedelta(minutes=30),
            perimeter_address=alert.subject_address,
            triggering_alert_id=alert.alert_id,
            contamination_ratio=alert.contamination_ratio,
            suspect_amount=alert.suspect_amount,
        ),
        ResponseAction(
            action_id="DEMO-ACT-DESTROY",
            action_type=ResponseActionType.DESTROY,
            status=ResponseActionStatus.APPLIED,
            created_at=alert.created_at + timedelta(minutes=8),
            perimeter_address=alert.subject_address,
            triggering_alert_id=alert.alert_id,
            decision_id="DEMO-DEC-0001",
            contamination_ratio=alert.contamination_ratio,
            suspect_amount=alert.suspect_amount,
        ),
    ]


def fictive_audit_entries(alert: Alert) -> list[AuditLogEntry]:
    """Entrees de journal d'audit fictives liees a l'alerte."""
    return [
        AuditLogEntry(
            entry_id="DEMO-AUD-0001",
            recorded_at=alert.created_at + timedelta(seconds=1),
            actor=f"monitor:{alert.monitor_name}",
            event_type="alert_raised",
            subject_address=alert.subject_address,
            related_tx_hash=alert.source_tx_hash,
            payload={"alert_id": alert.alert_id},
            message="Alerte de mint anormal journalisée (fictif)",
        ),
        AuditLogEntry(
            entry_id="DEMO-AUD-0002",
            recorded_at=alert.created_at + timedelta(minutes=8),
            actor="multisig",
            event_type="destroy_confirmed",
            subject_address=alert.subject_address,
            related_action_id="DEMO-ACT-DESTROY",
            payload={"decision_id": "DEMO-DEC-0001"},
            message="Destruction du Ghost suspect confirmée par le multisig (fictif)",
        ),
    ]


class OfflineConverseStub:
    """Faux client `bedrock-runtime` : reponses Converse en dur, sans reseau."""

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        """Retourne une reponse au format Converse selon le prompt systeme recu."""
        system_text = kwargs.get("system", [{}])[0].get("text", "")
        if system_text == SYSTEM_PROMPT_REPORT:
            text = json.dumps(
                {
                    "description": f"{OFFLINE_TAG} Mint anormal signalé par le surveillant ; "
                    "voir les faits et la chronologie ci-dessus.",
                    "probable_cause": f"{OFFLINE_TAG} Non établie : à confirmer par "
                    "l'analyse humaine (hypothèse : clé de service compromise).",
                    "impact": f"{OFFLINE_TAG} Limité au périmètre listé ; montants : "
                    "voir la section Périmètre affecté.",
                    "mitigation": f"{OFFLINE_TAG} Retard local appliqué par le surveillant, "
                    "destruction décidée par le multisig ; revue de la clé à planifier.",
                },
                ensure_ascii=False,
            )
        else:
            text = (
                f"{OFFLINE_TAG} Le surveillant a détecté un mint sans dépôt correspondant. "
                "L'IA ne décide rien : la suite revient au multisig."
            )
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": "end_turn",
        }
