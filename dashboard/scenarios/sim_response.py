"""Réponse simulée : simulation hors chaîne, à remplacer par #17 (orchestrateur) et #19 (journal DORA).

Machine a etats OPEN_ANSWERS §3.5 : le surveillant ne peut que RETARDER
(`delay` auto-expirant, fenetre allongee) ; la destruction passe uniquement par
une `ReleaseDecision` multisig 2/3 (l'IA ne decide jamais seule). Sans
decision, le retard expire et le Ghost est converti 1:1 (silence = retour a la
normale). Les objets sont coherents avec `dashboard.view_model.derive_perimeter_states`.
"""

from __future__ import annotations

from datetime import datetime

from dashboard.demo_data import (
    DEMO_CHAIN_ID,
    DEMO_EXTENDED_WINDOW,
    DEMO_REFERENCE_TIME,
    DemoDataset,
    _Builder,
    _fake_address,
    _fake_id,
    _fake_tx_hash,
)
from dashboard.scenarios.sim_detector import MONITOR_NAME
from shared.models import (
    Alert,
    BeaconRiskLevel,
    GhostTokenBurnEvent,
    GhostTokenRedemptionEvent,
    QuarantineStatus,
    ReleaseDecision,
    ReleaseVerdict,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
)

MONITOR_ACTOR = f"monitor:{MONITOR_NAME}"
MULTISIG_SIGNERS = 3
MULTISIG_THRESHOLD = 2


def _set_quarantine(builder: _Builder, address: str, status: QuarantineStatus, balance: int,
                    ratio: float, opened_at: datetime) -> None:
    """Un seul enregistrement de quarantaine par adresse (le dernier etat)."""
    builder.quarantine = [q for q in builder.quarantine if q.address != address]
    builder.quarantine_record(address, status, balance, ratio, opened_at, DEMO_EXTENDED_WINDOW)


def apply_delay(builder: _Builder, alert: Alert, at: datetime, ghost_balance: int = 0,
                perimeter: str | None = None) -> ResponseAction:
    """Retard auto-expirant applique par le surveillant (fenetre Ghost allongee)."""
    address = perimeter or alert.subject_address
    expires_at = at + DEMO_EXTENDED_WINDOW
    action = builder.action(
        ResponseActionType.DELAY, ResponseActionStatus.APPLIED, at, MONITOR_ACTOR,
        "Fenêtre Ghost allongée (retarder, auto-expirant) : conversion suspendue.",
        address, alert, expires_at=expires_at,
    )
    _set_quarantine(builder, address, QuarantineStatus.EXTENDED, ghost_balance,
                    alert.contamination_ratio, at)
    builder.beacon(address, BeaconRiskLevel.ELEVATED, alert.contamination_ratio,
                   alert.suspect_amount, at, window_expires_at=expires_at)
    return action


def expire_delay(builder: _Builder, action: ResponseAction, ghost_amount: int,
                 contamination_ratio: float) -> GhostTokenRedemptionEvent | None:
    """Aucune decision humaine : le retard expire, le Ghost est converti 1:1."""
    if action.expires_at is None or action.perimeter_address is None:
        raise ValueError("expire_delay attend un retard sur un perimetre")
    at = action.expires_at
    address = action.perimeter_address
    builder.actions = [
        a.model_copy(update={"status": ResponseActionStatus.EXPIRED})
        if a.action_id == action.action_id else a
        for a in builder.actions
    ]
    builder.log(at, "contract", "response_delay_expired",
                "Retard expiré sans décision : retour automatique à la normale.",
                {"action_id": action.action_id}, subject_address=address,
                related_action_id=action.action_id)
    _set_quarantine(builder, address, QuarantineStatus.RELEASED, ghost_amount,
                    contamination_ratio, action.created_at)
    redemption = None
    if ghost_amount > 0:
        redemption = GhostTokenRedemptionEvent(
            tx_hash=_fake_tx_hash(builder.rng), log_index=0, block_number=builder.next_block(),
            chain_id=DEMO_CHAIN_ID, redeemed_at=at, holder=address, ghost_amount=ghost_amount,
            token_amount=ghost_amount, fee_amount=0, contamination_ratio=contamination_ratio,
        )
        builder.ghost_redemptions.append(redemption)
        builder.log(at, "contract", "ghost_redeemed", "Ghost converti 1:1 en vrai token.",
                    {"ghost_amount": ghost_amount, "token_amount": ghost_amount},
                    subject_address=address, related_tx_hash=redemption.tx_hash)
    builder.beacon(address, BeaconRiskLevel.NORMAL, contamination_ratio,
                   int(contamination_ratio * ghost_amount), at)
    return redemption


