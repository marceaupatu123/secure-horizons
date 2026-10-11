"""Checkpoint du dernier bloc lu par le monitor (issue #74).

But : qu'un redemarrage (crash, mise a jour, coupure RPC qui a fait tomber le
process) reprenne au bloc suivant le dernier bloc TRAITE, au lieu de repartir
de la tete de chaine et de perdre tout ce qui a ete minte pendant l'arret.

Semantique « au moins une fois » : le bloc est enregistre APRES que le
consommateur a repris la main sur le lot de cette plage. Un crash pendant le
traitement d'un lot fait donc relire ce lot au redemarrage (doublon possible),
jamais le sauter (trou impossible). Les consommateurs dedupliquent sur
`(tx_hash, log_index)` si besoin.

Format : petit fichier JSON `{"last_block": <int>}` ecrit de facon atomique
(fichier temporaire + `os.replace`), pour qu'un crash pendant l'ecriture ne
laisse jamais un checkpoint tronque.

PROVISOIRE — a valider par l'equipe : un fichier local par process. Deux
ecouteurs (ex. `python -m monitor` et le pipeline `detection`) ne doivent PAS
partager le meme chemin, sinon chacun avancerait le curseur de l'autre.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class BlockCheckpoint:
    """Lit et ecrit le dernier bloc traite dans un fichier JSON."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        """Prepare le checkpoint (aucune lecture/ecriture ici).

        Args:
            path: chemin du fichier JSON ; le dossier parent est cree au
                premier `save`.
        """
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Chemin du fichier de checkpoint."""
        return self._path

    def load(self) -> int | None:
        """Retourne le dernier bloc traite, ou `None` si aucun checkpoint.

        Un fichier illisible ou corrompu est signale (log ERROR) et traite
        comme absent : le monitor repart alors de `start_block`, ce qui est
        visible dans les logs plutot que silencieux.

        Returns:
            Le numero du dernier bloc traite (>= 0), ou `None`.
        """
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            last_block = payload["last_block"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            LOGGER.error("checkpoint illisible %s (%s) : ignore", self._path, exc)
            return None
        if not isinstance(last_block, int) or isinstance(last_block, bool) or last_block < 0:
            LOGGER.error("checkpoint invalide %s : %r ignore", self._path, last_block)
            return None
        return last_block

    def save(self, last_block: int) -> None:
        """Enregistre `last_block` de facon atomique.

        Args:
            last_block: dernier bloc dont le lot a ete traite (>= 0).

        Raises:
            ValueError: si `last_block` est negatif.
            OSError: si l'ecriture echoue.
        """
        if last_block < 0:
            raise ValueError("last_block doit etre >= 0")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=self._path.name + ".", suffix=".tmp", dir=self._path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"last_block": last_block}, handle)
            os.replace(tmp_name, self._path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
