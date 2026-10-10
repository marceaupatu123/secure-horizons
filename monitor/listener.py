"""Ecoute on-chain des evenements de mint et de transfert (Avalanche Fuji).

Mints (issue #9) : ecouteur ERC-20 GENERIQUE, faute de contrat deploye
(`contracts/DEPLOYMENTS.md`). Un mint = evenement standard
`Transfer(address indexed from, address indexed to, uint256 value)` emis par le
contrat token configure, avec `from == 0x000...000`. Les logs sont lus par
polling `eth_getLogs` sur des plages de blocs.

GAP connu — `MintEvent.request_id` : un `Transfer` ERC-20 ne porte pas
l'identifiant de la `MintRequest` (« demande n°X », OPEN_ANSWERS §0). Le
decodeur ERC-20 renseigne donc `UNKNOWN_REQUEST_ID` (sentinelle PROVISOIRE).
Quand le contrat protege (#5) emettra un evenement dedie (ex. `Minted` avec
l'id de demande), on branche un nouveau `MintLogDecoder` a la place du decodeur
ERC-20 (`ChainListener(..., mint_decoders=(MINTED_DECODER,))`), sans toucher a
la boucle de polling. Meme mecanisme envisage pour les evenements
d'administration (`Upgraded`, `RoleGranted`, OPEN_ANSWERS §1), non implementes
ici : leur liste exacte reste ouverte.

Le module produit des `MintEvent` et `TransferEvent` (`docs/CONTRACTS.md`) a
destination du module `detection`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from web3 import Web3

from monitor.config import MonitorConfig
from shared.models import MintEvent, TransferEvent

# keccak256("Transfer(address,address,uint256)") — topic0 standard ERC-20.
ERC20_TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
ZERO_ADDRESS = "0x" + "00" * 20
# Adresse nulle encodee en topic indexe (32 octets).
ZERO_ADDRESS_TOPIC = "0x" + "00" * 32

# PROVISOIRE — sentinelle tant que l'evenement de mint ne porte pas l'id de
# demande (voir GAP en tete de module). Ne PAS l'interpreter comme « demande 0 ».
UNKNOWN_REQUEST_ID = 0

RawLog = Mapping[str, Any]


class EthLike(Protocol):
    """Sous-ensemble de `web3.eth` utilise par l'ecouteur (facile a simuler)."""

    @property
    def block_number(self) -> int: ...

    def get_logs(self, filter_params: Any) -> Sequence[RawLog]: ...


class Web3Like(Protocol):
    """Sous-ensemble de `web3.Web3` utilise par l'ecouteur."""

    @property
    def eth(self) -> EthLike: ...


@dataclass(frozen=True)
class DecodedMint:
    """Champs metier extraits d'un log de mint, avant conversion en `MintEvent`."""

    recipient: str
    amount: int
    request_id: int


@dataclass(frozen=True)
class MintLogDecoder:
    """Branche un type d'evenement de mint dans l'ecouteur.

    Attributes:
        name: nom lisible du decodeur.
        topics: filtre `topics` passe a `eth_getLogs` (topic0 en tete,
            `None` = joker).
        decode: transforme un log brut en `DecodedMint`, ou `None` si le log
            n'est pas un mint exploitable.
    """

    name: str
    topics: tuple[str | None, ...]
    decode: Callable[[RawLog], DecodedMint | None]


def to_hex(value: Any) -> str:
    """Normalise une valeur hex web3 (bytes/HexBytes ou str) en `0x...` minuscule.

    Args:
        value: octets ou chaine hex (avec ou sans prefixe).

    Returns:
        La chaine hex prefixee `0x`, en minuscules.

    Raises:
        TypeError: si le type n'est pas supporte.
    """
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, str):
        lowered = value.lower()
        return lowered if lowered.startswith("0x") else "0x" + lowered
    raise TypeError(f"Valeur hex non supportee : {type(value).__name__}")


