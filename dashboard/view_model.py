"""Couche logique du dashboard : transformations pures, sans Streamlit.

Tout chiffre affiche par `app.py` est calcule ici a partir du jeu de donnees
(jamais de valeur en dur). Chaque etat / gravite a un libelle TEXTE explicite :
la couleur ou l'icone n'est jamais le seul porteur d'information.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum

import pandas as pd
from pydantic import BaseModel, ConfigDict

from dashboard.demo_data import DemoDataset
from shared.models import (
    Alert,
    AlertKind,
    AlertSeverity,
    AuditLogEntry,
    BeaconRiskLevel,
    GhostTokenBurnEvent,
    GhostTokenMintEvent,
    GhostTokenRedemptionEvent,
    QuarantineRecord,
    QuarantineStatus,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    RiskBeaconUpdate,
)

THOUSANDS_SEPARATOR = " "
MISSING_LABEL = "—"


class PerimeterState(str, Enum):
    """Etat d'un perimetre (machine a etats OPEN_ANSWERS §3.5), derive des actions."""

    NORMAL = "normal"
    DELAYED = "delayed"
    DESTROYED = "destroyed"
    GLOBAL_PAUSE = "global_pause"


PERIMETER_STATE_LABELS: dict[PerimeterState, str] = {
    PerimeterState.NORMAL: "Normal",
    PerimeterState.DELAYED: "Retardé (fenêtre allongée)",
    PerimeterState.DESTROYED: "Ghost suspect détruit",
    PerimeterState.GLOBAL_PAUSE: "Pause globale",
}

# Priorite d'affichage quand plusieurs actions coexistent (a valider en equipe).
_STATE_PRIORITY: dict[PerimeterState, int] = {
    PerimeterState.NORMAL: 0,
    PerimeterState.DELAYED: 1,
    PerimeterState.DESTROYED: 2,
    PerimeterState.GLOBAL_PAUSE: 3,
}

SEVERITY_LABELS: dict[AlertSeverity, str] = {
    AlertSeverity.INFO: "Info",
    AlertSeverity.WARNING: "Avertissement",
    AlertSeverity.CRITICAL: "Critique",
}

ALERT_KIND_LABELS: dict[AlertKind, str] = {
    AlertKind.MINT: "Mint",
    AlertKind.TRANSFER: "Transfert",
    AlertKind.BASELINE_ANOMALY: "Anomalie de baseline",
    AlertKind.BEACON: "Balise",
}

ACTION_TYPE_LABELS: dict[ResponseActionType, str] = {
    ResponseActionType.DELAY: "Retarder",
    ResponseActionType.DESTROY: "Détruire",
    ResponseActionType.GLOBAL_PAUSE: "Pause globale",
}

ACTION_STATUS_LABELS: dict[ResponseActionStatus, str] = {
    ResponseActionStatus.PROPOSED: "Proposée (en attente)",
    ResponseActionStatus.APPLIED: "Appliquée",
    ResponseActionStatus.EXPIRED: "Expirée",
    ResponseActionStatus.REJECTED: "Rejetée",
}

QUARANTINE_STATUS_LABELS: dict[QuarantineStatus, str] = {
    QuarantineStatus.ACTIVE: "Active (fenêtre normale)",
    QuarantineStatus.EXTENDED: "Allongée",
    QuarantineStatus.RELEASED: "Convertie (libérée)",
    QuarantineStatus.BURNED: "Détruite (fraction suspecte)",
}

BEACON_LEVEL_LABELS: dict[BeaconRiskLevel, str] = {
    BeaconRiskLevel.NORMAL: "Normal",
    BeaconRiskLevel.ELEVATED: "Élevé",
    BeaconRiskLevel.FROZEN: "Gelé",
}

_ACTIVE_QUARANTINE = {QuarantineStatus.ACTIVE, QuarantineStatus.EXTENDED}
_MULTISIG_ACTIONS = {ResponseActionType.DESTROY, ResponseActionType.GLOBAL_PAUSE}


def format_base_units(amount: int) -> str:
    """Formate un montant en base units avec separateur de milliers (sans decimales)."""
    return f"{amount:,}".replace(",", THOUSANDS_SEPARATOR)


def short_address(address: str) -> str:
    """Raccourcit une adresse EVM : `0x1234…abcd`."""
    return f"{address[:6]}…{address[-4:]}"


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else MISSING_LABEL


def known_perimeters(alerts: list[Alert], actions: list[ResponseAction]) -> set[str]:
    """Union des adresses vues dans les alertes et des perimetres des actions."""
    addresses = {alert.subject_address for alert in alerts}
    addresses.update(a.perimeter_address for a in actions if a.perimeter_address is not None)
    return addresses


def _action_state(action: ResponseAction, at: datetime) -> PerimeterState | None:
    """Effet d'une action a l'instant `at` (None si aucun effet)."""
    if action.created_at > at or action.status != ResponseActionStatus.APPLIED:
        return None
    if action.action_type == ResponseActionType.DELAY:
        if action.expires_at is not None and action.expires_at > at:
            return PerimeterState.DELAYED
        return None
    if action.action_type == ResponseActionType.DESTROY:
        return PerimeterState.DESTROYED
    return PerimeterState.GLOBAL_PAUSE


