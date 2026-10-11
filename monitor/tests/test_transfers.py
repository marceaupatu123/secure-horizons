"""Tests de l'ecoute des transferts ERC-20 (issue #10) avec un faux web3."""

from __future__ import annotations

import pytest
from web3 import Web3

from monitor.config import MonitorConfig
from monitor.listener import (
    ERC20_TRANSFER_TOPIC,
    ChainListener,
    DecodedTransfer,
    decode_erc20_transfer,
    to_hex,
)
from monitor.tests.test_listener import (
    ALICE,
    BOB,
    FIXED_NOW,
    TOKEN,
    FakeEth,
    FakeWeb3,
    _listener,
    _mint_log,
    _transfer_log,
)
from shared.models import TransferEvent

ZERO = "0x" + "00" * 20


# --- Decodage ---


def test_decode_transfer_extracts_sender_recipient_amount() -> None:
    log = _transfer_log(sender=ALICE, recipient=BOB, amount=5_000 * 10**18, block=1)
    assert decode_erc20_transfer(log) == DecodedTransfer(
        sender=Web3.to_checksum_address(ALICE),
        recipient=Web3.to_checksum_address(BOB),
        amount=5_000 * 10**18,
    )


def test_decode_transfer_accepts_json_rpc_hex_strings() -> None:
    log = _transfer_log(sender=ALICE, recipient=BOB, amount=7, block=1)
    log["topics"] = [to_hex(t) for t in log["topics"]]
    log["data"] = to_hex(log["data"])
    decoded = decode_erc20_transfer(log)
    assert decoded is not None and decoded.amount == 7


def test_decode_transfer_excludes_mint_and_burn() -> None:
    assert decode_erc20_transfer(_mint_log(ALICE, 10, block=1)) is None
    burn = _transfer_log(sender=ALICE, recipient=ZERO, amount=10, block=1)
    assert decode_erc20_transfer(burn) is None


def test_decode_transfer_ignores_zero_amount_erc721_and_other_topic0() -> None:
    assert decode_erc20_transfer(
        _transfer_log(sender=ALICE, recipient=BOB, amount=0, block=1)
    ) is None
    erc721 = _transfer_log(sender=ALICE, recipient=BOB, amount=1, block=1)
    erc721["topics"] = [*erc721["topics"], bytes(32)]
    erc721["data"] = b""
    assert decode_erc20_transfer(erc721) is None
    other = _transfer_log(sender=ALICE, recipient=BOB, amount=1, block=1)
    other["topics"][0] = bytes(32)
    assert decode_erc20_transfer(other) is None


# --- Conversion + filtrage ---


def test_fetch_converts_only_ordinary_transfers() -> None:
    logs = [
        _mint_log(ALICE, 100, block=10, log_index=0),
        _transfer_log(
            sender=ALICE, recipient=BOB, amount=50, block=10, log_index=1, tx_byte="01"
        ),
        _transfer_log(sender=BOB, recipient=ZERO, amount=5, block=10, log_index=2),
        _transfer_log(sender=BOB, recipient=ALICE, amount=20, block=11, log_index=0),
    ]
    listener, eth, _ = _listener(logs, heads=[20])

    events = listener.fetch_transfer_events(10, 11)

    assert [e.amount for e in events] == [50, 20]
    first = events[0]
    assert isinstance(first, TransferEvent)
    # exclude_none : `token_address` (optionnel, ajoute par #79) reste None ici.
    assert first.model_dump(exclude_none=True) == {
        "tx_hash": "0x" + "01" * 32,
        "log_index": 1,
        "block_number": 10,
        "chain_id": 43113,
        "observed_at": FIXED_NOW,
        "sender": Web3.to_checksum_address(ALICE),
        "recipient": Web3.to_checksum_address(BOB),
        "amount": 50,
        "is_ghost": False,
    }
    # Filtre RPC : contrat configure, topic0 Transfer seul (pas de topic1).
    assert eth.calls[0]["address"] == Web3.to_checksum_address(TOKEN)
    assert eth.calls[0]["topics"] == [ERC20_TRANSFER_TOPIC]


def test_is_ghost_comes_from_config() -> None:
    logs = [_transfer_log(sender=ALICE, recipient=BOB, amount=1, block=1)]
    listener, _, _ = _listener(logs, heads=[5], token_is_ghost=True)
    [event] = listener.fetch_transfer_events(0, 5)
    assert event.is_ghost is True


def test_fetch_transfers_skips_removed_sorts_and_chunks() -> None:
    removed = _transfer_log(sender=ALICE, recipient=BOB, amount=1, block=3)
    removed["removed"] = True
    logs = [
        _transfer_log(sender=BOB, recipient=ALICE, amount=3, block=6, log_index=0),
        removed,
        _transfer_log(sender=ALICE, recipient=BOB, amount=2, block=3, log_index=4),
    ]
    listener, eth, _ = _listener(logs, heads=[20], block_batch_size=3)

    assert [e.amount for e in listener.fetch_transfer_events(0, 7)] == [2, 3]
    assert [(c["fromBlock"], c["toBlock"]) for c in eth.calls] == [(0, 2), (3, 5), (6, 7)]


def test_missing_token_address_raises_for_transfers() -> None:
    listener = ChainListener(
        MonitorConfig(rpc_url=None, token_address=None), FakeWeb3(FakeEth([], [0]))
    )
    with pytest.raises(RuntimeError, match="MONITOR_TOKEN_ADDRESS"):
        listener.fetch_transfer_events(0, 1)
    with pytest.raises(RuntimeError, match="MONITOR_TOKEN_ADDRESS"):
        next(listener.stream_transfer_events(max_polls=1))


# --- Polling (meme boucle que les mints) ---


def test_stream_transfers_polls_new_block_ranges_only() -> None:
    logs = [
        _transfer_log(sender=ALICE, recipient=BOB, amount=1, block=5),
        _mint_log(ALICE, 99, block=6),
        _transfer_log(sender=BOB, recipient=ALICE, amount=2, block=7),
        _transfer_log(sender=ALICE, recipient=BOB, amount=3, block=9),
    ]
    listener, eth, sleeps = _listener(logs, heads=[7, 7, 9], start_block=5)

    events = list(listener.stream_transfer_events(max_polls=3))

    assert [e.amount for e in events] == [1, 2, 3]
    assert [(c["fromBlock"], c["toBlock"]) for c in eth.calls] == [(5, 7), (8, 9)]
    assert sleeps == [2.0, 2.0]


def test_stream_transfers_defaults_to_head_and_respects_confirmations() -> None:
    logs = [
        _transfer_log(sender=ALICE, recipient=BOB, amount=1, block=8),
        _transfer_log(sender=BOB, recipient=ALICE, amount=2, block=10),
    ]
    listener, eth, _ = _listener(logs, heads=[12], confirmations=2)

    events = list(listener.stream_transfer_events(max_polls=1))

    assert [e.amount for e in events] == [2]
    assert [(c["fromBlock"], c["toBlock"]) for c in eth.calls] == [(10, 10)]
