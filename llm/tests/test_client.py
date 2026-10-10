"""Tests du client Bedrock Converse (boto3 jamais instancie, aucun reseau)."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from llm.client import DEFAULT_MAX_TOKENS, BedrockClient, LLMError
from llm.prompts import SYSTEM_PROMPT_EXPLAIN
from llm.tests.conftest import FakeBedrockRuntime, RecordingRateLimiter, converse_response
from shared.config import Settings
from shared.models import Alert


def _client(
    settings: Settings, limiter: RecordingRateLimiter, fake: FakeBedrockRuntime
) -> BedrockClient:
    return BedrockClient(settings, rate_limiter=limiter, client=fake)


def test_explain_request_shape(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], alert: Alert
) -> None:
    fake = FakeBedrockRuntime(events, converse_response({"text": "  Explication.  "}))
    result = _client(settings, limiter, fake).explain(alert)

    assert result == "Explication."
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["modelId"] == settings.bedrock_model_id
    assert call["system"] == [{"text": SYSTEM_PROMPT_EXPLAIN}]
    assert len(call["messages"]) == 1
    message = call["messages"][0]
    assert message["role"] == "user"
    user_text = message["content"][0]["text"]
    assert alert.alert_id in user_text
    assert alert.reason in user_text
    assert call["inferenceConfig"]["temperature"] <= 0.3
    assert 0 < call["inferenceConfig"]["maxTokens"] <= DEFAULT_MAX_TOKENS


def test_model_id_property(settings: Settings) -> None:
    assert BedrockClient(settings, client=object()).model_id == "test-model-id"


def test_rate_limiter_before_every_call(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], alert: Alert
) -> None:
    client = _client(settings, limiter, FakeBedrockRuntime(events))
    client.explain(alert)
    assert events == ["wait", "converse"]
    client.explain(alert)
    assert events == ["wait", "converse", "wait", "converse"]


def test_complete_max_tokens_override(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str]
) -> None:
    fake = FakeBedrockRuntime(events)
    _client(settings, limiter, fake).complete("u", "s", max_tokens=42)
    assert fake.calls[0]["inferenceConfig"]["maxTokens"] == 42


def test_complete_joins_text_blocks_and_skips_others(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str]
) -> None:
    fake = FakeBedrockRuntime(
        events,
        converse_response({"text": "a"}, {"toolUse": {"name": "x"}}, {"text": "b"}),
    )
    assert _client(settings, limiter, fake).complete("u", "s") == "ab"


@pytest.mark.parametrize(
    "response",
    [converse_response(), converse_response({"text": "   "}), {"output": {}}, {}],
)
def test_complete_empty_or_malformed_raises(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], response: Any
) -> None:
    fake = FakeBedrockRuntime(events, response)
    with pytest.raises(LLMError):
        _client(settings, limiter, fake).complete("u", "s")


def test_throttling_raises_without_retry(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str]
) -> None:
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
    )
    fake = FakeBedrockRuntime(events, error=error)
    with pytest.raises(LLMError, match="ThrottlingException"):
        _client(settings, limiter, fake).complete("u", "s")
    assert len(fake.calls) == 1


def test_explain_fallback_on_error(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str], alert: Alert
) -> None:
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
    )
    fake = FakeBedrockRuntime(events, error=error)
    result = _client(settings, limiter, fake).explain(alert)
    assert "Explication IA indisponible" in result
    assert alert.reason in result
    assert len(fake.calls) == 1


def test_botocore_error_wrapped(
    settings: Settings, limiter: RecordingRateLimiter, events: list[str]
) -> None:
    fake = FakeBedrockRuntime(events, error=NoCredentialsError())
    with pytest.raises(LLMError, match="NoCredentialsError"):
        _client(settings, limiter, fake).complete("u", "s")


def test_boto3_client_created_lazily_once(
    settings: Settings,
    limiter: RecordingRateLimiter,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    fake = FakeBedrockRuntime(events)

    def spy(*args: Any, **kwargs: Any) -> FakeBedrockRuntime:
        created.append((args, kwargs))
        return fake

    monkeypatch.setattr("llm.client.boto3.client", spy)
    client = BedrockClient(settings, rate_limiter=limiter)
    assert created == []

    client.complete("u", "s")
    client.complete("u", "s")
    assert len(created) == 1
    args, kwargs = created[0]
    assert args == ("bedrock-runtime",)
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["config"].retries["max_attempts"] == 1
    assert len(fake.calls) == 2
