"""Surveillants : detection d'anomalies sur mints et transferts.

Un surveillant consomme des evenements (`MintEvent`, `TransferEvent`) et renvoie
une `Alert` quand il juge une situation anormale, sinon `None`. L'IA n'est qu'un
surveillant parmi d'autres et ne decide jamais seule d'un blocage.

`RuleBasedMonitor.check_mint` suit la DECISION docs/OPEN_ANSWERS.md §1 : AUCUN
seuil sur la taille d'un mint individuel. Il verifie, independamment du
contrat, que les hypotheses du volet 1 tiennent :

- I1 : `minted = depot x taux`, a epsilon pres (frais) ;
- I5 : `Delta totalSupply = Somme Mint - Somme Burn` ;
- I6 : `totalSupply <= valeur du collateral x facteur` ;
- evenement d'administration (`Upgraded`, `RoleGranted`, changement
  d'oracle/taux) non annonce au prealable ;
- ecart du taux applique au-dela de delta vs une source de reference.

Une `Alert` signifie seulement « retarder le perimetre » (§3) : le surveillant
ne decide jamais d'une destruction ni d'une pause globale (multisig).

Les parametres (epsilon, delta, facteur I6...) vivent dans `detection/params.py`
(PROVISOIRE / A MESURER). Les donnees absentes de `MintEvent` arrivent via
`detection.inputs.MintContext` (GAP documente dans `detection/inputs.py`).
`MintEvent.request_id` n'est PAS utilise (optionnel, `None` possible depuis #79).

`RuleBasedMonitor.check_transfer` (#12) suit la DECISION docs/OPEN_ANSWERS.md
§9 : il agrege les transferts par tranche (5 min PROVISOIRE), normalise le
volume par l'offre en circulation, mesure la dispersion (Herfindahl,
PROVISOIRE), compare a la baseline mediane + MAD du MEME creneau, et n'alerte
que si volume eleve ET dispersion effondree — jamais sur le volume seul. Voir
`detection/transfers.py`.
"""

from __future__ import annotations

import logging
import math
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Protocol

from detection.inputs import AdminAnnouncement, AdminEvent, MintContext
from detection.params import (
    MINT_MONITOR_NAME,
    TRANSFER_MONITOR_NAME,
    MintRuleParams,
    TransferRuleParams,
)
from detection.transfers import SlotAggregate, TransferSlotStats, robust_zscore
from shared.models import (
    Alert,
    AlertKind,
    AlertSeed,
    AlertSeverity,
    MintEvent,
    TransferEvent,
)

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
}

_RESPONSE_NOTE = (
    "Action permise au surveillant : retarder le perimetre (OPEN_ANSWERS §3) ; "
    "detruire / pause globale = multisig."
)


class Monitor(Protocol):
    """Interface d'un surveillant independant.

    Plusieurs implementations possibles (regles, ML, signaux de transferts).
    Chacune reste optionnelle et independante des autres.
    """

    def check_mint(self, event: MintEvent) -> Alert | None:
        """Analyse un evenement de mint.

        Args:
            event: l'evenement de mint a evaluer.

        Returns:
            Une `Alert` si anomalie detectee, sinon `None`.
        """
        ...

    def check_transfer(self, event: TransferEvent) -> Alert | None:
        """Analyse un evenement de transfert.

        Args:
            event: l'evenement de transfert a evaluer.

        Returns:
            Une `Alert` si anomalie detectee, sinon `None`.
        """
        ...


@dataclass(frozen=True)
class _Finding:
    """Regle declenchee : gravite, explication, montant suspect attribuable
    au destinataire du mint (0 si non attribuable a une adresse)."""

    severity: AlertSeverity
    reason: str
    recipient_suspect_amount: int = 0


def _excess(minted: int, expected: Fraction) -> int:
    """Montant minte au-dela de `expected`, arrondi a l'unite inferieure."""
    return max(0, math.floor(Fraction(minted) - expected))


