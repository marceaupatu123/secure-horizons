"""Ecoute on-chain des evenements de mint et de transfert (Avalanche Fuji).

Mints (issue #9) : ecouteur ERC-20 GENERIQUE, faute de contrat deploye
(`contracts/DEPLOYMENTS.md`). Un mint = evenement standard
`Transfer(address indexed from, address indexed to, uint256 value)` emis par le
contrat token configure, avec `from == 0x000...000`. Les logs sont lus par
polling `eth_getLogs` sur des plages de blocs.

GAP résolu (#79, OPEN_ANSWERS §79) — `MintEvent.request_id` : un `Transfer`
ERC-20 ne porte pas l'identifiant de la `MintRequest` (« demande n°X »,
OPEN_ANSWERS §0). `MintEvent.request_id` est desormais `int | None` et le
decodeur ERC-20 renseigne `UNKNOWN_REQUEST_ID = None` (plus `0`, qui entrait en
collision avec la vraie demande n°0). Mode « contrat protege » (#104) : avec
`MONITOR_MINTER_ADDRESS`, `fetch_events` lit aussi les evenements du
`ProtectedMinter` (`monitor/protected.py`) et rattache chaque mint a sa demande
(vrai `request_id`) ; les evenements d'administration (`RoleGranted`,
`RoleRevoked`, `RateChanged`) sortent dans le flux en `AdminObservation`.

Transferts (issue #10) : meme evenement `Transfer` ERC-20 du meme contrat, lu
par la meme boucle de polling. Sont exclus : les mints (`from == 0x0`, deja
emis par `stream_mint_events`) et — PROVISOIRE, a valider par l'equipe — les
burns (`to == 0x0`), qui ne sont pas des transferts entre deux adresses.

GAP connu — `TransferEvent.is_ghost` : un `Transfer` ERC-20 ne dit pas si le
token transfere est un Ghost. La valeur vient de `MonitorConfig.token_is_ghost`
(defaut PROVISOIRE False) tant que le design du contrat Ghost n'est pas fixe.

Branchement vers `detection` (issue #86) : `stream_event_batches` emet, a
chaque poll, les mints ET transferts nouveaux dans l'ordre de la chaine (liste
vide si rien de neuf) pour que le consommateur reprenne la main a chaque poll
(cloture des tranches a l'heure, meme sans transfert). `read_total_supply` lit
`totalSupply()` du token (offre utilisee pour normaliser le volume).

Le module produit des `MintEvent` et `TransferEvent` (`docs/CONTRACTS.md`) a
destination du module `detection`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar

from web3 import Web3

from monitor.checkpoint import BlockCheckpoint
from monitor.config import MonitorConfig
from monitor.protected import (
    GHOST_ISSUED_TOPIC,
    GHOST_TOPICS,
    ISSUE_KIND_MINT,
    MINTER_TOPICS,
    SWAP_COMPLETED_TOPIC,
    SWAP_REQUESTED_TOPIC,
    AdminObservation,
    GhostConvertedLog,
    MintCorrelator,
    SwapCompletedLog,
    decode_admin,
    decode_ghost_converted,
    decode_ghost_issued,
    decode_swap_completed,
    decode_swap_requested,
    split_underlying_mints,
)
from shared.models import MintEvent, TransferEvent

LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class MonitorConfigurationError(RuntimeError):
    """Reglage manquant (RPC, adresse du token) : erreur NON retentee.

    Toute autre exception levee pendant un poll (RPC injoignable, timeout,
    reponse invalide) est consideree transitoire et retentee (issue #74).
    """

# keccak256("Transfer(address,address,uint256)") — topic0 standard ERC-20.
ERC20_TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
ZERO_ADDRESS = "0x" + "00" * 20
# Adresse nulle encodee en topic indexe (32 octets).
ZERO_ADDRESS_TOPIC = "0x" + "00" * 32

# Sentinelle « id de demande inconnu » : un Transfer ERC-20 nu ne porte pas
# l'id de demande. Depuis la decision #79 (OPEN_ANSWERS §79), c'est `None` et
# non plus `0` — `0` entrait en collision avec la vraie demande n°0
# (`data/generate.py` numerote a partir de 0). `MintEvent.request_id` est
# desormais `int | None`. Un evenement dedie futur (`Minted` cote contrat #5)
# renseignera un vrai id.
UNKNOWN_REQUEST_ID: int | None = None

# Selecteur ERC-20 `totalSupply()` = 4 premiers octets de keccak256("totalSupply()").
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"

RawLog = Mapping[str, Any]
ChainEvent = TypeVar("ChainEvent", MintEvent, TransferEvent)
ObservedEvent = MintEvent | TransferEvent
#: Ce que `fetch_events` peut rendre en mode « contrat protege » (#104).
ProtectedObservedEvent = MintEvent | TransferEvent | AdminObservation


class EthLike(Protocol):
    """Sous-ensemble de `web3.eth` utilise par l'ecouteur (facile a simuler)."""

    @property
    def block_number(self) -> int: ...

    def get_logs(self, filter_params: Any) -> Sequence[RawLog]: ...

    def call(self, transaction: Any) -> Any: ...


class Web3Like(Protocol):
    """Sous-ensemble de `web3.Web3` utilise par l'ecouteur."""

    @property
    def eth(self) -> EthLike: ...


@dataclass(frozen=True)
class DecodedMint:
    """Champs metier extraits d'un log de mint, avant conversion en `MintEvent`."""

    recipient: str
    amount: int
    request_id: int | None


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


@dataclass(frozen=True)
class DecodedTransfer:
    """Champs d'un `Transfer` ERC-20 brut (forme standard, 3 topics)."""

    sender: str
    recipient: str
    amount: int


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


def decode_erc20_transfer_log(log: RawLog) -> DecodedTransfer | None:
    """Decode un `Transfer` ERC-20 brut, sans filtrage metier.

    Ignore (retourne `None`) : autre topic0, forme ERC-721 (4 topics, tokenId
    indexe), topics ou donnees mal formes.

    Args:
        log: log brut `eth_getLogs`.

    Returns:
        `(sender, recipient, amount)` (adresses checksum), ou `None`.
    """
    topics = [to_hex(t) for t in log.get("topics", ())]
    if len(topics) != 3 or topics[0] != ERC20_TRANSFER_TOPIC:
        return None
    sender = topic_to_address(topics[1])
    recipient = topic_to_address(topics[2])
    if sender is None or recipient is None:
        return None
    data = to_hex(log.get("data", "0x"))
    if len(data) != 2 + 64:
        return None
    return DecodedTransfer(sender=sender, recipient=recipient, amount=int(data, 16))


def decode_erc20_mint(log: RawLog) -> DecodedMint | None:
    """Decode un `Transfer` ERC-20 emis depuis l'adresse nulle (= mint).

    Ignore (retourne `None`) : log non decodable (`decode_erc20_transfer_log`),
    emetteur non nul (transfert ordinaire), montant nul (`MintEvent.amount`
    exige `> 0`).

    Args:
        log: log brut `eth_getLogs`.

    Returns:
        Le mint decode, avec `request_id = UNKNOWN_REQUEST_ID` (GAP), ou `None`.
    """
    decoded = decode_erc20_transfer_log(log)
    if decoded is None or decoded.sender != ZERO_ADDRESS or decoded.amount <= 0:
        return None
    return DecodedMint(
        recipient=decoded.recipient,
        amount=decoded.amount,
        request_id=UNKNOWN_REQUEST_ID,
    )


def decode_erc20_transfer(log: RawLog) -> DecodedTransfer | None:
    """Decode un transfert ERC-20 ordinaire (ni mint, ni burn).

    Ignore (retourne `None`) : log non decodable (`decode_erc20_transfer_log`),
    mint (`from == 0x0`), burn (`to == 0x0`, exclusion PROVISOIRE — a valider
    par l'equipe), montant nul (`TransferEvent.amount` exige `> 0`).

    Args:
        log: log brut `eth_getLogs`.

    Returns:
        Le transfert decode, ou `None`.
    """
    decoded = decode_erc20_transfer_log(log)
    if (
        decoded is None
        or decoded.sender == ZERO_ADDRESS
        or decoded.recipient == ZERO_ADDRESS
        or decoded.amount <= 0
    ):
        return None
    return decoded


# Decodeur par defaut : filtre cote RPC sur topic0 = Transfer ET from = 0x0.
ERC20_MINT_DECODER = MintLogDecoder(
    name="erc20_transfer_from_zero",
    topics=(ERC20_TRANSFER_TOPIC, ZERO_ADDRESS_TOPIC),
    decode=decode_erc20_mint,
)

# Filtre RPC des transferts : topic0 = Transfer seulement (`eth_getLogs` ne sait
# pas exprimer « from != 0x0 ») ; mints et burns sont exclus cote client.
ERC20_TRANSFER_TOPICS: tuple[str | None, ...] = (ERC20_TRANSFER_TOPIC,)


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
        # Mode « contrat protege » (#104) : etat garde entre deux polls.
        self.correlator: MintCorrelator | None = (
            MintCorrelator() if config.minter_address is not None else None
        )

    @property
    def _eth(self) -> EthLike:
        if self._web3 is None:
            if not self._config.rpc_url:
                raise MonitorConfigurationError(
                    "FUJI_RPC_URL manquante : impossible de se connecter au RPC."
                )
            self._web3 = connect_web3(self._config.rpc_url)
        return self._web3.eth

    def _token_address(self) -> str:
        if self._config.token_address is None:
            raise MonitorConfigurationError(
                "MONITOR_TOKEN_ADDRESS manquante : aucun contrat token a ecouter "
                "(voir contracts/DEPLOYMENTS.md)."
            )
        return self._config.token_address

    def _safe_head(self) -> int:
        return max(self._eth.block_number - self._config.confirmations, 0)

    def _fetch_events(
        self,
        from_block: int,
        to_block: int,
        sources: Sequence[
            tuple[tuple[str | None, ...], Callable[[RawLog], ChainEvent | None]]
        ],
    ) -> list[ChainEvent]:
        """Lit les logs du token par plages et les convertit (commun mints/transferts).

        Args:
            from_block: premier bloc.
            to_block: dernier bloc (inclus).
            sources: couples `(topics, convertisseur)` ; un appel `eth_getLogs`
                par couple et par plage.

        Returns:
            Les evenements, tries par `(block_number, log_index)`.
        """
        token = self._token_address()
        events: list[ChainEvent] = []
        for start, end in block_ranges(
            from_block, to_block, self._config.block_batch_size
        ):
            for topics, convert in sources:
                logs = self._eth.get_logs(
                    {
                        "fromBlock": start,
                        "toBlock": end,
                        "address": token,
                        "topics": list(topics),
                    }
                )
                for log in logs:
                    if log.get("removed"):
                        # Log annule par une reorganisation de chaine.
                        continue
                    try:
                        event = convert(log)
                    except (ValueError, KeyError, TypeError) as exc:
                        # Log mal forme (champ manquant, validation pydantic) :
                        # erreur deterministe, un retry ne changerait rien.
                        # On le signale et on continue, au lieu de couper
                        # toute la surveillance (issue #74).
                        LOGGER.error(
                            "log ignore (bloc %s, index %s) : %s",
                            log.get("blockNumber"),
                            log.get("logIndex"),
                            exc,
                        )
                        continue
                    if event is not None:
                        events.append(event)
        events.sort(key=lambda e: (e.block_number, e.log_index))
        return events

    def _poll_batches(
        self,
        fetch: Callable[[int, int], list[ChainEvent]],
        max_polls: int | None,
    ) -> Iterator[list[ChainEvent]]:
        """Boucle de polling commune : lit les blocs nouveaux a chaque tour.

        Commence apres le checkpoint s'il existe (`config.checkpoint_path`),
        sinon a `config.start_block` (ou au bloc courant si None), puis a
        chaque poll lit les blocs nouveaux jusqu'a la tete moins
        `config.confirmations`, et attend `config.poll_interval_seconds`.

        Reprise sur erreur (issue #74) : chaque appel RPC est retente avec
        attente exponentielle plafonnee, sans limite de tentatives. Le curseur
        n'avance qu'apres une plage lue ET rendue au consommateur, donc la
        reprise se fait sans trou ni doublon. Le checkpoint est ecrit au meme
        moment (semantique « au moins une fois » au redemarrage).

        Yields:
            Une liste d'evenements par plage de `config.block_batch_size`
            blocs lue, ou une liste vide si le poll n'a aucun bloc nouveau
            (le consommateur reprend ainsi la main a chaque poll).

        Raises:
            MonitorConfigurationError: si l'adresse du token ou l'URL RPC
                manque (non retente).
        """
        self._token_address()
        checkpoint = (
            BlockCheckpoint(self._config.checkpoint_path)
            if self._config.checkpoint_path
            else None
        )
        next_block = self._config.start_block
        if checkpoint is not None:
            last = checkpoint.load()
            if last is not None:
                next_block = last + 1
                LOGGER.info("reprise apres le checkpoint : bloc %d", next_block)
        else:
            LOGGER.warning(
                "aucun checkpoint (MONITOR_CHECKPOINT_PATH vide) : les blocs "
                "produits pendant un arret du monitor ne seront pas relus"
            )
        polls = 0
        while True:
            head = self._with_retry(self._safe_head, "lecture de la tete de chaine")
            if next_block is None:
                next_block = head
            if head >= next_block:
                for start, end in block_ranges(
                    next_block, head, self._config.block_batch_size
                ):
                    batch = self._with_retry(
                        lambda s=start, e=end: fetch(s, e),
                        f"lecture des blocs {start}-{end}",
                    )
                    yield batch
                    next_block = end + 1
                    if checkpoint is not None:
                        self._save_checkpoint(checkpoint, end)
            else:
                yield []
            polls += 1
            if max_polls is not None and polls >= max_polls:
                return
            self._sleep(self._config.poll_interval_seconds)

    def _with_retry(self, call: Callable[[], _T], what: str) -> _T:
        """Execute `call`, en le retentant sans limite sur erreur transitoire.

        Attente `base * 2**(n-1)` plafonnee a `config.rpc_retry_max_seconds`.
        Chaque echec est logue en WARNING ; a partir de
        `config.rpc_failure_alert_after` echecs consecutifs, en ERROR
        (« surveillance aveugle ») pour qu'un humain soit prevenu plutot que
        de laisser le monitor se taire.

        Args:
            call: l'appel a proteger.
            what: description lisible pour les logs.

        Returns:
            Le resultat de `call`.

        Raises:
            MonitorConfigurationError: jamais retentee (reglage manquant).
        """
        failures = 0
        while True:
            try:
                result = call()
            except MonitorConfigurationError:
                raise
            except Exception as exc:  # noqa: BLE001 — tout echec RPC est retente
                failures += 1
                delay = min(
                    self._config.rpc_retry_base_seconds * 2 ** (failures - 1),
                    self._config.rpc_retry_max_seconds,
                )
                level = (
                    logging.ERROR
                    if failures >= self._config.rpc_failure_alert_after
                    else logging.WARNING
                )
                LOGGER.log(
                    level,
                    "%s : echec %d (%s: %s), nouvel essai dans %.1fs%s",
                    what,
                    failures,
                    type(exc).__name__,
                    exc,
                    delay,
                    " — SURVEILLANCE AVEUGLE" if level == logging.ERROR else "",
                )
                self._sleep(delay)
                continue
            if failures:
                LOGGER.info("%s : reprise apres %d echec(s)", what, failures)
            return result

    @staticmethod
    def _save_checkpoint(checkpoint: BlockCheckpoint, last_block: int) -> None:
        """Ecrit le checkpoint ; un echec d'ecriture ne coupe pas la surveillance."""
        try:
            checkpoint.save(last_block)
        except OSError as exc:
            LOGGER.error("checkpoint non ecrit (%s) : %s", checkpoint.path, exc)

    def _poll(
        self,
        fetch: Callable[[int, int], list[ChainEvent]],
        max_polls: int | None,
    ) -> Iterator[ChainEvent]:
        """Meme boucle que `_poll_batches`, evenement par evenement."""
        for batch in self._poll_batches(fetch, max_polls):
            yield from batch

    def _to_mint_event(self, log: RawLog, decoder: MintLogDecoder) -> MintEvent | None:
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
        return self._fetch_events(
            from_block,
            to_block,
            [
                (decoder.topics, lambda log, d=decoder: self._to_mint_event(log, d))
                for decoder in self._mint_decoders
            ],
        )

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
        return self._poll(self.fetch_mint_events, max_polls)

    def _to_transfer_event(
        self, log: RawLog, *, is_ghost: bool | None = None
    ) -> TransferEvent | None:
        """`TransferEvent` d'un `Transfer` ERC-20 ordinaire.

        Args:
            log: log brut.
            is_ghost: force `TransferEvent.is_ghost` (mode Ghost, #8 : un
                `Transfer` lu sur l'adresse du Ghost EST un transfert de Ghost) ;
                None = `config.token_is_ghost`.
        """
        decoded = decode_erc20_transfer(log)
        if decoded is None:
            return None
        return TransferEvent(
            tx_hash=to_hex(log["transactionHash"]),
            log_index=_to_int(log["logIndex"]),
            block_number=_to_int(log["blockNumber"]),
            chain_id=self._config.chain_id,
            observed_at=self._now(),
            sender=decoded.sender,
            recipient=decoded.recipient,
            amount=decoded.amount,
            is_ghost=self._config.token_is_ghost if is_ghost is None else is_ghost,
        )

    def fetch_transfer_events(
        self, from_block: int, to_block: int
    ) -> list[TransferEvent]:
        """Lit les transferts d'une plage de blocs (bornes incluses).

        Meme `Transfer` ERC-20 que les mints, hors mints (`from == 0x0`) et
        burns (`to == 0x0`, exclusion PROVISOIRE). La plage est decoupee selon
        `config.block_batch_size`.

        Args:
            from_block: premier bloc.
            to_block: dernier bloc (inclus).

        Returns:
            Les transferts, tries par `(block_number, log_index)`.

        Raises:
            RuntimeError: si l'adresse du token ou l'URL RPC manque.
        """
        return self._fetch_events(
            from_block,
            to_block,
            [(ERC20_TRANSFER_TOPICS, self._to_transfer_event)],
        )

    def stream_transfer_events(
        self, max_polls: int | None = None
    ) -> Iterator[TransferEvent]:
        """Emet les evenements de transfert au fil de l'eau (polling).

        Meme boucle que `stream_mint_events` (depart, confirmations, pause).

        Args:
            max_polls: nombre de polls avant arret (None = infini ; utile en
                test).

        Yields:
            Un `TransferEvent` par transfert observe, dans l'ordre de la chaine.

        Raises:
            RuntimeError: si l'adresse du token ou l'URL RPC manque.
        """
        return self._poll(self.fetch_transfer_events, max_polls)

    def fetch_events(self, from_block: int, to_block: int) -> list[ObservedEvent]:
        """Lit mints ET transferts d'une plage de blocs (bornes incluses).

        Memes decodeurs que `fetch_mint_events` et `fetch_transfer_events`.

        Args:
            from_block: premier bloc.
            to_block: dernier bloc (inclus).

        Returns:
            Mints et transferts melanges, tries par `(block_number, log_index)`.

        Raises:
            RuntimeError: si l'adresse du token ou l'URL RPC manque.
        """
        if self.correlator is not None:
            return self.fetch_protected_events(from_block, to_block)  # type: ignore[return-value]
        sources: list[
            tuple[tuple[str | None, ...], Callable[[RawLog], ObservedEvent | None]]
        ] = [
            (decoder.topics, lambda log, d=decoder: self._to_mint_event(log, d))
            for decoder in self._mint_decoders
        ]
        sources.append((ERC20_TRANSFER_TOPICS, self._to_transfer_event))
        return self._fetch_events(from_block, to_block, sources)  # type: ignore[arg-type]

    def fetch_protected_events(
        self, from_block: int, to_block: int
    ) -> list[ProtectedObservedEvent]:
        """Mode « contrat protege » (#104) : mints rattaches, transferts, admin.

        Deux appels `eth_getLogs` par plage : les `Transfer` du token (mints
        ET transferts, un seul appel) et les evenements du `ProtectedMinter`
        (`MINTER_TOPICS`, OU logique en position 0). Les `SwapRequested`
        alimentent le cache du correlateur ; chaque `Transfer(0x0)` devient
        un `MintEvent` dont le `request_id` vient du `SwapCompleted` de la
        meme transaction (provenance consultable via
        `self.correlator.provenance_for`).

        Args:
            from_block: premier bloc.
            to_block: dernier bloc (inclus).

        Returns:
            `MintEvent`, `TransferEvent` et `AdminObservation`, tries par
            `(block_number, log_index)`.
        """
        correlator = self.correlator
        minter = self._config.minter_address
        if correlator is None or minter is None:
            raise MonitorConfigurationError(
                "MONITOR_MINTER_ADDRESS manquante : mode contrat protege inactif."
            )
        token = self._token_address()
        ghost = self._config.ghost_address
        events: list[ProtectedObservedEvent] = []
        for start, end in block_ranges(
            from_block, to_block, self._config.block_batch_size
        ):
            minter_logs = self._eth.get_logs(
                {
                    "fromBlock": start,
                    "toBlock": end,
                    "address": minter,
                    "topics": [list(MINTER_TOPICS)],
                }
            )
            token_logs = self._eth.get_logs(
                {
                    "fromBlock": start,
                    "toBlock": end,
                    "address": token,
                    "topics": [ERC20_TRANSFER_TOPIC],
                }
            )
            completions: list[SwapCompletedLog] = []
            # Ordre de la chaine : une demande et son traitement dans la meme
            # plage doivent etre vus dans cet ordre.
            for log in sorted(
                (lg for lg in minter_logs if not lg.get("removed")),
                key=lambda lg: (_to_int(lg["blockNumber"]), _to_int(lg["logIndex"])),
            ):
                try:
                    topic0 = to_hex(log["topics"][0])
                    if topic0 == SWAP_REQUESTED_TOPIC:
                        correlator.observe_request(decode_swap_requested(log))
                    elif topic0 == SWAP_COMPLETED_TOPIC:
                        completions.append(decode_swap_completed(log))
                    else:
                        events.append(decode_admin(log))
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    LOGGER.error(
                        "log du minter ignore (bloc %s, index %s) : %s",
                        log.get("blockNumber"),
                        log.get("logIndex"),
                        exc,
                    )
            mints: list[MintEvent] = []
            for log in token_logs:
                if log.get("removed"):
                    continue
                try:
                    mint = self._to_mint_event(log, ERC20_MINT_DECODER)
                    if mint is not None:
                        mints.append(mint)
                        continue
                    transfer = self._to_transfer_event(log)
                except (ValueError, KeyError, TypeError) as exc:
                    LOGGER.error(
                        "log du token ignore (bloc %s, index %s) : %s",
                        log.get("blockNumber"),
                        log.get("logIndex"),
                        exc,
                    )
                    continue
                if transfer is not None:
                    events.append(transfer)
            if ghost is None:
                correlator.correlate(
                    [(m.tx_hash, m.log_index, m.recipient, m.amount) for m in mints],
                    completions,
                )
            else:
                ghost_transfers: list[TransferEvent] = []
                mints = self._ghost_mints(
                    start, end, ghost, mints, completions, ghost_transfers
                )
                events.extend(ghost_transfers)
            for mint in mints:
                found = correlator.peek(mint.tx_hash, mint.log_index)
                request_id = found.request_id if found is not None else None
                events.append(mint.model_copy(update={"request_id": request_id}))
        events.sort(key=lambda e: (e.block_number, e.log_index))
        return events

    def _ghost_mints(
        self,
        start: int,
        end: int,
        ghost: str,
        underlying_mints: list[MintEvent],
        completions: list[SwapCompletedLog],
        ghost_transfers: list[TransferEvent],
    ) -> list[MintEvent]:
        """Mode Ghost (#8) : les mints a verifier sur une plage deja lue.

        - Un `GhostIssued(kind=MINT)` est LE mint (seul chemin de creation de
          valeur, `ProtectedMinter.completeSwap` -> `issueFromMinter`) : il
          devient un `MintEvent` rattache au `SwapCompleted` de sa transaction.
        - Un `Transfer(0x0)` sur M accompagne d'un `GhostConverted` est une
          conversion (valeur deja comptee a l'emission du Ghost) : retire du
          flux de mints.
        - Un `Transfer(0x0)` sur M SANS `GhostConverted` contourne le Ghost :
          garde comme mint SANS provenance -> alerte I4 critique en detection.
        - Un `Transfer` ERC-20 ordinaire sur le Ghost (ni emission ni burn) est
          un transfert de Ghost : ajoute a `ghost_transfers` avec
          `is_ghost=True` (entree du lignage, #106). Meme appel `eth_getLogs`.
        """
        correlator = self.correlator
        assert correlator is not None  # garanti par fetch_protected_events
        ghost_logs = self._eth.get_logs(
            {
                "fromBlock": start,
                "toBlock": end,
                "address": ghost,
                "topics": [[*GHOST_TOPICS, ERC20_TRANSFER_TOPIC]],
            }
        )
        issued: list[MintEvent] = []
        conversions: list[GhostConvertedLog] = []
        for log in ghost_logs:
            if log.get("removed"):
                continue
            try:
                topic0 = to_hex(log["topics"][0])
                if topic0 == ERC20_TRANSFER_TOPIC:
                    moved = self._to_transfer_event(log, is_ghost=True)
                    if moved is not None:
                        ghost_transfers.append(moved)
                elif topic0 == GHOST_ISSUED_TOPIC:
                    decoded = decode_ghost_issued(log)
                    if decoded.kind != ISSUE_KIND_MINT or decoded.amount <= 0:
                        # TRANSFER_M / RESTITUTION : pas de valeur nouvelle.
                        continue
                    issued.append(
                        MintEvent(
                            tx_hash=decoded.position.tx_hash,
                            log_index=decoded.position.log_index,
                            block_number=decoded.position.block_number,
                            chain_id=self._config.chain_id,
                            observed_at=self._now(),
                            recipient=decoded.recipient,
                            amount=decoded.amount,
                            request_id=None,
                        )
                    )
                else:
                    conversions.append(decode_ghost_converted(log))
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                LOGGER.error(
                    "log du Ghost ignore (bloc %s, index %s) : %s",
                    log.get("blockNumber"),
                    log.get("logIndex"),
                    exc,
                )
        correlator.correlate(
            [(m.tx_hash, m.log_index, m.recipient, m.amount) for m in issued],
            completions,
        )
        _converted, rogue = split_underlying_mints(
            [(m.tx_hash, m.log_index, m.recipient, m.amount) for m in underlying_mints],
            conversions,
        )
        rogue_keys = {(tx.lower(), idx) for tx, idx, _r, _a in rogue}
        rogue_mints = [
            m for m in underlying_mints if (m.tx_hash.lower(), m.log_index) in rogue_keys
        ]
        # Aucun SwapCompleted offert : un mint de M hors conversion n'a jamais
        # de provenance legitime (I4), meme si la tx contient un traitement.
        correlator.correlate(
            [(m.tx_hash, m.log_index, m.recipient, m.amount) for m in rogue_mints],
            [],
        )
        return issued + rogue_mints

    def stream_event_batches(
        self, max_polls: int | None = None
    ) -> Iterator[list[ObservedEvent]]:
        """Emet mints ET transferts par lots, au fil de l'eau (polling).

        Meme boucle que `stream_mint_events` (depart, confirmations, pause).
        Contrairement aux flux par type, un lot (eventuellement VIDE) est emis
        a chaque poll : le consommateur peut cloturer ses tranches a l'heure
        meme quand aucun transfert n'arrive.

        Args:
            max_polls: nombre de polls avant arret (None = infini ; utile en
                test).

        Yields:
            Une liste par plage lue (ou vide si rien de neuf), dans l'ordre de
            la chaine.

        Raises:
            RuntimeError: si l'adresse du token ou l'URL RPC manque.
        """
        return self._poll_batches(self.fetch_events, max_polls)

    def read_total_supply(self) -> int:
        """Lit `totalSupply()` du token ecoute (appel `eth_call`, bloc `latest`).

        Returns:
            L'offre totale, base units.

        Raises:
            RuntimeError: si l'adresse du token ou l'URL RPC manque.
            ValueError: si la reponse n'est pas un `uint256` ABI (32 octets).
        """
        raw = self._eth.call({"to": self._token_address(), "data": TOTAL_SUPPLY_SELECTOR})
        data = to_hex(raw)
        if len(data) != 2 + 64:
            raise ValueError(f"reponse totalSupply() inattendue : {data!r}")
        return int(data, 16)
