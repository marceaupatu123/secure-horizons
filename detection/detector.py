"""Surveillants : detection d'anomalies sur mints et transferts.

SQUELETTE : signatures et types poses, corps a implementer par le proprietaire
du module `detection`. Les SEUILS, invariants et signaux ne sont PAS decides
ici (decisions d'equipe : voir `docs/OPEN_QUESTIONS.md`).

Un surveillant consomme des evenements (`MintEvent`, `TransferEvent`) et renvoie
une `Alert` quand il juge une situation anormale, sinon `None`. L'IA n'est qu'un
surveillant parmi d'autres et ne decide jamais seule d'un blocage.
"""

from __future__ import annotations

from typing import Protocol

from shared.models import Alert, MintEvent, TransferEvent


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


class RuleBasedMonitor:
    """Surveillant base sur des regles (squelette).

    Les regles et seuils concrets sont a definir en equipe avant implementation.
    """

    def check_mint(self, event: MintEvent) -> Alert | None:
        """Voir `Monitor.check_mint`."""
        raise NotImplementedError("detection.check_mint : a implementer")

    def check_transfer(self, event: TransferEvent) -> Alert | None:
        """Voir `Monitor.check_transfer`."""
        raise NotImplementedError("detection.check_transfer : a implementer")
