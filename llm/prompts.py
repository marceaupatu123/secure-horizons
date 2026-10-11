"""Prompts du module llm (proprietaire : @denybs).

Regroupe le materiel de prompt pour que `llm/client.py` n'en contienne aucun.
Regles actees reprises dans les prompts systeme (OPEN_ANSWERS §3, §4, §5) :
  - l'IA ne decide rien : elle explique / redige ;
  - seule action possible cote IA/surveillant : retarder (auto-expirant) ;
  - detruire = multisig 2/3, pause globale = multisig 3/3 ;
  - aucun chiffre invente : uniquement les chiffres fournis ;
  - donnees fictives.

Les montants sont rendus tels quels en `int` (base units), sans conversion
flottante, pour ne pas introduire de decimales inventees.
"""

from __future__ import annotations

from shared.models import Alert

REPORT_JSON_KEYS: tuple[str, ...] = ("description", "probable_cause", "impact", "mitigation")

_COMMON_RULES = (
    "Règles impératives :\n"
    "- Réponds en français, de façon concise et factuelle.\n"
    "- N'utilise que les faits et chiffres fournis : aucun chiffre inventé, "
    "aucune estimation non fournie. Si une information manque, écris « non disponible ».\n"
    "- Les données sont fictives (environnement de test).\n"
    "- L'IA ne décide rien : tu expliques et tu rédiges, tu ne prends aucune décision "
    "de blocage. La seule action possible côté surveillant/IA est un retard local "
    "auto-expirant ; la destruction exige un multisig 2/3 et la pause globale un "
    "multisig 3/3 (décisions humaines).\n"
    "- Ne recommande jamais une action comme si elle était déjà décidée."
)

SYSTEM_PROMPT_EXPLAIN: str = (
    "Tu es un assistant d'analyse sécurité pour un stablecoin de démonstration. "
    "Tu expliques une alerte émise par un surveillant on-chain à un opérateur humain, "
    "en 3 à 5 phrases.\n" + _COMMON_RULES
)

SYSTEM_PROMPT_REPORT: str = (
    "Tu es un assistant qui pré-rédige les parties narratives d'un rapport d'incident "
    "TIC (rubriques inspirées de DORA, sans prétention de conformité). Les champs "
    "factuels du rapport sont déjà remplis de façon déterministe ; tu ne rédiges que "
    "la description, la cause probable, l'impact et les mesures de mitigation.\n"
    + _COMMON_RULES
    + "\n- Réponds UNIQUEMENT par un objet JSON avec exactement les clés "
    '"description", "probable_cause", "impact", "mitigation" (valeurs : chaînes en '
    "français), sans bloc markdown ni texte autour."
)


def _or_na(value: object | None) -> str:
    """Rend `value` en texte, ou « n/a » si absente."""
    return "n/a" if value is None else str(value)


def format_alert_facts(alert: Alert) -> str:
    """Liste a puces deterministe des faits d'une alerte.

    Args:
        alert: alerte (fictive) a decrire.

    Returns:
        Le texte des faits, un fait par ligne, montants en base units.
    """
    lines = [
        f"- alert_id : {alert.alert_id}",
        f"- kind : {alert.kind.value}",
        f"- severity : {alert.severity.value}",
        f"- created_at : {alert.created_at.isoformat()}",
        f"- monitor_name : {alert.monitor_name}",
        f"- subject_address : {alert.subject_address}",
        f"- source_tx_hash : {_or_na(alert.source_tx_hash)}",
        f"- contamination_ratio : {alert.contamination_ratio}",
        f"- suspect_amount : {alert.suspect_amount} (base units)",
        f"- dispersion_score : {_or_na(alert.dispersion_score)}",
        f"- volume_zscore : {_or_na(alert.volume_zscore)}",
        f"- reason : {alert.reason}",
    ]
    if alert.seeds:
        lines.append("- seeds :")
        for seed in alert.seeds:
            lines.append(
                f"  - {seed.address} : suspect_amount={seed.suspect_amount} (base units), "
                f"contamination_ratio={seed.contamination_ratio}"
            )
    else:
        lines.append("- seeds : aucune")
    return "\n".join(lines)


def build_explain_prompt(alert: Alert) -> str:
    """Construit le message utilisateur pour expliquer une alerte.

    Args:
        alert: alerte a expliquer.

    Returns:
        Le texte envoye au modele (faits + consigne).
    """
    return (
        "Explique cette alerte à un opérateur : ce qui a été observé, pourquoi c'est "
        "suspect, et ce que les humains doivent vérifier. Rappelle que la décision "
        "revient au multisig.\n\nFaits de l'alerte :\n" + format_alert_facts(alert)
    )


def build_report_prompt(
    alert: Alert, timeline_lines: list[str], decision_lines: list[str]
) -> str:
    """Construit le message utilisateur pour la partie narrative du rapport.

    Args:
        alert: alerte confirmee a l'origine du rapport.
        timeline_lines: chronologie deja etablie (une ligne par evenement).
        decision_lines: decisions deja etablies (qui a decide quoi).

    Returns:
        Le texte envoye au modele, demandant un objet JSON aux 4 cles.
    """
    timeline = "\n".join(f"- {line}" for line in timeline_lines) or "- aucune"
    decisions = "\n".join(f"- {line}" for line in decision_lines) or "- aucune"
    keys = ", ".join(f'"{key}"' for key in REPORT_JSON_KEYS)
    return (
        "Rédige les parties narratives du rapport d'incident à partir des seuls faits "
        f"ci-dessous. Réponds par un objet JSON avec exactement les clés {keys}.\n\n"
        "Faits de l'alerte :\n"
        + format_alert_facts(alert)
        + "\n\nChronologie :\n"
        + timeline
        + "\n\nDécisions :\n"
        + decisions
    )
