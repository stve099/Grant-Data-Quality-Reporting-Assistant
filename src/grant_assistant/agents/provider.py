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
from asyncio import to_thread
from collections.abc import Callable, Iterator
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"
MODEL_ENV_VAR = "GRANT_ASSISTANT_MODEL"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

#: Factual answers should be reproducible, so default to greedy decoding.
DEFAULT_TEMPERATURE = 0.0
#: Wall-clock ceiling for a single API call. Without it a hung request blocks the
#: Streamlit UI indefinitely with no feedback; a local model on cold start and a
#: long narrative both need well under this.
DEFAULT_TIMEOUT_SECONDS = 120.0
#: Transient 429/5xx retries, handled inside the SDKs with backoff.
DEFAULT_MAX_RETRIES = 2

#: Optional prices in USD per million tokens. Left to the environment because
#: published rates change and differ per model; a stale built-in table would
#: quietly report wrong money.
INPUT_COST_ENV_VAR = "GRANT_ASSISTANT_INPUT_COST_PER_MTOK"
OUTPUT_COST_ENV_VAR = "GRANT_ASSISTANT_OUTPUT_COST_PER_MTOK"
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


class AIProviderFailure(StrEnum):
    """Stable failure categories shared across provider SDKs."""

    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    INVALID_REQUEST = "invalid_request"
    PROVIDER = "provider"


class AIProviderError(Exception):
    """Provider failure with a stable category and retryability signal."""

    def __init__(
        self,
        message: str,
        *,
        failure: AIProviderFailure = AIProviderFailure.PROVIDER,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.failure = failure
        self.retryable = retryable

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        *,
        provider: str,
        operation: str,
    ) -> AIProviderError:
        """Translate Anthropic/OpenAI/stdlib errors without importing optional SDK types."""
        name = type(exc).__name__.casefold()
        status_code = getattr(exc, "status_code", None)
        if isinstance(exc, TimeoutError) or "timeout" in name or status_code == 408:
            failure = AIProviderFailure.TIMEOUT
            detail = "timed out"
            retryable = True
        elif "authentication" in name or "permissiondenied" in name or status_code in {401, 403}:
            failure = AIProviderFailure.AUTHENTICATION
            detail = "authentication failed"
            retryable = False
        elif "ratelimit" in name or "rate_limit" in name or status_code == 429:
            failure = AIProviderFailure.RATE_LIMIT
            detail = "rate limit reached"
            retryable = True
        elif "connection" in name:
            failure = AIProviderFailure.CONNECTION
            detail = "connection failed"
            retryable = True
        elif (
            "badrequest" in name
            or "invalidrequest" in name
            or (isinstance(status_code, int) and 400 <= status_code < 500)
        ):
            failure = AIProviderFailure.INVALID_REQUEST
            detail = "request was rejected"
            retryable = False
        else:
            failure = AIProviderFailure.PROVIDER
            detail = "failed"
            retryable = isinstance(status_code, int) and status_code >= 500
        return cls(
            f"{provider} {operation} {detail}: {exc}",
            failure=failure,
            retryable=retryable,
        )


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


async def complete_async(
    provider: AIProvider,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1500,
) -> str:
    """Run a provider completion without blocking an async caller's event loop.

    Provider implementations remain synchronous for Streamlit and Typer compatibility.
    Async applications and concurrent orchestration can use this adapter immediately,
    including third-party providers that only implement the minimal protocol.
    """
    return await to_thread(provider.complete, system, messages, max_tokens)


