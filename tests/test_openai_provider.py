"""OpenAI-compatible provider tests: request construction, streaming, tool loop.

The OpenAI client is stubbed so request construction (system message, tool schema
conversion, tool-result round-trip) can be asserted without network access.
Mirrors tests/test_provider_features.py: hand-rolled fakes + SimpleNamespace,
swapping ``provider._client`` post-construction.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.agents.provider import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT_SECONDS,
    AIProviderError,
    AnthropicProvider,
    OpenAICompatibleProvider,
    ai_available,
    get_provider,
)
from grant_assistant.agents.tools import AnalystTools

# The OpenAI SDK is an optional extra; skip rather than fail when it is absent.
pytest.importorskip("openai")

# -- Fakes -------------------------------------------------------------------


class FakeChatCompletions:
    """Records create() kwargs and returns scripted responses in order."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses: list[Any] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _content_response(text: str = "canned answer") -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
    )


def _tool_call_response(
    call_id: str = "call_1",
    name: str = "get_metric",
    arguments: str = '{"name": "total_enrollments"}',
) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id=call_id,
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
    )


def _stream_chunks(*pieces: str) -> Any:
    return [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p))]) for p in pieces
    ]


def _make_provider(
    monkeypatch, kind: str, responses: list[Any], **env: str
) -> OpenAICompatibleProvider:
    """Construct a provider with the OpenAI SDK replaced by a fake client."""
    import openai

    completions = FakeChatCompletions(responses)
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(  # type: ignore[attr-defined]
            chat=SimpleNamespace(completions=completions), _kwargs=kwargs
        ),
    )
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", kind)
    if kind == "openai":
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return OpenAICompatibleProvider(kind=kind)


def _completions(provider: OpenAICompatibleProvider) -> FakeChatCompletions:
    return provider._client.chat.completions  # type: ignore[no-any-return,attr-defined]


# -- Configuration -----------------------------------------------------------


def test_missing_key_raises_for_openai(monkeypatch):
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AIProviderError, match="No API key"):
        OpenAICompatibleProvider(kind="openai")


def test_ollama_constructs_keyless_with_defaults(monkeypatch):
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "ollama")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    recorded: dict[str, Any] = {}

    def fake_openai(**kwargs: Any) -> Any:
        recorded.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=FakeChatCompletions([])))

    import openai

    monkeypatch.setattr(openai, "OpenAI", fake_openai)  # type: ignore[attr-defined]
    p = OpenAICompatibleProvider(kind="ollama")
    assert p.name == "ollama"
    assert p.model == DEFAULT_OLLAMA_MODEL
    # A dummy bearer is required by the SDK even for a keyless server.
    assert recorded["api_key"] == "ollama"
    assert recorded["base_url"] == DEFAULT_OLLAMA_BASE_URL


def test_openai_default_model(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response()])
    assert p.model == DEFAULT_OPENAI_MODEL


def test_model_override_from_env(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response()], GRANT_ASSISTANT_MODEL="gpt-4o")
    assert p.model == "gpt-4o"


def test_client_gets_timeout_and_retries(monkeypatch):
    """A hung request must not block the UI forever."""
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    recorded: dict[str, Any] = {}

    import openai

    def fake_openai(**kwargs: Any) -> Any:
        recorded.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=FakeChatCompletions([])))

    monkeypatch.setattr(openai, "OpenAI", fake_openai)  # type: ignore[attr-defined]
    OpenAICompatibleProvider(kind="openai")
    assert recorded["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert recorded["max_retries"] == DEFAULT_MAX_RETRIES


def test_unknown_kind_raises():
    with pytest.raises(AIProviderError, match="Unknown OpenAI-compatible provider kind"):
        OpenAICompatibleProvider(kind="huggingface")


# -- Request construction ----------------------------------------------------


def test_system_message_is_prepended(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response()])
    p.complete("SYSTEM", [{"role": "user", "content": "hi"}])
    msgs = _completions(p).calls[0]["messages"]
    assert msgs[0] == {"role": "system", "content": "SYSTEM"}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_temperature_is_deterministic(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response()])
    p.complete("S", [{"role": "user", "content": "q"}])
    assert _completions(p).calls[0]["temperature"] == DEFAULT_TEMPERATURE == 0.0


