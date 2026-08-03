"""Provider-agnostic AI abstraction.

The application talks to a minimal :class:`AIProvider` protocol. Two backends are
built in: Anthropic Claude and an OpenAI-compatible provider (OpenAI, Ollama local
or cloud, any OpenAI-compatible endpoint). :func:`get_provider` selects between
them from the ``GRANT_ASSISTANT_PROVIDER`` environment variable. API keys come
from environment variables only — never from config files.

The Anthropic implementation uses three API features deliberately:

* **Prompt caching** — the system prompt carries a large fact sheet that is
  identical for every turn of a session, so it is marked with a cache
  breakpoint. Subsequent turns read it from cache instead of re-processing it.
* **Streaming** — the chat UI renders tokens as they arrive.
* **Extended thinking** — enabled only for narrative generation, where the
  model benefits from reasoning before writing. It is off for factual lookups,
  which are answered from tools.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"
MODEL_ENV_VAR = "GRANT_ASSISTANT_MODEL"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

#: Factual answers should be reproducible, so default to greedy decoding.
DEFAULT_TEMPERATURE = 0.0
#: Extended thinking requires temperature 1.0 and a budget below max_tokens.
THINKING_BUDGET_TOKENS = 2000

# --- Provider selection --------------------------------------------------
#: Selects the AI backend: "anthropic" (default) | "openai" | "ollama". Ollama and
#: any OpenAI-compatible endpoint (LM Studio, OpenAI itself, Ollama Cloud) share
#: :class:`OpenAICompatibleProvider`; only the defaults differ.
PROVIDER_ENV_VAR = "GRANT_ASSISTANT_PROVIDER"
DEFAULT_PROVIDER = "anthropic"
OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENV_VAR = "OPENAI_BASE_URL"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OLLAMA_MODEL = "llama3.1"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
#: The OpenAI SDK requires *some* bearer even for a keyless local Ollama server.
OLLAMA_DUMMY_KEY = "ollama"


class AIProviderError(Exception):
    """Raised when an AI provider call fails or is misconfigured."""


@runtime_checkable
class AIProvider(Protocol):
    """Minimal interface every AI provider must implement."""

    name: str

    def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> str:
        """Return the model's text response for a system prompt + message history."""
        ...


