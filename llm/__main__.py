"""Point d'entree du module llm : `python -m llm`.

Par defaut, demo HORS LIGNE sur une alerte fictive (aucun appel AWS, pas de
`.env` requis). Mode reel uniquement avec `--live` ou `LLM_LIVE=1` : appel
Bedrock Converse avec les reglages de `shared.config` (`.env` renseigne).

Exactement 2 appels LLM par execution (explication + rapport), via le limiteur.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence

from llm.client import BedrockClient
from llm.demo import (
    OfflineConverseStub,
    fictive_actions,
    fictive_alert,
    fictive_audit_entries,
)
from llm.report import build_incident_report
from shared.config import Settings, load_settings


def is_live_mode(argv: Sequence[str], env: Mapping[str, str]) -> bool:
    """Vrai si l'appel Bedrock reel est explicitement demande.

    Args:
        argv: arguments de la ligne de commande.
        env: variables d'environnement.

    Returns:
        `True` si `--live` est passe ou si `LLM_LIVE=1`.
    """
    return "--live" in argv or env.get("LLM_LIVE") == "1"


def offline_settings(env: Mapping[str, str]) -> Settings:
    """Reglages pour la demo hors ligne (aucune variable requise).

    Args:
        env: variables d'environnement (lues si presentes).

    Returns:
        Des `Settings` ; le model id hors ligne n'est jamais envoye a AWS.
    """
    return Settings(
        aws_region=env.get("AWS_REGION") or "us-east-1",
        bedrock_model_id=env.get("BEDROCK_MODEL_ID") or "offline-stub",
        fuji_rpc_url=env.get("FUJI_RPC_URL") or "offline",
        guardian_private_key="offline",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Lance la demo (hors ligne par defaut).

    Args:
        argv: arguments (defaut : ceux du processus).

    Returns:
        Le code de sortie (0 = succes).
    """
    parser = argparse.ArgumentParser(prog="python -m llm", description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="appel Bedrock réel (sinon démo hors ligne)"
    )
    args_list = list(argv) if argv is not None else None
    args = parser.parse_args(args_list)
    live = args.live or is_live_mode([], os.environ)

    if live:
        client = BedrockClient(load_settings())
        print(f"llm : mode LIVE (Bedrock Converse), modèle {client.model_id}")
    else:
        client = BedrockClient(offline_settings(os.environ), client=OfflineConverseStub())
        print("llm : mode hors ligne (aucun appel AWS ; --live ou LLM_LIVE=1 pour Bedrock)")

    alert = fictive_alert()
    print("\n--- Explication de l'alerte ---")
    print(client.explain(alert))
    report = build_incident_report(
        alert, client, fictive_actions(alert), fictive_audit_entries(alert)
    )
    print("\n--- Rapport d'incident ---")
    print(report.to_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