class UsageStats:
    """Token accounting for the last call and for the session so far.

    A single call's numbers answer "did the cache hit?"; the running totals
    answer "what has this session cost?", which is the question anyone running
    an eval sweep or a long chat actually has.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0
        #: Tokens a reasoning model spent before writing its answer. Counted
        #: against max_tokens, so an empty response with a healthy figure here
        #: means the budget ran out during reasoning rather than the model
        #: failing — a distinction that cost real debugging time.
        self.reasoning_tokens = 0

        self.calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_reasoning_tokens = 0

    def _accumulate(self) -> None:
        self.calls += 1
        self.total_input_tokens += self.input_tokens
        self.total_output_tokens += self.output_tokens
        self.total_cache_read_tokens += self.cache_read_tokens
        self.total_reasoning_tokens += self.reasoning_tokens

    def record(self, usage: Any) -> None:
        """Record an Anthropic usage object."""
        self.input_tokens = getattr(usage, "input_tokens", 0) or 0
        self.output_tokens = getattr(usage, "output_tokens", 0) or 0
        self.cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.reasoning_tokens = 0
        self._accumulate()

    def record_openai(self, usage: Any) -> None:
        """Record an OpenAI-shaped usage object, including its nested details.

        Cached and reasoning counts live one level down and are absent on
        endpoints that do not report them, so every lookup is defensive.
        """
        self.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        self.output_tokens = getattr(usage, "completion_tokens", 0) or 0
        self.cache_creation_tokens = 0
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        self.cache_read_tokens = getattr(prompt_details, "cached_tokens", 0) or 0
        completion_details = getattr(usage, "completion_tokens_details", None)
        self.reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0) or 0
        self._accumulate()

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0

    def estimated_cost_usd(self) -> float | None:
        """Session cost, or None when no prices are configured.

        Rates come from the environment rather than a built-in table: published
        prices change, and a stale hardcoded number is worse than no number.
        """
        input_rate = _rate_from_env(INPUT_COST_ENV_VAR)
        output_rate = _rate_from_env(OUTPUT_COST_ENV_VAR)
        if input_rate is None and output_rate is None:
            return None
        return (self.total_input_tokens / 1_000_000) * (input_rate or 0.0) + (
            self.total_output_tokens / 1_000_000
        ) * (output_rate or 0.0)

    def summary(self) -> str:
        parts = [
            f"in={self.input_tokens} out={self.output_tokens} "
            f"cache_write={self.cache_creation_tokens} cache_read={self.cache_read_tokens}"
        ]
        if self.reasoning_tokens:
            parts.append(f"reasoning={self.reasoning_tokens}")
        return " ".join(parts)

    def session_summary(self) -> str:
        """One line covering the whole session, for a UI footer or a log."""
        total = self.total_input_tokens + self.total_output_tokens
        text = (
            f"{self.calls} call(s), {total:,} tokens "
            f"({self.total_input_tokens:,} in / {self.total_output_tokens:,} out)"
        )
        if self.total_cache_read_tokens:
            text += f", {self.total_cache_read_tokens:,} read from cache"
        if self.total_reasoning_tokens:
            text += f", {self.total_reasoning_tokens:,} reasoning"
        cost = self.estimated_cost_usd()
        if cost is not None:
            text += f" — about ${cost:,.4f}"
        return text


def _rate_from_env(name: str) -> float | None:
    """A price per million tokens, or None when unset or unparseable."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s is not a number: %r — ignoring.", name, raw)
        return None


class AnthropicProvider:
    """Anthropic Claude implementation of :class:`AIProvider`."""

    name = "anthropic"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        use_caching: bool = True,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
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
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=max_retries)
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
            raise AIProviderError.from_exception(
                exc, provider="Claude", operation="API call"
            ) from exc
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
            raise AIProviderError.from_exception(
                exc, provider="Claude", operation="streaming call"
            ) from exc

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
            raise AIProviderError.from_exception(
                exc, provider="Claude", operation="extended-thinking call"
            ) from exc
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
                raise AIProviderError.from_exception(
                    exc, provider="Claude", operation="API call"
                ) from exc
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
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
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
        client_kwargs: dict[str, Any] = {
            "api_key": key,
            "timeout": timeout,
            "max_retries": max_retries,
        }
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
            self.usage.record_openai(usage)
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
            raise AIProviderError.from_exception(
                exc, provider=self.name, operation="API call"
            ) from exc
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
            raise AIProviderError.from_exception(
                exc, provider=self.name, operation="streaming call"
            ) from exc

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
                raise AIProviderError.from_exception(
                    exc, provider=self.name, operation="API call"
                ) from exc
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
