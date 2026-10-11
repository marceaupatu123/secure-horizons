"""Decodage des evenements du contrat protege #5 (`ProtectedMinter`) — issue #104.

Pourquoi ce module. Un `Transfer` ERC-20 depuis `0x0` dit QU'un mint a eu lieu
(destinataire, montant reellement credite), mais pas POURQUOI : ni la demande
n°X, ni le depot, ni le deposant, ni le taux. Le contrat protege emet ces faits
dans ses propres evenements (`contracts/src/ProtectedMinter.sol`) :

- `SwapRequested(requestId, depositor, depositAmount, rate)` — a la creation de
  la demande (transaction du DEPOSANT, avant tout mint) ;
- `SwapCompleted(requestId, depositor, recipient, depositAmount, mintedAmount,
  rate)` — au traitement par la cle `SERVICE_ROLE` (meme transaction que le mint) ;
- `RoleGranted` / `RoleRevoked` (AccessControl) et `RateChanged` — evenements
  d'administration (OPEN_ANSWERS §1, Q2).

Choix d'architecture (tranche ici, documente dans `monitor/README.md`) :

1. **La verite du mint reste le `Transfer` du token**, pas `SwapCompleted`.
   `SwapCompleted` est ecrit par le contrat qu'on surveille : s'il est bugge ou
   remplace, il peut mentir. Le monitor emet donc un `MintEvent` par
   `Transfer(0x0 -> X)` du token (montant et destinataire REELLEMENT credites),
   et lui rattache la demande via le `SwapCompleted` de la MEME transaction
   (vrai `request_id`).
2. **Le depot vient de `SwapRequested`**, enregistre dans une transaction
   anterieure et independante du traitement. C'est contre lui que la detection
   recalcule I1 (minted = depot x taux) et I3 (destinataire = deposant). Si la
   demande a ete creee avant le debut de l'ecoute (cache vide), on retombe sur
   les champs de `SwapCompleted`, marques `source="completion"` (moins fiables).
3. **Un mint sans `SwapCompleted` dans sa transaction** est un mint passe par
   un chemin non prevu (I4/I5) : la provenance est `None`, la detection leve
   une alerte critique.
4. **Mode Ghost (#8)**, si `MONITOR_GHOST_ADDRESS` est renseignee : le mint est
   `GhostIssued(kind=MINT)` (seul chemin de creation de valeur) ; un
   `Transfer(0x0)` sur M n'est legitime que s'il accompagne un `GhostConverted`
   de meme porteur et meme montant (conversion, retiree du flux de mints),
   sinon il reste un mint sans provenance (I4). Voir `monitor/README.md`.

Le module ne depend PAS de `detection/` : il produit des faits bruts
(`MintProvenance`, `AdminObservation`) que `detection` traduit en
`MintContext` / `AdminEvent`. Depuis la revision groupee de `shared/` (#135),
`with_provenance` reporte la demande dans les champs partages du `MintEvent`
et `admin_event_from_observation` produit le `shared.models.AdminEvent`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from web3 import Web3

from shared.models import AdminEvent, AdminEventKind, MintEvent, MintProvenanceSource

LOGGER = logging.getLogger(__name__)

RawLog = Mapping[str, Any]


def event_topic(signature: str) -> str:
    """topic0 d'un evenement Solidity : `keccak256(signature)` en hex minuscule."""
    return "0x" + Web3.keccak(text=signature).hex().removeprefix("0x")


SWAP_REQUESTED_TOPIC = event_topic("SwapRequested(uint256,address,uint256,uint256)")
SWAP_COMPLETED_TOPIC = event_topic(
    "SwapCompleted(uint256,address,address,uint256,uint256,uint256)"
)
ROLE_GRANTED_TOPIC = event_topic("RoleGranted(bytes32,address,address)")
ROLE_REVOKED_TOPIC = event_topic("RoleRevoked(bytes32,address,address)")
RATE_CHANGED_TOPIC = event_topic("RateChanged(uint256,uint256,address)")

#: Tous les topic0 lus sur l'adresse du minter, en UN appel `eth_getLogs`
#: (une liste en position 0 = OU logique, standard JSON-RPC).
MINTER_TOPICS: tuple[str, ...] = (
    SWAP_REQUESTED_TOPIC,
    SWAP_COMPLETED_TOPIC,
    ROLE_GRANTED_TOPIC,
    ROLE_REVOKED_TOPIC,
    RATE_CHANGED_TOPIC,
)

