"""Provider-agnostic AI abstraction.

The application talks to a minimal :class:`AIProvider` protocol. Anthropic
Claude is the built-in implementation; an OpenAI-compatible provider can be
added by implementing the same protocol and extending :func:`get_provider`.
API keys come from environment variables only — never from config files.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"
MODEL_ENV_VAR = "GRANT_ASSISTANT_MODEL"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"


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


class AnthropicProvider:
    """Anthropic Claude implementation of :class:`AIProvider`."""

    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
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
                system=system,
                messages=payload,
            )
        except Exception as exc:
            raise AIProviderError(f"Claude API call failed: {exc}") from exc
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
        for _ in range(max_rounds):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=convo,
                    tools=tools,  # type: ignore[arg-type]
                )
            except Exception as exc:
                raise AIProviderError(f"Claude API call failed: {exc}") from exc
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


def ai_available() -> bool:
    """True when an API key is configured for the default provider."""
    return bool(os.environ.get(API_KEY_ENV_VAR, "").strip())


def get_provider(model: str | None = None) -> AIProvider | None:
    """Return a configured provider, or None to run in non-AI fallback mode."""
    if not ai_available():
        logger.info("No %s set — running in non-AI fallback mode.", API_KEY_ENV_VAR)
        return None
    try:
        return AnthropicProvider(model=model)
    except AIProviderError as exc:
        logger.warning("AI provider unavailable: %s", exc)
        return None
