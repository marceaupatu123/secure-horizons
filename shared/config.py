"""Configuration partagee : chargement typé des variables d'environnement.

Lit le fichier `.env` (jamais commite) via python-dotenv. Aucune valeur n'est
codee en dur ici. Voir `.env.example` pour la liste des variables attendues.

Ce module ne tranche aucune decision metier : il expose seulement l'acces aux
reglages d'environnement. A completer si de nouvelles variables apparaissent
(penser a les ajouter aussi dans `.env.example`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Charge .env s'il existe (no-op s'il est absent, ex : en CI).
load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Reglages d'environnement du projet.

    Les valeurs proviennent du `.env` local. Garder ce conteneur neutre :
    pas de secret en dur, pas de valeur par defaut sensible.
    """

    aws_region: str
    bedrock_model_id: str
    fuji_rpc_url: str
    guardian_private_key: str


def _require(name: str) -> str:
    """Retourne la variable d'environnement `name` ou leve une erreur claire.

    Args:
        name: nom de la variable d'environnement attendue.

    Returns:
        La valeur de la variable.

    Raises:
        RuntimeError: si la variable est absente ou vide.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Variable d'environnement manquante : {name}. "
            f"Copie .env.example vers .env et renseigne des valeurs de TEST."
        )
    return value


def load_settings() -> Settings:
    """Construit un objet `Settings` a partir de l'environnement.

    Returns:
        Les reglages charges depuis `.env` / l'environnement.

    Raises:
        RuntimeError: si une variable requise est absente.
    """
    return Settings(
        aws_region=_require("AWS_REGION"),
        bedrock_model_id=_require("BEDROCK_MODEL_ID"),
        fuji_rpc_url=_require("FUJI_RPC_URL"),
        guardian_private_key=_require("GUARDIAN_PRIVATE_KEY"),
    )
