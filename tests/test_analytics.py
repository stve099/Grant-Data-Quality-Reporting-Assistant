"""Analytics calculation tests on a small, fully controlled dataset."""

from __future__ import annotations

import pytest

from grant_assistant.analytics import compute_analytics
from grant_assistant.analytics.metrics import NOT_REPORTED_VALUES
from grant_assistant.ingestion import prepare_dataset
from tests.conftest import TODAY, VALID_EXITED, make_row, make_source_df

FOLLOWUPS_DONE = {
    "followup_3m": "2025-04-20",
    "followup_6m": "2025-07-20",
    "followup_12m": "2026-01-20",
}


@pytest.fixture(scope="module")
def controlled_rows() -> list[dict]:
    return [
        # Active clients
        make_row(client_id="C-1", household_id="H-1", household_size=2, adults=1, children=1),
        make_row(client_id="C-5", household_id="H-5", program="Emergency Shelter"),
        # Exit to permanent housing with income gain (+400)
        make_row(
            VALID_EXITED,
            client_id="C-2",
            household_id="H-2",
            entry_income=500,
            exit_income=900,
            **FOLLOWUPS_DONE,
        ),
        # Exit to a homeless destination, income unchanged
        make_row(
            VALID_EXITED,
            client_id="C-3",
            household_id="H-3",
            exit_destination="Emergency shelter",
            entry_income=400,
            exit_income=400,
            **FOLLOWUPS_DONE,
        ),
        # Exit to temporary housing with income gain (+200)
        make_row(
            VALID_EXITED,
            client_id="C-4",
            household_id="H-4",
            program="Emergency Shelter",
            exit_destination="Transitional housing",
            entry_income=0,
            exit_income=200,
            **FOLLOWUPS_DONE,
        ),
        # Exit to permanent housing but exit income missing
        make_row(
            VALID_EXITED,
            client_id="C-6",
            household_id="H-6",
            program="Permanent Supportive Housing",
            exit_destination="Homeownership",
            entry_income=300,
            exit_income="",
            **FOLLOWUPS_DONE,
        ),
    ]


@pytest.fixture(scope="module")
def analytics(controlled_rows, profile):
    prepared = prepare_dataset(make_source_df(controlled_rows), profile)
    return compute_analytics(prepared, profile, as_of=TODAY)


def test_population_totals(analytics):
    assert analytics.total_enrollments == 6
    assert analytics.households_served == 6
    assert analytics.total_individuals == 7  # one 2-person household, five singles
    assert analytics.total_adults == 6
    assert analytics.total_children == 1
    assert analytics.active_enrollments == 2


def test_exit_metrics(analytics):
    assert analytics.total_exits == 4
    assert analytics.exit_rate == 66.7
    assert analytics.successful_exits == 2  # permanent housing only for this profile
    assert analytics.successful_exit_rate == 50.0
    assert analytics.permanent_housing_exits == 2
    assert analytics.permanent_housing_rate == 50.0


def test_exit_destination_breakdown(analytics):
    assert analytics.exit_destination_breakdown == {
        "Rental by client, no subsidy": 1,
        "Emergency shelter": 1,
        "Transitional housing": 1,
        "Homeownership": 1,
    }
    assert analytics.exit_category_breakdown == {
        "permanent_housing": 2,
        "homeless": 1,
        "temporary_housing": 1,
    }


def test_income_change_metrics(analytics):
    # Pairs: C-2 (+400), C-3 (0), C-4 (+200); C-6 excluded (missing exit income)
    assert analytics.n_income_pairs == 3
    assert analytics.avg_income_change == 200.0
    assert analytics.median_income_change == 200.0
    assert analytics.pct_income_increased == 66.7
    assert sorted(analytics.income_changes) == [0.0, 200.0, 400.0]


def test_successful_exits_respect_profile_definition(controlled_rows, rrh_profile):
    prepared = prepare_dataset(make_source_df(controlled_rows), rrh_profile)
    analytics = compute_analytics(prepared, rrh_profile, as_of=TODAY)
    # rapid_rehousing counts temporary housing as successful: C-2, C-4, C-6
    assert analytics.successful_exits == 3
    assert analytics.successful_exit_rate == 75.0
    assert analytics.permanent_housing_exits == 2


def test_program_breakdown(analytics):
    by_name = {p.program: p for p in analytics.programs}
    assert by_name["Rapid Re-Housing"].enrollments == 3
    assert by_name["Rapid Re-Housing"].exits == 2
    assert by_name["Rapid Re-Housing"].successful_exits == 1
    assert by_name["Rapid Re-Housing"].successful_exit_rate == 50.0
    assert by_name["Emergency Shelter"].exits == 1
    assert by_name["Permanent Supportive Housing"].successful_exit_rate == 100.0
    assert all(p.small_sample for p in analytics.programs)  # fewer than 10 exits each


def test_demographics_and_age_groups(analytics):
    assert analytics.demographics["gender"]["Female"] == 6
    assert analytics.age_groups.get("25–34") == 6
    assert analytics.household_size_distribution == {"1": 5, "2": 1}


def test_unreported_demographics_totals_the_absent_categories(analytics_flawed):
    """The model must be able to retrieve this instead of summing categories."""
    gender = analytics_flawed.demographics["gender"]
    expected = sum(
        count for value, count in gender.items() if value.strip().casefold() in NOT_REPORTED_VALUES
    )
    assert expected > 0, "flawed sample should contain unreported responses"
    assert analytics_flawed.unreported_demographics["gender"] == expected
    # Real values are never counted as absent.
    assert analytics_flawed.unreported_demographics["gender"] < sum(gender.values())


def test_unreported_demographics_are_retrievable_as_metrics(analytics_flawed):
    lookup = analytics_flawed.metric_lookup()
    assert lookup["unreported_gender"] == analytics_flawed.unreported_demographics["gender"]


def test_unreported_is_zero_when_every_response_is_recorded(analytics):
    """The clean sample uses only controlled values, so nothing is unreported."""
    assert analytics.unreported_demographics["gender"] == 0


def test_monthly_trends(analytics):
    assert analytics.monthly_enrollments == {"2024-08": 6}
    assert analytics.monthly_exits == {"2025-01": 4}


def test_followup_metrics_all_complete(analytics):
    for fu in analytics.followups:
        assert fu.due == 4
        assert fu.completed_of_due == 4
        assert fu.overdue == 0
        assert fu.completion_rate == 100.0
    assert analytics.overall_followup_completion_rate == 100.0
    assert analytics.total_overdue_followups == 0


def test_duplicates_removed_before_analytics(controlled_rows, profile):
    rows = [*controlled_rows, dict(controlled_rows[0])]  # exact duplicate enrollment
    prepared = prepare_dataset(make_source_df(rows), profile)
    analytics = compute_analytics(prepared, profile, as_of=TODAY)
    assert analytics.total_enrollments == 6
    assert analytics.duplicates_removed == 1
    assert any("duplicate" in note.lower() for note in analytics.notes)


def test_metric_lookup_contains_headline_metrics(analytics):
    lookup = analytics.metric_lookup()
    assert lookup["total_enrollments"] == 6
    assert lookup["successful_exit_rate"] == 50.0
    assert lookup["followup_3_month_completion_rate"] == 100.0
