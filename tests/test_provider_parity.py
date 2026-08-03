"""Contract tests every AI provider must satisfy, run against all backends.

``analyst.py`` duck-types the optional methods with ``getattr``, so a backend
that implements ``complete_with_tools`` with a subtly different contract fails
silently at runtime rather than at import. The per-backend suites
(test_provider_features.py, test_openai_provider.py) assert how each one builds
its own requests; this file asserts the behaviour they must *share*.

Adding a third backend means adding one entry to ``BACKENDS`` and making these
pass. Everything the analyst relies on is pinned here: return shapes, the tool
loop, streaming, usage accounting, and error translation.
"""

from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace
from typing import Any

import pytest

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.agents.provider import (
    AIProvider,
    AIProviderError,
    AnthropicProvider,
    OpenAICompatibleProvider,
)
from grant_assistant.agents.tools import AnalystTools

# -- Backend adapters --------------------------------------------------------
#
# Each adapter scripts responses in a provider-neutral form — ("text", str) or
# ("tool_use", name, args) — and renders them into that SDK's response shape.

_ANTHROPIC_USAGE = SimpleNamespace(
    input_tokens=120,
    output_tokens=30,
    cache_creation_input_tokens=0,
    cache_read_input_tokens=0,
)
_OPENAI_USAGE = SimpleNamespace(prompt_tokens=120, completion_tokens=30)


