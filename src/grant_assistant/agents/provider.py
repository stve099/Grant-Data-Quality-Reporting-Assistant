"""Provider-agnostic AI abstraction.

The application talks to a minimal :class:`AIProvider` protocol. Anthropic
Claude is the built-in implementation; an OpenAI-compatible provider can be
added by implementing the same protocol and extending :func:`get_provider`.
API keys come from environment variables only — never from config files.
"""

from __future__ import annotations

import logging
import os
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
