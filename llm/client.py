"""Appels LLM via Amazon Bedrock (API Converse).

Regles actees respectees ici :
  - LLM appele UNIQUEMENT sur alerte (pas de boucle serree).
  - ≈ 1 requete/seconde/personne -> `shared.rate_limiter` avant CHAQUE appel.
  - Aucun nouvel essai automatique (pas de « retry storm ») : botocore est
    configure avec `max_attempts=1` et aucune boucle de retry n'existe ici.
  - L'IA ne decide rien : ce client explique / redige, il n'emet aucune action.

Aucun prompt n'est code ici (voir `llm/prompts.py`) et aucun modele n'est code
en dur : le `BEDROCK_MODEL_ID` et la region viennent de `shared.config`.
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from llm.prompts import SYSTEM_PROMPT_EXPLAIN, build_explain_prompt
from shared.config import Settings
from shared.models import Alert
from shared.rate_limiter import RateLimiter

DEFAULT_TEMPERATURE: float = 0.2
DEFAULT_MAX_TOKENS: int = 800
REPORT_MAX_TOKENS: int = 1500


class LLMError(RuntimeError):
    """Echec d'un appel Bedrock (erreur AWS, reseau, reponse vide)."""


class BedrockClient:
    """Client minimal autour de l'API Converse de Bedrock.

    Le client boto3 `bedrock-runtime` est injectable (tests) ; sinon il est cree
    paresseusement au premier appel : construire un `BedrockClient` ne contacte
    jamais AWS.
    """

    def __init__(
        self,
        settings: Settings,
        rate_limiter: RateLimiter | None = None,
        client: Any | None = None,
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        """Initialise le client.

        Args:
            settings: reglages d'environnement (region, model id).
            rate_limiter: limiteur de debit partage. Si `None`, un limiteur
                par defaut (≈ 1 req/s) est cree.
            client: client boto3 `bedrock-runtime` deja construit (ou faux
                client de test). Si `None`, cree au premier appel.
            temperature: temperature d'inference (basse = factuel).
            max_tokens: plafond de tokens generes par defaut.
        """
        self._settings = settings
        self._rate_limiter = rate_limiter or RateLimiter(min_interval_seconds=1.0)
        self._client = client
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        """Identifiant du modele Bedrock utilise (issu de `BEDROCK_MODEL_ID`)."""
        return self._settings.bedrock_model_id

    def _get_client(self) -> Any:
        """Retourne le client boto3, en le creant au premier besoin."""
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._settings.aws_region,
                config=Config(
                    retries={"max_attempts": 1, "mode": "standard"},
                    connect_timeout=5,
                    read_timeout=60,
                ),
            )
        return self._client

    def complete(
        self, user_text: str, system_prompt: str, *, max_tokens: int | None = None
    ) -> str:
        """Envoie UN appel Converse et retourne le texte de la reponse.

        Passe par le limiteur de debit avant l'appel. Aucun nouvel essai.

        Args:
            user_text: message utilisateur envoye au modele.
            system_prompt: prompt systeme.
            max_tokens: plafond de tokens pour cet appel (defaut : celui du client).

        Returns:
            Le texte genere (blocs texte concatenes, espaces de bord retires).

        Raises:
            LLMError: erreur AWS (ex. ThrottlingException), erreur botocore
                (identifiants, reseau) ou reponse sans texte.
        """
        self._rate_limiter.wait()
        client = self._get_client()
        try:
            response = client.converse(
                modelId=self._settings.bedrock_model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_text}]}],
                inferenceConfig={
                    "maxTokens": max_tokens if max_tokens is not None else self._max_tokens,
                    "temperature": self._temperature,
                },
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "inconnu")
            raise LLMError(
                f"Bedrock a refusé l'appel ({code}) ; pas de nouvel essai automatique."
            ) from exc
        except BotoCoreError as exc:
            raise LLMError(
                f"Appel Bedrock impossible ({type(exc).__name__}) ; "
                "pas de nouvel essai automatique."
            ) from exc
        return _extract_text(response)

    def explain(self, alert: Alert) -> str:
        """Demande au LLM une explication courte d'une alerte (appel sur alerte).

        Ne leve pas : en cas d'echec Bedrock, retourne un texte de repli
        deterministe reprenant le motif de l'alerte.

        Args:
            alert: alerte a expliquer.

        Returns:
            L'explication du modele, ou le texte de repli.
        """
        try:
            return self.complete(build_explain_prompt(alert), SYSTEM_PROMPT_EXPLAIN)
        except LLMError as err:
            return (
                f"[Explication IA indisponible : {err}] "
                f"Motif détecté par {alert.monitor_name} : {alert.reason}"
            )


def _extract_text(response: Any) -> str:
    """Extrait le texte d'une reponse Converse.

    Raises:
        LLMError: si la reponse est mal formee ou ne contient aucun texte.
    """
    try:
        content = response["output"]["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise LLMError("Réponse Bedrock mal formée (pas de output.message.content).") from exc
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    text = "".join(parts).strip()
    if not text:
        raise LLMError("Réponse Bedrock sans texte.")
    return text
