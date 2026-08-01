"""Anthropic API feature tests: caching, streaming, thinking, temperature.

The Anthropic client is stubbed so request construction can be asserted
without network access.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.agents.provider import (
    DEFAULT_TEMPERATURE,
    AIProviderError,
    AnthropicProvider,
)


class FakeMessages:
    """Records create/stream kwargs and returns canned responses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="canned answer")],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=30,
                cache_creation_input_tokens=900,
                cache_read_input_tokens=0,
            ),
        )

    def stream(self, **kwargs: Any) -> Any:
        self.stream_calls.append(kwargs)

        class _Stream:
            text_stream = iter(["Hello ", "from ", "the stream"])

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def get_final_message(self_inner):
                return SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=5,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=900,
                    )
                )

        return _Stream()


@pytest.fixture()
def provider(monkeypatch) -> AnthropicProvider:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = AnthropicProvider()
    p._client = SimpleNamespace(messages=FakeMessages())  # type: ignore[assignment]
    return p


def _messages(provider: AnthropicProvider) -> FakeMessages:
    return provider._client.messages  # type: ignore[attr-defined,no-any-return]


# -- Configuration -----------------------------------------------------------


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AIProviderError, match="No API key"):
        AnthropicProvider()


def test_model_override_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("GRANT_ASSISTANT_MODEL", "claude-opus-5")
    assert AnthropicProvider().model == "claude-opus-5"


# -- Prompt caching ----------------------------------------------------------


def test_system_prompt_carries_cache_breakpoint(provider):
    provider.complete("SYSTEM", [{"role": "user", "content": "hi"}])
    system = _messages(provider).calls[0]["system"]
    assert isinstance(system, list)
    assert system[0]["text"] == "SYSTEM"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_caching_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    p = AnthropicProvider(use_caching=False)
    p._client = SimpleNamespace(messages=FakeMessages())  # type: ignore[assignment]
    p.complete("SYSTEM", [{"role": "user", "content": "hi"}])
    assert "cache_control" not in p._client.messages.calls[0]["system"][0]  # type: ignore[attr-defined]


def test_tools_get_a_cache_breakpoint_on_the_last_definition(provider):
    tools = [
        {"name": "a", "description": "", "input_schema": {"type": "object"}},
        {"name": "b", "description": "", "input_schema": {"type": "object"}},
    ]
    provider.complete_with_tools("S", [{"role": "user", "content": "q"}], tools, lambda n, i: "{}")
    sent = _messages(provider).calls[0]["tools"]
    assert "cache_control" not in sent[0]
    assert sent[-1]["cache_control"] == {"type": "ephemeral"}
    # The caller's list must not be mutated.
    assert "cache_control" not in tools[-1]


def test_usage_records_cache_statistics(provider):
    provider.complete("S", [{"role": "user", "content": "q"}])
    assert provider.usage.input_tokens == 120
    assert provider.usage.cache_creation_tokens == 900
    assert not provider.usage.cache_hit
    assert "cache_write=900" in provider.usage.summary()


# -- Temperature -------------------------------------------------------------


def test_default_temperature_is_deterministic(provider):
    provider.complete("S", [{"role": "user", "content": "q"}])
    assert _messages(provider).calls[0]["temperature"] == DEFAULT_TEMPERATURE == 0.0


# -- Streaming ---------------------------------------------------------------


def test_streaming_yields_chunks_and_records_cache_hit(provider):
    chunks = list(provider.complete_stream("S", [{"role": "user", "content": "q"}]))
    assert chunks == ["Hello ", "from ", "the stream"]
    assert provider.usage.cache_hit
    assert provider.usage.cache_read_tokens == 900


def test_stream_request_includes_cached_system(provider):
    list(provider.complete_stream("SYSTEM", [{"role": "user", "content": "q"}]))
    system = _messages(provider).stream_calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


# -- Extended thinking -------------------------------------------------------


def test_thinking_enables_budget_and_required_temperature(provider):
    provider.complete_thinking("S", [{"role": "user", "content": "q"}], budget_tokens=1500)
    call = _messages(provider).calls[0]
    assert call["thinking"] == {"type": "enabled", "budget_tokens": 1500}
    assert call["temperature"] == 1.0
    assert call["max_tokens"] > 1500


# -- Agent integration -------------------------------------------------------


class StreamingProvider:
    name = "fake-stream"

    def __init__(self) -> None:
        self.streamed = False

    def complete(self, system, messages, max_tokens=1500):
        return "non-streamed"

    def complete_stream(self, system, messages, max_tokens=1500):
        self.streamed = True
        yield "streamed "
        yield "answer"


def test_agent_ask_stream_uses_provider_streaming(analytics_flawed, audit_flawed, profile):
    provider = StreamingProvider()
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=provider)
    assert "".join(agent.ask_stream("How many exits?")) == "streamed answer"
    assert provider.streamed


def test_agent_ask_stream_falls_back_without_provider(analytics_flawed, audit_flawed, profile):
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=None)
    text = "".join(agent.ask_stream("Which program had the highest successful exit rate?"))
    assert "Non-AI mode" in text


def test_agent_narration_prefers_extended_thinking(analytics_flawed, audit_flawed, profile):
    class ThinkingProvider:
        name = "fake-thinking"

        def __init__(self) -> None:
            self.used_thinking = False

        def complete(self, system, messages, max_tokens=1500):
            return "plain"

        def complete_thinking(self, system, messages, max_tokens=3000, budget_tokens=2000):
            self.used_thinking = True
            return "thoughtful narrative"

    provider = ThinkingProvider()
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=provider)
    assert agent.narrated_insights() == "thoughtful narrative"
    assert provider.used_thinking