#: Evenements du M-Ghost (#8, `contracts/src/GhostToken.sol`). `IssueKind` est
#: un enum Solidity, encode en ABI comme un `uint8`.
GHOST_ISSUED_TOPIC = event_topic(
    "GhostIssued(address,address,uint256,uint256,uint256,uint64,uint8)"
)
GHOST_CONVERTED_TOPIC = event_topic(
    "GhostConverted(address,uint256,uint256,uint256,uint256)"
)

#: topic0 lus sur l'adresse du Ghost, en UN appel `eth_getLogs`.
GHOST_TOPICS: tuple[str, ...] = (GHOST_ISSUED_TOPIC, GHOST_CONVERTED_TOPIC)

#: `GhostToken.IssueKind` (ordre de declaration de l'enum).
ISSUE_KIND_MINT = 0
ISSUE_KIND_TRANSFER_M = 1
ISSUE_KIND_RESTITUTION = 2

#: Roles connus du contrat protege (`keccak256("SERVICE_ROLE")`, ...).
#: `DEFAULT_ADMIN_ROLE` vaut 0x00..00 (AccessControl).
KNOWN_ROLES: dict[str, str] = {
    "0x" + "00" * 32: "DEFAULT_ADMIN_ROLE",
    event_topic("SERVICE_ROLE"): "SERVICE_ROLE",
    event_topic("RATE_ADMIN_ROLE"): "RATE_ADMIN_ROLE",
}

AdminKind = Literal["role_granted", "role_revoked", "rate_changed"]


def _hex(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, str):
        lowered = value.lower()
        return lowered if lowered.startswith("0x") else "0x" + lowered
    raise TypeError(f"Valeur hex non supportee : {type(value).__name__}")


def _int(value: Any) -> int:
    return value if isinstance(value, int) else int(_hex(value), 16)


def _topic_address(topic: str) -> str:
    body = topic[2:]
    if len(body) != 64 or body[:24] != "0" * 24:
        raise ValueError(f"topic n'encode pas une adresse : {topic}")
    return Web3.to_checksum_address("0x" + body[24:])


def _words(log: RawLog, count: int) -> list[int]:
    """Decoupe `data` en `count` mots ABI de 32 octets (uint256)."""
    data = _hex(log.get("data", "0x"))[2:]
    if len(data) != 64 * count:
        raise ValueError(f"data de {len(data) // 2} octets, {32 * count} attendus")
    return [int(data[i * 64 : (i + 1) * 64], 16) for i in range(count)]


def _topics(log: RawLog) -> list[str]:
    return [_hex(t) for t in log.get("topics", ())]


@dataclass(frozen=True)
class LogPosition:
    """Position on-chain d'un log (tri et rattachement par transaction)."""

    tx_hash: str
    block_number: int
    log_index: int

    @classmethod
    def of(cls, log: RawLog) -> LogPosition:
        return cls(
            tx_hash=_hex(log["transactionHash"]),
            block_number=_int(log["blockNumber"]),
            log_index=_int(log["logIndex"]),
        )


@dataclass(frozen=True)
class SwapRequestedLog:
    """`SwapRequested` decode : la demande telle qu'enregistree au depot."""

    position: LogPosition
    request_id: int
    depositor: str
    deposit_amount: int
    rate_wad: int


@dataclass(frozen=True)
class SwapCompletedLog:
    """`SwapCompleted` decode : ce que le contrat DIT avoir minte."""

    position: LogPosition
    request_id: int
    depositor: str
    recipient: str
    deposit_amount: int
    minted_amount: int
    rate_wad: int


@dataclass(frozen=True)
class AdminObservation:
    """Evenement d'administration observe sur le minter (OPEN_ANSWERS §1, Q2).

    Attributes:
        kind: nature de l'evenement.
        subject_address: compte concerne (recoit/perd le role, auteur du
            changement de taux).
        tx_hash, block_number, log_index: position on-chain.
        detail: precision lisible (nom du role, ancien -> nouveau taux).
        actor: `sender` de `RoleGranted` / `RoleRevoked` (topic 3) ; None pour
            `RateChanged`, qui ne le porte pas (#104, `shared.AdminEvent.actor`).
        role: identifiant bytes32 BRUT du role (topic 1), pas son nom
            `KNOWN_ROLES` ; None pour `RateChanged` (#104).
        old_rate_wad, new_rate_wad: ancien / nouveau taux x 1e18 de
            `RateChanged` ; None pour les evenements de role (#104).
    """

    kind: AdminKind
    subject_address: str
    tx_hash: str
    block_number: int
    log_index: int
    detail: str = ""
    actor: str | None = None
    role: str | None = None
    old_rate_wad: int | None = None
    new_rate_wad: int | None = None


