"""Point d'entree du module response : `python -m response`.

Rejoue un parcours fictif de bout en bout (donnees synthetiques uniquement) :
alerte critique -> retard auto-expirant -> proposition de destruction par l'IA
-> decision multisig 2/3 -> destruction, puis un second perimetre dont le retard
expire en silence. Affiche le journal d'audit DORA.

Option : `--audit-jsonl PATH` recopie le journal en JSONL.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from response.orchestrator import ResponseOrchestrator, ResponsePolicy
from shared.models import (
    Alert,
    AlertKind,
    AlertSeverity,
    FreezeDirection,
    FreezeRequest,
    ReleaseDecision,
    ReleaseVerdict,
)

# Adresses et hash FICTIFS.
GUARDIANS = (
    "0x5555555555555555555555555555555555555555",
    "0x6666666666666666666666666666666666666666",
    "0x7777777777777777777777777777777777777777",
)
SUSPECT = "0x2222222222222222222222222222222222222222"
OTHER = "0x8888888888888888888888888888888888888888"
TX = "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778"


class _DemoClock:
    """Horloge manuelle pour rendre la demo deterministe."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def run_demo(audit_path: Path | None = None) -> ResponseOrchestrator:
    """Execute le scenario fictif et renvoie l'orchestrateur final.

    Args:
        audit_path: fichier JSONL optionnel recevant le journal d'audit.

    Returns:
        L'orchestrateur apres le scenario (journal consultable).
    """
    clock = _DemoClock(datetime(2026, 10, 10, 14, 30, tzinfo=timezone.utc))
    counter = iter(range(1, 10_000))
    orchestrator = ResponseOrchestrator(
        ResponsePolicy(guardians=frozenset(GUARDIANS)),
        clock=clock,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
        audit_path=audit_path,
    )

    alert = Alert(
        alert_id="alert-0001",
        kind=AlertKind.TRANSFER,
        severity=AlertSeverity.CRITICAL,
        created_at=clock.now,
        monitor_name="rule_transfer",
        subject_address=SUSPECT,
        source_tx_hash=TX,
        contamination_ratio=0.87,
        suspect_amount=870_000_000_000_000_000,
        reason="Volume eleve ET dispersion effondree (donnees fictives)",
    )
    orchestrator.handle_alert(alert)

    clock.now += timedelta(minutes=2)
    proposal = FreezeRequest(
        request_id="fr-ai-0001",
        direction=FreezeDirection.CONFIRM,
        requested_by="llm",
        created_at=clock.now,
        perimeter_address=SUSPECT,
        triggering_alert_id=alert.alert_id,
        contamination_ratio=0.87,
        suspect_amount=870_000_000_000_000_000,
    )
    orchestrator.request_freeze(proposal)

    clock.now += timedelta(minutes=10)
    orchestrator.apply_release(
        ReleaseDecision(
            decision_id="rd-0001",
            verdict=ReleaseVerdict.CONFIRM_DESTROY,
            decided_at=clock.now,
            perimeter_address=SUSPECT,
            related_freeze_id=proposal.request_id,
            signers=list(GUARDIANS[:2]),
            threshold=2,
            burn_ratio=0.87,
            rationale="Audit humain : lignage frauduleux confirme (fictif)",
        )
    )

    # Second perimetre : faux positif, personne ne tranche -> retour auto.
    orchestrator.handle_alert(
        alert.model_copy(
            update={
                "alert_id": "alert-0002",
                "severity": AlertSeverity.WARNING,
                "subject_address": OTHER,
                "contamination_ratio": 0.05,
                "suspect_amount": 1_000,
            }
        )
    )
    clock.now += timedelta(minutes=orchestrator.policy.delay_minutes + 1)
    orchestrator.expire_due()
    return orchestrator


def main(argv: list[str] | None = None) -> None:
    """Point d'entree executable.

    Args:
        argv: arguments CLI (par defaut ceux du processus).
    """
    parser = argparse.ArgumentParser(description="Demo fictive de la reponse graduee.")
    parser.add_argument("--audit-jsonl", type=Path, default=None, help="copie JSONL du journal")
    args = parser.parse_args(argv)

    orchestrator = run_demo(args.audit_jsonl)
    print("Journal d'audit (DORA) - donnees fictives :")
    for entry in orchestrator.audit_log:
        print(f"  {entry.recorded_at.isoformat()}  {entry.actor:<22} {entry.message}")


if __name__ == "__main__":
    main()
