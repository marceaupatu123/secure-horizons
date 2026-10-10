"""Modeles de donnees partages (Pydantic) — SQUELETTES VIDES.

⚠️ Les CHAMPS de ces modeles ne sont PAS encore decides : c'est une decision
d'equipe (voir `docs/OPEN_QUESTIONS.md` et `docs/CONTRACTS.md`). Ce fichier ne
fournit volontairement que des coquilles typables, pour donner des points
d'ancrage d'import aux autres modules sans trancher le schema.

Procedure pour ajouter des champs (ne pas court-circuiter) :
  1. En discuter en equipe, acter dans `docs/CONTRACTS.md`.
  2. Le proprietaire de `shared/` remplit le modele dans une PR dediee.
  3. Les autres font `git pull` avant de continuer.

Tant que les champs ne sont pas definis, ces classes acceptent n'importe quel
contenu (configuration permissive) pour ne pas bloquer les imports.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _OpenModel(BaseModel):
    """Base commune tant que les schemas ne sont pas figes.

    `extra="allow"` laisse passer des champs arbitraires : utile pour prototyper
    sans decider le schema. A retirer quand les champs seront actes en equipe.
    """

    model_config = ConfigDict(extra="allow")


# --- Interfaces decrites dans docs/CONTRACTS.md (champs a definir ensemble) ---


class MintEvent(_OpenModel):
    """Evenement de mint observe on-chain. Champs : voir docs/CONTRACTS.md."""


class TransferEvent(_OpenModel):
    """Transfert de tokens observe on-chain. Champs : voir docs/CONTRACTS.md."""


class Alert(_OpenModel):
    """Anomalie detectee (mint ou transfert). Champs : voir docs/CONTRACTS.md."""


class ResponseAction(_OpenModel):
    """Action de la reponse graduee. Champs : voir docs/CONTRACTS.md."""


class AuditLogEntry(_OpenModel):
    """Entree du journal d'audit (DORA). Champs : voir docs/CONTRACTS.md."""


class MintRequest(_OpenModel):
    """Demande de mint + depot associe. Champs : voir docs/CONTRACTS.md."""


class QuarantineRecord(_OpenModel):
    """Mint place en quarantaine. Champs : voir docs/CONTRACTS.md."""


class FreezeRequest(_OpenModel):
    """Demande de gel par un surveillant. Champs : voir docs/CONTRACTS.md."""


class ReleaseDecision(_OpenModel):
    """Levee/confirmation de gel par un humain. Champs : voir docs/CONTRACTS.md."""


class RiskBeaconUpdate(_OpenModel):
    """Publication d'un etat de risque. Champs : voir docs/CONTRACTS.md."""


class GhostTokenMintEvent(_OpenModel):
    """Emission d'un Token Ghost temporaire. Champs : voir docs/CONTRACTS.md."""


class GhostTokenRedemptionEvent(_OpenModel):
    """Conversion ghost -> vrai token. Champs : voir docs/CONTRACTS.md."""


class GhostTokenBurnEvent(_OpenModel):
    """Destruction d'un Token Ghost. Champs : voir docs/CONTRACTS.md."""