def test_complete_returns_content(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response("hello world")])
    assert p.complete("S", [{"role": "user", "content": "q"}]) == "hello world"


def test_complete_strips_whitespace(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response("  spaced  ")])
    assert p.complete("S", [{"role": "user", "content": "q"}]) == "spaced"


# -- Tools / schema conversion ----------------------------------------------


def test_tools_converted_to_openai_shape(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response("done")])
    schemas = AnalystTools.schemas()
    p.complete_with_tools("S", [{"role": "user", "content": "q"}], schemas, lambda n, i: "{}")
    sent = _completions(p).calls[0]["tools"]
    assert sent[0]["type"] == "function"
    assert sent[0]["function"]["name"] == "get_metric"
    assert sent[0]["function"]["parameters"] == schemas[0]["input_schema"]
    # The caller's Anthropic-shaped schemas must not be mutated.
    assert "function" not in schemas[0]
    assert "input_schema" in schemas[0]


def test_tool_loop_executes_and_feeds_result_back(monkeypatch):
    executed: list[tuple[str, dict[str, Any]]] = []

    def executor(name: str, args: dict[str, Any]) -> str:
        executed.append((name, args))
        return json.dumps({"name": "total_enrollments", "value": 260})

    p = _make_provider(
        monkeypatch,
        "openai",
        [_tool_call_response(), _content_response("The total is 260.")],
    )
    answer = p.complete_with_tools(
        "S", [{"role": "user", "content": "q"}], AnalystTools.schemas(), executor
    )
    assert answer == "The total is 260."
    assert executed == [("get_metric", {"name": "total_enrollments"})]

    # Second call carries the assistant tool-call message and the tool result.
    second_msgs = _completions(p).calls[1]["messages"]
    assistant_msg = second_msgs[-2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] is None
    assert (
        assistant_msg["tool_calls"][0]["function"]["arguments"] == '{"name": "total_enrollments"}'
    )
    tool_result = second_msgs[-1]
    assert tool_result == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": json.dumps({"name": "total_enrollments", "value": 260}),
    }


def test_tool_loop_returns_immediately_without_tool_calls(monkeypatch):
    def executor(name: str, args: dict[str, Any]) -> str:  # pragma: no cover - should not run
        raise AssertionError("executor should not be called")

    p = _make_provider(monkeypatch, "openai", [_content_response("no tools needed")])
    answer = p.complete_with_tools(
        "S", [{"role": "user", "content": "q"}], AnalystTools.schemas(), executor
    )
    assert answer == "no tools needed"
    assert len(_completions(p).calls) == 1


def test_tool_loop_max_rounds_raises(monkeypatch):
    p = _make_provider(
        monkeypatch,
        "openai",
        [_tool_call_response() for _ in range(3)],
    )
    with pytest.raises(AIProviderError, match="exceeded"):
        p.complete_with_tools(
            "S",
            [{"role": "user", "content": "q"}],
            AnalystTools.schemas(),
            lambda n, i: "{}",
            max_rounds=3,
        )


def test_malformed_tool_arguments_become_empty_dict(monkeypatch):
    executed: list[tuple[str, dict[str, Any]]] = []
    p = _make_provider(
        monkeypatch,
        "openai",
        [_tool_call_response(arguments="not json"), _content_response("ok")],
    )
    p.complete_with_tools(
        "S",
        [{"role": "user", "content": "q"}],
        AnalystTools.schemas(),
        lambda n, i: executed.append((n, i)) or "{}",
    )
    assert executed == [("get_metric", {})]


def test_executor_errors_returned_to_model_not_raised(monkeypatch):
    def executor(name: str, args: dict[str, Any]) -> str:
        raise RuntimeError("boom")

    p = _make_provider(
        monkeypatch,
        "openai",
        [_tool_call_response(), _content_response("recovered")],
    )
    answer = p.complete_with_tools(
        "S", [{"role": "user", "content": "q"}], AnalystTools.schemas(), executor
    )
    # The error was sent back as a tool result and the model produced a final answer.
    assert answer == "recovered"
    tool_result = _completions(p).calls[1]["messages"][-1]
    assert tool_result["role"] == "tool"
    assert "Tool error" in tool_result["content"]


