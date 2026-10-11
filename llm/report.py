"""Rapport d'incident pre-rempli, structure d'apres les rubriques DORA.

A partir d'une alerte confirmee (et, si disponibles, des `ResponseAction` et
entrees du journal d'audit), produit un `IncidentReport` :
  - champs deterministes copies des modeles d'entree (identifiant, horodatage
    de detection, classification, perimetre, chronologie, qui a decide quoi) ;
  - champs narratifs (description, cause probable, impact, mitigation) rediges
    par le LLM en UN SEUL appel par rapport, sans nouvel essai.

Si l'appel LLM echoue ou repond hors format, les champs narratifs sont des
espaces reserves « a completer » : le rapport est toujours produit.

Ce rapport est un brouillon structure : il ne constitue pas une declaration
conforme a DORA (OPEN_ANSWERS §4). Le modele est local a `llm/` (pas de
contrat partage).

L'appelant est responsable de n'appeler `build_incident_report` que sur une
alerte confirmee : `Alert` ne porte pas de champ de confirmation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from llm.client import REPORT_MAX_TOKENS, BedrockClient, LLMError
from llm.prompts import SYSTEM_PROMPT_REPORT, build_report_prompt
from shared.models import (
    Alert,
    AlertKind,
    AlertSeed,
    AlertSeverity,
    AuditLogEntry,
    ResponseAction,
    ResponseActionType,
)

REPORT_SECTIONS: tuple[str, ...] = (
    "## 1. Identification de l'incident",
    "## 2. Classification",
    "## 3. Périmètre affecté",
    "## 4. Chronologie",
    "## 5. Décisions (qui a décidé quoi)",
    "## 6. Description",
    "## 7. Impact",
    "## 8. Cause racine probable",
    "## 9. Mesures de mitigation et de remédiation",
)

REPORT_DISCLAIMER: str = (
    "Brouillon structuré d'après les rubriques de notification d'incident majeur lié "
    "aux TIC (DORA). Ce document ne constitue pas une déclaration conforme ; il doit "
    "être relu et complété par un humain. Données fictives (environnement de test)."
)

PLACEHOLDER_PREFIX: str = "[À compléter par l'analyste"

AI_NO_DECISION_LINE: str = (
    "L'IA n'a pris aucune décision de destruction ni de pause globale."
)


class _ReportModel(BaseModel):
    """Base locale : aucun champ hors schema."""

    model_config = ConfigDict(extra="forbid")


class TimelineEntry(_ReportModel):
    """Evenement horodate de la chronologie de l'incident."""

    at: datetime
    actor: str
    event: str
    detail: str


class DecisionEntry(_ReportModel):
    """Action de reponse et l'auteur de la decision correspondante."""

    action_id: str
    action_type: ResponseActionType
    status: str
    decided_by: str
    decision_id: str | None = None


class IncidentNarrative(_ReportModel):
    """Parties narratives du rapport (redigees par le LLM ou a completer)."""

    description: str = Field(..., min_length=1)
    probable_cause: str = Field(..., min_length=1)
    impact: str = Field(..., min_length=1)
    mitigation: str = Field(..., min_length=1)


