"""Jeu de donnees SYNTHETIQUE et seede pour la demo du dashboard.

Tout est fictif : adresses, hash, identifiants et montants sont tires d'un
`random.Random(seed)` local. Aucune vraie cle, aucune vraie adresse. La meme
seed donne exactement le meme jeu (pas de `datetime.now()`, pas d'`uuid4`).

Le scenario suit la machine a etats de `docs/OPEN_ANSWERS.md` §3.5 et les trois
verbes de §9 (retarder / detruire / pause globale) sur quatre perimetres :

(a) NORMAL      : alerte info, retard propose puis rejete ;
(b) RETARDE     : alerte critique (volume eleve ET dispersion effondree),
                  retard applique encore actif a l'heure de reference ;
(c) EXPIRE      : retard applique puis expire (silence = retour a la normale),
                  Ghost converti 1:1 ;
(d) DETRUIT     : decision multisig 2/3 `confirm_destroy`, Ghost suspect detruit ;
(e) une pause globale seulement PROPOSEE (en attente du multisig 3/3).

Les fenetres 10 min / 1 h sont la « proposition de reference » de §3.1 :
valeurs de demo, a mesurer et a valider en equipe.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

from shared.models import (
    Alert,
    AlertKind,
    AlertSeed,
    AlertSeverity,
    AuditLogEntry,
    BeaconRiskLevel,
    GhostTokenBurnEvent,
    GhostTokenMintEvent,
    GhostTokenRedemptionEvent,
    QuarantineRecord,
    QuarantineStatus,
    ReleaseDecision,
    ReleaseVerdict,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    RiskBeaconUpdate,
)

DEMO_SEED = 20
DEMO_REFERENCE_TIME = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
DEMO_CHAIN_ID = 43113  # Avalanche Fuji (testnet)
DEMO_NORMAL_WINDOW = timedelta(minutes=10)  # valeur de demo (§3.1), a mesurer
DEMO_EXTENDED_WINDOW = timedelta(hours=1)  # valeur de demo (§3.1), a mesurer


class DemoDataset(BaseModel):
    """Agregat local au dashboard des modeles shared du jeu de demo."""

    model_config = ConfigDict(extra="forbid")

    seed: int
    reference_time: datetime
    alerts: list[Alert]
    actions: list[ResponseAction]
    decisions: list[ReleaseDecision]
    audit_log: list[AuditLogEntry]
    quarantine: list[QuarantineRecord]
    beacons: list[RiskBeaconUpdate]
    ghost_mints: list[GhostTokenMintEvent]
    ghost_redemptions: list[GhostTokenRedemptionEvent]
    ghost_burns: list[GhostTokenBurnEvent]


def _fake_address(rng: random.Random) -> str:
    return "0x" + format(rng.getrandbits(160), "040x")


def _fake_tx_hash(rng: random.Random) -> str:
    return "0x" + format(rng.getrandbits(256), "064x")


def _fake_id(rng: random.Random, prefix: str) -> str:
    return f"{prefix}-{rng.getrandbits(32):08x}"


class _Builder:
    """Accumule les objets du scenario et leurs entrees d'audit."""

    def __init__(self, rng: random.Random, reference_time: datetime) -> None:
        self.rng = rng
        self.t0 = reference_time
        self.block = 30_000_000 + rng.randint(0, 1_000_000)
        self.alerts: list[Alert] = []
        self.actions: list[ResponseAction] = []
        self.decisions: list[ReleaseDecision] = []
        self.audit: list[AuditLogEntry] = []
        self.quarantine: list[QuarantineRecord] = []
        self.beacons: list[RiskBeaconUpdate] = []
        self.ghost_mints: list[GhostTokenMintEvent] = []
        self.ghost_redemptions: list[GhostTokenRedemptionEvent] = []
        self.ghost_burns: list[GhostTokenBurnEvent] = []

    def at(self, minutes: float) -> datetime:
        return self.t0 + timedelta(minutes=minutes)

    def next_block(self) -> int:
        self.block += self.rng.randint(1, 50)
        return self.block

    def log(
        self,
        recorded_at: datetime,
        actor: str,
        event_type: str,
        message: str,
        payload: dict[str, object],
        subject_address: str | None = None,
        related_action_id: str | None = None,
        related_tx_hash: str | None = None,
    ) -> None:
        self.audit.append(
            AuditLogEntry(
                entry_id=_fake_id(self.rng, "audit"),
                recorded_at=recorded_at,
                actor=actor,
                event_type=event_type,
                subject_address=subject_address,
                related_action_id=related_action_id,
                related_tx_hash=related_tx_hash,
                payload={k: str(v) for k, v in payload.items()},
                message=message,
            )
        )

    def ghost_mint(self, recipient: str, amount: int, ratio: float, minted_at: datetime,
                   window: timedelta) -> GhostTokenMintEvent:
        event = GhostTokenMintEvent(
            tx_hash=_fake_tx_hash(self.rng),
            log_index=self.rng.randint(0, 5),
            block_number=self.next_block(),
            chain_id=DEMO_CHAIN_ID,
            minted_at=minted_at,
            recipient=recipient,
            amount=amount,
            incoming_ratio=ratio,
            window_expires_at=minted_at + window,
            source_transfer_tx=_fake_tx_hash(self.rng),
        )
        self.ghost_mints.append(event)
        self.log(minted_at, "contract", "ghost_minted",
                 "Ghost emis chez le destinataire (quarantaine liquide).",
                 {"amount": amount, "incoming_ratio": f"{ratio:.4f}"},
                 subject_address=recipient, related_tx_hash=event.tx_hash)
        return event

    def alert(self, kind: AlertKind, severity: AlertSeverity, created_at: datetime,
              monitor_name: str, subject: str, ratio: float, suspect_amount: int,
              reason: str, dispersion: float | None = None, zscore: float | None = None,
              seeds: list[AlertSeed] | None = None) -> Alert:
        alert = Alert(
            alert_id=_fake_id(self.rng, "alert"),
            kind=kind,
            severity=severity,
            created_at=created_at,
            monitor_name=monitor_name,
            subject_address=subject,
            source_tx_hash=_fake_tx_hash(self.rng),
            contamination_ratio=ratio,
            suspect_amount=suspect_amount,
            dispersion_score=dispersion,
            volume_zscore=zscore,
            reason=reason,
            seeds=seeds or [],
        )
        return self.add_alert(alert)

    def add_alert(self, alert: Alert) -> Alert:
        """Enregistre une alerte deja construite (ex. par un vrai surveillant) et la journalise."""
        self.alerts.append(alert)
        self.log(alert.created_at, f"monitor:{alert.monitor_name}", "alert_raised", alert.reason,
                 {"alert_id": alert.alert_id, "severity": alert.severity.value,
                  "kind": alert.kind.value,
                  "contamination_ratio": f"{alert.contamination_ratio:.4f}",
                  "suspect_amount": alert.suspect_amount},
                 subject_address=alert.subject_address, related_tx_hash=alert.source_tx_hash)
        return alert

    def action(self, action_type: ResponseActionType, status: ResponseActionStatus,
               created_at: datetime, actor: str, message: str,
               perimeter: str | None, alert: Alert, expires_at: datetime | None = None,
               decision_id: str | None = None) -> ResponseAction:
        action = ResponseAction(
            action_id=_fake_id(self.rng, "action"),
            action_type=action_type,
            status=status,
            created_at=created_at,
            expires_at=expires_at,
            perimeter_address=perimeter,
            triggering_alert_id=alert.alert_id,
            decision_id=decision_id,
            contamination_ratio=alert.contamination_ratio,
            suspect_amount=alert.suspect_amount,
        )
        self.actions.append(action)
        payload: dict[str, object] = {"action_type": action_type.value,
                                      "status": status.value,
                                      "alert_id": alert.alert_id}
        if expires_at is not None:
            payload["expires_at"] = expires_at.isoformat()
        if decision_id is not None:
            payload["decision_id"] = decision_id
        self.log(created_at, actor, f"response_{action_type.value}", message, payload,
                 subject_address=perimeter, related_action_id=action.action_id)
        return action

    def quarantine_record(self, address: str, status: QuarantineStatus, balance: int,
                          ratio: float, opened_at: datetime, window: timedelta) -> None:
        self.quarantine.append(
            QuarantineRecord(
                record_id=_fake_id(self.rng, "quar"),
                address=address,
                status=status,
                ghost_balance=balance,
                contamination_ratio=ratio,
                suspect_amount=int(ratio * balance),
                window_opened_at=opened_at,
                window_expires_at=opened_at + window,
                chain_id=DEMO_CHAIN_ID,
            )
        )

    def beacon(self, address: str, level: BeaconRiskLevel, ratio: float, suspect_amount: int,
               published_at: datetime, window_expires_at: datetime | None = None) -> None:
        self.beacons.append(
            RiskBeaconUpdate(
                beacon_id=_fake_id(self.rng, "beacon"),
                address=address,
                risk_level=level,
                contamination_ratio=ratio,
                suspect_amount=suspect_amount,
                published_at=published_at,
                window_expires_at=window_expires_at,
                chain_id=DEMO_CHAIN_ID,
            )
        )
        self.log(published_at, "contract", "beacon_published",
                 "Balise de risque publiee pour l'aval.",
                 {"risk_level": level.value, "contamination_ratio": f"{ratio:.4f}"},
                 subject_address=address)


