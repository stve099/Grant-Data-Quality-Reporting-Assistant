"""AI Data Analyst agent: provider abstraction, grounding, and insights."""

from grant_assistant.agents.analyst import DataAnalystAgent
from grant_assistant.agents.context import build_fact_sheet
from grant_assistant.agents.insights import InsightReport, generate_insights
from grant_assistant.agents.provider import (
    AIProvider,
    AIProviderError,
    AIProviderFailure,
    AnthropicProvider,
    OpenAICompatibleProvider,
    complete_async,
    get_provider,
)

__all__ = [
    "AIProvider",
    "AIProviderError",
    "AIProviderFailure",
    "AnthropicProvider",
    "DataAnalystAgent",
    "InsightReport",
    "OpenAICompatibleProvider",
    "build_fact_sheet",
    "complete_async",
    "generate_insights",
    "get_provider",
]
