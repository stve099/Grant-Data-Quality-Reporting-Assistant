"""Run history tests.

The store's value is that it answers "is this getting better?" across runs, so
the tests exercise sequences rather than single writes, and pin the behaviour
when a profile changes shape between runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from grant_assistant.history import (
    load_history,
    metric_series,
    record_run,
    score_trend,
)

BASE = datetime(2026, 1, 15, 9, 0, 0)


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "history.db"


def _record(db, profile, audit, analytics, *, when=BASE, label=""):
    return record_run(profile, audit, analytics, db, label=label, recorded_at=when)


# -- Recording ---------------------------------------------------------------


def test_a_run_round_trips(db, profile, audit_flawed, analytics_flawed):
    run_id = _record(db, profile, audit_flawed, analytics_flawed, label="Q1")
    entries = load_history(db)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.run_id == run_id
    assert entry.label == "Q1"
    assert entry.profile_id == profile.profile_id
    assert entry.score == audit_flawed.overall_score
    assert entry.grade == audit_flawed.grade
    assert entry.total_rows == audit_flawed.total_rows
    assert entry.blocking == len(audit_flawed.blocking_issues)


def test_metrics_are_stored_with_the_run(db, profile, audit_flawed, analytics_flawed):
    _record(db, profile, audit_flawed, analytics_flawed)
    stored = load_history(db)[0].metrics
    assert stored["total_enrollments"] == float(analytics_flawed.total_enrollments)
    assert set(stored) == set(analytics_flawed.metric_lookup())


def test_the_database_is_created_on_demand(tmp_path, profile, audit_flawed, analytics_flawed):
    nested = tmp_path / "a" / "b" / "history.db"
    _record(nested, profile, audit_flawed, analytics_flawed)
    assert nested.exists()


def test_missing_database_reads_as_empty(tmp_path):
    """Asking before recording is a normal state, not an error."""
    assert load_history(tmp_path / "nothing.db") == []


# -- Sequences ---------------------------------------------------------------


def test_entries_come_back_oldest_first(db, profile, audit_clean, audit_flawed, analytics_flawed):
    _record(db, profile, audit_flawed, analytics_flawed, when=BASE, label="first")
    _record(
        db, profile, audit_clean, analytics_flawed, when=BASE + timedelta(days=90), label="second"
    )
    labels = [e.label for e in load_history(db)]
    assert labels == ["first", "second"]


def test_score_trend_measures_first_to_last(
    db, profile, audit_clean, audit_flawed, analytics_flawed
):
    _record(db, profile, audit_flawed, analytics_flawed, when=BASE)
    _record(db, profile, audit_clean, analytics_flawed, when=BASE + timedelta(days=90))
    expected = round(audit_clean.overall_score - audit_flawed.overall_score, 1)
    assert score_trend(load_history(db)) == expected


def test_a_single_run_has_no_trend(db, profile, audit_flawed, analytics_flawed):
    """One point is not a direction."""
    _record(db, profile, audit_flawed, analytics_flawed)
    assert score_trend(load_history(db)) is None


def test_metric_series_tracks_one_metric_over_time(
    db, profile, audit_flawed, analytics_flawed, analytics_clean
):
    _record(db, profile, audit_flawed, analytics_flawed, when=BASE)
    _record(db, profile, audit_flawed, analytics_clean, when=BASE + timedelta(days=30))
    series = metric_series(load_history(db), "total_enrollments")
    assert len(series) == 2
    assert series[0][0] < series[1][0]


def test_a_metric_absent_from_earlier_runs_simply_has_fewer_points(
    db, profile, audit_flawed, analytics_flawed
):
    """A profile that gains a measure must not require a migration."""
    _record(db, profile, audit_flawed, analytics_flawed)
    assert metric_series(load_history(db), "a_metric_added_next_quarter") == []


def test_profiles_are_kept_apart(db, profile, rrh_profile, audit_flawed, analytics_flawed):
    _record(db, profile, audit_flawed, analytics_flawed, label="housing")
    _record(db, rrh_profile, audit_flawed, analytics_flawed, label="rrh")

    assert len(load_history(db)) == 2
    housing = load_history(db, profile.profile_id)
    assert [e.label for e in housing] == ["housing"]


def test_limit_returns_the_most_recent_runs(db, profile, audit_flawed, analytics_flawed):
    for day in range(5):
        _record(
            db,
            profile,
            audit_flawed,
            analytics_flawed,
            when=BASE + timedelta(days=day),
            label=f"run{day}",
        )
    recent = load_history(db, limit=2)
    # Most recent two, still presented oldest-first.
    assert [e.label for e in recent] == ["run3", "run4"]


# -- Presentation-facing helpers ---------------------------------------------


def test_history_frame_lists_every_run_oldest_first(db, profile, audit_flawed, analytics_flawed):
    """One table definition, so the app and any export cannot disagree."""
    from grant_assistant.history import history_frame

    for day, label in enumerate(("Q1", "Q2")):
        _record(
            db,
            profile,
            audit_flawed,
            analytics_flawed,
            when=BASE + timedelta(days=day),
            label=label,
        )
    frame = history_frame(load_history(db))

    assert list(frame["Label"]) == ["Q1", "Q2"]
    assert list(frame["Score"]) == [round(audit_flawed.overall_score, 1)] * 2
    assert list(frame["Grade"]) == [audit_flawed.grade] * 2


def test_history_frame_of_no_runs_still_has_its_columns():
    """An empty table must render, not collapse to a shapeless frame."""
    from grant_assistant.history import history_frame

    frame = history_frame([])
    assert frame.empty
    assert "Score" in frame.columns


def test_an_unlabelled_run_reads_as_a_dash(db, profile, audit_flawed, analytics_flawed):
    from grant_assistant.history import history_frame

    _record(db, profile, audit_flawed, analytics_flawed)
    assert history_frame(load_history(db))["Label"][0] == "—"


def test_the_default_database_can_be_redirected(monkeypatch, tmp_path):
    """The web app has nowhere to type a path, so the environment is the control."""
    from grant_assistant.history import DB_PATH_ENV_VAR, default_db_path

    monkeypatch.delenv(DB_PATH_ENV_VAR, raising=False)
    assert default_db_path() == Path("output") / "history.db"

    monkeypatch.setenv(DB_PATH_ENV_VAR, str(tmp_path / "elsewhere.db"))
    assert default_db_path() == tmp_path / "elsewhere.db"