def derive_perimeter_states(
    alerts: list[Alert], actions: list[ResponseAction], at: datetime
) -> dict[str, PerimeterState]:
    """Derive l'etat de chaque perimetre connu a l'instant `at`.

    `proposed` / `rejected` / `expired` n'ont aucun effet ; un retard dont
    `expires_at <= at` est revenu a la normale (silence = retour auto, §3.3).
    """
    states = {address: PerimeterState.NORMAL for address in known_perimeters(alerts, actions)}
    global_pause = False
    for action in actions:
        effect = _action_state(action, at)
        if effect is None:
            continue
        if effect == PerimeterState.GLOBAL_PAUSE:
            global_pause = True
            continue
        address = action.perimeter_address
        if address is None:
            continue
        if _STATE_PRIORITY[effect] > _STATE_PRIORITY[states[address]]:
            states[address] = effect
    if global_pause:
        states = {address: PerimeterState.GLOBAL_PAUSE for address in states}
    return states


class DashboardSummary(BaseModel):
    """Compteurs de la vue d'ensemble, tous calcules a partir du jeu de donnees."""

    model_config = ConfigDict(extra="forbid")

    alert_count_by_severity: dict[str, int]
    perimeter_count_by_state: dict[str, int]
    active_quarantine_ghost_balance: int
    active_suspect_amount: int
    burned_ghost_total: int
    redeemed_ghost_total: int
    pending_multisig_actions: int


def compute_summary(dataset: DemoDataset, at: datetime) -> DashboardSummary:
    """Calcule la vue d'ensemble a l'instant `at` (evenements d'horodatage <= at)."""
    by_severity = {severity.value: 0 for severity in AlertSeverity}
    for alert in dataset.alerts:
        if alert.created_at <= at:
            by_severity[alert.severity.value] += 1

    by_state = {state.value: 0 for state in PerimeterState}
    for state in derive_perimeter_states(dataset.alerts, dataset.actions, at).values():
        by_state[state.value] += 1

    active = [q for q in dataset.quarantine if q.status in _ACTIVE_QUARANTINE]
    return DashboardSummary(
        alert_count_by_severity=by_severity,
        perimeter_count_by_state=by_state,
        active_quarantine_ghost_balance=sum(q.ghost_balance for q in active),
        active_suspect_amount=sum(q.suspect_amount for q in active),
        burned_ghost_total=sum(e.burned_amount for e in dataset.ghost_burns if e.burned_at <= at),
        redeemed_ghost_total=sum(
            e.ghost_amount for e in dataset.ghost_redemptions if e.redeemed_at <= at
        ),
        pending_multisig_actions=sum(
            1
            for a in dataset.actions
            if a.action_type in _MULTISIG_ACTIONS
            and a.status == ResponseActionStatus.PROPOSED
            and a.created_at <= at
        ),
    )


def filter_alerts(
    alerts: list[Alert], severities: set[AlertSeverity], kinds: set[AlertKind]
) -> list[Alert]:
    """Garde les alertes dont la gravite ET le type sont dans les ensembles donnes."""
    return [a for a in alerts if a.severity in severities and a.kind in kinds]


ALERT_COLUMNS = [
    "Créée le", "Gravité", "Type", "Surveillant", "Adresse", "Ratio de contamination",
    "Montant suspect (base units)", "Dispersion", "Z-score volume", "Graines", "Raison",
]


def alerts_to_frame(alerts: list[Alert]) -> pd.DataFrame:
    """Tableau des alertes, de la plus recente a la plus ancienne."""
    rows = [
        [
            _iso(a.created_at),
            SEVERITY_LABELS[a.severity],
            ALERT_KIND_LABELS[a.kind],
            a.monitor_name,
            short_address(a.subject_address),
            round(a.contamination_ratio, 4),
            format_base_units(a.suspect_amount),
            MISSING_LABEL if a.dispersion_score is None else f"{a.dispersion_score:.3f}",
            MISSING_LABEL if a.volume_zscore is None else f"{a.volume_zscore:.2f}",
            len(a.seeds),
            a.reason,
        ]
        for a in sorted(alerts, key=lambda a: a.created_at, reverse=True)
    ]
    return pd.DataFrame(rows, columns=ALERT_COLUMNS)


PERIMETER_COLUMNS = [
    "Adresse", "État", "Statut quarantaine", "Ratio de contamination",
    "Montant suspect (base units)", "Niveau de balise",
]


