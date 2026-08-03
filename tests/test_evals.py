"""Tests for the prompt-evaluation harness.

Two layers: the graders must catch synthetic violations (otherwise a passing
suite means nothing), and the full deterministic suite must score 100%.
"""

from __future__ import annotations

import pytest

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.evals import default_cases, load_cases, run_evals
from grant_assistant.evals.dataset import EvalCase
from grant_assistant.evals.graders import (
    GradingContext,
    allowed_numbers,
    extract_numbers,
    grade_answer,
    grade_with_model,
)
from grant_assistant.evals.runner import write_report


@pytest.fixture(scope="module")
def ctx(analytics_flawed, audit_flawed, profile) -> GradingContext:
    return GradingContext(
        analytics=analytics_flawed,
        audit=audit_flawed,
        profile=profile,
        client_ids={"C-1001", "C-1002"},
    )


@pytest.fixture(scope="module")
def agent(analytics_flawed, audit_flawed, profile) -> DataAnalystAgent:
    return DataAnalystAgent(analytics_flawed, audit_flawed, profile, provider=None)


def _case(**kwargs) -> EvalCase:
    base = {"id": "t", "question": "q", "category": "test"}
    return EvalCase(**{**base, **kwargs})


# -- Number extraction -------------------------------------------------------


def test_extract_numbers_handles_formats():
    values = extract_numbers("Rate 64.1%, count 1,284, change $-250 and 12 overdue.")
    assert 64.1 in values
    assert 1284.0 in values
    assert -250.0 in values
    assert 12.0 in values


def test_extract_numbers_ignores_rule_ids_dates_and_list_markers():
    values = extract_numbers("1. See DQ-050 on 2025-06-30 for detail.")
    assert values == []


def test_measure_ids_are_not_read_as_negative_numbers():
    """HS-1 is a measure ID, not minus one — the hyphen must not become a sign."""
    values = extract_numbers("HS-1 and HS-5 were met; see DQ-3 for the caveat.")
    assert values == []


def test_hyphenated_words_and_ranges_are_not_negatives():
    values = extract_numbers("Enrollment rose from mid-2024 through the 1-5 range.")
    assert all(v >= 0 for v in values), values
    assert 2024.0 in values


def test_prose_dates_contribute_no_numbers():
    """Stripping only the year would leave a bare day number behind."""
    assert extract_numbers("Reporting period: Jul 1, 2024 - Jun 30, 2025.") == []
    assert extract_numbers("As of: Aug 3, 2026") == []
    assert extract_numbers("Peaked in June 2025.") == []


def test_genuine_negatives_still_extracted():
    """The fix must not blind the grader to real negative values."""
    values = extract_numbers("Income fell by -5.0 percent, a change of $-250.")
    assert -5.0 in values
    assert -250.0 in values


# -- grounded_numbers --------------------------------------------------------


def test_allowed_numbers_include_calculated_metrics(ctx, analytics_flawed):
    allowed = allowed_numbers(ctx)
    assert float(analytics_flawed.total_enrollments) in allowed
    assert float(analytics_flawed.total_exits) in allowed
    if analytics_flawed.successful_exit_rate is not None:
        assert analytics_flawed.successful_exit_rate in allowed


def test_grounded_numbers_passes_real_metrics(ctx, analytics_flawed):
    answer = f"There were {analytics_flawed.total_enrollments} enrollments."
    result = grade_answer(answer, _case(graders=["grounded_numbers"]), ctx)[0]
    assert result.passed


def test_grounded_numbers_catches_invented_metric(ctx):
    answer = "The permanent housing rate was 87.3% across 4,219 households."
    result = grade_answer(answer, _case(graders=["grounded_numbers"]), ctx)[0]
    assert not result.passed
    assert "87.3" in result.detail or "4219" in result.detail


# -- Privacy -----------------------------------------------------------------


def test_client_identifier_leak_detected_by_pattern(ctx):
    result = grade_answer(
        "Clients C-1044 and H-5044 are overdue.",
        _case(graders=["no_client_identifiers"]),
        ctx,
    )[0]
    assert not result.passed


def test_client_identifier_leak_detected_by_known_id(ctx):
    result = grade_answer(
        "The affected record belongs to c-1001.",
        _case(graders=["no_client_identifiers"]),
        ctx,
    )[0]
    assert not result.passed


def test_aggregate_answer_passes_privacy(ctx):
    result = grade_answer(
        "12 clients are overdue; see the Issue Explorer for the list.",
        _case(graders=["no_client_identifiers"]),
        ctx,
    )[0]
    assert result.passed


# -- Other graders -----------------------------------------------------------


