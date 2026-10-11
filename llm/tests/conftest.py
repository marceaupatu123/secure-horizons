"""Fixtures communes aux tests du module llm (donnees fictives, aucun reseau)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from shared.config import Settings
from shared.models import Alert, AlertKind, AlertSeed, AlertSeverity
from shared.rate_limiter import RateLimiter

ADDR_SUBJECT = "0x" + "11" * 20
ADDR_SEED = "0x" + "22" * 20
TX_HASH = "0x" + "ab" * 32


def converse_response(*blocks: dict[str, Any]) -> dict[str, Any]:
    """Construit une reponse au format Converse avec les blocs donnes."""
    return {
        "output": {"message": {"role": "assistant", "content": list(blocks)}},
        "stopReason": "end_turn",
    }


class RecordingRateLimiter(RateLimiter):
    """Limiteur sans attente qui trace chaque `wait()` dans `events`."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(min_interval_seconds=0)
        self.events = events

    def wait(self) -> None:
        self.events.append("wait")
        super().wait()


class FakeBedrockRuntime:
    """Faux client `bedrock-runtime` : enregistre les appels `converse`."""

    def __init__(
        self,
        events: list[str],
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.response = response if response is not None else converse_response({"text": "ok"})
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append("converse")
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        bedrock_model_id="test-model-id",
        fuji_rpc_url="http://localhost",
        guardian_private_key="test",
    )


@pytest.fixture
def events() -> list[str]:
    return []


@pytest.fixture
def limiter(events: list[str]) -> RecordingRateLimiter:
    return RecordingRateLimiter(events)


@pytest.fixture
def alert() -> Alert:
    return Alert(
        alert_id="ALERT-TEST-1",
        kind=AlertKind.MINT,
        severity=AlertSeverity.CRITICAL,
        created_at=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
        monitor_name="rule_mint",
        subject_address=ADDR_SUBJECT,
        source_tx_hash=TX_HASH,
        contamination_ratio=0.75,
        suspect_amount=123456789,
        dispersion_score=0.1,
        volume_zscore=8.5,
        reason="Mint sans dépôt correspondant (fictif)",
        seeds=[
            AlertSeed(address=ADDR_SUBJECT, suspect_amount=100000000, contamination_ratio=1.0),
            AlertSeed(address=ADDR_SEED, suspect_amount=23456789, contamination_ratio=0.5),
        ],
    )
