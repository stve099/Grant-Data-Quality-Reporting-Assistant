"""What the analyst does when the AI path fails.

This is real shipped behaviour that nothing verified: a provider that errors
mid-report must not take the report with it. Every AI entry point has a
deterministic answer already computed, and the contract is that a failure falls
back to it silently rather than propagating.

The failure has to be invisible in the output but visible in the logs — a user
should still get their report; an operator should still learn the provider
broke.
"""

from __future__ import annotations

import logging

import pytest

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.agents.provider import AIProviderError


class FailingProvider:
    """A provider that is configured but broken — the interesting case."""

    name = "failing"
    model = "failing-1"

    def complete(self, system, messages, max_tokens=1500):
        raise AIProviderError("upstream returned 503")

    def complete_thinking(self, system, messages, max_tokens=3000, budget_tokens=2000):
        raise AIProviderError("upstream returned 503")

    def complete_with_tools(self, system, messages, tools, executor, max_tokens=1500, max_rounds=6):
        raise AIProviderError("upstream returned 503")


class TextProvider:
    """A provider that works, for comparison."""

    name = "fake"
    model = "fake-1"

    def __init__(self, text: str = "AI narrative.") -> None:
        self.text = text
        self.calls = 0

    def complete(self, system, messages, max_tokens=1500):
        self.calls += 1
        return self.text


@pytest.fixture()
def failing_agent(analytics_flawed, audit_flawed, profile) -> DataAnalystAgent:
    return DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=FailingProvider())


@pytest.fixture()
def deterministic_agent(analytics_flawed, audit_flawed, profile) -> DataAnalystAgent:
    return DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=None)


# -- Fallback ----------------------------------------------------------------


def test_narrated_insights_falls_back_to_the_deterministic_report(
    failing_agent, deterministic_agent
):
    """A broken provider must not cost the user their insights."""
    assert (
        failing_agent.narrated_insights() == deterministic_agent.proactive_insights().as_markdown()
    )


def test_executive_summary_falls_back(failing_agent, deterministic_agent):
    assert failing_agent.executive_summary() == deterministic_agent.executive_summary()


def test_ask_falls_back_and_says_why(failing_agent, deterministic_agent):
    """Unlike the report paths, a chat answer tells the user the AI was down.

    That asymmetry is right: a report is a document whose provenance is stated
    elsewhere, while someone waiting on a chat answer needs to know they got the
    deterministic one.
    """
    question = "Which program had the highest successful exit rate?"
    answer = failing_agent.ask(question)

    assert "AI provider unavailable" in answer
    # The substance is identical to the pure deterministic answer.
    substance = deterministic_agent.ask(question).split("\n\n", 1)[1]
    assert substance in answer


def test_the_failure_is_logged_even_though_it_is_invisible(failing_agent, caplog):
    """The user sees a report; the operator has to see the cause."""
    with caplog.at_level(logging.WARNING):
        failing_agent.executive_summary()
    assert any("503" in record.message or "503" in str(record.args) for record in caplog.records)


# -- The working path, for contrast ------------------------------------------


def test_a_working_provider_is_actually_used(analytics_flawed, audit_flawed, profile):
    provider = TextProvider("Polished narrative.")
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=provider)
    assert agent.executive_summary() == "Polished narrative."
    assert provider.calls == 1


def test_thinking_is_preferred_for_narration_when_offered(analytics_flawed, audit_flawed, profile):
    """narrated_insights uses extended thinking where the backend has it."""

    class ThinkingProvider(TextProvider):
        def __init__(self) -> None:
            super().__init__()
            self.thinking_calls = 0

        def complete_thinking(self, system, messages, max_tokens=3000, budget_tokens=2000):
            self.thinking_calls += 1
            return "Thought-through narrative."

    provider = ThinkingProvider()
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=provider)
    assert agent.narrated_insights() == "Thought-through narrative."
    assert provider.thinking_calls == 1
    assert provider.calls == 0


def test_a_backend_without_thinking_uses_plain_completion(analytics_flawed, audit_flawed, profile):
    provider = TextProvider("Plain narrative.")
    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=provider)
    assert agent.narrated_insights() == "Plain narrative."
    assert provider.calls == 1


# -- Deterministic answers by intent -----------------------------------------
#
# Non-AI mode is the documented default, so each routed intent needs to produce
# a real answer rather than a shrug.


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Which program had the highest successful exit rate?", "successful-exit rate"),
        ("Which program had the most exits?", "number of exits"),
        ("Which program had the highest permanent housing rate?", "permanent-housing rate"),
        ("What are the data quality issues?", "data quality score"),
        ("Are any metrics distorted by small samples?", "small-sample"),
        ("What are the enrollment trends?", "Non-AI mode"),
    ],
)
def test_deterministic_intents_answer_substantively(deterministic_agent, question, expected):
    answer = deterministic_agent.ask(question)
    assert expected.casefold() in answer.casefold(), answer


def test_an_unmatched_question_says_what_is_available(deterministic_agent):
    """An honest miss names the metrics rather than inventing an answer."""
    answer = deterministic_agent.ask("What is the average credit score?")
    assert "not available" in answer.casefold() or "could not match" in answer.casefold()
    assert "total_enrollments" in answer


# -- The recorded trend in non-AI mode ----------------------------------------
#
# Non-AI mode is a first-class mode here, so history reaching only the model's
# fact sheet would leave every keyless installation unable to answer the one
# question the history store exists for.


def _agent_with_history(tmp_path, analytics, audit_before, audit_after, profile):
    from grant_assistant.agents import DataAnalystAgent
    from grant_assistant.history import build_history_summary, load_history, record_run

    db = tmp_path / "history.db"
    record_run(profile, audit_before, analytics, db, label="Q1")
    summary = build_history_summary(load_history(db), audit_after, profile.profile_id)
    return DataAnalystAgent(analytics, audit_after, profile, provider=None, history=summary)


def test_a_data_quality_question_reports_the_recorded_movement(
    tmp_path, analytics_flawed, audit_flawed, audit_clean, profile
):
    agent = _agent_with_history(tmp_path, analytics_flawed, audit_flawed, audit_clean, profile)
    answer = agent.ask("is data quality improving over time?")

    assert "Across recorded runs" in answer
    assert "recorded run(s)" in answer


def test_a_trend_question_reports_it_too(
    tmp_path, analytics_flawed, audit_flawed, audit_clean, profile
):
    agent = _agent_with_history(tmp_path, analytics_flawed, audit_flawed, audit_clean, profile)
    assert "Across recorded runs" in agent.ask("what is the trend over time?")


def test_without_history_the_answer_is_unchanged(analytics_flawed, audit_flawed, profile):
    """No recorded runs must add nothing rather than an empty heading."""
    from grant_assistant.agents import DataAnalystAgent

    agent = DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=None)
    answer = agent.ask("any data quality issues?")
    assert "Across recorded runs" not in answer
    assert answer.strip().endswith(agent.audit.executive_summary().strip())


def test_the_deterministic_trend_answer_does_no_arithmetic_of_its_own(
    tmp_path, analytics_flawed, audit_flawed, audit_clean, profile
):
    """Every figure in the sentence comes from the summary, as in AI mode."""
    agent = _agent_with_history(tmp_path, analytics_flawed, audit_flawed, audit_clean, profile)
    assert agent.history is not None
    answer = agent.ask("is data quality improving over time?")
    assert f"{abs(agent.history.since_previous):.1f} points" in answer
