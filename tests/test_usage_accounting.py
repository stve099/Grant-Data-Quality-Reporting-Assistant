"""Token, cache, and cost accounting.

Cost is only ever reported from rates the operator supplies. A built-in price
table would go stale silently, and a wrong number about money is worse than no
number, so "unknown" has to be a first-class answer.
"""

from __future__ import annotations

from types import SimpleNamespace

from grant_assistant.agents.provider import (
    INPUT_COST_ENV_VAR,
    OUTPUT_COST_ENV_VAR,
    UsageStats,
)


def _anthropic_usage(inp=100, out=20, write=0, read=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=write,
        cache_read_input_tokens=read,
    )


def _openai_usage(inp=100, out=20, cached=0, reasoning=0):
    return SimpleNamespace(
        prompt_tokens=inp,
        completion_tokens=out,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached) if cached else None,
        completion_tokens_details=(
            SimpleNamespace(reasoning_tokens=reasoning) if reasoning else None
        ),
    )


# -- Per-call recording ------------------------------------------------------


def test_anthropic_usage_is_recorded():
    stats = UsageStats()
    stats.record(_anthropic_usage(inp=120, out=30, write=900, read=0))
    assert (stats.input_tokens, stats.output_tokens) == (120, 30)
    assert stats.cache_creation_tokens == 900
    assert not stats.cache_hit


def test_cache_hit_is_detected():
    stats = UsageStats()
    stats.record(_anthropic_usage(read=900))
    assert stats.cache_hit


def test_openai_cached_tokens_are_recorded():
    """The OpenAI path reported no cache data at all before this."""
    stats = UsageStats()
    stats.record_openai(_openai_usage(inp=500, cached=384))
    assert stats.cache_read_tokens == 384
    assert stats.cache_hit


def test_openai_reasoning_tokens_are_recorded():
    """An empty answer with reasoning tokens means the budget ran out."""
    stats = UsageStats()
    stats.record_openai(_openai_usage(out=20, reasoning=18))
    assert stats.reasoning_tokens == 18
    assert "reasoning=18" in stats.summary()


def test_missing_detail_objects_are_tolerated():
    """Not every OpenAI-compatible endpoint returns the nested details."""
    stats = UsageStats()
    stats.record_openai(SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    assert stats.cache_read_tokens == 0
    assert stats.reasoning_tokens == 0


# -- Session totals ----------------------------------------------------------


def test_totals_accumulate_across_calls():
    stats = UsageStats()
    stats.record(_anthropic_usage(inp=100, out=20))
    stats.record(_anthropic_usage(inp=200, out=30))
    assert stats.calls == 2
    assert stats.total_input_tokens == 300
    assert stats.total_output_tokens == 50
    # The per-call figures still describe the latest call only.
    assert stats.input_tokens == 200


def test_totals_span_both_provider_shapes():
    stats = UsageStats()
    stats.record(_anthropic_usage(inp=100, out=10))
    stats.record_openai(_openai_usage(inp=50, out=5, reasoning=40))
    assert stats.calls == 2
    assert stats.total_input_tokens == 150
    assert stats.total_reasoning_tokens == 40


def test_session_summary_reads_plainly():
    stats = UsageStats()
    stats.record_openai(_openai_usage(inp=1000, out=200, cached=500, reasoning=90))
    text = stats.session_summary()
    assert "1 call(s)" in text
    assert "1,200 tokens" in text
    assert "500 read from cache" in text
    assert "90 reasoning" in text


# -- Cost --------------------------------------------------------------------


def test_cost_is_none_without_configured_rates(monkeypatch):
    monkeypatch.delenv(INPUT_COST_ENV_VAR, raising=False)
    monkeypatch.delenv(OUTPUT_COST_ENV_VAR, raising=False)
    stats = UsageStats()
    stats.record(_anthropic_usage(inp=1_000_000, out=1_000_000))
    assert stats.estimated_cost_usd() is None
    assert "$" not in stats.session_summary()


def test_cost_uses_the_configured_rates(monkeypatch):
    monkeypatch.setenv(INPUT_COST_ENV_VAR, "3.00")
    monkeypatch.setenv(OUTPUT_COST_ENV_VAR, "15.00")
    stats = UsageStats()
    stats.record(_anthropic_usage(inp=1_000_000, out=1_000_000))
    assert stats.estimated_cost_usd() == 18.0
    assert "$18.0000" in stats.session_summary()


def test_one_configured_rate_is_enough(monkeypatch):
    monkeypatch.setenv(INPUT_COST_ENV_VAR, "3.00")
    monkeypatch.delenv(OUTPUT_COST_ENV_VAR, raising=False)
    stats = UsageStats()
    stats.record(_anthropic_usage(inp=1_000_000, out=1_000_000))
    assert stats.estimated_cost_usd() == 3.0


def test_an_unparseable_rate_is_ignored_not_guessed(monkeypatch):
    monkeypatch.setenv(INPUT_COST_ENV_VAR, "three dollars")
    monkeypatch.delenv(OUTPUT_COST_ENV_VAR, raising=False)
    stats = UsageStats()
    stats.record(_anthropic_usage(inp=1_000_000))
    assert stats.estimated_cost_usd() is None