# -- Streaming ---------------------------------------------------------------


def test_streaming_yields_chunks(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_stream_chunks("Hello ", "from ", "stream")])
    assert list(p.complete_stream("S", [{"role": "user", "content": "q"}])) == [
        "Hello ",
        "from ",
        "stream",
    ]
    assert _completions(p).calls[0]["stream"] is True


# -- Error handling / usage ---------------------------------------------------


def test_api_error_mapped_to_aiprovidererror(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [])
    _completions(p).responses = []  # pop on empty raises IndexError
    # Inject a raising completion by replacing create.
    _completions(p).create = lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="API call failed"):
        p.complete("S", [{"role": "user", "content": "q"}])


def test_usage_records_tokens(monkeypatch):
    p = _make_provider(monkeypatch, "openai", [_content_response()])
    p.complete("S", [{"role": "user", "content": "q"}])
    assert p.usage.input_tokens == 120
    assert p.usage.output_tokens == 30


# -- Agent integration -------------------------------------------------------


def test_agent_ask_routes_through_complete_with_tools(
    monkeypatch, analytics_flawed, audit_flawed, profile
):
    p = _make_provider(
        monkeypatch,
        "openai",
        [
            _tool_call_response(name="list_metrics", arguments="{}"),
            _content_response("Grounded tool answer."),
        ],
    )
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=p)
    answer = agent.ask("What metrics are available?")
    assert answer == "Grounded tool answer."
    # The first request carried tools — proof the tool loop (not plain complete) was used.
    assert "tools" in _completions(p).calls[0]
    assert len(_completions(p).calls) == 2


def test_agent_narration_falls_back_to_complete_without_thinking(
    monkeypatch, analytics_flawed, audit_flawed, profile
):
    p = _make_provider(monkeypatch, "openai", [_content_response("polished narrative")])
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=p)
    assert agent.narrated_insights() == "polished narrative"
    # No extended-thinking call exists; a single plain completion was made.
    assert len(_completions(p).calls) == 1


# -- Provider selection -------------------------------------------------------
#
# ``ai_available`` and ``get_provider`` dispatch on GRANT_ASSISTANT_PROVIDER, so
# each backend needs its own credential rule. The autouse conftest fixture clears
# the OpenAI selector vars but leaves ANTHROPIC_API_KEY alone, so these tests set
# and delete it explicitly.


def _stub_openai_client(monkeypatch) -> None:
    """Keep get_provider() from constructing a real SDK client."""
    import openai

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(  # type: ignore[attr-defined]
            chat=SimpleNamespace(completions=FakeChatCompletions([]))
        ),
    )


def test_ai_available_defaults_to_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert ai_available() is True
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai_available() is False


def test_ai_available_openai_requires_its_own_key(monkeypatch):
    # An Anthropic key must not make the OpenAI backend look available.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "openai")
    assert ai_available() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert ai_available() is True


def test_ai_available_ollama_is_keyless(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "ollama")
    assert ai_available() is True


def test_ai_available_false_for_unknown_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "huggingface")
    assert ai_available() is False


def test_provider_selection_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "  OpenAI  ")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert ai_available() is True


def test_get_provider_returns_anthropic_by_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert isinstance(get_provider(), AnthropicProvider)


def test_get_provider_returns_openai_when_selected(monkeypatch):
    _stub_openai_client(monkeypatch)
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = get_provider()
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.name == "openai"


def test_get_provider_returns_ollama_when_selected(monkeypatch):
    _stub_openai_client(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "ollama")
    p = get_provider()
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.name == "ollama"
    assert p.model == DEFAULT_OLLAMA_MODEL


def test_get_provider_returns_none_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_provider() is None


def test_get_provider_returns_none_for_unknown_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "huggingface")
    assert get_provider() is None


def test_get_provider_falls_back_to_none_when_sdk_missing(monkeypatch):
    """A missing optional SDK degrades to deterministic mode, never a crash."""
    import builtins

    real_import = builtins.__import__

    def fail_openai(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_openai)
    monkeypatch.setenv("GRANT_ASSISTANT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert get_provider() is None