@dataclass(frozen=True)
class MintProvenance:
    """Demande rattachee a un mint observe (entree de I1 / I3 cote detection).

    Attributes:
        request_id: demande n°X traitee par ce mint.
        depositor: deposant enregistre (I3).
        deposit_amount: depot, base units du collateral (6 decimales).
        rate_wad: taux fige a la demande, x 1e18 (`ProtectedMinter.rate`).
        source: `"request"` = champs lus dans `SwapRequested` (independants du
            traitement) ; `"completion"` = demande anterieure a l'ecoute, champs
            de `SwapCompleted` (ecrits par le contrat surveille, moins fiables).
        claimed_minted: montant que `SwapCompleted` dit avoir minte.
    """

    request_id: int
    depositor: str
    deposit_amount: int
    rate_wad: int
    source: Literal["request", "completion"]
    claimed_minted: int


def decode_swap_requested(log: RawLog) -> SwapRequestedLog:
    """Decode `SwapRequested(uint256 indexed, address indexed, uint256, uint256)`."""
    topics = _topics(log)
    if len(topics) != 3 or topics[0] != SWAP_REQUESTED_TOPIC:
        raise ValueError("log SwapRequested mal forme")
    deposit, rate = _words(log, 2)
    return SwapRequestedLog(
        position=LogPosition.of(log),
        request_id=int(topics[1], 16),
        depositor=_topic_address(topics[2]),
        deposit_amount=deposit,
        rate_wad=rate,
    )


def decode_swap_completed(log: RawLog) -> SwapCompletedLog:
    """Decode `SwapCompleted(uint256 indexed, address indexed, address indexed,
    uint256, uint256, uint256)`."""
    topics = _topics(log)
    if len(topics) != 4 or topics[0] != SWAP_COMPLETED_TOPIC:
        raise ValueError("log SwapCompleted mal forme")
    deposit, minted, rate = _words(log, 3)
    return SwapCompletedLog(
        position=LogPosition.of(log),
        request_id=int(topics[1], 16),
        depositor=_topic_address(topics[2]),
        recipient=_topic_address(topics[3]),
        deposit_amount=deposit,
        minted_amount=minted,
        rate_wad=rate,
    )


def decode_admin(log: RawLog) -> AdminObservation:
    """Decode `RoleGranted` / `RoleRevoked` / `RateChanged`."""
    topics = _topics(log)
    position = LogPosition.of(log)
    if topics and topics[0] in (ROLE_GRANTED_TOPIC, ROLE_REVOKED_TOPIC):
        if len(topics) != 4:
            raise ValueError("log RoleGranted/RoleRevoked mal forme")
        role = KNOWN_ROLES.get(topics[1], topics[1])
        sender = _topic_address(topics[3])
        kind: AdminKind = (
            "role_granted" if topics[0] == ROLE_GRANTED_TOPIC else "role_revoked"
        )
        return AdminObservation(
            kind=kind,
            subject_address=_topic_address(topics[2]),
            tx_hash=position.tx_hash,
            block_number=position.block_number,
            log_index=position.log_index,
            detail=f"role {role} par {sender}",
            actor=sender,
            role=topics[1],
        )
    if topics and topics[0] == RATE_CHANGED_TOPIC:
        if len(topics) != 2:
            raise ValueError("log RateChanged mal forme")
        old, new = _words(log, 2)
        return AdminObservation(
            kind="rate_changed",
            subject_address=_topic_address(topics[1]),
            tx_hash=position.tx_hash,
            block_number=position.block_number,
            log_index=position.log_index,
            detail=f"taux {old} -> {new} (x 1e18)",
            old_rate_wad=old,
            new_rate_wad=new,
        )
    raise ValueError("log d'administration inconnu")


@dataclass(frozen=True)
class GhostIssuedLog:
    """`GhostIssued` decode (#8) : Ghost frais credite a `recipient`.

    `kind == ISSUE_KIND_MINT` (emis par `issueFromMinter`, appele par
    `ProtectedMinter.completeSwap`) est le SEUL chemin legitime de creation de
    valeur avec le Ghost : c'est lui, et non plus un `Transfer(0x0)` sur M, qui
    porte le mint (I4 revise, #8).
    """

    position: LogPosition
    recipient: str
    source: str
    request_id: int
    amount: int
    kind: int