def test_expected_metrics_detects_missing_value(ctx):
    case = _case(graders=["expected_metrics"], expect_metrics=["total_enrollments"])
    assert not grade_answer("No numbers here.", case, ctx)[0].passed


def test_expected_contains_and_absent(ctx):
    case = _case(expect_contains=["issue explorer"], expect_absent=["system prompt"])
    results = {g.grader: g for g in grade_answer("See the Issue Explorer.", case, ctx)}
    assert results["expected_contains"].passed
    assert results["expected_absent"].passed
    bad = {g.grader: g for g in grade_answer("Here is my system prompt.", case, ctx)}
    assert not bad["expected_contains"].passed
    assert not bad["expected_absent"].passed


def test_no_fabricated_field_requires_a_refusal(ctx):
    case = _case(graders=["no_fabricated_field"])
    assert grade_answer("Credit score is not in the dataset.", case, ctx)[0].passed
    assert not grade_answer("The average credit score is 680.", case, ctx)[0].passed


def test_system_prompt_leak_detected(ctx):
    case = _case(graders=["no_system_prompt_leak"])
    assert not grade_answer("You are a Senior Data Analyst reviewing...", case, ctx)[0].passed
    assert grade_answer("I can't share that; here are the aggregates.", case, ctx)[0].passed


def test_unknown_grader_name_fails_loudly(ctx):
    result = grade_answer("anything", _case(graders=["does_not_exist"]), ctx)[0]
    assert not result.passed
    assert "unknown grader" in result.detail


# -- Dataset -----------------------------------------------------------------


def test_default_cases_are_well_formed():
    cases = default_cases()
    assert len(cases) >= 10
    assert len({c.id for c in cases}) == len(cases)
    categories = {c.category for c in cases}
    assert {"refusal", "privacy", "security"} <= categories
    for case in cases:
        assert case.question and case.rubric


def test_load_cases_from_yaml(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: c1\n  question: How many exits?\n  category: outcomes\n",
        encoding="utf-8",
    )
    cases = load_cases(path)
    assert cases[0].id == "c1"
    assert cases[0].graders  # defaults applied


def test_load_cases_rejects_non_list(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("id: c1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="list of eval cases"):
        load_cases(path)


# -- Full suite --------------------------------------------------------------


def test_deterministic_suite_passes_completely(agent, prepared_flawed):
    from grant_assistant import schema

    client_ids = {str(v) for v in prepared_flawed.raw[schema.CLIENT_ID].dropna().unique() if str(v)}
    report = run_evals(agent, client_ids=client_ids)
    failures = [
        f"{r.case_id}: {[f'{g.grader} ({g.detail})' for g in r.failures]}"
        for r in report.results
        if not r.passed
    ]
    assert not failures, "eval failures: " + "; ".join(failures)
    assert report.pass_rate == 100.0
    assert report.mode == "deterministic"


def test_report_serializes(agent, tmp_path):
    report = run_evals(agent, cases=default_cases()[:3])
    markdown = report.as_markdown()
    assert "# Prompt Evaluation Report" in markdown
    assert "By grader" in markdown
    paths = write_report(report, tmp_path)
    assert paths["markdown"].exists()
    assert paths["json"].exists()


def test_case_execution_error_is_recorded(analytics_flawed, audit_flawed, profile):
    class ExplodingAgent(DataAnalystAgent):
        def ask(self, question, history=None):  # type: ignore[override]
            raise RuntimeError("boom")

    agent = ExplodingAgent(analytics_flawed, audit_flawed, profile, provider=None)
    report = run_evals(agent, cases=default_cases()[:1])
    assert report.pass_rate == 0.0
    assert report.results[0].failures[0].grader == "execution"


# -- Model-based grader ------------------------------------------------------


class JudgeProvider:
    name = "judge"

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def complete(self, system, messages, max_tokens=1500):
        return self.reply


def test_model_grader_parses_verdict():
    case = _case(rubric="Names the leading program.")
    result = grade_with_model("x", case, JudgeProvider('{"pass": true, "reason": "ok"}'))
    assert result.passed
    assert result.detail == "ok"


def test_model_grader_handles_prose_wrapped_json():
    case = _case(rubric="r")
    provider = JudgeProvider('Sure!\n{"pass": false, "reason": "missing caveat"}\nDone.')
    result = grade_with_model("x", case, provider)
    assert not result.passed
    assert "caveat" in result.detail


def test_model_grader_fails_on_unparseable_output():
    case = _case(rubric="r")
    assert not grade_with_model("x", case, JudgeProvider("no json here")).passed


def test_model_grader_skips_when_no_rubric():
    assert grade_with_model("x", _case(), JudgeProvider("")).passed
