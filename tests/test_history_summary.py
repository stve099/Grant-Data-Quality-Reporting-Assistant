"""The recorded history, reduced to what a report and an analyst can state.

These pin the arithmetic, because every number here reaches a funder document
and the AI analyst is forbidden from recomputing any of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from grant_assistant.history import (
    build_history_summary,
    load_history_summary,
    record_run,
)

BASE = datetime(2026, 1, 15, 9, 0, 0)


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "history.db"


def _entries(db, profile, audit, analytics, count=2, scores=None):
    from grant_assistant.history import load_history

    for index in range(count):
        record_run(
            profile,
            audit,
            analytics,
            db,
            label=f"Q{index + 1}",
            recorded_at=BASE + timedelta(days=30 * index),
        )
    return load_history(db, profile.profile_id)


def test_no_runs_summarizes_as_no_trend(audit_flawed):
    summary = build_history_summary([], audit_flawed)
    assert summary.runs == 0
    assert summary.since_previous is None
    assert "No previous runs" in summary.headline()


def test_the_movement_is_measured_against_the_previous_run(
    db, profile, audit_flawed, audit_clean, analytics_flawed
):
    """ "Since we last reported" is the figure a funder asks about."""
    entries = _entries(db, profile, audit_flawed, analytics_flawed, count=2)
    summary = build_history_summary(entries, audit_clean, profile.profile_id)

    assert summary.runs == 2
    assert summary.latest_score == round(audit_flawed.overall_score, 1)
    assert summary.since_previous == round(
        audit_clean.overall_score - audit_flawed.overall_score, 1
    )
    assert "up" in summary.headline()


def test_one_recorded_run_still_reports_a_movement(
    db, profile, audit_flawed, audit_clean, analytics_flawed
):
    entries = _entries(db, profile, audit_flawed, analytics_flawed, count=1)
    summary = build_history_summary(entries, audit_clean, profile.profile_id)
    assert summary.runs == 1
    assert summary.since_previous is not None
    # First-to-last needs two points; since-previous needs one.
    assert summary.score_delta is None


def test_an_excluded_run_is_not_its_own_history(db, profile, audit_flawed, analytics_flawed):
    """The run just recorded from this dataset is not an observation before it."""
    entries = _entries(db, profile, audit_flawed, analytics_flawed, count=1)
    only = entries[0].run_id

    summary = build_history_summary(entries, audit_flawed, profile.profile_id, {only})
    assert summary.runs == 0
    assert summary.persistent_findings == []
    assert summary.since_previous is None


def test_a_finding_open_three_runs_is_reported_as_long_standing(
    db, profile, audit_flawed, analytics_flawed
):
    entries = _entries(db, profile, audit_flawed, analytics_flawed, count=3)
    summary = build_history_summary(entries, audit_flawed, profile.profile_id)

    assert summary.persistent_findings, "a repeated finding must age"
    finding = summary.persistent_findings[0]
    assert finding.consecutive_runs >= 3
    assert "consecutive runs" in finding.describe()
    assert finding.change == 0, "the same extract recorded twice has not moved"


def test_a_cleared_finding_is_reported_as_resolved(
    db, profile, audit_flawed, audit_clean, analytics_flawed
):
    entries = _entries(db, profile, audit_flawed, analytics_flawed, count=1)
    summary = build_history_summary(entries, audit_clean, profile.profile_id)
    assert summary.resolved_rule_ids, "the clean extract clears what the flawed one flagged"


def test_the_trend_points_read_oldest_first(db, profile, audit_flawed, analytics_flawed):
    entries = _entries(db, profile, audit_flawed, analytics_flawed, count=3)
    summary = build_history_summary(entries, audit_flawed, profile.profile_id)
    assert [p.label for p in summary.points] == ["Q1", "Q2", "Q3"]


def test_loading_from_a_database_that_does_not_exist_is_not_an_error(tmp_path, audit_flawed):
    assert load_history_summary(tmp_path / "absent.db", "housing_stability", audit_flawed) is None


def test_loading_a_profile_with_no_runs_returns_nothing(
    db, profile, audit_flawed, analytics_flawed
):
    _entries(db, profile, audit_flawed, analytics_flawed, count=1)
    assert load_history_summary(db, "a_profile_never_recorded", audit_flawed) is None


def test_loading_scopes_to_one_profile(db, profile, rrh_profile, audit_flawed, analytics_flawed):
    """Two funders' scores in one summary would compare different rule sets."""
    _entries(db, profile, audit_flawed, analytics_flawed, count=2)
    record_run(rrh_profile, audit_flawed, analytics_flawed, db, label="other grant")

    summary = load_history_summary(db, profile.profile_id, audit_flawed)
    assert summary is not None
    assert summary.runs == 2
    assert [p.label for p in summary.points] == ["Q1", "Q2"]