class IncidentReport(_ReportModel):
    """Rapport d'incident pre-rempli (local au module llm)."""

    report_id: str
    incident_id: str
    generated_at: datetime
    detected_at: datetime
    kind: AlertKind
    severity: AlertSeverity
    monitor_name: str
    subject_address: str
    source_tx_hash: str | None
    contamination_ratio: float
    suspect_amount: int
    seeds: list[AlertSeed]
    total_seed_suspect_amount: int
    timeline: list[TimelineEntry]
    decisions: list[DecisionEntry]
    narrative: IncidentNarrative
    narrative_source: Literal["llm", "placeholder"]

    def to_markdown(self) -> str:
        """Rend le rapport en Markdown, rubriques dans l'ordre de `REPORT_SECTIONS`.

        Returns:
            Le rapport complet en Markdown.
        """
        s = REPORT_SECTIONS
        ai_note = " _(rédaction IA — à relire)_" if self.narrative_source == "llm" else ""
        lines: list[str] = [
            f"# Rapport d'incident (pré-rempli) — {self.incident_id}",
            "",
            f"> {REPORT_DISCLAIMER}",
            "",
            s[0],
            "",
            f"- Identifiant du rapport : `{self.report_id}`",
            f"- Identifiant de l'incident (alerte) : `{self.incident_id}`",
            f"- Détecté le (UTC) : {self.detected_at.isoformat()}",
            f"- Rapport généré le (UTC) : {self.generated_at.isoformat()}",
            "",
            s[1],
            "",
            f"- Nature : `{self.kind.value}`",
            f"- Gravité (alerte) : `{self.severity.value}`",
            f"- Surveillant émetteur : `{self.monitor_name}`",
            f"- Ratio de contamination : {self.contamination_ratio}",
            f"- Montant suspect : {self.suspect_amount} (base units)",
            "- Qualification « incident majeur » : non déterminée (critères à fixer par l'équipe).",
            "",
            s[2],
            "",
            f"- Adresse concernée : `{self.subject_address}`",
            f"- Transaction déclenchante : `{self.source_tx_hash or 'n/a'}`",
            f"- Montant suspect : {self.suspect_amount} (base units)",
            f"- Ratio de contamination : {self.contamination_ratio}",
            f"- Total suspect des graines : {self.total_seed_suspect_amount} (base units)",
            "",
        ]
        if self.seeds:
            lines += [
                "| Adresse graine | Montant suspect (base units) | Ratio |",
                "| --- | --- | --- |",
            ]
            lines += [
                f"| `{seed.address}` | {seed.suspect_amount} | {seed.contamination_ratio} |"
                for seed in self.seeds
            ]
        else:
            lines.append("Aucune adresse graine.")
        lines += [
            "",
            s[3],
            "",
            "| Horodatage (UTC) | Acteur | Événement | Détail |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {entry.at.isoformat()} | {_cell(entry.actor)} | {_cell(entry.event)} "
            f"| {_cell(entry.detail)} |"
            for entry in self.timeline
        ]
        lines += ["", s[4], ""]
        if self.decisions:
            lines += [
                f"- `{d.action_id}` — `{d.action_type.value}` ({d.status}) : {d.decided_by}"
                for d in self.decisions
            ]
        else:
            lines.append("- Aucune action de réponse enregistrée.")
        lines += [
            f"- {AI_NO_DECISION_LINE}",
            "",
            s[5] + ai_note,
            "",
            _neutralise_headings(self.narrative.description),
            "",
            s[6] + ai_note,
            "",
            _neutralise_headings(self.narrative.impact),
            "",
            s[7] + ai_note,
            "",
            _neutralise_headings(self.narrative.probable_cause),
            "",
            s[8] + ai_note,
            "",
            _neutralise_headings(self.narrative.mitigation),
            "",
        ]
        return "\n".join(lines)


def _cell(text: str) -> str:
    """Echappe un texte libre pour une cellule de tableau Markdown."""
    return text.replace("|", "\\|").replace("\n", " ")