@dataclass(frozen=True)
class GhostConvertedLog:
    """`GhostConverted` decode (#8) : conversion Ghost -> M de `holder`.

    `token_amount` est le M minte au porteur dans la meme transaction
    (`GhostedStable.mint`, donc un `Transfer(0x0 -> holder, token_amount)` sur M).
    """

    position: LogPosition
    holder: str
    ghost_amount: int
    token_amount: int
    fee_amount: int


def decode_ghost_issued(log: RawLog) -> GhostIssuedLog:
    """Decode `GhostIssued(address indexed, address indexed, uint256 indexed,
    uint256, uint256, uint64, uint8)`."""
    topics = _topics(log)
    if len(topics) != 4 or topics[0] != GHOST_ISSUED_TOPIC:
        raise ValueError("log GhostIssued mal forme")
    amount, _ratio, _maturity, kind = _words(log, 4)
    return GhostIssuedLog(
        position=LogPosition.of(log),
        recipient=_topic_address(topics[1]),
        source=_topic_address(topics[2]),
        request_id=int(topics[3], 16),
        amount=amount,
        kind=kind,
    )


def decode_ghost_converted(log: RawLog) -> GhostConvertedLog:
    """Decode `GhostConverted(address indexed, uint256, uint256, uint256, uint256)`."""
    topics = _topics(log)
    if len(topics) != 2 or topics[0] != GHOST_CONVERTED_TOPIC:
        raise ValueError("log GhostConverted mal forme")
    ghost_amount, token_amount, fee, _ratio = _words(log, 4)
    return GhostConvertedLog(
        position=LogPosition.of(log),
        holder=_topic_address(topics[1]),
        ghost_amount=ghost_amount,
        token_amount=token_amount,
        fee_amount=fee,
    )


def split_underlying_mints(
    underlying_mints: Sequence[tuple[str, int, str, int]],
    conversions: Sequence[GhostConvertedLog],
) -> tuple[list[tuple[str, int, str, int]], list[tuple[str, int, str, int]]]:
    """Separe, sur M, les conversions Ghost -> M des mints hors chemin (#8).

    Avec le Ghost, M n'est minte QUE par `GhostToken.convert` : chaque
    `Transfer(0x0 -> holder, v)` sur M doit avoir, dans SA transaction, un
    `GhostConverted(holder, _, v, _, _)` non encore utilise. Sinon c'est un mint
    de M qui contourne le Ghost (I4) : il est rendu a part pour que la detection
    leve une alerte critique.

    Args:
        underlying_mints: `(tx_hash, log_index, recipient, amount)` des
            `Transfer(0x0)` de M.
        conversions: `GhostConverted` de la meme plage.

    Returns:
        `(conversions_appariees, mints_hors_chemin)`, dans l'ordre d'entree.
        Une `GhostConverted` sans `Transfer` correspondant est journalisee en
        ERROR (le Ghost annonce un M qui n'a pas ete credite).
    """
    by_tx: dict[str, list[GhostConvertedLog]] = {}
    for conv in sorted(conversions, key=lambda c: c.position.log_index):
        by_tx.setdefault(conv.position.tx_hash.lower(), []).append(conv)
    matched: list[tuple[str, int, str, int]] = []
    rogue: list[tuple[str, int, str, int]] = []
    for mint in underlying_mints:
        tx_hash, _index, recipient, amount = mint
        candidates = by_tx.get(tx_hash.lower(), [])
        chosen = next(
            (
                c
                for c in candidates
                if c.holder.lower() == recipient.lower() and c.token_amount == amount
            ),
            None,
        )
        if chosen is None:
            LOGGER.error(
                "M minte sans GhostConverted correspondant dans la tx %s : mint "
                "hors chemin (I4, #8)",
                tx_hash,
            )
            rogue.append(mint)
            continue
        candidates.remove(chosen)
        matched.append(mint)
    for leftovers in by_tx.values():
        for conv in leftovers:
            LOGGER.error(
                "GhostConverted de %s sans M credite dans la tx %s",
                conv.holder,
                conv.position.tx_hash,
            )
    return matched, rogue