def _to_int(value: Any) -> int:
    """Entier depuis un int web3 ou une quantite hex JSON-RPC (`0x1a`)."""
    if isinstance(value, int):
        return value
    return int(to_hex(value), 16)


def topic_to_address(topic: str) -> str | None:
    """Extrait une adresse d'un topic indexe de 32 octets.

    Args:
        topic: topic hex `0x` + 64 hex.

    Returns:
        L'adresse checksum, ou `None` si le topic n'encode pas une adresse.
    """
    body = topic[2:]
    if len(body) != 64 or body[:24] != "0" * 24:
        return None
    return Web3.to_checksum_address("0x" + body[24:])


def decode_erc20_mint(log: RawLog) -> DecodedMint | None:
    """Decode un `Transfer` ERC-20 emis depuis l'adresse nulle (= mint).

    Ignore (retourne `None`) : autre topic0, forme ERC-721 (4 topics, tokenId
    indexe), emetteur non nul (transfert ordinaire), donnees mal formees,
    montant nul (`MintEvent.amount` exige `> 0`).

    Args:
        log: log brut `eth_getLogs`.

    Returns:
        Le mint decode, avec `request_id = UNKNOWN_REQUEST_ID` (GAP), ou `None`.
    """
    topics = [to_hex(t) for t in log.get("topics", ())]
    if len(topics) != 3 or topics[0] != ERC20_TRANSFER_TOPIC:
        return None
    sender = topic_to_address(topics[1])
    recipient = topic_to_address(topics[2])
    if sender is None or recipient is None or sender != ZERO_ADDRESS:
        return None
    data = to_hex(log.get("data", "0x"))
    if len(data) != 2 + 64:
        return None
    amount = int(data, 16)
    if amount <= 0:
        return None
    return DecodedMint(
        recipient=recipient, amount=amount, request_id=UNKNOWN_REQUEST_ID
    )


# Decodeur par defaut : filtre cote RPC sur topic0 = Transfer ET from = 0x0.
ERC20_MINT_DECODER = MintLogDecoder(
    name="erc20_transfer_from_zero",
    topics=(ERC20_TRANSFER_TOPIC, ZERO_ADDRESS_TOPIC),
    decode=decode_erc20_mint,
)


def block_ranges(start: int, end: int, batch_size: int) -> Iterator[tuple[int, int]]:
    """Decoupe `[start, end]` (bornes incluses) en plages d'au plus `batch_size`.

    Args:
        start: premier bloc.
        end: dernier bloc (inclus).
        batch_size: largeur max d'une plage (>= 1).

    Yields:
        Des couples `(debut, fin)` inclusifs, dans l'ordre.
    """
    current = start
    while current <= end:
        stop = min(current + batch_size - 1, end)
        yield current, stop
        current = stop + 1


