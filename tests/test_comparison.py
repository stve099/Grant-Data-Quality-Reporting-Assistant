"""Period-over-period comparison tests."""

from __future__ import annotations

import pytest

from grant_assistant.analytics import compute_analytics
from grant_assistant.analytics.comparison import compare_analytics
from grant_assistant.ingestion import prepare_dataset
from tests.conftest import TODAY, VALID_EXITED, make_row, make_source_df

FU = {"followup_3m": "2025-04-20", "followup_6m": "2025-07-20", "followup_12m": "2026-01-20"}


def _analytics(rows, profile):
    return compute_analytics(prepare_dataset(make_source_df(rows), profile), profile, as_of=TODAY)


@pytest.fixture(scope="module")
def comparison(profile):
    # Current period: 2 of 3 exits successful (66.7%)
    current = _analytics(
        [
            make_row(VALID_EXITED, client_id="C-1", household_id="H-1", **FU),
            make_row(
                VALID_EXITED,
                client_id="C-2",
                household_id="H-2",
                exit_destination="Homeownership",
                **FU,
            ),
            make_row(
                VALID_EXITED,
                client_id="C-3",
                household_id="H-3",
                exit_destination="Emergency shelter",
                **FU,
            ),
        ],
        profile,
    )
    # Prior period: 1 of 2 exits successful (50%)
    prior = _analytics(
        [
            make_row(VALID_EXITED, client_id="P-1", household_id="H-4", **FU),
            make_row(
                VALID_EXITED,
                client_id="P-2",
                household_id="H-5",
                exit_destination="Emergency shelter",
                **FU,
            ),
        ],
        profile,
    )
    return compare_analytics(current, prior, "Q2", "Q1")


def test_headline_deltas(comparison):
    by_key = {d.key: d for d in comparison.headline}
    exits = by_key["total_exits"]
    assert exits.prior == 2 and exits.current == 3
    assert exits.delta == 1
    assert exits.pct_change == 50.0
    assert exits.improved is True

    rate = by_key["successful_exit_rate"]
    assert rate.prior == 50.0 and rate.current == 66.7
    assert rate.improved is True


def test_lower_is_better_metrics(comparison):
    overdue = {d.key: d for d in comparison.headline}["total_overdue_followups"]
    assert overdue.current == 0 and overdue.prior == 0
    assert overdue.improved is None  # no movement


def test_program_deltas_and_small_sample_flag(comparison):
    rrh = next(p for p in comparison.programs if p.program == "Rapid Re-Housing")
    assert rrh.prior_rate == 50.0
    assert rrh.current_rate == 66.7
    assert rrh.delta == 16.7
    assert rrh.small_sample is True  # tiny fixture counts


def test_narrative_mentions_improvement_and_causation_caveat(comparison):
    text = " ".join(comparison.narrative)
    assert "Improved vs. prior period" in text
    assert "not causal" in text


def test_metric_delta_formatting(comparison):
    rate = next(d for d in comparison.headline if d.key == "successful_exit_rate")
    assert rate.format_value(rate.current) == "66.7%"
    median = next(d for d in comparison.headline if d.key == "median_income_change")
    assert median.format_value(100.0) == "$100"