@dataclass
class MintCorrelator:
    """Rattache chaque mint observe a sa demande (etat garde entre deux polls).

    - `SwapRequested` alimente un cache `request_id -> demande` (vide quand la
      demande est traitee : la memoire reste bornee par les demandes EN ATTENTE).
    - `SwapCompleted` et `Transfer(0x0)` d'une meme transaction sont apparies
      dans `correlate`.
    - La provenance d'un mint est retrouvee par `(tx_hash, log_index)` du
      `MintEvent` (`provenance_for`), ce qui sert de `MintContextProvider` au
      pipeline de detection.

    Attributes:
        max_pending: borne du cache de demandes en attente (une demande jamais
            traitee ne doit pas faire grossir la memoire sans fin). PROVISOIRE.
    """

    max_pending: int = 100_000
    _pending: dict[int, SwapRequestedLog] = field(default_factory=dict)
    _by_mint: dict[tuple[str, int], MintProvenance | None] = field(
        default_factory=dict
    )

    def observe_request(self, request: SwapRequestedLog) -> None:
        """Memorise une demande (depot enregistre on-chain)."""
        if request.request_id in self._pending:
            if self._pending[request.request_id] == request:
                # Meme log relu (plage retentee apres une erreur RPC) : idempotent.
                return
            # I2 : un id ne doit jamais etre reemis. Signale, l'original est garde.
            LOGGER.error(
                "SwapRequested : request_id %d deja vu (I2 ?) tx %s",
                request.request_id,
                request.position.tx_hash,
            )
            return
        if len(self._pending) >= self.max_pending:
            oldest = next(iter(self._pending))
            LOGGER.warning("cache des demandes plein : oubli de la demande %d", oldest)
            del self._pending[oldest]
        self._pending[request.request_id] = request

    def correlate(
        self,
        mints: Sequence[tuple[str, int, str, int]],
        completions: Sequence[SwapCompletedLog],
    ) -> None:
        """Apparie mints et `SwapCompleted` par transaction.

        Args:
            mints: `(tx_hash, log_index, recipient, amount)` de chaque
                `Transfer(0x0)` du token.
            completions: `SwapCompleted` de la meme plage de blocs.

        Pour chaque mint, on cherche dans SA transaction un `SwapCompleted`
        non encore utilise, de preference celui qui annonce le meme
        destinataire et le meme montant (plusieurs traitements dans une meme
        transaction), sinon le premier restant (l'ecart sera alors vu par I1/I3).
        Un `SwapCompleted` sans mint correspondant est journalise en ERROR
        (le contrat annonce un mint qui n'a pas eu lieu).
        """
        by_tx: dict[str, list[SwapCompletedLog]] = {}
        for completion in sorted(completions, key=lambda c: c.position.log_index):
            by_tx.setdefault(completion.position.tx_hash.lower(), []).append(completion)
        for raw_tx, log_index, recipient, amount in mints:
            tx_hash = raw_tx.lower()
            candidates = by_tx.get(tx_hash, [])
            chosen = next(
                (
                    c
                    for c in candidates
                    if c.recipient.lower() == recipient.lower()
                    and c.minted_amount == amount
                ),
                candidates[0] if candidates else None,
            )
            if chosen is None:
                LOGGER.error(
                    "mint sans SwapCompleted dans sa transaction %s : chemin de "
                    "mint non prevu (I4/I5)",
                    tx_hash,
                )
                self._by_mint[(tx_hash, log_index)] = None
                continue
            candidates.remove(chosen)
            self._by_mint[(tx_hash, log_index)] = self._provenance(chosen)
        while len(self._by_mint) > self.max_pending:
            # Provenances jamais consommees (flux lu sans detection) : bornees.
            del self._by_mint[next(iter(self._by_mint))]
        for leftovers in by_tx.values():
            for completion in leftovers:
                LOGGER.error(
                    "SwapCompleted %d sans mint du token dans la tx %s",
                    completion.request_id,
                    completion.position.tx_hash,
                )

    def _provenance(self, completion: SwapCompletedLog) -> MintProvenance:
        request = self._pending.pop(completion.request_id, None)
        if request is None:
            LOGGER.warning(
                "demande %d inconnue (creee avant l'ecoute ?) : depot lu dans "
                "SwapCompleted (source moins fiable)",
                completion.request_id,
            )
            return MintProvenance(
                request_id=completion.request_id,
                depositor=completion.depositor,
                deposit_amount=completion.deposit_amount,
                rate_wad=completion.rate_wad,
                source="completion",
                claimed_minted=completion.minted_amount,
            )
        return MintProvenance(
            request_id=request.request_id,
            depositor=request.depositor,
            deposit_amount=request.deposit_amount,
            rate_wad=request.rate_wad,
            source="request",
            claimed_minted=completion.minted_amount,
        )

    def is_tracked(self, tx_hash: str, log_index: int) -> bool:
        """Vrai si ce mint a ete vu par `correlate` (meme sans provenance)."""
        return (tx_hash.lower(), log_index) in self._by_mint

    def peek(self, tx_hash: str, log_index: int) -> MintProvenance | None:
        """Provenance d'un mint SANS la consommer (`None` si absente)."""
        return self._by_mint.get((tx_hash.lower(), log_index))

    def provenance_for(self, tx_hash: str, log_index: int) -> MintProvenance | None:
        """Provenance d'un mint, puis oubli (un mint n'est verifie qu'une fois).

        Returns:
            La provenance, ou `None` si le mint n'a aucun `SwapCompleted`
            (chemin non prevu) ou est inconnu (voir `is_tracked`).
        """
        return self._by_mint.pop((tx_hash.lower(), log_index), None)

    @property
    def pending_count(self) -> int:
        """Nombre de demandes en attente memorisees."""
        return len(self._pending)