def _neutralise_headings(text: str) -> str:
    """Echappe les `#` de tete de ligne d'un texte libre (texte LLM).

    Le texte du modele ne peut ainsi pas creer de titre dans le rapport.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            indent = line[: len(line) - len(stripped)]
            line = f"{indent}\\{stripped}"
        out.append(line)
    return "\n".join(out)


def _as_utc(value: datetime) -> datetime:
    """Interprete un datetime naif comme UTC (sans modifier l'entree)."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _decided_by(action: ResponseAction) -> str:
    """Auteur de la decision pour une action (regles OPEN_ANSWERS §3)."""
    if action.action_type is ResponseActionType.DELAY:
        return "surveillant / IA (retard local, auto-expirant)"
    if action.decision_id is None:
        return "multisig — décision non référencée (à vérifier)"
    quorum = "2/3" if action.action_type is ResponseActionType.DESTROY else "3/3"
    return f"multisig {quorum} (decision_id={action.decision_id})"


def _build_timeline(
    alert: Alert,
    actions: Sequence[ResponseAction],
    audit_entries: Sequence[AuditLogEntry],
) -> list[TimelineEntry]:
    """Chronologie triee (stable) : alerte, actions, journal d'audit.

    Les datetimes naifs sont interpretes comme UTC (melange naif/aware trie
    sans `TypeError`).
    """
    entries = [
        TimelineEntry(
            at=_as_utc(alert.created_at),
            actor=f"monitor:{alert.monitor_name}",
            event="alerte créée",
            detail=alert.reason,
        )
    ]
    for action in actions:
        perimeter = action.perimeter_address or "global"
        entries.append(
            TimelineEntry(
                at=_as_utc(action.created_at),
                actor=_decided_by(action),
                event=f"action {action.action_type.value} ({action.status.value})",
                detail=f"{action.action_id} — périmètre {perimeter}",
            )
        )
        if action.expires_at is not None:
            entries.append(
                TimelineEntry(
                    at=_as_utc(action.expires_at),
                    actor="système",
                    event=f"expiration prévue de {action.action_type.value}",
                    detail=action.action_id,
                )
            )
    for audit in audit_entries:
        entries.append(
            TimelineEntry(
                at=_as_utc(audit.recorded_at),
                actor=audit.actor,
                event=audit.event_type,
                detail=audit.message,
            )
        )
    return sorted(entries, key=lambda entry: entry.at)


def _placeholder_narrative(reason: str) -> IncidentNarrative:
    """Narratif « a completer » quand la redaction IA est indisponible."""
    text = f"{PLACEHOLDER_PREFIX} — rédaction IA indisponible : {reason}]"
    return IncidentNarrative(
        description=text, probable_cause=text, impact=text, mitigation=text
    )


def _parse_narrative(raw: str) -> IncidentNarrative:
    """Extrait l'objet JSON (fences ``` tolerees) et le valide.

    Raises:
        ValueError: aucun objet JSON trouve.
        pydantic.ValidationError: JSON invalide ou hors schema.
    """
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("réponse sans objet JSON")
    return IncidentNarrative.model_validate_json(raw[start : end + 1])


def build_incident_report(
    alert: Alert,
    client: BedrockClient,
    actions: Sequence[ResponseAction] = (),
    audit_entries: Sequence[AuditLogEntry] = (),
    *,
    generated_at: datetime | None = None,
) -> IncidentReport:
    """Construit le rapport d'incident pre-rempli d'une alerte confirmee.

    Exactement un appel LLM (via `client.complete`, donc via le limiteur) ;
    aucun nouvel essai. L'IA redige seulement : elle n'emet aucune action.

    Args:
        alert: alerte confirmee a l'origine de l'incident.
        client: client Bedrock utilise pour la partie narrative.
        actions: actions de reponse liees (optionnel).
        audit_entries: entrees du journal d'audit liees (optionnel).
        generated_at: horodatage de generation (defaut : maintenant, UTC).

    Returns:
        Le rapport, toujours produit (narratif « a completer » si le LLM echoue).
    """
    timeline = _build_timeline(alert, actions, audit_entries)
    decisions = [
        DecisionEntry(
            action_id=action.action_id,
            action_type=action.action_type,
            status=action.status.value,
            decided_by=_decided_by(action),
            decision_id=action.decision_id,
        )
        for action in actions
    ]
    timeline_lines = [
        f"{entry.at.isoformat()} | {entry.actor} | {entry.event} | {entry.detail}"
        for entry in timeline
    ]
    decision_lines = [
        f"{d.action_id} {d.action_type.value} ({d.status}) : {d.decided_by}"
        for d in decisions
    ] + [AI_NO_DECISION_LINE]

    narrative_source: Literal["llm", "placeholder"]
    try:
        raw = client.complete(
            build_report_prompt(alert, timeline_lines, decision_lines),
            SYSTEM_PROMPT_REPORT,
            max_tokens=REPORT_MAX_TOKENS,
        )
        narrative = _parse_narrative(raw)
        narrative_source = "llm"
    except LLMError as err:
        narrative = _placeholder_narrative(str(err))
        narrative_source = "placeholder"
    except (ValueError, ValidationError):
        narrative = _placeholder_narrative("réponse hors format JSON attendu")
        narrative_source = "placeholder"

    return IncidentReport(
        report_id=f"IR-{alert.alert_id}",
        incident_id=alert.alert_id,
        generated_at=_as_utc(generated_at or datetime.now(timezone.utc)),
        detected_at=_as_utc(alert.created_at),
        kind=alert.kind,
        severity=alert.severity,
        monitor_name=alert.monitor_name,
        subject_address=alert.subject_address,
        source_tx_hash=alert.source_tx_hash,
        contamination_ratio=alert.contamination_ratio,
        suspect_amount=alert.suspect_amount,
        seeds=list(alert.seeds),
        total_seed_suspect_amount=sum(seed.suspect_amount for seed in alert.seeds),
        timeline=timeline,
        decisions=decisions,
        narrative=narrative,
        narrative_source=narrative_source,
    )