def confirm_destroy(builder: _Builder, alert: Alert, at: datetime, ghost_balance: int,
                    burn_ratio: float, perimeter: str | None = None) -> GhostTokenBurnEvent | None:
    """Decision multisig 2/3 `confirm_destroy` puis destruction de burn_ratio x solde non converti.

    Renvoie None (aucune decision consignee) s'il n'y a rien a detruire.
    """
    address = perimeter or alert.subject_address
    burned = int(burn_ratio * ghost_balance)
    if burned <= 0:
        return None
    signers = [_fake_address(builder.rng) for _ in range(MULTISIG_SIGNERS)]
    decision = ReleaseDecision(
        decision_id=_fake_id(builder.rng, "decision"), verdict=ReleaseVerdict.CONFIRM_DESTROY,
        decided_at=at, perimeter_address=address, signers=signers[:MULTISIG_THRESHOLD],
        threshold=MULTISIG_THRESHOLD, burn_ratio=burn_ratio,
        rationale="Audit humain simulé : drainage confirmé, destruction de la fraction suspecte.",
    )
    builder.decisions.append(decision)
    builder.log(at, "multisig", "release_decision", decision.rationale,
                {"decision_id": decision.decision_id, "verdict": decision.verdict.value,
                 "threshold": f"{MULTISIG_THRESHOLD}/{MULTISIG_SIGNERS}",
                 "signers": len(decision.signers), "burn_ratio": f"{burn_ratio:.4f}"},
                subject_address=address)
    builder.action(ResponseActionType.DESTROY, ResponseActionStatus.APPLIED, at, "multisig",
                   "Destruction du Ghost suspect (ratio x solde non converti).",
                   address, alert, decision_id=decision.decision_id)
    burn = GhostTokenBurnEvent(
        tx_hash=_fake_tx_hash(builder.rng), log_index=0, block_number=builder.next_block(),
        chain_id=DEMO_CHAIN_ID, burned_at=at, address=address, burned_amount=burned,
        contamination_ratio=burn_ratio, suspect_amount=burned, decision_id=decision.decision_id,
    )
    builder.ghost_burns.append(burn)
    builder.log(at, "contract", "ghost_burned", "Fraction suspecte du Ghost détruite.",
                {"burned_amount": burned, "decision_id": decision.decision_id},
                subject_address=address, related_tx_hash=burn.tx_hash)
    # Apres destruction, le solde restant est la fraction saine (ratio 0).
    _set_quarantine(builder, address, QuarantineStatus.BURNED, ghost_balance - burned, 0.0, at)
    builder.beacon(address, BeaconRiskLevel.FROZEN, burn_ratio, burned, at)
    return burn


def build_dataset(builder: _Builder, seed: int) -> DemoDataset:
    """Fige l'etat du builder en `DemoDataset` (audit trie par horodatage)."""
    return DemoDataset(
        seed=seed,
        reference_time=DEMO_REFERENCE_TIME,
        alerts=list(builder.alerts),
        actions=list(builder.actions),
        decisions=list(builder.decisions),
        audit_log=sorted(builder.audit, key=lambda entry: entry.recorded_at),
        quarantine=list(builder.quarantine),
        beacons=list(builder.beacons),
        ghost_mints=list(builder.ghost_mints),
        ghost_redemptions=list(builder.ghost_redemptions),
        ghost_burns=list(builder.ghost_burns),
    )
