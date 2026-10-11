"""Rapport d'incident DORA (#15) de l'incident REEL joue sur Avalanche Fuji (#148).

Traduit le rejeu `fuji_live.FujiRun` (vraies transactions) en `Alert`, `ResponseAction` et
`AuditLogEntry` partages (`shared/`), puis appelle tel quel `llm.report` via
`real_report.incident_report_markdown` (hors ligne par defaut, Bedrock avec `LLM_LIVE=1`).
Chaque etape du rapport pointe vers sa transaction sur Snowtrace.

Le declencheur de l'alerte (tentative de mint gonfle rejetee on-chain, venant de la cle de
service) est une REGLE DE DEMO du dashboard, pas un surveillant du module `detection` : le rapport
le dit. Le retard et la destruction sont, eux, les vraies transactions des roles on-chain.
"""

from __future__ import annotations

from datetime import timedelta

from dashboard.scenarios.fuji_live import FUJI_ACTORS_ONCHAIN, FujiRun, TxRecord, address_url
from dashboard.scenarios.real_report import incident_report_markdown
from llm.client import BedrockClient
from shared.models import (
    Alert,
    AlertKind,
    AlertSeverity,
    AuditLogEntry,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
)

DEMO_RULE_NAME = "dashboard:regle_demo_mint_gonfle_rejete"
INCIDENT_ACTORS = ("attacker", "watcher", "guardian1", "guardian2", "guardian3")
WINDOW = timedelta(seconds=600)  # fenetre W de la fixture Ghost (cf. fuji_live.GHOST_W_SECONDS)


class FujiReportError(ValueError):
    """Le rejeu ne contient pas les transactions d'un incident complet."""


def _find(run: FujiRun, predicate: object, what: str) -> TxRecord:
    for record in run.transactions:
        if predicate(record):  # type: ignore[operator]
            return record
    raise FujiReportError(f"transaction introuvable dans le rejeu : {what}")


def _at(record: TxRecord, run: FujiRun):  # noqa: ANN202 - datetime
    return record.timestamp or run.finished_at


def build_fuji_incident(run: FujiRun) -> tuple[Alert, list[ResponseAction], list[AuditLogEntry]]:
    """Alerte, actions et journal de l'incident Fuji, construits sur les vraies transactions."""
    attacker = run.accounts["attacker"]
    inflated = _find(run, lambda r: r.actor == "attacker" and not r.success,
                     "mint gonflé rejeté")
    delay = _find(run, lambda r: r.actor == "watcher", "retard du surveillant")
    propose = _find(run, lambda r: r.actor == "guardian1" and "proposition" in r.label.lower(),
                    "proposition de destruction")
    approve = _find(run, lambda r: r.actor == "guardian2" and "validation" in r.label.lower(),
                    "validation 2 sur 3")
    suspect = run.sell_mprime or run.seller_payment_before * DECIMALS_SCALE
    multiplier = run.signed_amount // run.deposit if run.deposit else 0

    alert = Alert(
        alert_id=f"fuji-{inflated.tx_hash[2:10]}",
        kind=AlertKind.MINT,
        severity=AlertSeverity.CRITICAL,
        created_at=_at(inflated, run),
        monitor_name=DEMO_RULE_NAME,
        subject_address=attacker,
        source_tx_hash=inflated.tx_hash,
        contamination_ratio=1.0,
        suspect_amount=suspect,
        reason=(f"Clé de service présumée compromise : un mint gonflé (×{multiplier} le dépôt) a été "
                "rejeté on-chain par le ProtectedMinter, et le même acteur, vendeur de Ghost, a été "
                "signalé (méthode non divulguée) sur Avalanche Fuji. Règle de démo du dashboard, pas "
                "un surveillant du module detection."),
    )
    delay_action = ResponseAction(
        action_id=f"fuji-delay-{delay.tx_hash[2:10]}",
        action_type=ResponseActionType.DELAY,
        status=ResponseActionStatus.APPLIED,
        created_at=_at(delay, run),
        expires_at=_at(delay, run) + WINDOW,
        perimeter_address=attacker,
        triggering_alert_id=alert.alert_id,
        contamination_ratio=1.0,
        suspect_amount=suspect,
    )
    destroy_action = ResponseAction(
        action_id=f"fuji-destroy-{approve.tx_hash[2:10]}",
        action_type=ResponseActionType.DESTROY,
        status=ResponseActionStatus.APPLIED,
        created_at=_at(approve, run),
        perimeter_address=attacker,
        triggering_alert_id=alert.alert_id,
        decision_id=f"multisig 2/3 (proposition {propose.tx_hash[:10]}…, validation "
                    f"{approve.tx_hash[:10]}…)",
        contamination_ratio=1.0,
        suspect_amount=suspect,
    )
    linked = {delay.tx_hash: delay_action.action_id, propose.tx_hash: destroy_action.action_id,
              approve.tx_hash: destroy_action.action_id}
    start = run.transactions.index(inflated) - 1  # le depot qui precede la tentative
    audit = [
        AuditLogEntry(
            entry_id=f"fuji-{record.tx_hash[2:14]}",
            recorded_at=_at(record, run),
            actor=FUJI_ACTORS_ONCHAIN.get(record.actor, record.actor),
            event_type="tx_success" if record.success else "tx_reverted",
            subject_address=attacker,
            related_action_id=linked.get(record.tx_hash),
            related_tx_hash=record.tx_hash,
            payload={"snowtrace": record.url, "bloc": str(record.block_number),
                     "statut": "succès" if record.success else "rejetée on-chain"},
            message=record.label,
        )
        for record in run.transactions[max(start, 0):]
        if record.actor in INCIDENT_ACTORS
    ]
    return alert, [delay_action, destroy_action], audit


def _evidence(run: FujiRun, audit: list[AuditLogEntry]) -> str:
    lines = ["", "## Preuves on-chain (Avalanche Fuji, chain id 43113)", "",
             "| Heure (UTC) | Qui | Quoi | Statut | Transaction |", "|---|---|---|---|---|"]
    for entry in audit:
        lines.append(f"| {entry.recorded_at:%H:%M:%S} | {entry.actor} | {entry.message} | "
                     f"{entry.payload['statut']} | [Snowtrace]({entry.payload['snowtrace']}) |")
    lines += ["", "Contrats : " + " · ".join(f"[{name}]({address_url(address)})"
                                             for name, address in run.contracts.items()),
              "", "_Testnet Fuji : jetons de test sans valeur. Schéma reproduit d'après l'incident "
              "Resolv (Ethereum)._"]
    return "\n".join(lines)


def fuji_incident_report(run: FujiRun, client: BedrockClient | None = None,
                         mode: str | None = None) -> str:
    """Rapport DORA (Markdown) de l'incident Fuji, suivi du tableau des preuves Snowtrace."""
    alert, actions, audit = build_fuji_incident(run)
    report = incident_report_markdown(alert, actions, audit, generated_at=run.finished_at,
                                      client=client, mode=mode)
    return report + "\n" + _evidence(run, audit)


__all__ = ["DEMO_RULE_NAME", "FujiReportError", "build_fuji_incident", "fuji_incident_report"]
