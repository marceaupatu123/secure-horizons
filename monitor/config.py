"""Configuration du module `monitor` — SEUL endroit ou vivent ses reglages.

Sources :
- `FUJI_RPC_URL` : lue via `shared.config` (`Settings.fuji_rpc_url`) quand un
  `Settings` est fourni, sinon directement dans l'environnement (meme nom de
  variable). Evite d'exiger les variables Bedrock / cle guardian dont le
  monitor n'a pas besoin (`shared.config.load_settings()` les rend toutes
  obligatoires).
- `MONITOR_*` : variables propres au monitor (voir `.env.example`).

Aucun contrat n'est deploye a ce jour (`contracts/DEPLOYMENTS.md`) : l'adresse
du token est donc optionnelle ici et exigee seulement au moment d'ecouter.

Tout parametre non tranche par l'equipe a un defaut marque PROVISOIRE ou
A MESURER. Aucun chiffre ci-dessous n'est une mesure.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from web3 import Web3

# Importer shared.config charge `.env` (python-dotenv) dans l'environnement.
from shared.config import Settings

# Fait, pas un choix : chain id d'Avalanche Fuji C-Chain (contracts/DEPLOYMENTS.md).
FUJI_CHAIN_ID = 43113

# PROVISOIRE — a valider par l'equipe. Intervalle entre deux polls du RPC.
# Doit rester tres en dessous de la fenetre Ghost (ex. 10 min, OPEN_ANSWERS
# §0bis) pour que l'alerte arrive a temps. Latence reelle A MESURER.
DEFAULT_POLL_INTERVAL_SECONDS = 2.0

# A MESURER — taille max d'une plage `eth_getLogs`. Les RPC publics limitent la
# largeur des plages ; valeur a ajuster selon la limite effective du RPC Fuji.
DEFAULT_BLOCK_BATCH_SIZE = 2000

# PROVISOIRE — a valider par l'equipe. Nombre de blocs de retard tenus sous la
# tete de chaine avant de lire les logs (0 = lire jusqu'a la tete).
DEFAULT_CONFIRMATIONS = 0

# PROVISOIRE — a valider par l'equipe. None = commencer au bloc courant
# (pas de rattrapage de l'historique au demarrage).
DEFAULT_START_BLOCK: int | None = None

# PROVISOIRE — a valider par l'equipe. Valeur de `TransferEvent.is_ghost` pour
# les transferts du token ecoute : un `Transfer` ERC-20 generique ne dit pas si
# le token transfere est un Ghost (design du contrat Ghost non tranche). False =
# le token ecoute est le vrai token.
DEFAULT_TOKEN_IS_GHOST = False

# PROVISOIRE — a valider par l'equipe (issue #74). Reprise sur erreur RPC :
# attente exponentielle `base * 2**(n-1)`, plafonnee a `max`, retentee SANS
# limite (le monitor ne doit pas s'arreter seul). Valeurs non mesurees.
DEFAULT_RPC_RETRY_BASE_SECONDS = 1.0
DEFAULT_RPC_RETRY_MAX_SECONDS = 30.0
# PROVISOIRE — nombre d'echecs consecutifs a partir duquel le monitor logue en
# ERROR « surveillance aveugle » (au lieu de WARNING) : signal a remonter.
DEFAULT_RPC_FAILURE_ALERT_AFTER = 5

# PROVISOIRE — a valider par l'equipe (issue #74). Fichier du dernier bloc lu.
# None = pas de checkpoint (desactive par defaut : deux process ne doivent pas
# partager le meme fichier, chacun choisit le sien via MONITOR_CHECKPOINT_PATH).
DEFAULT_CHECKPOINT_PATH: str | None = None

ENV_RPC_URL = "FUJI_RPC_URL"
ENV_TOKEN_ADDRESS = "MONITOR_TOKEN_ADDRESS"
ENV_POLL_INTERVAL_SECONDS = "MONITOR_POLL_INTERVAL_SECONDS"
ENV_BLOCK_BATCH_SIZE = "MONITOR_BLOCK_BATCH_SIZE"
ENV_CONFIRMATIONS = "MONITOR_CONFIRMATIONS"
ENV_START_BLOCK = "MONITOR_START_BLOCK"
ENV_TOKEN_IS_GHOST = "MONITOR_TOKEN_IS_GHOST"
ENV_RPC_RETRY_BASE_SECONDS = "MONITOR_RPC_RETRY_BASE_SECONDS"
ENV_RPC_RETRY_MAX_SECONDS = "MONITOR_RPC_RETRY_MAX_SECONDS"
ENV_RPC_FAILURE_ALERT_AFTER = "MONITOR_RPC_FAILURE_ALERT_AFTER"
ENV_CHECKPOINT_PATH = "MONITOR_CHECKPOINT_PATH"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})

_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class MonitorConfig:
    """Reglages de l'ecouteur on-chain.

    Attributes:
        rpc_url: URL RPC Fuji (None si non renseignee).
        token_address: adresse (checksum) du contrat token a ecouter, None tant
            qu'aucun contrat n'est deploye.
        chain_id: identifiant de chaine reporte dans les evenements.
        poll_interval_seconds: pause entre deux polls (PROVISOIRE).
        block_batch_size: largeur max d'une plage `eth_getLogs` (A MESURER).
        confirmations: blocs de retard sous la tete (PROVISOIRE).
        start_block: premier bloc lu, None = bloc courant (PROVISOIRE).
        token_is_ghost: valeur de `TransferEvent.is_ghost` pour le token
            ecoute (PROVISOIRE).
        rpc_retry_base_seconds: premiere attente apres une erreur RPC
            (PROVISOIRE).
        rpc_retry_max_seconds: plafond de l'attente exponentielle (PROVISOIRE).
        rpc_failure_alert_after: echecs consecutifs avant log ERROR
            « surveillance aveugle » (PROVISOIRE).
        checkpoint_path: fichier du dernier bloc traite, None = desactive
            (PROVISOIRE).
    """

    rpc_url: str | None
    token_address: str | None
    chain_id: int = FUJI_CHAIN_ID
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    block_batch_size: int = DEFAULT_BLOCK_BATCH_SIZE
    confirmations: int = DEFAULT_CONFIRMATIONS
    start_block: int | None = DEFAULT_START_BLOCK
    token_is_ghost: bool = DEFAULT_TOKEN_IS_GHOST
    rpc_retry_base_seconds: float = DEFAULT_RPC_RETRY_BASE_SECONDS
    rpc_retry_max_seconds: float = DEFAULT_RPC_RETRY_MAX_SECONDS
    rpc_failure_alert_after: int = DEFAULT_RPC_FAILURE_ALERT_AFTER
    checkpoint_path: str | None = DEFAULT_CHECKPOINT_PATH

    def __post_init__(self) -> None:
        if self.token_address is not None:
            object.__setattr__(
                self, "token_address", normalize_address(self.token_address)
            )
        if self.chain_id < 1:
            raise ValueError("chain_id doit etre >= 1")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds doit etre > 0")
        if self.block_batch_size < 1:
            raise ValueError("block_batch_size doit etre >= 1")
        if self.confirmations < 0:
            raise ValueError("confirmations doit etre >= 0")
        if self.start_block is not None and self.start_block < 0:
            raise ValueError("start_block doit etre >= 0")
        if self.rpc_retry_base_seconds <= 0:
            raise ValueError("rpc_retry_base_seconds doit etre > 0")
        if self.rpc_retry_max_seconds < self.rpc_retry_base_seconds:
            raise ValueError("rpc_retry_max_seconds doit etre >= rpc_retry_base_seconds")
        if self.rpc_failure_alert_after < 1:
            raise ValueError("rpc_failure_alert_after doit etre >= 1")


def normalize_address(address: str) -> str:
    """Valide une adresse EVM et la retourne au format checksum (EIP-55).

    Args:
        address: adresse `0x` + 40 hex, casse indifferente.

    Returns:
        L'adresse au format checksum.

    Raises:
        ValueError: si le format est invalide.
    """
    if not _ADDRESS_RE.match(address):
        raise ValueError(f"Adresse EVM invalide : {address!r}")
    return Web3.to_checksum_address(address)


def _optional_str(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def _int_from_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _optional_str(env, name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} doit etre un entier, recu {raw!r}") from exc


def _float_from_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _optional_str(env, name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} doit etre un nombre, recu {raw!r}") from exc


def _bool_from_env(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _optional_str(env, name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} doit etre un booleen (true/false), recu {raw!r}")


def load_monitor_config(
    settings: Settings | None = None,
    env: Mapping[str, str] | None = None,
) -> MonitorConfig:
    """Construit la configuration du monitor depuis l'environnement.

    Args:
        settings: reglages partages ; si fourni, `fuji_rpc_url` en est lu.
        env: environnement a lire (defaut : `os.environ`, apres chargement
            de `.env` par `shared.config`).

    Returns:
        La configuration du monitor.

    Raises:
        ValueError: si une variable renseignee a un format invalide.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    rpc_url = settings.fuji_rpc_url if settings else _optional_str(source, ENV_RPC_URL)
    start_raw = _optional_str(source, ENV_START_BLOCK)
    return MonitorConfig(
        rpc_url=rpc_url,
        token_address=_optional_str(source, ENV_TOKEN_ADDRESS),
        poll_interval_seconds=_float_from_env(
            source, ENV_POLL_INTERVAL_SECONDS, DEFAULT_POLL_INTERVAL_SECONDS
        ),
        block_batch_size=_int_from_env(
            source, ENV_BLOCK_BATCH_SIZE, DEFAULT_BLOCK_BATCH_SIZE
        ),
        confirmations=_int_from_env(source, ENV_CONFIRMATIONS, DEFAULT_CONFIRMATIONS),
        start_block=(
            None
            if start_raw is None
            else _int_from_env(source, ENV_START_BLOCK, 0)
        ),
        token_is_ghost=_bool_from_env(
            source, ENV_TOKEN_IS_GHOST, DEFAULT_TOKEN_IS_GHOST
        ),
        rpc_retry_base_seconds=_float_from_env(
            source, ENV_RPC_RETRY_BASE_SECONDS, DEFAULT_RPC_RETRY_BASE_SECONDS
        ),
        rpc_retry_max_seconds=_float_from_env(
            source, ENV_RPC_RETRY_MAX_SECONDS, DEFAULT_RPC_RETRY_MAX_SECONDS
        ),
        rpc_failure_alert_after=_int_from_env(
            source, ENV_RPC_FAILURE_ALERT_AFTER, DEFAULT_RPC_FAILURE_ALERT_AFTER
        ),
        checkpoint_path=_optional_str(source, ENV_CHECKPOINT_PATH)
        or DEFAULT_CHECKPOINT_PATH,
    )
