"""AI Data Analyst agent: provider abstraction, grounding, and insights."""

from grant_assistant.agents.analyst import DataAnalystAgent
from grant_assistant.agents.context import build_fact_sheet
from grant_assistant.agents.insights import InsightReport, generate_insights
from grant_assistant.agents.provider import (
    AIProvider,
    AIProviderError,
    AnthropicProvider,
    OpenAICompatibleProvider,
    get_provider,
)

__all__ = [
    "AIProvider",
    "AIProviderError",
    "AnthropicProvider",
    "DataAnalystAgent",
    "InsightReport",
    "OpenAICompatibleProvider",
    "build_fact_sheet",
    "generate_insights",
    "get_provider",
]
