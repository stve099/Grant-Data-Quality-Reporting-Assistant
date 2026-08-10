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


def test_program_scoped_measure(rrh_profile):
    rows = [
        # RRH: 1 of 2 exits permanent (50%) -> below the 65% program target
        make_row(VALID_EXITED, client_id="C-1", household_id="H-1", **FOLLOWUPS_DONE),
        make_row(
            VALID_EXITED,
            client_id="C-2",
            household_id="H-2",
            exit_destination="Emergency shelter",
            **FOLLOWUPS_DONE,
        ),
        # A permanent-housing exit in another program must not count toward RRH-6
        make_row(
            VALID_EXITED,
            client_id="C-3",
            household_id="H-3",
            program="Permanent Supportive Housing",
            exit_destination="Homeownership",
            **FOLLOWUPS_DONE,
        ),
    ]
    prepared = prepare_dataset(make_source_df(rows), rrh_profile)
    analytics = compute_analytics(prepared, rrh_profile, as_of=TODAY)
    by_id = {m.id: m for m in analytics.measures}
    rrh6 = by_id["RRH-6"]
    assert rrh6.program == "Rapid Re-Housing"
    assert rrh6.actual == 50.0  # PSH exit excluded from the scoped rate
    assert rrh6.met is False
    assert rrh6.small_sample is True


def test_program_scoped_diversion_measure(hp_profile):
    # SN-6 scopes successful_exit_rate to Emergency Shelter, and the diversion
    # definition counts temporary housing as successful — a different metric on
    # a different program than RRH-6, so it gets its own guard.
    rows = [
        # ES exit to temporary housing: successful under the diversion definition.
        make_row(
            VALID_EXITED,
            client_id="C-1",
            household_id="H-1",
            program="Emergency Shelter",
            exit_destination="Transitional housing",
            **FOLLOWUPS_DONE,
        ),
        # ES exit to homelessness: not successful.
        make_row(
            VALID_EXITED,
            client_id="C-2",
            household_id="H-2",
            program="Emergency Shelter",
            exit_destination="Emergency shelter",
            **FOLLOWUPS_DONE,
        ),
        # A successful exit in another program must not count toward SN-6.
        make_row(
            VALID_EXITED,
            client_id="C-3",
            household_id="H-3",
            program="Rapid Re-Housing",
            exit_destination="Homeownership",
            **FOLLOWUPS_DONE,
        ),
    ]
    prepared = prepare_dataset(make_source_df(rows), hp_profile)
    analytics = compute_analytics(prepared, hp_profile, as_of=TODAY)
    by_id = {m.id: m for m in analytics.measures}
    sn6 = by_id["SN-6"]
    assert sn6.program == "Emergency Shelter"
    assert sn6.actual == 50.0  # 1 of 2 ES exits successful; RRH exit excluded
    assert sn6.met is False
    assert sn6.small_sample is True


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
