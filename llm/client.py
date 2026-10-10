"""Appels LLM via Amazon Bedrock (API Converse).

SQUELETTE : signatures et types poses, corps a implementer par le proprietaire
du module `llm`. Regles deja actees et respectees par la structure :
  - LLM appele UNIQUEMENT sur alerte (pas de boucle serree).
  - ≈ 1 requete/seconde/personne -> on passe par `shared.rate_limiter`.

Aucun prompt ni aucun modele n'est code en dur ici (le `BEDROCK_MODEL_ID` vient
du `.env` via `shared.config`).
"""

from __future__ import annotations

from shared.config import Settings
from shared.rate_limiter import RateLimiter


class BedrockClient:
    """Client minimal autour de l'API Converse de Bedrock (squelette).

    A implementer : creation du client boto3 (`bedrock-runtime`), appel
    `converse(...)`, extraction de la reponse.
    """

    def __init__(self, settings: Settings, rate_limiter: RateLimiter | None = None) -> None:
        """Initialise le client.

        Args:
            settings: reglages d'environnement (region, model id).
            rate_limiter: limiteur de debit partage. Si `None`, un limiteur
                par defaut (≈ 1 req/s) est cree.
        """
        self._settings = settings
        self._rate_limiter = rate_limiter or RateLimiter(min_interval_seconds=1.0)

    def explain(self, prompt: str) -> str:
        """Demande une explication / un texte au LLM (appel sur alerte).

        Respecte le limiteur de debit avant d'appeler Bedrock.

        Args:
            prompt: le texte d'entree envoye au modele.

        Returns:
            La reponse textuelle du modele.
        """
        self._rate_limiter.wait()
        raise NotImplementedError("llm.explain : appel Bedrock Converse a implementer")