def connect_web3(rpc_url: str) -> Web3Like:
    """Ouvre une connexion HTTP web3 vers le RPC (aucun appel reseau ici)."""
    return Web3(Web3.HTTPProvider(rpc_url))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChainListener:
    """Ecoute un noeud RPC Fuji et emet les evenements observes."""

    def __init__(
        self,
        config: MonitorConfig,
        web3: Web3Like | None = None,
        *,
        mint_decoders: Sequence[MintLogDecoder] = (ERC20_MINT_DECODER,),
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Initialise l'ecouteur.

        Args:
            config: reglages du monitor (`monitor.config.load_monitor_config()`).
            web3: client web3 (ou faux client en test) ; si absent, connexion
                paresseuse a `config.rpc_url` au premier appel.
            mint_decoders: types d'evenements consideres comme des mints.
                Pour un evenement dedie, REMPLACER le decodeur ERC-20 plutot que
                l'ajouter (sinon un meme mint serait emis deux fois).
            sleep: fonction d'attente entre deux polls (injectable en test).
            now: horloge UTC pour `observed_at` (injectable en test).
        """
        self._config = config
        self._web3 = web3
        self._mint_decoders = tuple(mint_decoders)
        self._sleep = sleep
        self._now = now

    @property
    def _eth(self) -> EthLike:
        if self._web3 is None:
            if not self._config.rpc_url:
                raise RuntimeError(
                    "FUJI_RPC_URL manquante : impossible de se connecter au RPC."
                )
            self._web3 = connect_web3(self._config.rpc_url)
        return self._web3.eth

    def _token_address(self) -> str:
        if self._config.token_address is None:
            raise RuntimeError(
                "MONITOR_TOKEN_ADDRESS manquante : aucun contrat token a ecouter "
                "(voir contracts/DEPLOYMENTS.md)."
            )
        return self._config.token_address

    def _safe_head(self) -> int:
        return max(self._eth.block_number - self._config.confirmations, 0)

    def _to_mint_event(self, log: RawLog, decoder: MintLogDecoder) -> MintEvent | None:
        if log.get("removed"):
            # Log annule par une reorganisation de chaine.
            return None
        decoded = decoder.decode(log)
        if decoded is None:
            return None
        return MintEvent(
            tx_hash=to_hex(log["transactionHash"]),
            log_index=_to_int(log["logIndex"]),
            block_number=_to_int(log["blockNumber"]),
            chain_id=self._config.chain_id,
            observed_at=self._now(),
            recipient=decoded.recipient,
            amount=decoded.amount,
            request_id=decoded.request_id,
        )

    def fetch_mint_events(self, from_block: int, to_block: int) -> list[MintEvent]:
        """Lit les mints d'une plage de blocs (bornes incluses).

        La plage est decoupee selon `config.block_batch_size`.

        Args:
            from_block: premier bloc.
            to_block: dernier bloc (inclus).

        Returns:
            Les mints, tries par `(block_number, log_index)`.

        Raises:
            RuntimeError: si l'adresse du token ou l'URL RPC manque.
        """
        token = self._token_address()
        events: list[MintEvent] = []
        for start, end in block_ranges(
            from_block, to_block, self._config.block_batch_size
        ):
            for decoder in self._mint_decoders:
                logs = self._eth.get_logs(
                    {
                        "fromBlock": start,
                        "toBlock": end,
                        "address": token,
                        "topics": list(decoder.topics),
                    }
                )
                for log in logs:
                    event = self._to_mint_event(log, decoder)
                    if event is not None:
                        events.append(event)
        events.sort(key=lambda e: (e.block_number, e.log_index))
        return events

    def stream_mint_events(self, max_polls: int | None = None) -> Iterator[MintEvent]:
        """Emet les evenements de mint au fil de l'eau (polling).

        Commence a `config.start_block` (ou au bloc courant si None), puis a
        chaque poll lit les blocs nouveaux jusqu'a la tete moins
        `config.confirmations`, et attend `config.poll_interval_seconds`.

        Args:
            max_polls: nombre de polls avant arret (None = infini ; utile en
                test).

        Yields:
            Un `MintEvent` par mint observe, dans l'ordre de la chaine.

        Raises:
            RuntimeError: si l'adresse du token ou l'URL RPC manque.
        """
        self._token_address()
        next_block = self._config.start_block
        polls = 0
        while True:
            head = self._safe_head()
            if next_block is None:
                next_block = head
            if head >= next_block:
                for start, end in block_ranges(
                    next_block, head, self._config.block_batch_size
                ):
                    yield from self.fetch_mint_events(start, end)
                next_block = head + 1
            polls += 1
            if max_polls is not None and polls >= max_polls:
                return
            self._sleep(self._config.poll_interval_seconds)

    def stream_transfer_events(self) -> Iterator[TransferEvent]:
        """Emet les evenements de transfert au fil de l'eau.

        Yields:
            Un `TransferEvent` par transfert observe.
        """
        raise NotImplementedError("monitor.stream_transfer_events : a implementer")