class UsageStats:
    """Token accounting for the most recent call, including cache performance."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0

    def record(self, usage: Any) -> None:
        self.input_tokens = getattr(usage, "input_tokens", 0) or 0
        self.output_tokens = getattr(usage, "output_tokens", 0) or 0
        self.cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0

    def summary(self) -> str:
        return (
            f"in={self.input_tokens} out={self.output_tokens} "
            f"cache_write={self.cache_creation_tokens} cache_read={self.cache_read_tokens}"
        )


class AnthropicProvider:
    """Anthropic Claude implementation of :class:`AIProvider`."""

    name = "anthropic"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        use_caching: bool = True,
    ) -> None:
        key = api_key or os.environ.get(API_KEY_ENV_VAR, "").strip()
        if not key:
            raise AIProviderError(
                f"No API key found. Set the {API_KEY_ENV_VAR} environment variable "
                "(see .env.example) to enable AI features."
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise AIProviderError("The 'anthropic' package is not installed.") from exc
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model or os.environ.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL
        self.temperature = temperature
        self.use_caching = use_caching
        self.usage = UsageStats()

    # -- Request construction ------------------------------------------------

    def _system_blocks(self, system: str) -> list[dict[str, Any]]:
        """System prompt as blocks, with a cache breakpoint when caching is on.

        The fact sheet is stable for the whole session and dominates the prompt,
        so caching it turns every follow-up turn into a cache read.
        """
        block: dict[str, Any] = {"type": "text", "text": system}
        if self.use_caching:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def _cached_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mark the final tool definition so the whole tool block is cached."""
        if not tools or not self.use_caching:
            return tools
        cached = [dict(tool) for tool in tools]
        cached[-1]["cache_control"] = {"type": "ephemeral"}
        return cached

    def _record(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage.record(usage)
            logger.debug("Claude usage: %s", self.usage.summary())

    # -- Completions ---------------------------------------------------------

    def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> str:
        payload: list[Any] = [{"role": m["role"], "content": m["content"]} for m in messages]
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=self.temperature,
                system=self._system_blocks(system),  # type: ignore[arg-type]
                messages=payload,
            )
        except Exception as exc:
            raise AIProviderError(f"Claude API call failed: {exc}") from exc
        self._record(response)
        parts = [block.text for block in response.content if block.type == "text"]
        return "\n".join(parts).strip()

    def complete_stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> Iterator[str]:
        """Yield response text incrementally so the UI can render as it arrives."""
        payload: list[Any] = [{"role": m["role"], "content": m["content"]} for m in messages]
        try:
            with self._client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                temperature=self.temperature,
                system=self._system_blocks(system),  # type: ignore[arg-type]
                messages=payload,
            ) as stream:
                yield from stream.text_stream
                self._record(stream.get_final_message())
        except Exception as exc:
            raise AIProviderError(f"Claude streaming call failed: {exc}") from exc

    def complete_thinking(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int = 3000,
        budget_tokens: int = THINKING_BUDGET_TOKENS,
    ) -> str:
        """Completion with extended thinking, for narrative and synthesis work.

        Thinking blocks are internal reasoning and are never surfaced to the
        user or written into a report; only the text blocks are returned.
        """
        payload: list[Any] = [{"role": m["role"], "content": m["content"]} for m in messages]
        thinking: Any = {"type": "enabled", "budget_tokens": budget_tokens}
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max(max_tokens, budget_tokens + 1000),
                temperature=1.0,  # required when extended thinking is enabled
                thinking=thinking,
                system=self._system_blocks(system),  # type: ignore[arg-type]
                messages=payload,
            )
        except Exception as exc:
            raise AIProviderError(f"Claude extended-thinking call failed: {exc}") from exc
        self._record(response)
        parts = [block.text for block in response.content if block.type == "text"]
        return "\n".join(parts).strip()

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        executor: Callable[[str, dict[str, Any] | None], str],
        max_tokens: int = 1500,
        max_rounds: int = 6,
    ) -> str:
        """Agentic loop: let the model call tools, feed results back, return text.

        ``executor(name, input)`` runs a tool and returns its JSON result string;
        executor errors are returned to the model as error tool results rather
        than aborting the conversation.
        """
        convo: list[Any] = [{"role": m["role"], "content": m["content"]} for m in messages]
        cached_tools = self._cached_tools(tools)
        for _ in range(max_rounds):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=self.temperature,
                    system=self._system_blocks(system),  # type: ignore[arg-type]
                    messages=convo,
                    tools=cached_tools,  # type: ignore[arg-type]
                )
            except Exception as exc:
                raise AIProviderError(f"Claude API call failed: {exc}") from exc
            self._record(response)
            if response.stop_reason != "tool_use":
                parts = [b.text for b in response.content if b.type == "text"]
                return "\n".join(parts).strip()
            results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    content = executor(block.name, dict(block.input or {}))  # type: ignore[arg-type]
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": content}
                    )
                except Exception as exc:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Tool error: {exc}",
                            "is_error": True,
                        }
                    )
            convo.append({"role": "assistant", "content": response.content})
            convo.append({"role": "user", "content": results})
        raise AIProviderError(f"Tool loop exceeded {max_rounds} rounds without a final answer.")


