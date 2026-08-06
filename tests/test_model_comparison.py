"""Model comparison tests.

Ranking is the whole product here, so the ordering rules get the attention: a
model that averages well but collapses occasionally must not outrank a steady
one, and an unreachable model must not silently vanish from the table.
"""

from __future__ import annotations

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.evals.comparison import ComparisonResult, ModelResult, compare_models
from grant_assistant.evals.dataset import default_cases


class _Provider:
    """Deterministic stand-in; the analyst falls back to calculated answers."""

    def __init__(self, name: str) -> None:
        self.name = "fake"
        self.model = name


def _result(model: str, rates: list[float], tokens: int = 0, **kwargs) -> ModelResult:
    return ModelResult(model=model, pass_rates=rates, total_tokens=tokens, **kwargs)


# -- Ranking -----------------------------------------------------------------


def test_higher_mean_wins():
    comparison = ComparisonResult(results=[_result("weak", [80.0]), _result("strong", [95.0])])
    assert [r.model for r in comparison.ranked] == ["strong", "weak"]
    assert comparison.winner is not None
    assert comparison.winner.model == "strong"


def test_a_steady_model_beats_an_erratic_one_on_the_same_mean():
    """Averaging 90 by scoring 90 twice is better than 100 and 80."""
    comparison = ComparisonResult(
        results=[_result("erratic", [100.0, 80.0]), _result("steady", [90.0, 90.0])]
    )
    assert comparison.ranked[0].model == "steady"


def test_cost_breaks_a_genuine_tie():
    comparison = ComparisonResult(
        results=[
            _result("expensive", [95.0, 95.0], tokens=900_000),
            _result("cheap", [95.0, 95.0], tokens=90_000),
        ]
    )
    assert comparison.ranked[0].model == "cheap"


def test_failed_models_are_excluded_from_the_ranking_but_not_the_report():
    comparison = ComparisonResult(
        results=[_result("good", [90.0]), ModelResult(model="unreachable", error="no key")]
    )
    assert [r.model for r in comparison.ranked] == ["good"]
    assert "unreachable" in comparison.as_markdown()
    assert "no key" in comparison.as_markdown()


def test_no_winner_when_every_model_failed():
    comparison = ComparisonResult(results=[ModelResult(model="a", error="boom")])
    assert comparison.winner is None


def test_mean_is_zero_without_runs():
    assert ModelResult(model="x").mean_pass_rate == 0.0


# -- Reporting ---------------------------------------------------------------


def test_markdown_reports_mean_worst_and_cost():
    comparison = ComparisonResult(
        results=[_result("m1", [100.0, 80.0], tokens=1234)], runs_per_model=2
    )
    text = comparison.as_markdown()
    assert "ran the evaluation 2 time(s)" in text
    assert "90.0%" in text  # mean
    assert "80.0%" in text  # worst run, which a mean alone would hide
    assert "1,234" in text


def test_intermittent_cases_are_named():
    comparison = ComparisonResult(
        results=[_result("m1", [100.0, 50.0], flaky_cases=["refusal-causal-claim"])]
    )
    assert "refusal-causal-claim" in comparison.as_markdown()


# -- Sweeping ----------------------------------------------------------------


def test_each_model_is_evaluated(analytics_flawed, audit_flawed, profile):
    def factory(model: str) -> DataAnalystAgent:
        return DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=_Provider(model))

    comparison = compare_models(["model-a", "model-b"], factory, cases=default_cases()[:2], runs=1)
    assert {r.model for r in comparison.results} == {"model-a", "model-b"}
    assert all(r.ok for r in comparison.results)
    assert all(len(r.pass_rates) == 1 for r in comparison.results)


def test_runs_are_repeated(analytics_flawed, audit_flawed, profile):
    def factory(model: str) -> DataAnalystAgent:
        return DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=_Provider(model))

    comparison = compare_models(["m"], factory, cases=default_cases()[:1], runs=3)
    assert len(comparison.results[0].pass_rates) == 3
    assert comparison.runs_per_model == 3


def test_an_unreachable_model_does_not_stop_the_sweep(analytics_flawed, audit_flawed, profile):
    """The other models are still worth comparing."""

    def factory(model: str) -> DataAnalystAgent:
        if model == "broken":
            raise RuntimeError("no credentials for this model")
        return DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=_Provider(model))

    comparison = compare_models(["broken", "fine"], factory, cases=default_cases()[:1])
    by_model = {r.model: r for r in comparison.results}
    assert not by_model["broken"].ok
    assert "no credentials" in by_model["broken"].error
    assert by_model["fine"].ok


def test_a_model_that_fails_mid_sweep_is_recorded(analytics_flawed, audit_flawed, profile):
    class Exploding(DataAnalystAgent):
        def ask(self, question, history=None):  # type: ignore[override]
            raise RuntimeError("provider died")

    def factory(model: str) -> DataAnalystAgent:
        return Exploding(analytics_flawed, audit_flawed, profile, provider=_Provider(model))

    comparison = compare_models(["m"], factory, cases=default_cases()[:1])
    # The runner records per-case failures rather than raising, so the sweep
    # completes with a low score instead of an error.
    assert comparison.results[0].ok
    assert comparison.results[0].mean_pass_rate == 0.0