class RuleBasedMonitor:
    """Surveillant base sur des regles : invariants du mint (OPEN_ANSWERS §1)
    et « volume eleve ET dispersion effondree » sur les transferts (§9).

    Args:
        params: parametres du surveillant de mint (defaut :
            `detection/params.py`).
        announced_admin_changes: changements d'administration annonces au
            prealable ; un evenement admin correspondant ne leve pas d'alerte.
        transfer_params: parametres du surveillant de transferts (defaut :
            `detection/params.py`).
        circulating_supply: offre en circulation, base units, pour normaliser
            le volume (GAP : aucun modele partage ne la porte ; mise a jour via
            `update_circulating_supply`). None = tranches non evaluees.
        known_addresses: adresses deja vues avant le debut de l'observation
            (historique du jeu de donnees) ; elles ne sont pas « neuves ».
    """

    def __init__(
        self,
        params: MintRuleParams | None = None,
        announced_admin_changes: Iterable[AdminAnnouncement] = (),
        transfer_params: TransferRuleParams | None = None,
        circulating_supply: int | None = None,
        known_addresses: Iterable[str] = (),
    ) -> None:
        self.params = params if params is not None else MintRuleParams()
        self._announced = frozenset(
            (a.kind, a.subject_address.lower()) for a in announced_admin_changes
        )
        self.transfer_params = (
            transfer_params if transfer_params is not None else TransferRuleParams()
        )
        self._circulating_supply: int | None = None
        if circulating_supply is not None:
            self.update_circulating_supply(circulating_supply)
        self._exit_points = frozenset(
            a.lower() for a in self.transfer_params.exit_points
        )
        self._known: set[str] = {a.lower() for a in known_addresses}
        self._open_slot: SlotAggregate | None = None
        self._baselines: dict[int, deque[tuple[float, float]]] = {}
        self._last_slot_stats: TransferSlotStats | None = None

    @property
    def last_slot_stats(self) -> TransferSlotStats | None:
        """Mesures de la derniere tranche evaluee (pour le dashboard)."""
        return self._last_slot_stats

    def update_circulating_supply(self, supply: int) -> None:
        """Met a jour l'offre en circulation (base units) utilisee a la
        cloture des prochaines tranches.

        Raises:
            ValueError: si `supply` <= 0.
        """
        if supply <= 0:
            raise ValueError("circulating_supply doit etre > 0")
        self._circulating_supply = supply

    def check_mint(
        self, event: MintEvent, context: MintContext | None = None
    ) -> Alert | None:
        """Verifie I1, I3, I5, I6, les evenements admin et l'ecart d'oracle.

        Aucune regle ne porte sur la taille du mint. Une verification dont les
        entrees manquent dans `context` est sautee. Plusieurs regles
        declenchees produisent UNE alerte (gravite max, raisons concatenees).

        Args:
            event: le mint observe.
            context: donnees hors `MintEvent` (depot, deposant/`requester` pour
                I3, taux, offre, collateral, evenements admin, taux de
                reference). None = rien a verifier.

        Returns:
            Une `Alert` (« retarder le perimetre ») si une regle est violee,
            sinon `None`.
        """
        if context is None:
            return None
        findings = [
            finding
            for finding in (
                self._check_i1(event, context),
                self._check_i3(event, context),
                self._check_oracle(event, context),
                self._check_i5(event, context),
                self._check_i6(context),
            )
            if finding is not None
        ]
        findings.extend(self._check_admin_events(context.admin_events))
        if not findings:
            return None
        return self._build_alert(event, findings)

    def check_transfer(self, event: TransferEvent) -> Alert | None:
        """Agrege un transfert dans sa tranche ; evalue la tranche precedente
        quand `event` ouvre une tranche plus recente.

        L'alerte part a la CLOTURE d'une tranche (pas au transfert) : soit
        quand un transfert d'une tranche suivante arrive (ici), soit via
        `close_slot_if_due` (horloge), pour ne pas attendre le trafic suivant.
        Un transfert en retard (tranche anterieure a la tranche ouverte) est
        compte dans la tranche ouverte. Les tranches vides ne sont pas
        enregistrees dans la baseline.

        Args:
            event: le transfert observe (Ghost ou non, tous comptes).

        Returns:
            Une `Alert` (« retarder le perimetre ») si la tranche cloturee par
            cet evenement presente volume eleve ET dispersion effondree vs la
            baseline du meme creneau, sinon `None`.
        """
        slot_index = self._slot_index(event.observed_at)
        alert = None
        if self._open_slot is not None and slot_index > self._open_slot.slot_index:
            alert = self._close_open_slot()
        if self._open_slot is None:
            self._open_slot = SlotAggregate(slot_index)
        self._open_slot.add(event)
        return alert

    def close_slot_if_due(self, now: datetime) -> Alert | None:
        """Cloture la tranche ouverte si `now` a atteint sa fin.

        A appeler sur un minuteur : la detection doit etre plus rapide que la
        fenetre Ghost normale (OPEN_QUESTIONS §2, proposition 1).

        Args:
            now: heure courante (UTC).

        Returns:
            L'`Alert` de la tranche cloturee le cas echeant, sinon `None`.
        """
        if self._open_slot is None:
            return None
        if self._slot_index(now) <= self._open_slot.slot_index:
            return None
        return self._close_open_slot()

    def _slot_index(self, moment: datetime) -> int:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return math.floor(moment.timestamp()) // self.transfer_params.slot_seconds

    def _is_new(self, address: str) -> bool:
        """« Adresse neuve » PROVISOIRE (OPEN_QUESTIONS §2, proposition 2) :
        aucune transaction avant le debut de la tranche dans nos donnees.
        Les points de sortie etiquetes ne sont jamais neufs."""
        return address not in self._known and address not in self._exit_points

    def _close_open_slot(self) -> Alert | None:
        slot = self._open_slot
        assert slot is not None
        self._open_slot = None
        tp = self.transfer_params
        supply = self._circulating_supply
        slot_start = datetime.fromtimestamp(
            slot.slot_index * tp.slot_seconds, tz=timezone.utc
        )
        if supply is None:
            # GAP : sans offre en circulation, pas de ratio normalise (§9) :
            # la tranche n'est ni evaluee ni enregistree.
            logger.warning(
                "tranche %s UTC NON evaluee : offre en circulation inconnue "
                "(%d transferts ni evalues ni ajoutes a la baseline)",
                f"{slot_start:%Y-%m-%d %H:%M}",
                len(slot.events),
            )
            self._known.update(slot.participants())
            self._last_slot_stats = None
            return None

        volume = slot.volume
        volume_ratio = volume / supply
        herfindahl = slot.herfindahl()
        slots_per_period = tp.baseline_period_seconds // tp.slot_seconds
        baseline = self._baselines.setdefault(
            slot.slot_index % slots_per_period,
            deque(maxlen=tp.baseline_window_slots),
        )
        volume_z: float | None = None
        hhi_z: float | None = None
        if len(baseline) >= tp.min_history_slots:
            volume_z = robust_zscore(
                volume_ratio,
                [v for v, _ in baseline],
                tp.mad_scale,
                tp.mad_floor_relative,
            )
            hhi_z = robust_zscore(
                herfindahl,
                [h for _, h in baseline],
                tp.mad_scale,
                tp.mad_floor_relative,
            )
        else:
            logger.warning(
                "tranche %s UTC NON evaluee : historique insuffisant (%d/%d "
                "tranches du meme creneau) ; elle nourrit la baseline sans alerter",
                f"{slot_start:%Y-%m-%d %H:%M}",
                len(baseline),
                tp.min_history_slots,
            )
        stats = TransferSlotStats(
            slot_start=slot_start,
            slot_end=slot_start + timedelta(seconds=tp.slot_seconds),
            transfer_count=len(slot.events),
            volume=volume,
            gross_volume=slot.gross_volume,
            circulating_supply=supply,
            volume_ratio=volume_ratio,
            herfindahl=herfindahl,
            effective_recipients=1 / herfindahl if herfindahl else 0.0,
            distinct_recipients=len(slot.inflows()),
            new_sender_share=slot.share(lambda e: self._is_new(e.sender.lower())),
            exit_share=slot.share(lambda e: e.recipient.lower() in self._exit_points),
            max_fan_out=slot.max_fan_out(),
            history_size=len(baseline),
            volume_zscore=volume_z,
            herfindahl_zscore=hhi_z,
        )
        triggered = (
            volume_z is not None
            and hhi_z is not None
            and volume_z >= tp.volume_z_threshold
            and hhi_z >= tp.hhi_z_threshold
        )
        alert = self._build_transfer_alert(slot, stats) if triggered else None
        if not triggered:
            # PROVISOIRE : une tranche declenchante n'entre pas dans la
            # baseline (l'attaque ne doit pas elargir sa propre reference).
            baseline.append((volume_ratio, herfindahl))
        self._known.update(slot.participants())
        self._last_slot_stats = stats
        return alert

    def _build_transfer_alert(
        self, slot: SlotAggregate, stats: TransferSlotStats
    ) -> Alert:
        assert stats.volume_zscore is not None
        assert stats.herfindahl_zscore is not None
        seeds = slot.seeds(self._is_new)
        inflows = slot.inflows()
        if seeds:
            subject = max(seeds, key=lambda s: s.suspect_amount).address
            suspect = sum(s.suspect_amount for s in seeds)
            seeds_inflow = sum(inflows[s.address.lower()] for s in seeds)
            ratio = min(1.0, suspect / seeds_inflow)
        else:
            # Aucun flux issu d'adresses neuves : alerte sur le destinataire
            # le plus concentre (solde net : un relais n'est pas un sujet,
            # #87), sans graine (voir SlotAggregate.seeds).
            concentration = slot.net_inflows() or inflows
            subject = max(sorted(concentration), key=lambda a: concentration[a])
            suspect = 0
            ratio = 0.0
        source = slot.largest_transfer_to(subject.lower())
        reason = (
            f"Volume eleve ET dispersion effondree sur la tranche "
            f"{stats.slot_start:%Y-%m-%d %H:%M}-{stats.slot_end:%H:%M} UTC : "
            f"volume/offre {stats.volume_ratio:.4%} (z={stats.volume_zscore:.1f}), "
            f"Herfindahl {stats.herfindahl:.4f} (z={stats.herfindahl_zscore:.1f}) "
            f"vs mediane+MAD de {stats.history_size} tranches du meme creneau ; "
            f"nombre effectif de destinataires {stats.effective_recipients:.1f}, "
            f"destinataires distincts {stats.distinct_recipients} (indicatif) ; "
            f"part envoyee par des adresses neuves {stats.new_sender_share:.0%}, "
            f"part vers points de sortie {stats.exit_share:.0%}, "
            f"fan-out max {stats.max_fan_out}. " + _RESPONSE_NOTE
        )
        return Alert(
            alert_id=str(uuid.uuid4()),
            kind=AlertKind.TRANSFER,
            severity=self.transfer_params.anomaly_severity,
            created_at=datetime.now(timezone.utc),
            monitor_name=TRANSFER_MONITOR_NAME,
            subject_address=source.recipient,
            source_tx_hash=source.tx_hash,
            contamination_ratio=ratio,
            suspect_amount=suspect,
            # Champ « effondree = concentration » : 1/HHI (nombre effectif de
            # destinataires), le HHI brut est dans `reason` / last_slot_stats.
            dispersion_score=stats.effective_recipients,
            volume_zscore=stats.volume_zscore,
            reason=reason,
            seeds=seeds,
        )

    def _check_i1(self, event: MintEvent, context: MintContext) -> _Finding | None:
        if context.deposit_amount is None or context.rate is None:
            return None
        expected = Fraction(context.deposit_amount) * context.rate
        tolerance = expected * self.params.i1_epsilon
        if abs(Fraction(event.amount) - expected) <= tolerance:
            return None
        return _Finding(
            severity=self.params.invariant_severity,
            reason=(
                f"I1 viole : minte {event.amount} pour depot "
                f"{context.deposit_amount} x taux {context.rate} = "
                f"{math.floor(expected)} attendu (epsilon {self.params.i1_epsilon})"
            ),
            recipient_suspect_amount=_excess(event.amount, expected),
        )

    def _check_i3(self, event: MintEvent, context: MintContext) -> _Finding | None:
        """I3 : le destinataire du mint est le deposant de la demande (#91).

        Detecte le detournement a 1:1 (scenario B) : bilan global juste, mais
        la demande d'une victime est mintee vers une autre adresse. Tout le
        mint est attribue au destinataire comme montant suspect.
        """
        if context.requester is None:
            return None
        if event.recipient.lower() == context.requester.lower():
            return None
        return _Finding(
            severity=self.params.invariant_severity,
            reason=(
                f"I3 viole : mint de {event.amount} vers {event.recipient}, "
                f"deposant de la demande {context.requester} (detournement ?)"
            ),
            recipient_suspect_amount=event.amount,
        )

    def _check_oracle(
        self, event: MintEvent, context: MintContext
    ) -> _Finding | None:
        if context.rate is None or context.reference_rate is None:
            return None
        reference = context.reference_rate
        if abs(context.rate - reference) <= reference * self.params.oracle_delta:
            return None
        suspect = 0
        if context.deposit_amount is not None:
            suspect = _excess(
                event.amount, Fraction(context.deposit_amount) * reference
            )
        return _Finding(
            severity=self.params.oracle_deviation_severity,
            reason=(
                f"ecart d'oracle : taux applique {context.rate} vs reference "
                f"{reference} (delta {self.params.oracle_delta})"
            ),
            recipient_suspect_amount=suspect,
        )

    def _check_i5(self, event: MintEvent, context: MintContext) -> _Finding | None:
        if context.total_supply_before is None or context.total_supply_after is None:
            return None
        minted_total = (
            context.interval_minted_total
            if context.interval_minted_total is not None
            else event.amount
        )
        supply_delta = context.total_supply_after - context.total_supply_before
        drift = supply_delta - (minted_total - context.interval_burned_total)
        if abs(drift) <= self.params.i5_supply_tolerance:
            return None
        return _Finding(
            severity=self.params.invariant_severity,
            reason=(
                f"I5 viole : Delta totalSupply {supply_delta} != Somme Mint "
                f"{minted_total} - Somme Burn {context.interval_burned_total} "
                f"(ecart {drift}, mint hors chemin prevu ?)"
            ),
        )

    def _check_i6(self, context: MintContext) -> _Finding | None:
        if context.total_supply_after is None or context.collateral_value is None:
            return None
        ceiling = Fraction(context.collateral_value) * self.params.i6_collateral_factor
        if context.total_supply_after <= ceiling:
            return None
        return _Finding(
            severity=self.params.invariant_severity,
            reason=(
                f"I6 viole : totalSupply {context.total_supply_after} > collateral "
                f"{context.collateral_value} x facteur "
                f"{self.params.i6_collateral_factor}"
            ),
        )

    def _check_admin_events(self, events: Iterable[AdminEvent]) -> list[_Finding]:
        return [
            _Finding(
                severity=self.params.admin_event_severity,
                reason=(
                    f"evenement admin non annonce : {event.kind.value} "
                    f"{event.subject_address} (tx {event.tx_hash})"
                ),
            )
            for event in events
            if (event.kind, event.subject_address.lower()) not in self._announced
        ]

    def _build_alert(self, event: MintEvent, findings: list[_Finding]) -> Alert:
        severity = max(
            (f.severity for f in findings), key=lambda s: _SEVERITY_RANK[s]
        )
        # Les montants suspects de plusieurs regles se recouvrent (meme mint) :
        # on garde le plus grand, borne par le montant minte.
        suspect = min(
            event.amount, max(f.recipient_suspect_amount for f in findings)
        )
        ratio = suspect / event.amount
        seeds = (
            [
                AlertSeed(
                    address=event.recipient,
                    suspect_amount=suspect,
                    contamination_ratio=ratio,
                )
            ]
            if suspect > 0
            else []
        )
        return Alert(
            alert_id=str(uuid.uuid4()),
            kind=AlertKind.MINT,
            severity=severity,
            created_at=datetime.now(timezone.utc),
            monitor_name=MINT_MONITOR_NAME,
            subject_address=event.recipient,
            source_tx_hash=event.tx_hash,
            contamination_ratio=ratio,
            suspect_amount=suspect,
            reason="; ".join(f.reason for f in findings) + ". " + _RESPONSE_NOTE,
            seeds=seeds,
        )