def _balance(rng: random.Random) -> int:
    return rng.randint(1_000_000, 900_000_000)


def generate_demo_dataset(
    seed: int = DEMO_SEED, reference_time: datetime = DEMO_REFERENCE_TIME
) -> DemoDataset:
    """Genere le jeu de demo synthetique, deterministe pour une seed donnee."""
    rng = random.Random(seed)
    b = _Builder(rng, reference_time)

    addr_normal = _fake_address(rng)
    addr_delayed = _fake_address(rng)
    addr_expired = _fake_address(rng)
    addr_destroyed = _fake_address(rng)

    # (a) NORMAL : petite alerte info, retard propose puis rejete.
    bal_a = _balance(rng)
    ratio_a = rng.uniform(0.0, 0.05)
    opened_a = b.at(-5)
    b.ghost_mint(addr_normal, bal_a, ratio_a, opened_a, DEMO_NORMAL_WINDOW)
    alert_a = b.alert(AlertKind.BASELINE_ANOMALY, AlertSeverity.INFO, b.at(-50), "baseline",
                      addr_normal, ratio_a, int(ratio_a * bal_a),
                      "Volume legerement au-dessus de la baseline, dispersion normale.",
                      dispersion=rng.uniform(0.6, 0.95), zscore=rng.uniform(1.0, 2.0))
    b.action(ResponseActionType.DELAY, ResponseActionStatus.REJECTED, b.at(-49), "ai",
             "Retard propose puis ecarte : dispersion normale, pas de concentration.",
             addr_normal, alert_a, expires_at=b.at(-49) + DEMO_EXTENDED_WINDOW)
    b.quarantine_record(addr_normal, QuarantineStatus.ACTIVE, bal_a, ratio_a, opened_a,
                        DEMO_NORMAL_WINDOW)
    b.beacon(addr_normal, BeaconRiskLevel.NORMAL, ratio_a, int(ratio_a * bal_a), b.at(-4))

    # (b) RETARDE : volume eleve ET dispersion effondree, retard encore actif.
    bal_b = _balance(rng)
    ratio_b = rng.uniform(0.3, 0.8)
    b.ghost_mint(addr_delayed, bal_b, ratio_b, b.at(-25), DEMO_NORMAL_WINDOW)
    seeds_b = [AlertSeed(address=_fake_address(rng),
                         suspect_amount=int(ratio_b * bal_b) // 2,
                         contamination_ratio=ratio_b) for _ in range(2)]
    alert_b = b.alert(AlertKind.TRANSFER, AlertSeverity.CRITICAL, b.at(-20), "rule_transfer",
                      addr_delayed, ratio_b, int(ratio_b * bal_b),
                      "Volume eleve ET dispersion effondree sur le perimetre.",
                      dispersion=rng.uniform(0.01, 0.1), zscore=rng.uniform(4.0, 8.0),
                      seeds=seeds_b)
    opened_b = b.at(-19)
    b.action(ResponseActionType.DELAY, ResponseActionStatus.APPLIED, opened_b,
             "monitor:rule_transfer",
             "Fenetre Ghost allongee (retarder, auto-expirant) : conversion suspendue.",
             addr_delayed, alert_b, expires_at=opened_b + DEMO_EXTENDED_WINDOW)
    b.quarantine_record(addr_delayed, QuarantineStatus.EXTENDED, bal_b, ratio_b, opened_b,
                        DEMO_EXTENDED_WINDOW)
    b.beacon(addr_delayed, BeaconRiskLevel.ELEVATED, ratio_b, int(ratio_b * bal_b),
             b.at(-18), window_expires_at=opened_b + DEMO_EXTENDED_WINDOW)

    # (c) EXPIRE : retard applique puis expire (silence = retour a la normale).
    bal_c = _balance(rng)
    ratio_c = rng.uniform(0.0, 0.05)
    b.ghost_mint(addr_expired, bal_c, ratio_c, b.at(-95), DEMO_NORMAL_WINDOW)
    alert_c = b.alert(AlertKind.MINT, AlertSeverity.WARNING, b.at(-90), "rule_mint",
                      addr_expired, ratio_c, int(ratio_c * bal_c),
                      "Mint important non annonce au prealable.")
    opened_c = b.at(-89)
    b.action(ResponseActionType.DELAY, ResponseActionStatus.EXPIRED, opened_c, "ai",
             "Retard applique ; expire sans audit (retour automatique a la normale).",
             addr_expired, alert_c, expires_at=opened_c + DEMO_EXTENDED_WINDOW)
    b.quarantine_record(addr_expired, QuarantineStatus.RELEASED, bal_c, ratio_c, opened_c,
                        DEMO_EXTENDED_WINDOW)
    redeemed_at = opened_c + DEMO_EXTENDED_WINDOW + timedelta(minutes=1)
    redemption = GhostTokenRedemptionEvent(
        tx_hash=_fake_tx_hash(rng), log_index=0, block_number=b.next_block(),
        chain_id=DEMO_CHAIN_ID, redeemed_at=redeemed_at, holder=addr_expired,
        ghost_amount=bal_c, token_amount=bal_c, fee_amount=0, contamination_ratio=ratio_c,
    )
    b.ghost_redemptions.append(redemption)
    b.log(redeemed_at, "contract", "ghost_redeemed", "Ghost converti 1:1 en vrai token.",
          {"ghost_amount": bal_c, "token_amount": bal_c},
          subject_address=addr_expired, related_tx_hash=redemption.tx_hash)
    b.beacon(addr_expired, BeaconRiskLevel.NORMAL, ratio_c, int(ratio_c * bal_c), redeemed_at)

    # (d) DETRUIT : retard puis decision multisig 2/3 confirm_destroy.
    bal_d = _balance(rng)
    ratio_d = rng.uniform(0.5, 0.95)
    b.ghost_mint(addr_destroyed, bal_d, ratio_d, b.at(-155), DEMO_NORMAL_WINDOW)
    alert_d = b.alert(AlertKind.TRANSFER, AlertSeverity.CRITICAL, b.at(-150), "rule_transfer",
                      addr_destroyed, ratio_d, int(ratio_d * bal_d),
                      "Volume eleve ET dispersion effondree ; schema de drainage.",
                      dispersion=rng.uniform(0.01, 0.05), zscore=rng.uniform(6.0, 10.0),
                      seeds=[AlertSeed(address=addr_destroyed,
                                       suspect_amount=int(ratio_d * bal_d),
                                       contamination_ratio=ratio_d)])
    opened_d = b.at(-149)
    b.action(ResponseActionType.DELAY, ResponseActionStatus.EXPIRED, opened_d,
             "monitor:rule_transfer", "Fenetre Ghost allongee en attente d'audit humain.",
             addr_destroyed, alert_d, expires_at=opened_d + DEMO_EXTENDED_WINDOW)
    decided_at = b.at(-100)
    signers = [_fake_address(rng) for _ in range(3)]
    decision = ReleaseDecision(
        decision_id=_fake_id(rng, "decision"), verdict=ReleaseVerdict.CONFIRM_DESTROY,
        decided_at=decided_at, perimeter_address=addr_destroyed, signers=signers[:2],
        threshold=2, burn_ratio=ratio_d,
        rationale="Audit humain : drainage confirme, destruction de la fraction suspecte.",
    )
    b.decisions.append(decision)
    b.log(decided_at, "multisig", "release_decision", decision.rationale,
          {"decision_id": decision.decision_id, "verdict": decision.verdict.value,
           "threshold": f"{decision.threshold}/{len(signers)}",
           "signers": len(decision.signers), "burn_ratio": f"{ratio_d:.4f}"},
          subject_address=addr_destroyed)
    b.action(ResponseActionType.DESTROY, ResponseActionStatus.APPLIED, b.at(-99), "multisig",
             "Destruction du Ghost suspect (ratio x solde non converti).",
             addr_destroyed, alert_d, decision_id=decision.decision_id)
    burned = max(1, int(ratio_d * bal_d))
    burn = GhostTokenBurnEvent(
        tx_hash=_fake_tx_hash(rng), log_index=0, block_number=b.next_block(),
        chain_id=DEMO_CHAIN_ID, burned_at=b.at(-98), address=addr_destroyed,
        burned_amount=burned, contamination_ratio=ratio_d, suspect_amount=burned,
        decision_id=decision.decision_id,
    )
    b.ghost_burns.append(burn)
    b.log(burn.burned_at, "contract", "ghost_burned", "Fraction suspecte du Ghost detruite.",
          {"burned_amount": burned, "decision_id": decision.decision_id},
          subject_address=addr_destroyed, related_tx_hash=burn.tx_hash)
    # Apres destruction, le solde restant est la fraction saine (ratio 0).
    b.quarantine_record(addr_destroyed, QuarantineStatus.BURNED, bal_d - burned, 0.0,
                        opened_d, DEMO_EXTENDED_WINDOW)
    b.beacon(addr_destroyed, BeaconRiskLevel.FROZEN, ratio_d, burned, b.at(-97))

    # (e) Pause globale PROPOSEE, en attente du multisig 3/3 : aucun effet.
    # Proposee par l'audit humain (l'IA ne fait que retarder, §3).
    b.action(ResponseActionType.GLOBAL_PAUSE, ResponseActionStatus.PROPOSED, b.at(-10),
             "auditor", "Escalade proposee : pause globale (en attente du multisig 3/3).",
             None, alert_d)

    b.audit.sort(key=lambda entry: entry.recorded_at)
    return DemoDataset(
        seed=seed,
        reference_time=reference_time,
        alerts=b.alerts,
        actions=b.actions,
        decisions=b.decisions,
        audit_log=b.audit,
        quarantine=b.quarantine,
        beacons=b.beacons,
        ghost_mints=b.ghost_mints,
        ghost_redemptions=b.ghost_redemptions,
        ghost_burns=b.ghost_burns,
    )