class _Recorder:
    """Returns scripted responses in order and records the kwargs it was sent."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.raises: Exception | None = None

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.responses.pop(0)


class AnthropicBackend:
    name = "anthropic"

    @staticmethod
    def render(script: tuple[Any, ...]) -> Any:
        if script[0] == "text":
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=script[1])],
                stop_reason="end_turn",
                usage=_ANTHROPIC_USAGE,
            )
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", id="call_1", name=script[1], input=dict(script[2]))
            ],
            stop_reason="tool_use",
            usage=_ANTHROPIC_USAGE,
        )

    @classmethod
    def make(cls, monkeypatch, scripts: list[tuple[Any, ...]], stream: list[str] | None = None):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        provider = AnthropicProvider()
        recorder = _Recorder([cls.render(s) for s in scripts])

        def _stream(**kwargs: Any) -> Any:
            recorder.calls.append(kwargs)

            class _S:
                text_stream = iter(stream or [])

                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc):
                    return False

                def get_final_message(self_inner):
                    return SimpleNamespace(usage=_ANTHROPIC_USAGE)

            return _S()

        provider._client = SimpleNamespace(  # type: ignore[assignment]
            messages=SimpleNamespace(create=recorder, stream=_stream)
        )
        return provider, recorder


class OpenAIBackend:
    name = "openai"

    @staticmethod
    def render(script: tuple[Any, ...]) -> Any:
        if script[0] == "text":
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=script[1], tool_calls=None))
                ],
                usage=_OPENAI_USAGE,
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name=script[1], arguments=json.dumps(script[2])
                                ),
                            )
                        ],
                    )
                )
            ],
            usage=_OPENAI_USAGE,
        )

    @classmethod
    def make(cls, monkeypatch, scripts: list[tuple[Any, ...]], stream: list[str] | None = None):
        import openai

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        responses: list[Any] = [cls.render(s) for s in scripts]
        if stream is not None:
            responses.append(
                [
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=c))])
                    for c in stream
                ]
            )
        recorder = _Recorder(responses)
        monkeypatch.setattr(
            openai,
            "OpenAI",
            lambda **kw: SimpleNamespace(  # type: ignore[attr-defined]
                chat=SimpleNamespace(completions=SimpleNamespace(create=recorder))
            ),
        )
        return OpenAICompatibleProvider(kind="openai"), recorder


BACKENDS = [
    pytest.param(AnthropicBackend, id="anthropic"),
    pytest.param(
        OpenAIBackend,
        id="openai",
        marks=pytest.mark.skipif(
            importlib.util.find_spec("openai") is None,
            reason="the openai extra is not installed",
        ),
    ),
]

pytestmark = pytest.mark.parametrize("backend", BACKENDS)


# -- The contract ------------------------------------------------------------


def test_satisfies_the_provider_protocol(backend, monkeypatch):
    provider, _ = backend.make(monkeypatch, [("text", "hi")])
    assert isinstance(provider, AIProvider)
    assert provider.name
    assert provider.model


def test_complete_returns_stripped_text(backend, monkeypatch):
    provider, _ = backend.make(monkeypatch, [("text", "  the answer  ")])
    assert provider.complete("S", [{"role": "user", "content": "q"}]) == "the answer"


def test_complete_records_usage(backend, monkeypatch):
    provider, _ = backend.make(monkeypatch, [("text", "x")])
    provider.complete("S", [{"role": "user", "content": "q"}])
    assert provider.usage.input_tokens == 120
    assert provider.usage.output_tokens == 30


def test_api_failure_becomes_aiprovidererror(backend, monkeypatch):
    """Callers catch one exception type regardless of which SDK raised."""
    provider, recorder = backend.make(monkeypatch, [("text", "x")])
    recorder.raises = RuntimeError("connection reset")
    with pytest.raises(AIProviderError):
        provider.complete("S", [{"role": "user", "content": "q"}])


def test_streaming_yields_incrementally(backend, monkeypatch):
    provider, _ = backend.make(monkeypatch, [], stream=["Hello ", "from ", "stream"])
    assert list(provider.complete_stream("S", [{"role": "user", "content": "q"}])) == [
        "Hello ",
        "from ",
        "stream",
    ]


def test_tool_loop_executes_and_returns_final_text(backend, monkeypatch):
    executed: list[tuple[str, dict[str, Any]]] = []

    def executor(name: str, args: dict[str, Any] | None) -> str:
        executed.append((name, dict(args or {})))
        return json.dumps({"name": "total_enrollments", "value": 260})

    provider, _ = backend.make(
        monkeypatch,
        [
            ("tool_use", "get_metric", {"name": "total_enrollments"}),
            ("text", "There are 260 enrollments."),
        ],
    )
    answer = provider.complete_with_tools(
        "S", [{"role": "user", "content": "q"}], AnalystTools.schemas(), executor
    )
    assert answer == "There are 260 enrollments."
    assert executed == [("get_metric", {"name": "total_enrollments"})]


def test_tool_loop_returns_immediately_when_no_tool_is_called(backend, monkeypatch):
    def executor(name: str, args: dict[str, Any] | None) -> str:  # pragma: no cover
        raise AssertionError("executor must not run")

    provider, recorder = backend.make(monkeypatch, [("text", "no tools needed")])
    answer = provider.complete_with_tools(
        "S", [{"role": "user", "content": "q"}], AnalystTools.schemas(), executor
    )
    assert answer == "no tools needed"
    assert len(recorder.calls) == 1


def test_executor_errors_are_returned_to_the_model_not_raised(backend, monkeypatch):
    """One bad tool call must not abort a conversation on any backend."""

    def executor(name: str, args: dict[str, Any] | None) -> str:
        raise RuntimeError("boom")

    provider, _ = backend.make(
        monkeypatch,
        [("tool_use", "get_metric", {"name": "nope"}), ("text", "recovered")],
    )
    answer = provider.complete_with_tools(
        "S", [{"role": "user", "content": "q"}], AnalystTools.schemas(), executor
    )
    assert answer == "recovered"


def test_tool_loop_is_bounded(backend, monkeypatch):
    """A model that only ever calls tools must terminate, not spin forever."""
    provider, _ = backend.make(
        monkeypatch, [("tool_use", "get_metric", {"name": "x"}) for _ in range(3)]
    )
    with pytest.raises(AIProviderError, match="exceeded"):
        provider.complete_with_tools(
            "S",
            [{"role": "user", "content": "q"}],
            AnalystTools.schemas(),
            lambda n, i: "{}",
            max_rounds=3,
        )


def test_caller_schemas_are_never_mutated(backend, monkeypatch):
    """Tool schemas are shared state; a provider must not rewrite them in place."""
    schemas = AnalystTools.schemas()
    before = json.dumps(schemas, sort_keys=True)
    provider, _ = backend.make(monkeypatch, [("text", "done")])
    provider.complete_with_tools(
        "S", [{"role": "user", "content": "q"}], schemas, lambda n, i: "{}"
    )
    assert json.dumps(schemas, sort_keys=True) == before


def test_agent_ask_is_grounded_through_the_tool_loop(
    backend, monkeypatch, analytics_flawed, audit_flawed, profile
):
    """The analyst reaches tools on every backend, not just the Anthropic one."""
    provider, recorder = backend.make(
        monkeypatch,
        [("tool_use", "list_metrics", {}), ("text", "Grounded tool answer.")],
    )
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=provider)
    assert agent.ask("What metrics are available?") == "Grounded tool answer."
    assert "tools" in recorder.calls[0]
    assert len(recorder.calls) == 2
