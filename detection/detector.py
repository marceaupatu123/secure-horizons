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
`MintEvent.request_id` n'est PAS utilise (sentinelle PROVISOIRE de #9).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from typing import Protocol

from detection.inputs import AdminAnnouncement, AdminEvent, MintContext
from detection.params import MINT_MONITOR_NAME, MintRuleParams
from shared.models import (
    Alert,
    AlertKind,
    AlertSeed,
    AlertSeverity,
    MintEvent,
    TransferEvent,
)

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
    """Surveillant base sur des regles (invariants du volet 1, OPEN_ANSWERS §1).

    Args:
        params: parametres de detection (defaut : `detection/params.py`).
        announced_admin_changes: changements d'administration annonces au
            prealable ; un evenement admin correspondant ne leve pas d'alerte.
    """

    def __init__(
        self,
        params: MintRuleParams | None = None,
        announced_admin_changes: Iterable[AdminAnnouncement] = (),
    ) -> None:
        self.params = params if params is not None else MintRuleParams()
        self._announced = frozenset(
            (a.kind, a.subject_address.lower()) for a in announced_admin_changes
        )

    def check_mint(
        self, event: MintEvent, context: MintContext | None = None
    ) -> Alert | None:
        """Verifie I1, I5, I6, les evenements admin et l'ecart d'oracle.

        Aucune regle ne porte sur la taille du mint. Une verification dont les
        entrees manquent dans `context` est sautee. Plusieurs regles
        declenchees produisent UNE alerte (gravite max, raisons concatenees).

        Args:
            event: le mint observe.
            context: donnees hors `MintEvent` (depot, taux, offre, collateral,
                evenements admin, taux de reference). None = rien a verifier.

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
        """Voir `Monitor.check_transfer`."""
        raise NotImplementedError("detection.check_transfer : a implementer")

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
