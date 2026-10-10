"""Ecoute on-chain des evenements de mint et de transfert (Avalanche Fuji).

SQUELETTE : signatures et types poses, corps a implementer par le proprietaire
du module `monitor`. Aucune logique metier ici (pas de choix de contrat, de
topics d'evenements ni de seuils — ce sont des decisions d'equipe).

Le module produit des `MintEvent` et `TransferEvent` (schema a definir dans
`docs/CONTRACTS.md`) a destination du module `detection`.
"""

from __future__ import annotations

from collections.abc import Iterator

from shared.config import Settings
from shared.models import MintEvent, TransferEvent


class ChainListener:
    """Ecoute un noeud RPC Fuji et emet les evenements observes.

    A implementer : connexion web3, souscription/polling des evenements,
    conversion en modeles `shared`.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise l'ecouteur avec les reglages d'environnement.

        Args:
            settings: reglages charges via `shared.config.load_settings()`
                (contient notamment `fuji_rpc_url`).
        """
        self._settings = settings

    def stream_mint_events(self) -> Iterator[MintEvent]:
        """Emet les evenements de mint au fil de l'eau.

        Yields:
            Un `MintEvent` par mint observe.
        """
        raise NotImplementedError("monitor.stream_mint_events : a implementer")

    def stream_transfer_events(self) -> Iterator[TransferEvent]:
        """Emet les evenements de transfert au fil de l'eau.

        Yields:
            Un `TransferEvent` par transfert observe.
        """
        raise NotImplementedError("monitor.stream_transfer_events : a implementer")
