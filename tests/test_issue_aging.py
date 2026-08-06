"""Issue aging tests.

"Open for four periods" is a different conversation from "6 records", so the
count has to be right. The subtle case is a run recorded before rule counts
existed: treating its silence as "clean" would invent a resolution that never
happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from grant_assistant.history import (
    load_history,
    record_run,
    resolved_since_last_run,
    rule_ages,
)

BASE = datetime(2026, 1, 1, 9, 0, 0)


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "history.db"


def _record(db, profile, audit, analytics, *, when, label=""):
    return record_run(profile, audit, analytics, db, label=label, recorded_at=when)


def _age_for(ages, rule_id):
    return next((a for a in ages if a.rule_id == rule_id), None)


# -- Counting ----------------------------------------------------------------


def test_a_finding_with_no_history_is_new(db, profile, audit_flawed, analytics_flawed):
    ages = rule_ages(load_history(db), audit_flawed)
    assert ages
    assert all(a.is_new for a in ages)
    assert all(a.consecutive_runs == 1 for a in ages)


def test_consecutive_runs_accumulate(db, profile, audit_flawed, analytics_flawed):
    for index in range(3):
        _record(
            db,
            profile,
            audit_flawed,
            analytics_flawed,
            when=BASE + timedelta(days=30 * index),
            label=f"P{index}",
        )
    ages = rule_ages(load_history(db), audit_flawed)
    target = _age_for(ages, audit_flawed.issues_sorted()[0].rule_id)
    assert target is not None
    # Three recorded runs plus the current audit.
    assert target.consecutive_runs == 4
    assert target.is_persistent


def test_persistence_needs_three_runs(db, profile, audit_flawed, analytics_flawed):
    _record(db, profile, audit_flawed, analytics_flawed, when=BASE, label="P0")
    ages = rule_ages(load_history(db), audit_flawed)
    target = _age_for(ages, audit_flawed.issues_sorted()[0].rule_id)
    assert target is not None
    assert target.consecutive_runs == 2
    assert not target.is_persistent
    assert not target.is_new


def test_a_gap_breaks_the_streak(db, profile, audit_clean, audit_flawed, analytics_flawed):
    """A clean run in between means the issue came back, not that it never left."""
    _record(db, profile, audit_flawed, analytics_flawed, when=BASE, label="dirty")
    _record(
        db, profile, audit_clean, analytics_flawed, when=BASE + timedelta(days=30), label="clean"
    )

    ages = rule_ages(load_history(db), audit_flawed)
    target = _age_for(ages, audit_flawed.issues_sorted()[0].rule_id)
    assert target is not None
    assert target.consecutive_runs == 1
    assert target.is_new


def test_change_since_the_previous_run_is_reported(db, profile, audit_flawed, analytics_flawed):
    _record(db, profile, audit_flawed, analytics_flawed, when=BASE, label="P0")
    ages = rule_ages(load_history(db), audit_flawed)
    # Same audit recorded then re-aged, so nothing moved.
    assert all(a.change == 0 for a in ages if a.change is not None)


def test_only_findings_with_records_are_aged(db, profile, audit_flawed):
    ages = rule_ages(load_history(db), audit_flawed)
    assert all(a.current_count > 0 for a in ages)


# -- The unknown-history case ------------------------------------------------


def test_runs_without_rule_counts_are_unknown_not_clean(
    db, profile, audit_flawed, analytics_flawed
):
    """A pre-aging row must not be read as evidence the issue was absent."""
    import sqlite3

    _record(db, profile, audit_flawed, analytics_flawed, when=BASE, label="legacy")
    with sqlite3.connect(db) as conn:  # simulate a row recorded before aging existed
        conn.execute("DELETE FROM run_rule_counts")
        conn.execute("UPDATE runs SET rules_recorded = 0")

    entries = load_history(db)
    assert entries and not entries[0].rules_recorded

    ages = rule_ages(entries, audit_flawed)
    target = _age_for(ages, audit_flawed.issues_sorted()[0].rule_id)
    assert target is not None
    # Counted as new rather than as a resolved-then-returned issue.
    assert target.consecutive_runs == 1
    assert target.change is None


# -- Resolution --------------------------------------------------------------


def test_resolved_rules_are_reported(db, profile, audit_flawed, audit_clean, analytics_flawed):
    """Cleanup that worked is otherwise invisible; a fixed finding just stops appearing."""
    _record(db, profile, audit_flawed, analytics_flawed, when=BASE, label="before")
    resolved = resolved_since_last_run(load_history(db), audit_clean)
    assert resolved
    assert all(r.startswith("DQ-") for r in resolved)


def test_nothing_resolved_without_history(db, audit_clean):
    assert resolved_since_last_run(load_history(db), audit_clean) == []


def test_a_legacy_run_reports_no_resolutions(
    db, profile, audit_flawed, analytics_flawed, audit_clean
):
    """Unknown history must not be read as "everything was fixed"."""
    import sqlite3

    _record(db, profile, audit_flawed, analytics_flawed, when=BASE, label="legacy")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM run_rule_counts")
        conn.execute("UPDATE runs SET rules_recorded = 0")

    assert resolved_since_last_run(load_history(db), audit_clean) == []


def test_an_existing_database_is_migrated(tmp_path, profile, audit_flawed, analytics_flawed):
    """A history.db created by v1.4.0 must keep working."""
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:  # the pre-aging schema
        conn.execute(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL,"
            " profile_id TEXT NOT NULL, grant_name TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',"
            " source TEXT NOT NULL DEFAULT '', period_start TEXT NOT NULL,"
            " period_end TEXT NOT NULL, total_rows INTEGER NOT NULL, score REAL NOT NULL,"
            " grade TEXT NOT NULL, findings INTEGER NOT NULL, blocking INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO runs (recorded_at, profile_id, grant_name, period_start, period_end,"
            " total_rows, score, grade, findings, blocking)"
            " VALUES ('2026-01-01T09:00:00','housing_stability','G','2024-07-01','2025-06-30',"
            "10, 88.0, 'B', 3, 1)"
        )

    entries = load_history(path)
    assert len(entries) == 1
    assert entries[0].rules_recorded is False

    # And new runs still record normally afterwards.
    _record(path, profile, audit_flawed, analytics_flawed, when=BASE, label="new")
    assert load_history(path)[-1].rules_recorded is True


# -- Wording -----------------------------------------------------------------


def test_description_reads_plainly(db, profile, audit_flawed, analytics_flawed):
    for index in range(3):
        _record(
            db,
            profile,
            audit_flawed,
            analytics_flawed,
            when=BASE + timedelta(days=30 * index),
            label=f"Q{index + 1}",
        )
    ages = rule_ages(load_history(db), audit_flawed)
    text = ages[0].describe()
    assert "consecutive runs" in text
    assert "since Q1" in text
