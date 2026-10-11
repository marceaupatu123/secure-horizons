"""Tests de l'ecouteur de mints ERC-20 avec un faux web3 (aucun appel reseau)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from web3 import Web3

from monitor.config import MonitorConfig
from monitor.listener import (
    ERC20_MINT_DECODER,
    ERC20_TRANSFER_TOPIC,
    UNKNOWN_REQUEST_ID,
    ZERO_ADDRESS_TOPIC,
    ChainListener,
    DecodedMint,
    MintLogDecoder,
    block_ranges,
    decode_erc20_mint,
    to_hex,
)
from shared.models import MintEvent

TOKEN = "0x" + "aa" * 20
ALICE = "0x" + "11" * 20
BOB = "0x" + "22" * 20
FIXED_NOW = datetime(2026, 10, 10, 14, 30, tzinfo=timezone.utc)


def _topic(address: str) -> str:
    return "0x" + "00" * 12 + address[2:].lower()


def _transfer_log(
    *,
    sender: str,
    recipient: str,
    amount: int,
    block: int,
    log_index: int = 0,
    tx_byte: str = "ab",
) -> dict[str, Any]:
    """Log `Transfer` au format web3 (topics/data en bytes, comme HexBytes)."""
    return {
        "address": Web3.to_checksum_address(TOKEN),
        "topics": [
            bytes.fromhex(ERC20_TRANSFER_TOPIC[2:]),
            bytes.fromhex(_topic(sender)[2:]),
            bytes.fromhex(_topic(recipient)[2:]),
        ],
        "data": amount.to_bytes(32, "big"),
        "blockNumber": block,
        "logIndex": log_index,
        "transactionHash": bytes.fromhex(tx_byte * 32),
        "removed": False,
    }


def _mint_log(recipient: str, amount: int, block: int, **kw: Any) -> dict[str, Any]:
    return _transfer_log(sender="0x" + "00" * 20, recipient=recipient, amount=amount, block=block, **kw)


class FakeEth:
    """Faux `web3.eth` : tete de chaine scriptable + logs en memoire.

    `get_logs` applique le filtre de plage de blocs, d'adresse et de topic0
    comme un vrai noeud, mais PAS le filtre topic1 : cela permet de verifier
    que l'ecouteur refiltre lui-meme les mints (from == 0x0).
    """

    def __init__(self, logs: list[dict[str, Any]], heads: list[int]) -> None:
        self._logs = logs
        self._heads = list(heads)
        self.calls: list[dict[str, Any]] = []

    @property
    def block_number(self) -> int:
        if len(self._heads) > 1:
            return self._heads.pop(0)
        return self._heads[0]

    def get_logs(self, filter_params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append(filter_params)
        return [
            log
            for log in self._logs
            if filter_params["fromBlock"] <= log["blockNumber"] <= filter_params["toBlock"]
            and log["address"].lower() == filter_params["address"].lower()
            and to_hex(log["topics"][0]) == filter_params["topics"][0]
        ]


class FakeWeb3:
    def __init__(self, eth: FakeEth) -> None:
        self.eth = eth


def _listener(
    logs: list[dict[str, Any]],
    heads: list[int],
    **config_kw: Any,
) -> tuple[ChainListener, FakeEth, list[float]]:
    eth = FakeEth(logs, heads)
    sleeps: list[float] = []
    config = MonitorConfig(rpc_url=None, token_address=TOKEN, **config_kw)
    listener = ChainListener(
        config, FakeWeb3(eth), sleep=sleeps.append, now=lambda: FIXED_NOW
    )
    return listener, eth, sleeps


# --- Decodage ---


def test_transfer_topic_is_keccak_of_signature() -> None:
    expected = Web3.keccak(text="Transfer(address,address,uint256)")
    assert ERC20_TRANSFER_TOPIC == to_hex(expected)


def test_decode_erc20_mint_extracts_recipient_and_amount() -> None:
    decoded = decode_erc20_mint(_mint_log(ALICE, 5_000 * 10**18, block=1))
    assert decoded == DecodedMint(
        recipient=Web3.to_checksum_address(ALICE),
        amount=5_000 * 10**18,
        request_id=UNKNOWN_REQUEST_ID,
    )


def test_decode_accepts_json_rpc_hex_strings() -> None:
    log = _mint_log(ALICE, 7, block=1)
    log["topics"] = [to_hex(t) for t in log["topics"]]
    log["data"] = to_hex(log["data"])
    decoded = decode_erc20_mint(log)
    assert decoded is not None and decoded.amount == 7


def test_decode_ignores_ordinary_transfer() -> None:
    log = _transfer_log(sender=BOB, recipient=ALICE, amount=10, block=1)
    assert decode_erc20_mint(log) is None


def test_decode_ignores_zero_amount_and_erc721_shape() -> None:
    assert decode_erc20_mint(_mint_log(ALICE, 0, block=1)) is None
    erc721 = _mint_log(ALICE, 1, block=1)
    erc721["topics"] = [*erc721["topics"], bytes(32)]
    erc721["data"] = b""
    assert decode_erc20_mint(erc721) is None


def test_decode_ignores_other_topic0() -> None:
    log = _mint_log(ALICE, 1, block=1)
    log["topics"][0] = bytes(32)
    assert decode_erc20_mint(log) is None


# --- Plages de blocs ---


def test_block_ranges_split_inclusive() -> None:
    assert list(block_ranges(10, 14, 2)) == [(10, 11), (12, 13), (14, 14)]
    assert list(block_ranges(5, 5, 100)) == [(5, 5)]
    assert list(block_ranges(6, 5, 100)) == []


# --- Conversion + filtrage ---


def test_fetch_converts_only_mints_to_mint_event() -> None:
    logs = [
        _mint_log(ALICE, 100, block=10, log_index=1, tx_byte="01"),
        _transfer_log(sender=ALICE, recipient=BOB, amount=50, block=10, log_index=2),
        _mint_log(BOB, 200, block=11, log_index=0, tx_byte="02"),
    ]
    listener, eth, _ = _listener(logs, heads=[20])

    events = listener.fetch_mint_events(10, 11)

    assert [e.amount for e in events] == [100, 200]
    first = events[0]
    assert isinstance(first, MintEvent)
    # exclude_none : les champs optionnels ajoutes par #79 (depot, taux...) restent None ici.
    assert first.model_dump(exclude_none=True) == {
        "tx_hash": "0x" + "01" * 32,
        "log_index": 1,
        "block_number": 10,
        "chain_id": 43113,
        "observed_at": FIXED_NOW,
        "recipient": Web3.to_checksum_address(ALICE),
        "amount": 100,
        "request_id": UNKNOWN_REQUEST_ID,
    }
    # Filtre RPC : contrat configure, topic0 Transfer, topic1 = from 0x0.
    assert eth.calls[0]["address"] == Web3.to_checksum_address(TOKEN)
    assert eth.calls[0]["topics"] == [ERC20_TRANSFER_TOPIC, ZERO_ADDRESS_TOPIC]


def test_fetch_skips_removed_logs_and_sorts_by_chain_order() -> None:
    removed = _mint_log(ALICE, 1, block=10, log_index=0)
    removed["removed"] = True
    logs = [
        _mint_log(BOB, 3, block=12, log_index=0),
        removed,
        _mint_log(ALICE, 2, block=10, log_index=5),
    ]
    listener, _, _ = _listener(logs, heads=[20])
    assert [e.amount for e in listener.fetch_mint_events(10, 12)] == [2, 3]


def test_fetch_chunks_by_block_batch_size() -> None:
    listener, eth, _ = _listener([], heads=[20], block_batch_size=3)
    listener.fetch_mint_events(0, 7)
    assert [(c["fromBlock"], c["toBlock"]) for c in eth.calls] == [(0, 2), (3, 5), (6, 7)]


def test_custom_decoder_can_replace_erc20() -> None:
    """Un evenement dedie futur (ex. Minted avec request_id) se branche seul."""
    minted_topic = "0x" + "cd" * 32
    decoder = MintLogDecoder(
        name="minted",
        topics=(minted_topic,),
        decode=lambda log: DecodedMint(recipient=ALICE, amount=9, request_id=42),
    )
    log = _mint_log(ALICE, 9, block=3)
    log["topics"] = [bytes.fromhex(minted_topic[2:])]
    eth = FakeEth([log], heads=[5])
    listener = ChainListener(
        MonitorConfig(rpc_url=None, token_address=TOKEN),
        FakeWeb3(eth),
        mint_decoders=(decoder,),
        now=lambda: FIXED_NOW,
    )
    [event] = listener.fetch_mint_events(0, 5)
    assert event.request_id == 42


def test_missing_token_address_raises() -> None:
    listener = ChainListener(MonitorConfig(rpc_url=None, token_address=None), FakeWeb3(FakeEth([], [0])))
    with pytest.raises(RuntimeError, match="MONITOR_TOKEN_ADDRESS"):
        listener.fetch_mint_events(0, 1)
    with pytest.raises(RuntimeError, match="MONITOR_TOKEN_ADDRESS"):
        next(listener.stream_mint_events(max_polls=1))


# --- Polling ---


def test_stream_polls_new_block_ranges_only() -> None:
    logs = [
        _mint_log(ALICE, 1, block=5),
        _mint_log(ALICE, 2, block=7),
        _mint_log(BOB, 3, block=9),
    ]
    # Tete : 7, puis 7 (rien de neuf), puis 9.
    listener, eth, sleeps = _listener(logs, heads=[7, 7, 9], start_block=5)

    events = list(listener.stream_mint_events(max_polls=3))

    assert [e.amount for e in events] == [1, 2, 3]
    assert [(c["fromBlock"], c["toBlock"]) for c in eth.calls] == [(5, 7), (8, 9)]
    assert sleeps == [2.0, 2.0]


def test_stream_defaults_to_current_head_and_respects_confirmations() -> None:
    logs = [_mint_log(ALICE, 1, block=8), _mint_log(BOB, 2, block=10)]
    # start_block None : on part de la tete sure (12 - 2 = 10), pas de l'historique.
    listener, eth, _ = _listener(logs, heads=[12], confirmations=2)

    events = list(listener.stream_mint_events(max_polls=1))

    assert [e.amount for e in events] == [2]
    assert [(c["fromBlock"], c["toBlock"]) for c in eth.calls] == [(10, 10)]


def test_default_decoder_is_erc20() -> None:
    assert ERC20_MINT_DECODER.decode is decode_erc20_mint
