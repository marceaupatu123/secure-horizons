"""Tests du mode « contrat protege » du monitor (#104).

Logs synthetiques au format `eth_getLogs`, construits a la main a partir des
signatures de `contracts/src/ProtectedMinter.sol`. Donnees FICTIVES.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from monitor.config import MonitorConfig
from monitor.listener import ERC20_TRANSFER_TOPIC, ChainListener
from monitor.protected import (
    KNOWN_ROLES,
    RATE_CHANGED_TOPIC,
    ROLE_GRANTED_TOPIC,
    SWAP_COMPLETED_TOPIC,
    SWAP_REQUESTED_TOPIC,
    AdminObservation,
    MintCorrelator,
    decode_admin,
    decode_swap_completed,
    decode_swap_requested,
    event_topic,
)
from shared.models import MintEvent, TransferEvent

TOKEN = "0x" + "11" * 20
MINTER = "0x" + "22" * 20
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b0" * 20
ATTACKER = "0x" + "ee" * 20
ZERO = "0x" + "00" * 20
WAD = 10**18
FIXED_NOW = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)


def _addr_topic(address: str) -> str:
    return "0x" + "00" * 12 + address[2:].lower()


def _uint_topic(value: int) -> str:
    return "0x" + f"{value:064x}"


def _data(*words: int) -> str:
    return "0x" + "".join(f"{w:064x}" for w in words)


def _tx(n: int) -> str:
    return "0x" + f"{n:064x}"


def _log(address: str, topics: list[str], data: str, block: int, index: int, tx: int) -> dict[str, Any]:
    return {
        "address": address,
        "topics": topics,
        "data": data,
        "blockNumber": block,
        "logIndex": index,
        "transactionHash": _tx(tx),
    }


def swap_requested(request_id: int, depositor: str, deposit: int, rate: int, *, block: int, index: int, tx: int) -> dict[str, Any]:
    return _log(
        MINTER,
        [SWAP_REQUESTED_TOPIC, _uint_topic(request_id), _addr_topic(depositor)],
        _data(deposit, rate),
        block,
        index,
        tx,
    )


def swap_completed(request_id: int, depositor: str, recipient: str, deposit: int, minted: int, rate: int, *, block: int, index: int, tx: int) -> dict[str, Any]:
    return _log(
        MINTER,
        [
            SWAP_COMPLETED_TOPIC,
            _uint_topic(request_id),
            _addr_topic(depositor),
            _addr_topic(recipient),
        ],
        _data(deposit, minted, rate),
        block,
        index,
        tx,
    )


def transfer(sender: str, recipient: str, amount: int, *, block: int, index: int, tx: int) -> dict[str, Any]:
    return _log(
        TOKEN,
        [ERC20_TRANSFER_TOPIC, _addr_topic(sender), _addr_topic(recipient)],
        _data(amount),
        block,
        index,
        tx,
    )


def role_granted(role: str, account: str, sender: str, *, block: int, index: int, tx: int) -> dict[str, Any]:
    return _log(
        MINTER,
        [ROLE_GRANTED_TOPIC, role, _addr_topic(account), _addr_topic(sender)],
        "0x",
        block,
        index,
        tx,
    )


class FakeEth:
    """Faux noeud : filtre plage, adresse et topic0 (chaine OU liste = OU)."""

    def __init__(self, logs: list[dict[str, Any]], head: int) -> None:
        self._logs = logs
        self._head = head
        self.calls: list[dict[str, Any]] = []

    @property
    def block_number(self) -> int:
        return self._head

    def get_logs(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append(params)
        wanted = params["topics"][0]
        wanted_set = set(wanted) if isinstance(wanted, list) else {wanted}
        return [
            log
            for log in self._logs
            if params["fromBlock"] <= log["blockNumber"] <= params["toBlock"]
            and log["address"].lower() == params["address"].lower()
            and log["topics"][0] in wanted_set
        ]

    def call(self, transaction: Any) -> Any:  # pragma: no cover - non utilise
        raise NotImplementedError


class FakeWeb3:
    def __init__(self, eth: FakeEth) -> None:
        self.eth = eth


def _listener(logs: list[dict[str, Any]], head: int = 100) -> tuple[ChainListener, FakeEth]:
    eth = FakeEth(logs, head)
    config = MonitorConfig(
        rpc_url=None, token_address=TOKEN, minter_address=MINTER, start_block=0
    )
    return ChainListener(config, FakeWeb3(eth), sleep=lambda _: None, now=lambda: FIXED_NOW), eth


# ------------------------------------------------------------------ decodage


def test_topics_sont_les_keccak_des_signatures() -> None:
    # Valeur de reference independante : topic0 standard ERC-20 Transfer.
    assert event_topic("Transfer(address,address,uint256)") == ERC20_TRANSFER_TOPIC
    assert KNOWN_ROLES["0x" + "00" * 32] == "DEFAULT_ADMIN_ROLE"


def test_topics_identiques_a_forge_inspect() -> None:
    """Valeurs relevees par `forge inspect ProtectedMinter events` (2026-10-11)."""
    assert SWAP_REQUESTED_TOPIC == (
        "0xbd1df758eb86d1fe43a7f5cfb29ebce34349bc8304150245649a10f5d2e00d69"
    )
    assert SWAP_COMPLETED_TOPIC == (
        "0x48838e6505edee8816fa772af7d9b8922e68efb7381e26f7b102a022f27220ef"
    )
    assert ROLE_GRANTED_TOPIC == (
        "0x2f8788117e7eff1d82e926ec794901d17c78024a50270940304540a733656f0d"
    )
    assert RATE_CHANGED_TOPIC == (
        "0xbf9a176966f913f4d8562a8d2fc7c771039e6a1257c5793f8bb9081e2a29f32b"
    )


def test_decode_swap_requested_et_completed() -> None:
    req = decode_swap_requested(swap_requested(7, ALICE, 1_000_000, WAD, block=1, index=0, tx=1))
    assert (req.request_id, req.depositor.lower(), req.deposit_amount, req.rate_wad) == (
        7, ALICE, 1_000_000, WAD,
    )
    done = decode_swap_completed(
        swap_completed(7, ALICE, ALICE, 1_000_000, 10**18, WAD, block=2, index=1, tx=2)
    )
    assert done.minted_amount == 10**18
    assert done.recipient.lower() == ALICE


def test_decode_admin_role_et_taux() -> None:
    service = event_topic("SERVICE_ROLE")
    obs = decode_admin(role_granted(service, ATTACKER, BOB, block=3, index=0, tx=3))
    assert obs.kind == "role_granted"
    assert obs.subject_address.lower() == ATTACKER
    assert "SERVICE_ROLE" in obs.detail
    rate = decode_admin(
        _log(MINTER, [RATE_CHANGED_TOPIC, _addr_topic(BOB)], _data(WAD, 2 * WAD), 4, 0, 4)
    )
    assert rate.kind == "rate_changed"
    assert "->" in rate.detail


def test_decode_rejette_un_log_mal_forme() -> None:
    bad = swap_requested(1, ALICE, 1, WAD, block=1, index=0, tx=1)
    bad["data"] = "0x" + "00" * 32  # un seul mot au lieu de deux
    with pytest.raises(ValueError):
        decode_swap_requested(bad)


# -------------------------------------------------------------- correlation


def test_mint_rattache_a_sa_demande_avec_le_depot_de_swaprequested() -> None:
    logs = [
        swap_requested(0, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        transfer(ZERO, ALICE, 10**18, block=11, index=0, tx=2),
        swap_completed(0, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
        transfer(ALICE, BOB, 5, block=12, index=0, tx=3),
    ]
    listener, eth = _listener(logs)
    events = listener.fetch_events(0, 100)

    # 2 appels getLogs : minter (topics en OU) + token.
    assert len(eth.calls) == 2
    mints = [e for e in events if isinstance(e, MintEvent)]
    transfers = [e for e in events if isinstance(e, TransferEvent)]
    assert len(mints) == 1 and len(transfers) == 1
    assert mints[0].request_id == 0  # la demande n°0 n'est plus confondue avec "inconnu"
    assert listener.correlator is not None
    prov = listener.correlator.provenance_for(mints[0].tx_hash, mints[0].log_index)
    assert prov is not None
    assert prov.source == "request"
    assert prov.deposit_amount == 1_000_000
    assert prov.depositor.lower() == ALICE
    assert listener.correlator.pending_count == 0


def test_depot_lu_dans_swaprequested_meme_si_swapcompleted_ment() -> None:
    """Le contrat annonce un faux depot : la provenance garde le depot enregistre."""
    logs = [
        swap_requested(3, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        transfer(ZERO, ATTACKER, 400 * 10**18, block=11, index=0, tx=2),
        swap_completed(3, ALICE, ATTACKER, 400_000_000, 400 * 10**18, WAD, block=11, index=1, tx=2),
    ]
    listener, _ = _listener(logs)
    (mint,) = [e for e in listener.fetch_events(0, 100) if isinstance(e, MintEvent)]
    assert listener.correlator is not None
    prov = listener.correlator.provenance_for(mint.tx_hash, mint.log_index)
    assert prov is not None
    assert prov.deposit_amount == 1_000_000
    assert prov.depositor.lower() == ALICE
    assert prov.claimed_minted == 400 * 10**18


def test_mint_sans_swapcompleted_est_trace_sans_provenance() -> None:
    logs = [transfer(ZERO, ATTACKER, 10**24, block=11, index=0, tx=9)]
    listener, _ = _listener(logs)
    (mint,) = listener.fetch_events(0, 100)
    assert isinstance(mint, MintEvent)
    assert mint.request_id is None
    assert listener.correlator is not None
    assert listener.correlator.is_tracked(mint.tx_hash, mint.log_index)
    assert listener.correlator.provenance_for(mint.tx_hash, mint.log_index) is None


def test_demande_anterieure_a_l_ecoute_retombe_sur_swapcompleted() -> None:
    logs = [
        transfer(ZERO, ALICE, 10**18, block=11, index=0, tx=2),
        swap_completed(5, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
    ]
    listener, _ = _listener(logs)
    (mint,) = listener.fetch_events(0, 100)
    assert listener.correlator is not None
    prov = listener.correlator.provenance_for(mint.tx_hash, mint.log_index)  # type: ignore[union-attr]
    assert prov is not None and prov.source == "completion"


def test_deux_traitements_dans_une_transaction_apparies_par_montant() -> None:
    logs = [
        swap_requested(1, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        swap_requested(2, BOB, 2_000_000, WAD, block=10, index=1, tx=1),
        transfer(ZERO, BOB, 2 * 10**18, block=11, index=0, tx=2),
        transfer(ZERO, ALICE, 10**18, block=11, index=2, tx=2),
        swap_completed(1, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
        swap_completed(2, BOB, BOB, 2_000_000, 2 * 10**18, WAD, block=11, index=3, tx=2),
    ]
    listener, _ = _listener(logs)
    mints = {e.recipient.lower(): e for e in listener.fetch_events(0, 100) if isinstance(e, MintEvent)}
    assert mints[ALICE].request_id == 1
    assert mints[BOB].request_id == 2


def test_evenement_admin_emis_dans_le_flux() -> None:
    logs = [role_granted(event_topic("SERVICE_ROLE"), ATTACKER, BOB, block=5, index=0, tx=1)]
    listener, _ = _listener(logs)
    (obs,) = listener.fetch_events(0, 100)
    assert isinstance(obs, AdminObservation)
    assert obs.subject_address.lower() == ATTACKER


def test_relecture_idempotente_d_une_demande() -> None:
    correlator = MintCorrelator()
    req = decode_swap_requested(swap_requested(1, ALICE, 1, WAD, block=1, index=0, tx=1))
    correlator.observe_request(req)
    correlator.observe_request(req)  # plage retentee apres erreur RPC
    assert correlator.pending_count == 1


def test_sans_minter_le_mode_generique_est_inchange() -> None:
    eth = FakeEth([transfer(ZERO, ALICE, 1, block=1, index=0, tx=1)], 10)
    config = MonitorConfig(rpc_url=None, token_address=TOKEN, start_block=0)
    listener = ChainListener(config, FakeWeb3(eth), sleep=lambda _: None, now=lambda: FIXED_NOW)
    assert listener.correlator is None
    (mint,) = listener.fetch_events(0, 10)
    assert isinstance(mint, MintEvent) and mint.request_id is None
