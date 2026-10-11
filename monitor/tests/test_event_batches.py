"""Tests du flux combine mints + transferts et de `totalSupply()` (issue #86)."""

from __future__ import annotations

from typing import Any

import pytest
from web3 import Web3

from monitor.config import MonitorConfig
from monitor.listener import TOTAL_SUPPLY_SELECTOR, ChainListener, to_hex
from monitor.tests.test_listener import (
    ALICE,
    BOB,
    FIXED_NOW,
    TOKEN,
    FakeEth,
    FakeWeb3,
    _mint_log,
    _transfer_log,
)
from shared.models import MintEvent, TransferEvent


class SupplyEth(FakeEth):
    """Faux `web3.eth` qui repond aussi a `eth_call` (totalSupply)."""

    def __init__(
        self, logs: list[dict[str, Any]], heads: list[int], supply_reply: Any
    ) -> None:
        super().__init__(logs, heads)
        self._supply_reply = supply_reply
        self.eth_calls: list[dict[str, Any]] = []

    def call(self, transaction: dict[str, Any]) -> Any:
        self.eth_calls.append(transaction)
        return self._supply_reply


def _listener(
    logs: list[dict[str, Any]], heads: list[int], supply_reply: Any = b"", **kw: Any
) -> tuple[ChainListener, SupplyEth, list[float]]:
    eth = SupplyEth(logs, heads, supply_reply)
    sleeps: list[float] = []
    listener = ChainListener(
        MonitorConfig(rpc_url=None, token_address=TOKEN, **kw),
        FakeWeb3(eth),
        sleep=sleeps.append,
        now=lambda: FIXED_NOW,
    )
    return listener, eth, sleeps


def test_fetch_events_merges_mints_and_transfers_in_chain_order() -> None:
    logs = [
        _transfer_log(sender=ALICE, recipient=BOB, amount=50, block=10, log_index=2),
        _mint_log(ALICE, 100, block=10, log_index=1),
        _transfer_log(sender=BOB, recipient="0x" + "00" * 20, amount=5, block=11),
    ]
    listener, _, _ = _listener(logs, heads=[20])

    events = listener.fetch_events(10, 11)

    # Chaque log une seule fois ; le burn reste exclu (PROVISOIRE, #10).
    assert [(type(e), e.amount) for e in events] == [
        (MintEvent, 100),
        (TransferEvent, 50),
    ]


def test_stream_event_batches_yields_empty_batch_when_nothing_new() -> None:
    logs = [
        _mint_log(ALICE, 1, block=5),
        _transfer_log(sender=ALICE, recipient=BOB, amount=2, block=6),
        _transfer_log(sender=BOB, recipient=ALICE, amount=3, block=9),
    ]
    # Tete : 7, puis 7 (rien de neuf), puis 9.
    listener, eth, sleeps = _listener(logs, heads=[7, 7, 9], start_block=5)

    batches = list(listener.stream_event_batches(max_polls=3))

    assert [[e.amount for e in batch] for batch in batches] == [[1, 2], [], [3]]
    assert sleeps == [2.0, 2.0]
    # Deux sources (mints, transferts) par plage lue.
    assert [(c["fromBlock"], c["toBlock"]) for c in eth.calls] == [
        (5, 7),
        (5, 7),
        (8, 9),
        (8, 9),
    ]


def test_stream_event_batches_requires_token_address() -> None:
    listener = ChainListener(
        MonitorConfig(rpc_url=None, token_address=None),
        FakeWeb3(SupplyEth([], [0], b"")),
    )
    with pytest.raises(RuntimeError, match="MONITOR_TOKEN_ADDRESS"):
        next(listener.stream_event_batches(max_polls=1))


def test_read_total_supply_decodes_uint256() -> None:
    supply = 123_456_789 * 10**6
    listener, eth, _ = _listener([], heads=[1], supply_reply=supply.to_bytes(32, "big"))

    assert listener.read_total_supply() == supply
    assert eth.eth_calls == [
        {"to": Web3.to_checksum_address(TOKEN), "data": TOTAL_SUPPLY_SELECTOR}
    ]


def test_total_supply_selector_is_keccak_prefix() -> None:
    assert TOTAL_SUPPLY_SELECTOR == to_hex(Web3.keccak(text="totalSupply()"))[:10]


def test_read_total_supply_rejects_malformed_reply() -> None:
    listener, _, _ = _listener([], heads=[1], supply_reply=b"\x01")
    with pytest.raises(ValueError, match="totalSupply"):
        listener.read_total_supply()
