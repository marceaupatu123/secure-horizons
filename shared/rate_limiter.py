"""Limiteur de debit simple pour les appels Bedrock.

Regle d'equipe (deja actee) : environ 1 requete par seconde par personne, et
jamais d'appel LLM en boucle serree. Ce limiteur fournit un garde-fou minimal
et reutilisable. Il n'implemente aucune logique metier.

Usage typique :

    limiter = RateLimiter(min_interval_seconds=1.0)
    limiter.wait()        # bloque si besoin pour respecter l'intervalle
    # ... appel Bedrock ...
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Garantit un intervalle minimal entre deux operations (thread-safe).

    Non specifique a Bedrock, mais dimensionne pour lui par defaut
    (1 req/s). A ajuster via `min_interval_seconds` si l'equipe le decide.
    """

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        """Initialise le limiteur.

        Args:
            min_interval_seconds: intervalle minimal entre deux `wait()`
                reussis, en secondes. Defaut : 1.0 (≈ 1 req/s).

        Raises:
            ValueError: si `min_interval_seconds` est negatif.
        """
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds doit etre >= 0")
        self._min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._last_call: float | None = None

    def wait(self) -> None:
        """Bloque si necessaire pour respecter l'intervalle minimal.

        Met a jour l'horodatage du dernier appel une fois l'attente ecoulee.
        """
        with self._lock:
            now = time.monotonic()
            if self._last_call is not None:
                elapsed = now - self._last_call
                remaining = self._min_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
                    now = time.monotonic()
            self._last_call = now
