"""Orchestration de la reponse graduee.

SQUELETTE : signatures et types poses, corps a implementer par le proprietaire
du module `response`. Les regles de declenchement (quels cas -> gel automatique,
quels cas -> validation humaine) ne sont PAS decidees ici (decisions d'equipe :
voir `docs/OPEN_QUESTIONS.md`).

Principe deja acte : l'IA ne decide jamais seule d'un blocage ; un gel est
reversible et sa levee passe par un humain (multisig). Veto asymetrique : on
peut ralentir (geler), on ne peut pas accelerer.
"""

from __future__ import annotations

from shared.models import (
    Alert,
    AuditLogEntry,
    FreezeRequest,
    ReleaseDecision,
    ResponseAction,
)


class ResponseOrchestrator:
    """Coordonne la reponse a partir d'une alerte (squelette)."""

    def handle_alert(self, alert: Alert) -> ResponseAction:
        """Decide et declenche la reponse graduee pour une alerte donnee.

        Args:
            alert: l'alerte emise par un surveillant.

        Returns:
            L'action de reponse appliquee ou proposee.
        """
        raise NotImplementedError("response.handle_alert : a implementer")

    def request_freeze(self, request: FreezeRequest) -> ResponseAction:
        """Enregistre une demande de gel emanant d'un surveillant.

        Args:
            request: la demande de gel.

        Returns:
            L'action de reponse correspondante.
        """
        raise NotImplementedError("response.request_freeze : a implementer")

    def apply_release(self, decision: ReleaseDecision) -> ResponseAction:
        """Applique une levee/confirmation de gel decidee par un humain.

        Args:
            decision: la decision humaine (multisig).

        Returns:
            L'action de reponse correspondante.
        """
        raise NotImplementedError("response.apply_release : a implementer")

    def record_audit(self, action: ResponseAction) -> AuditLogEntry:
        """Journalise une action pour la conformite DORA.

        Args:
            action: l'action de reponse a tracer.

        Returns:
            L'entree de journal d'audit creee.
        """
        raise NotImplementedError("response.record_audit : a implementer")