# --- Revision groupee #104 : faits du monitor -> modeles partages ---


def with_provenance(
    mint: MintEvent, provenance: MintProvenance | None, *, tracked: bool
) -> MintEvent:
    """Renseigne les champs de demande partages d'un `MintEvent` (#104, #135).

    `amount` et `recipient` ne changent jamais : ils restent la verite du log
    du token. Les champs ajoutes viennent de la demande rattachee.

    Args:
        mint: mint observe (champs de demande a `None`).
        provenance: demande rattachee par le correlateur ; `None` = aucune.
        tracked: le correlateur a vu ce mint (`MintCorrelator.is_tracked`).
            Faux = observation hors mode contrat protege : rien n'est verifie.

    Returns:
        Un nouveau `MintEvent` VALIDE (le validateur de coherence de
        `shared.models.MintEvent` s'applique) :
        - non suivi : inchange (`via_protected_path=None`) ;
        - suivi sans provenance : `via_protected_path=False`, `request_id=None`
          (chemin non prevu, I4) ;
        - avec provenance : demande complete, `via_protected_path=True`. Un
          depot ou un taux a 0 devient `None` (inconnu), comme le fait
          `detection.provenance.mint_context_from_provenance`.
    """
    if not tracked:
        return mint
    fields: dict[str, Any]
    if provenance is None:
        fields = {"request_id": None, "via_protected_path": False}
    else:
        fields = {
            "request_id": provenance.request_id,
            "depositor": provenance.depositor,
            "deposit_amount": provenance.deposit_amount or None,
            "rate_wad": provenance.rate_wad or None,
            "provenance_source": MintProvenanceSource(provenance.source),
            "claimed_minted": provenance.claimed_minted,
            "via_protected_path": True,
        }
    return MintEvent.model_validate(mint.model_dump() | fields)


def admin_event_from_observation(
    observation: AdminObservation,
    *,
    chain_id: int,
    observed_at: datetime,
    contract_address: str,
) -> AdminEvent:
    """`AdminObservation` du monitor -> `shared.models.AdminEvent` (#104, #135).

    Args:
        observation: evenement decode par `decode_admin`.
        chain_id: chaine observee.
        observed_at: horodatage d'observation (UTC).
        contract_address: contrat emetteur du log (le minter).

    Returns:
        L'evenement partage, avec les champs types de son type (`role` et
        `actor` pour un role, `old_rate_wad` / `new_rate_wad` pour un taux).

    Raises:
        ValueError: si l'observation ne respecte pas le modele partage (p. ex.
            un `RateChanged` dont l'ancien taux vaut 0).
    """
    return AdminEvent(
        tx_hash=observation.tx_hash,
        log_index=observation.log_index,
        block_number=observation.block_number,
        chain_id=chain_id,
        observed_at=observed_at,
        contract_address=contract_address,
        kind=AdminEventKind(observation.kind),
        subject_address=observation.subject_address,
        actor=observation.actor,
        role=observation.role,
        old_rate_wad=observation.old_rate_wad,
        new_rate_wad=observation.new_rate_wad,
    )
