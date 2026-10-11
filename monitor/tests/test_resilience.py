"""Reprise sur erreur RPC et checkpoint du dernier bloc lu (issue #74)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from monitor.checkpoint import BlockCheckpoint
from monitor.config import MonitorConfig, load_monitor_config
from monitor.listener import ChainListener, MonitorConfigurationError
from monitor.tests.test_listener import (
    ALICE,
    FIXED_NOW,
    TOKEN,
    FakeEth,
    FakeWeb3,
    _mint_log,
)


class FlakyEth(FakeEth):
    """FakeEth dont les N premiers appels a `block_number` / `get_logs` echouent."""

    def __init__(
        self,
        logs: list[dict[str, Any]],
        heads: list[int],
        *,
        head_failures: int = 0,
        logs_failures: int = 0,
    ) -> None:
        super().__init__(logs, heads)
        self.head_failures = head_failures
        self.logs_failures = logs_failures

    @property
    def block_number(self) -> int:
        if self.head_failures:
            self.head_failures -= 1
            raise ConnectionError("RPC injoignable")
        return FakeEth.block_number.fget(self)  # type: ignore[attr-defined]

    def get_logs(self, filter_params: dict[str, Any]) -> list[dict[str, Any]]:
        if self.logs_failures:
            self.logs_failures -= 1
            raise TimeoutError("eth_getLogs timeout")
        return super().get_logs(filter_params)


def _make(
    eth: FakeEth, **config_kw: Any
) -> tuple[ChainListener, list[float]]:
    sleeps: list[float] = []
    config = MonitorConfig(rpc_url=None, token_address=TOKEN, **config_kw)
    return (
        ChainListener(config, FakeWeb3(eth), sleep=sleeps.append, now=lambda: FIXED_NOW),
        sleeps,
    )


# --- Reprise sur erreur RPC ---


def test_head_error_is_retried_with_exponential_backoff() -> None:
    eth = FlakyEth([_mint_log(ALICE, 5, block=10)], [10], head_failures=3)
    listener, sleeps = _make(
        eth, start_block=10, rpc_retry_base_seconds=1.0, rpc_retry_max_seconds=3.0
    )
    events = list(listener.stream_mint_events(max_polls=1))
    assert [e.amount for e in events] == [5]
    # 1, 2, puis plafonne a 3.
    assert sleeps == [1.0, 2.0, 3.0]


def test_get_logs_error_resumes_without_gap_or_duplicate() -> None:
    logs = [_mint_log(ALICE, n, block=n, tx_byte=f"{n:02x}") for n in range(1, 7)]
    eth = FlakyEth(logs, [6], logs_failures=2)
    listener, _ = _make(eth, start_block=1, block_batch_size=2)
    events = list(listener.stream_mint_events(max_polls=1))
    assert [e.block_number for e in events] == [1, 2, 3, 4, 5, 6]


def test_failure_mid_poll_does_not_reread_already_yielded_ranges() -> None:
    logs = [_mint_log(ALICE, n, block=n, tx_byte=f"{n:02x}") for n in range(1, 5)]
    eth = FlakyEth(logs, [4])
    listener, _ = _make(eth, start_block=1, block_batch_size=2)
    stream = listener.stream_mint_events(max_polls=1)
    first = [next(stream), next(stream)]
    eth.logs_failures = 1  # la plage 3-4 echoue une fois
    rest = list(stream)
    assert [e.block_number for e in first + rest] == [1, 2, 3, 4]


def test_persistent_failure_escalates_to_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    eth = FlakyEth([], [10], head_failures=3)
    listener, _ = _make(eth, start_block=10, rpc_failure_alert_after=3)
    with caplog.at_level(logging.WARNING, logger="monitor.listener"):
        list(listener.stream_mint_events(max_polls=1))
    failures = [r for r in caplog.records if "echec" in r.getMessage()]
    assert [r.levelno for r in failures] == [logging.WARNING, logging.WARNING, logging.ERROR]
    assert "SURVEILLANCE AVEUGLE" in failures[-1].getMessage()


def test_missing_rpc_url_is_not_retried() -> None:
    config = MonitorConfig(rpc_url=None, token_address=TOKEN)
    listener = ChainListener(config, sleep=lambda _s: pytest.fail("retry inattendu"))
    with pytest.raises(MonitorConfigurationError):
        list(listener.stream_mint_events(max_polls=1))


def test_malformed_log_is_skipped_not_fatal() -> None:
    bad = _mint_log(ALICE, 7, block=3)
    del bad["transactionHash"]
    good = _mint_log(ALICE, 9, block=4, tx_byte="cd")
    eth = FakeEth([bad, good], [4])
    listener, _ = _make(eth, start_block=3)
    assert [e.amount for e in listener.stream_mint_events(max_polls=1)] == [9]


# --- Checkpoint ---


def test_checkpoint_roundtrip_and_absent(tmp_path: Path) -> None:
    cp = BlockCheckpoint(tmp_path / "sub" / "cp.json")
    assert cp.load() is None
    cp.save(42)
    assert cp.load() == 42
    assert not list((tmp_path / "sub").glob("*.tmp"))


def test_corrupt_checkpoint_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    path.write_text("{pas du json", encoding="utf-8")
    assert BlockCheckpoint(path).load() is None
    path.write_text('{"last_block": -3}', encoding="utf-8")
    assert BlockCheckpoint(path).load() is None


def test_checkpoint_written_after_each_consumed_range(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    eth = FakeEth([], [5])
    listener, _ = _make(
        eth, start_block=0, block_batch_size=3, checkpoint_path=str(path)
    )
    stream = listener.stream_event_batches(max_polls=1)
    next(stream)  # plage 0-2 rendue, pas encore « consommee »
    assert BlockCheckpoint(path).load() is None
    next(stream)  # le consommateur redemande : 0-2 traitee
    assert BlockCheckpoint(path).load() == 2
    list(stream)
    assert BlockCheckpoint(path).load() == 5


def test_restart_resumes_after_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    BlockCheckpoint(path).save(4)
    logs = [_mint_log(ALICE, n, block=n, tx_byte=f"{n:02x}") for n in range(1, 8)]
    eth = FakeEth(logs, [7])
    # start_block=None = « tete de chaine » : le checkpoint doit primer.
    listener, _ = _make(eth, checkpoint_path=str(path))
    events = list(listener.stream_mint_events(max_polls=1))
    assert [e.block_number for e in events] == [5, 6, 7]


def test_load_config_reads_resilience_env() -> None:
    config = load_monitor_config(
        env={
            "MONITOR_RPC_RETRY_BASE_SECONDS": "0.5",
            "MONITOR_RPC_RETRY_MAX_SECONDS": "8",
            "MONITOR_RPC_FAILURE_ALERT_AFTER": "2",
            "MONITOR_CHECKPOINT_PATH": "state/monitor.json",
        }
    )
    assert config.rpc_retry_base_seconds == 0.5
    assert config.rpc_retry_max_seconds == 8.0
    assert config.rpc_failure_alert_after == 2
    assert config.checkpoint_path == "state/monitor.json"
    assert load_monitor_config(env={}).checkpoint_path is None


def test_invalid_retry_config_rejected() -> None:
    with pytest.raises(ValueError):
        MonitorConfig(rpc_url=None, token_address=None, rpc_retry_base_seconds=0)
    with pytest.raises(ValueError):
        MonitorConfig(
            rpc_url=None,
            token_address=None,
            rpc_retry_base_seconds=5,
            rpc_retry_max_seconds=1,
        )