def perimeters_to_frame(
    states: dict[str, PerimeterState],
    quarantine: list[QuarantineRecord],
    beacons: list[RiskBeaconUpdate],
) -> pd.DataFrame:
    """Tableau des perimetres : etat derive, quarantaine et derniere balise publiee."""
    records = {q.address: q for q in quarantine}
    latest_beacon: dict[str, RiskBeaconUpdate] = {}
    for beacon in sorted(beacons, key=lambda b: b.published_at):
        latest_beacon[beacon.address] = beacon
    rows = []
    for address in sorted(states):
        record = records.get(address)
        beacon = latest_beacon.get(address)
        rows.append(
            [
                short_address(address),
                PERIMETER_STATE_LABELS[states[address]],
                MISSING_LABEL if record is None else QUARANTINE_STATUS_LABELS[record.status],
                MISSING_LABEL if record is None else f"{record.contamination_ratio:.4f}",
                MISSING_LABEL if record is None else format_base_units(record.suspect_amount),
                MISSING_LABEL if beacon is None else BEACON_LEVEL_LABELS[beacon.risk_level],
            ]
        )
    return pd.DataFrame(rows, columns=PERIMETER_COLUMNS)


ACTION_COLUMNS = [
    "Créée le", "Action", "Statut", "Périmètre", "Expire le", "Expire dans",
    "Alerte", "Décision multisig",
]


def _expires_in(action: ResponseAction, at: datetime) -> str:
    if action.expires_at is None:
        return MISSING_LABEL
    remaining = (action.expires_at - at).total_seconds()
    if remaining <= 0:
        return "expirée"
    return f"{math.ceil(remaining / 60)} min"


def actions_to_frame(actions: list[ResponseAction], at: datetime) -> pd.DataFrame:
    """Tableau des actions de reponse visibles a `at` (creees avant `at`)."""
    rows = [
        [
            _iso(a.created_at),
            ACTION_TYPE_LABELS[a.action_type],
            ACTION_STATUS_LABELS[a.status],
            "Tout le protocole" if a.perimeter_address is None
            else short_address(a.perimeter_address),
            _iso(a.expires_at),
            _expires_in(a, at),
            a.triggering_alert_id or MISSING_LABEL,
            a.decision_id or MISSING_LABEL,
        ]
        for a in sorted(actions, key=lambda a: a.created_at)
        if a.created_at <= at
    ]
    return pd.DataFrame(rows, columns=ACTION_COLUMNS)


QUARANTINE_COLUMNS = [
    "Adresse", "Statut", "Solde Ghost (base units)", "Ratio de contamination",
    "Montant suspect (base units)", "Fenêtre ouverte le", "Fenêtre expire le",
]


def quarantine_to_frame(records: list[QuarantineRecord]) -> pd.DataFrame:
    """Tableau des enregistrements de quarantaine Ghost."""
    rows = [
        [
            short_address(q.address),
            QUARANTINE_STATUS_LABELS[q.status],
            format_base_units(q.ghost_balance),
            f"{q.contamination_ratio:.4f}",
            format_base_units(q.suspect_amount),
            _iso(q.window_opened_at),
            _iso(q.window_expires_at),
        ]
        for q in records
    ]
    return pd.DataFrame(rows, columns=QUARANTINE_COLUMNS)


GHOST_EVENT_COLUMNS = ["Horodatage", "Événement", "Adresse", "Montant (base units)", "Ratio"]


def ghost_events_to_frame(
    mints: list[GhostTokenMintEvent],
    redemptions: list[GhostTokenRedemptionEvent],
    burns: list[GhostTokenBurnEvent],
    at: datetime,
) -> pd.DataFrame:
    """Chronologie des evenements Ghost (emission, conversion, destruction) <= `at`."""
    events: list[tuple[datetime, str, str, int, float]] = []
    events += [(m.minted_at, "Émission", m.recipient, m.amount, m.incoming_ratio) for m in mints]
    events += [
        (r.redeemed_at, "Conversion 1:1", r.holder, r.ghost_amount, r.contamination_ratio)
        for r in redemptions
    ]
    events += [
        (b.burned_at, "Destruction", b.address, b.burned_amount, b.contamination_ratio)
        for b in burns
    ]
    rows = [
        [_iso(when), label, short_address(address), format_base_units(amount), f"{ratio:.4f}"]
        for when, label, address, amount, ratio in sorted(events, key=lambda e: e[0])
        if when <= at
    ]
    return pd.DataFrame(rows, columns=GHOST_EVENT_COLUMNS)


AUDIT_COLUMNS = [
    "Horodatage", "Acteur", "Événement", "Adresse", "Action liée", "Message", "Détails",
]


def audit_log_to_frame(entries: list[AuditLogEntry]) -> pd.DataFrame:
    """Journal d'audit trie chronologiquement, payload aplati en `k=v; ...`."""
    rows = [
        [
            _iso(e.recorded_at),
            e.actor,
            e.event_type,
            MISSING_LABEL if e.subject_address is None else short_address(e.subject_address),
            e.related_action_id or MISSING_LABEL,
            e.message,
            "; ".join(f"{k}={v}" for k, v in e.payload.items()),
        ]
        for e in sorted(entries, key=lambda e: e.recorded_at)
    ]
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)
