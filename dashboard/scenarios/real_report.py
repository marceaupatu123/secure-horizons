"""Rapport d'incident DORA (#15) sur l'alerte confirmee d'un scenario (#113).

Ferme la chaine de demo : trafic #24 -> surveillants #11/#12 -> reponse #17 -> rapport
d'incident `llm.report.build_incident_report` (#15), avec les VRAIES actions et le VRAI
journal d'audit de l'orchestrateur. Rien n'est reimplemente : l'API publique de `llm/` est
appelee telle quelle.

- **Hors ligne par defaut** : faux client `llm.demo.OfflineConverseStub`, aucun appel AWS,
  resultat deterministe (meme seed = meme rapport, horodate a l'instant simule).
- **Bedrock reel en opt-in** : `LLM_LIVE=1` (meme variable que `python -m llm`), reglages de
  `.env` via `shared.config.load_settings`, limiteur ~1 req/s du `BedrockClient`. Un seul appel,
  et seulement quand une alerte a ete confirmee par le multisig (regle « LLM sur alerte »). Si
  les reglages manquent, repli hors ligne, signale dans le rapport.

L'IA redige seulement : elle n'emet aucune action (`llm.report`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime

from llm.client import BedrockClient
from llm.demo import OfflineConverseStub
from llm.report import build_incident_report
from shared.config import Settings, load_settings
from shared.models import Alert, AuditLogEntry, ResponseAction

LLM_LIVE_ENV = "LLM_LIVE"
MODE_OFFLINE = "hors ligne (aucun appel AWS)"
MODE_LIVE = "Bedrock Converse (LLM_LIVE=1)"


def _offline_client() -> BedrockClient:
    settings = Settings(aws_region="us-east-1", bedrock_model_id="offline-stub",
                        fuji_rpc_url="offline", guardian_private_key="offline")
    return BedrockClient(settings, client=OfflineConverseStub())


def report_client(env: Mapping[str, str] | None = None) -> tuple[BedrockClient, str]:
    """Client du rapport et libelle du mode (`LLM_LIVE=1` -> Bedrock, sinon hors ligne).

    Returns:
        `(client, mode)` ; repli hors ligne si `LLM_LIVE=1` mais reglages absents.
    """
    source = os.environ if env is None else env
    if source.get(LLM_LIVE_ENV) != "1":
        return _offline_client(), MODE_OFFLINE
    try:
        return BedrockClient(load_settings()), MODE_LIVE
    except (KeyError, ValueError, RuntimeError) as exc:
        return _offline_client(), f"{MODE_OFFLINE} — LLM_LIVE=1 mais réglages absents ({exc})"


def related_actions(alert_addresses: set[str],
                    actions: Sequence[ResponseAction]) -> list[ResponseAction]:
    """Actions de reponse sur les adresses de l'alerte (minuscules), ordre d'origine."""
    return [a for a in actions
            if a.perimeter_address is not None and a.perimeter_address.lower() in alert_addresses]


def related_audit(alert_addresses: set[str], actions: Sequence[ResponseAction],
                  entries: Sequence[AuditLogEntry]) -> list[AuditLogEntry]:
    """Entrees du journal qui concernent l'alerte (adresse ou action liee)."""
    action_ids = {a.action_id for a in actions}
    return [e for e in entries
            if (e.subject_address is not None and e.subject_address.lower() in alert_addresses)
            or (e.related_action_id is not None and e.related_action_id in action_ids)]


def incident_report_markdown(alert: Alert, actions: Sequence[ResponseAction],
                             audit_entries: Sequence[AuditLogEntry], generated_at: datetime,
                             client: BedrockClient | None = None,
                             mode: str | None = None) -> str:
    """Rapport d'incident DORA (Markdown) d'une alerte confirmee, via `llm.report`.

    Args:
        alert: alerte confirmee (perimetre detruit par le multisig).
        actions: actions de reponse liees.
        audit_entries: entrees du journal d'audit liees.
        generated_at: horodatage du rapport (instant simule, pour le determinisme).
        client: client LLM ; defaut : `report_client()`.
        mode: libelle du mode, affiche en tete ; defaut : celui de `report_client()`.

    Returns:
        Le rapport en Markdown, precede d'une ligne indiquant le mode LLM.
    """
    if client is None:
        client, default_mode = report_client()
        mode = mode or default_mode
    report = build_incident_report(alert, client, actions, audit_entries,
                                   generated_at=generated_at)
    return f"_Rapport généré par `llm` (#15), mode : {mode or MODE_OFFLINE}._\n\n" + \
        report.to_markdown()
