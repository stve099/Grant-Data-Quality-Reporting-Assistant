"""Analytics calculation tests on a small, fully controlled dataset."""

from __future__ import annotations

import pandas as pd
import pytest

from grant_assistant import schema
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


# -- Length of stay ----------------------------------------------------------


def test_median_length_of_stay_uses_only_completed_stays(analytics):
    """An active client's stay is not yet a length; counting it understates."""
    assert analytics.n_length_of_stay <= analytics.total_exits
    assert analytics.median_length_of_stay_days is not None
    assert analytics.median_length_of_stay_days > 0


def test_length_of_stay_ignores_exits_before_enrollment(profile):
    """A negative span is an audit finding, not a short stay."""
    from grant_assistant.analytics.metrics import _stay_days

    frame = pd.DataFrame(
        {
            schema.ENROLLMENT_DATE: pd.to_datetime(["2024-08-01", "2024-08-01"]),
            schema.EXIT_DATE: pd.to_datetime(["2024-08-31", "2024-07-01"]),
        }
    )
    days = _stay_days(frame)
    assert list(days) == [30.0]


def test_length_of_stay_is_none_without_completed_stays(profile):
    """No exit with both dates means no median, not a zero."""
    from grant_assistant.analytics.metrics import _stay_days

    frame = pd.DataFrame(
        {
            schema.ENROLLMENT_DATE: pd.to_datetime(["2024-08-01"]),
            schema.EXIT_DATE: pd.to_datetime([None]),
        }
    )
    assert len(_stay_days(frame)) == 0


def test_length_of_stay_by_destination_suppresses_small_groups(analytics_flawed):
    """A median over three stays is noise, so it must not be published."""
    from grant_assistant.analytics.metrics import SMALL_SAMPLE_N

    counts = analytics_flawed.exit_destination_breakdown
    for destination in analytics_flawed.median_length_of_stay_by_destination:
        assert counts.get(destination, 0) >= SMALL_SAMPLE_N, destination


def test_program_length_of_stay_is_reported(analytics):
    for program in analytics.programs:
        if program.exits:
            assert program.median_length_of_stay_days is not None


def test_length_of_stay_is_retrievable_as_a_metric(analytics):
    lookup = analytics.metric_lookup()
    assert lookup["median_length_of_stay_days"] == analytics.median_length_of_stay_days
    assert lookup["avg_length_of_stay_days"] == analytics.avg_length_of_stay_days


# -- Period pacing -----------------------------------------------------------


def test_period_elapsed_is_a_percentage(analytics):
    assert analytics.period_elapsed_pct is not None
    assert analytics.period_elapsed_pct > 0


def test_elapsed_can_exceed_one_hundred_after_the_period_closes(analytics):
    """Past 100% is meaningful, not an error: it says the figures are final."""
    assert analytics.period_elapsed_pct > 100


def test_attainment_is_actual_over_target(analytics):
    for measure in analytics.measures:
        if measure.actual is not None and measure.direction == "at_least" and measure.target:
            assert measure.attainment_pct == round(100.0 * measure.actual / measure.target, 1)


def test_at_most_targets_have_no_attainment(analytics):
    """ "62% of the way there" is backwards for a target you stay under."""
    for measure in analytics.measures:
        if measure.direction == "at_most":
            assert measure.attainment_pct is None


def test_on_pace_is_none_once_the_period_has_closed(analytics):
    """Pacing is a mid-period question; afterwards met/not-met is the answer."""
    assert analytics.period_elapsed_pct > 100
    assert all(m.on_pace is None for m in analytics.measures)


def test_on_pace_compares_attainment_against_elapsed_time():
    """The judgement this metric exists to make."""
    from grant_assistant.analytics.metrics import MeasureResult

    def measure(attainment: float, elapsed: float) -> MeasureResult:
        return MeasureResult(
            id="M-1",
            name="m",
            metric="x",
            unit="percent",
            direction="at_least",
            target=100.0,
            actual=attainment,
            denominator=50,
            met=False,
            small_sample=False,
            attainment_pct=attainment,
            period_elapsed_pct=elapsed,
        )

    assert measure(48.0, 62.0).on_pace is False  # behind
    assert measure(70.0, 62.0).on_pace is True  # ahead
    assert measure(62.0, 62.0).on_pace is True  # exactly on pace
    assert measure(20.0, 100.0).on_pace is None  # period closed