class OpenAICompatibleProvider:
    """OpenAI-compatible implementation of :class:`AIProvider`.

    One class serves OpenAI, Ollama (local keyless server or cloud), and any
    OpenAI-compatible endpoint — only the defaults differ. It implements the
    three optional methods the analyst duck-types, so the local model is a true
    drop-in: narration (``complete``), streaming chat (``complete_stream``),
    and the agent tool loop (``complete_with_tools``) all work. Extended
    thinking is deliberately omitted (no OpenAI equivalent); ``narrated_insights``
    falls back to ``complete``.

    The tool schema is converted from Anthropic's ``input_schema`` shape to
    OpenAI's ``function``/``parameters`` shape *inside* this provider, so the
    rest of the codebase keeps the Anthropic-shaped :func:`AnalystTools.schemas`.
    """

    def __init__(
        self,
        model: str | None = None,
        kind: str = "openai",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        if kind not in ("openai", "ollama"):
            raise AIProviderError(f"Unknown OpenAI-compatible provider kind: {kind!r}")
        self.name = kind
        self.kind = kind
        default_model = DEFAULT_OLLAMA_MODEL if kind == "ollama" else DEFAULT_OPENAI_MODEL
        default_base = DEFAULT_OLLAMA_BASE_URL if kind == "ollama" else None

        key = (api_key or os.environ.get(OPENAI_API_KEY_ENV_VAR, "")).strip()
        if not key:
            if kind == "ollama":
                # The SDK requires a bearer even for a keyless local server.
                key = OLLAMA_DUMMY_KEY
            else:
                raise AIProviderError(
                    f"No API key found. Set the {OPENAI_API_KEY_ENV_VAR} environment variable "
                    "to enable OpenAI features."
                )
        base = (base_url or os.environ.get(OPENAI_BASE_URL_ENV_VAR, "")).strip() or default_base

        try:
            import openai
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise AIProviderError(
                "The 'openai' package is not installed. Install it with: uv sync --extra openai"
            ) from exc
        client_kwargs: dict[str, Any] = {"api_key": key}
        if base:
            client_kwargs["base_url"] = base
        # Typed as Any: the OpenAI SDK's response/tool-call unions are over-narrow
        # (the live API always returns function tool calls), and tests swap in a
        # SimpleNamespace client. Treating the adapter as Any avoids fighting both.
        self._client: Any = openai.OpenAI(**client_kwargs)  # type: ignore[call-arg]
        self.model = (model or os.environ.get(MODEL_ENV_VAR, "")).strip() or default_model
        self.temperature = temperature
        self.usage = UsageStats()

    # -- Request construction ------------------------------------------------

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic tool defs to the OpenAI function-calling shape.

        ``input_schema`` is already a JSON-schema object, so it maps directly to
        OpenAI's ``parameters`` field with no restructuring.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def _full_messages(self, system: str, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """OpenAI takes the system prompt as the first message, not a param."""
        full: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            full.append({"role": m["role"], "content": m["content"]})
        return full

    def _record(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            self.usage.output_tokens = getattr(usage, "completion_tokens", 0) or 0
            logger.debug("%s usage: %s", self.name, self.usage.summary())

    # -- Completions ---------------------------------------------------------

    def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=self.temperature,
                messages=self._full_messages(system, messages),
            )
        except Exception as exc:
            raise AIProviderError(f"{self.name} API call failed: {exc}") from exc
        self._record(response)
        return (response.choices[0].message.content or "").strip()

    def complete_stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1500,
    ) -> Iterator[str]:
        """Yield response text incrementally so the UI can render as it arrives.

        Like the Anthropic path, streaming skips the tool loop — the chat UI
        uses it for open narrative questions whose numbers already live in the
        fact sheet.
        """
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=self.temperature,
                messages=self._full_messages(system, messages),
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            raise AIProviderError(f"{self.name} streaming call failed: {exc}") from exc

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        executor: Callable[[str, dict[str, Any] | None], str],
        max_tokens: int = 1500,
        max_rounds: int = 6,
    ) -> str:
        """Agentic loop over the OpenAI function-calling protocol.

        Mirrors :meth:`AnthropicProvider.complete_with_tools`: the model calls
        tools, ``executor(name, input)`` runs them, results are fed back as
        ``role: "tool"`` messages, and executor errors are returned to the model
        rather than aborting.
        """
        convo: list[dict[str, Any]] = self._full_messages(system, messages)
        openai_tools = self._to_openai_tools(tools)
        for _ in range(max_rounds):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=self.temperature,
                    messages=convo,
                    tools=openai_tools,
                )
            except Exception as exc:
                raise AIProviderError(f"{self.name} API call failed: {exc}") from exc
            self._record(response)
            msg = response.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                return (msg.content or "").strip()
            # Echo the assistant's tool-call message back verbatim: OpenAI
            # requires the raw JSON-string arguments here, not parsed dicts.
            convo.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    content = executor(tc.function.name, args)
                except Exception as exc:
                    content = f"Tool error: {exc}"
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        raise AIProviderError(f"Tool loop exceeded {max_rounds} rounds without a final answer.")


def _provider_choice() -> str:
    """Which provider the environment selects (lowercased; default anthropic)."""
    return (os.environ.get(PROVIDER_ENV_VAR, DEFAULT_PROVIDER) or DEFAULT_PROVIDER).strip().lower()


def ai_available() -> bool:
    """True when the selected provider has the credentials it needs.

    Anthropic and OpenAI require their keys; Ollama runs against a keyless local
    server (cloud users set a real key in ``OPENAI_API_KEY``), so it is available
    whenever selected — the constructor and the runtime fallback handle a
    missing server or missing ``openai`` package.
    """
    choice = _provider_choice()
    if choice == "anthropic":
        return bool(os.environ.get(API_KEY_ENV_VAR, "").strip())
    if choice == "ollama":
        return True
    if choice == "openai":
        return bool(os.environ.get(OPENAI_API_KEY_ENV_VAR, "").strip())
    return False


def get_provider(model: str | None = None) -> AIProvider | None:
    """Return a configured provider, or None to run in non-AI fallback mode."""
    if not ai_available():
        logger.info("No credentials set — running in non-AI fallback mode.")
        return None
    choice = _provider_choice()
    try:
        if choice == "anthropic":
            return AnthropicProvider(model=model)
        if choice in ("openai", "ollama"):
            return OpenAICompatibleProvider(model=model, kind=choice)
        logger.warning("Unknown provider %r — running in non-AI mode.", choice)
        return None
    except AIProviderError as exc:
        logger.warning("AI provider unavailable: %s", exc)
        return None
