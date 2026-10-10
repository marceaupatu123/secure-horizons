"""Tests de la configuration du monitor et du point d'entree `python -m monitor`."""

from __future__ import annotations

import pytest
from web3 import Web3

from monitor import __main__ as monitor_main
from monitor.config import (
    DEFAULT_BLOCK_BATCH_SIZE,
    DEFAULT_CONFIRMATIONS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TOKEN_IS_GHOST,
    FUJI_CHAIN_ID,
    MonitorConfig,
    load_monitor_config,
)
from shared.config import Settings

TOKEN = "0x" + "ab" * 20


def test_defaults_without_env() -> None:
    config = load_monitor_config(env={})
    assert config == MonitorConfig(rpc_url=None, token_address=None)
    assert config.chain_id == FUJI_CHAIN_ID == 43113
    assert config.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS
    assert config.block_batch_size == DEFAULT_BLOCK_BATCH_SIZE
    assert config.confirmations == DEFAULT_CONFIRMATIONS
    assert config.start_block is None
    assert config.token_is_ghost is DEFAULT_TOKEN_IS_GHOST is False


def test_reads_env_overrides_and_checksums_token() -> None:
    config = load_monitor_config(
        env={
            "FUJI_RPC_URL": "http://rpc.test",
            "MONITOR_TOKEN_ADDRESS": TOKEN,
            "MONITOR_POLL_INTERVAL_SECONDS": "0.5",
            "MONITOR_BLOCK_BATCH_SIZE": "10",
            "MONITOR_CONFIRMATIONS": "1",
            "MONITOR_START_BLOCK": "123",
            "MONITOR_TOKEN_IS_GHOST": "true",
        }
    )
    assert config.rpc_url == "http://rpc.test"
    assert config.token_address == Web3.to_checksum_address(TOKEN)
    assert (config.poll_interval_seconds, config.block_batch_size) == (0.5, 10)
    assert (config.confirmations, config.start_block) == (1, 123)
    assert config.token_is_ghost is True


def test_rpc_url_comes_from_shared_settings_when_given() -> None:
    settings = Settings(
        aws_region="r", bedrock_model_id="m", fuji_rpc_url="http://shared.test",
        guardian_private_key="FLAG{team20-canary}",
    )
    config = load_monitor_config(settings, env={"FUJI_RPC_URL": "http://ignored"})
    assert config.rpc_url == "http://shared.test"


@pytest.mark.parametrize(
    "env",
    [
        {"MONITOR_TOKEN_ADDRESS": "0x1234"},
        {"MONITOR_BLOCK_BATCH_SIZE": "abc"},
        {"MONITOR_BLOCK_BATCH_SIZE": "0"},
        {"MONITOR_POLL_INTERVAL_SECONDS": "0"},
        {"MONITOR_CONFIRMATIONS": "-1"},
        {"MONITOR_START_BLOCK": "-5"},
        {"MONITOR_TOKEN_IS_GHOST": "maybe"},
    ],
)
def test_invalid_values_are_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        load_monitor_config(env=env)


def test_main_without_token_prints_hint_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MONITOR_TOKEN_ADDRESS", raising=False)
    monitor_main.main()
    assert "MONITOR_TOKEN_ADDRESS" in capsys.readouterr().out
