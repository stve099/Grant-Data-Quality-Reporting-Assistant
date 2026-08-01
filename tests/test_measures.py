"""Performance measure (goal-vs-actual) evaluation tests."""

from __future__ import annotations

import pytest

from grant_assistant.analytics import compute_analytics
from grant_assistant.ingestion import prepare_dataset
from tests.conftest import TODAY, VALID_EXITED, make_row, make_source_df

FOLLOWUPS_DONE = {
    "followup_3m": "2025-04-20",
    "followup_6m": "2025-07-20",
    "followup_12m": "2026-01-20",
}


@pytest.fixture(scope="module")
def measures_by_id(profile):
    rows = [
        make_row(client_id="C-1", household_id="H-1"),
        make_row(
            VALID_EXITED,
            client_id="C-2",
            household_id="H-2",
            entry_income=500,
            exit_income=900,
            **FOLLOWUPS_DONE,
        ),
        make_row(
            VALID_EXITED,
            client_id="C-3",
            household_id="H-3",
            exit_destination="Emergency shelter",
            entry_income=400,
            exit_income=400,
            **FOLLOWUPS_DONE,
        ),
    ]
    prepared = prepare_dataset(make_source_df(rows), profile)
    analytics = compute_analytics(prepared, profile, as_of=TODAY)
    return {m.id: m for m in analytics.measures}


def test_measure_not_met(measures_by_id):
    hs1 = measures_by_id["HS-1"]  # permanent housing rate target 60, actual 50
    assert hs1.actual == 50.0
    assert hs1.target == 60.0
    assert hs1.met is False


def test_measure_met(measures_by_id):
    hs2 = measures_by_id["HS-2"]  # % income increased target 40, actual 50 (1 of 2)
    assert hs2.actual == 50.0
    assert hs2.met is True


def test_followup_measure_resolves_dynamic_metric_key(measures_by_id):
    hs3 = measures_by_id["HS-3"]  # 6-month follow-up completion, 100%
    assert hs3.actual == 100.0
    assert hs3.met is True


def test_small_sample_flagged(measures_by_id):
    assert measures_by_id["HS-1"].small_sample is True  # only 2 exits


def test_all_configured_measures_evaluated(measures_by_id, profile):
    assert set(measures_by_id) == {m.id for m in profile.performance_measures}


def test_unknown_metric_yields_no_data(rrh_profile):
    rows = [make_row(client_id="C-1", household_id="H-1")]
    prepared = prepare_dataset(make_source_df(rows), rrh_profile)
    analytics = compute_analytics(prepared, rrh_profile, as_of=TODAY)
    by_id = {m.id: m for m in analytics.measures}
    # no exits at all: successful_exit_rate has no denominator
    assert by_id["RRH-1"].actual is None
    assert by_id["RRH-1"].met is None


def test_currency_measure_direction(rrh_profile):
    rows = [
        make_row(
            VALID_EXITED,
            client_id="C-2",
            household_id="H-2",
            entry_income=100,
            exit_income=400,
            **FOLLOWUPS_DONE,
        ),
    ]
    prepared = prepare_dataset(make_source_df(rows), rrh_profile)
    analytics = compute_analytics(prepared, rrh_profile, as_of=TODAY)
    by_id = {m.id: m for m in analytics.measures}
    rrh4 = by_id["RRH-4"]  # median income change target $150
    assert rrh4.actual == 300.0
    assert rrh4.met is True
