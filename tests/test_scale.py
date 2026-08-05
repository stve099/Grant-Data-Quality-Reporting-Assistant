"""Behaviour at a realistic extract size.

Every other test runs on a few hundred rows. A real HMIS export is tens of
thousands, and two things could break there but not here: a rule that is
accidentally quadratic, and per-row logic that only shows its cost in bulk.

The timing assertion is deliberately loose. It is not a performance target — it
is a tripwire for an algorithmic regression, set far enough above the measured
figure (100k rows audit in about 6 seconds) that ordinary machine variance and
CI contention cannot trip it.
"""

from __future__ import annotations

import time

import pytest

from grant_assistant.analytics import compute_analytics
from grant_assistant.audit import run_audit
from grant_assistant.datagen import generate_clean_dataset, inject_issues
from grant_assistant.ingestion import prepare_dataset

pytestmark = pytest.mark.slow

SCALE_ROWS = 20_000
#: Measured at roughly 1s for this size; 60s only catches a change in complexity.
TIME_BUDGET_SECONDS = 60.0


@pytest.fixture(scope="module")
def large_prepared(profile):
    """Flawed data at scale — exercises every rule's record-collection path."""
    frame, _ = inject_issues(generate_clean_dataset(n_clients=SCALE_ROWS, seed=3), seed=4)
    return prepare_dataset(frame, profile)


@pytest.fixture(scope="module")
def large_clean_prepared(profile):
    """Clean data at scale.

    Aggregate reconciliation only holds here: the flawed generator deliberately
    injects impossible household compositions, so adults + children need not
    equal individuals in that dataset.
    """
    return prepare_dataset(generate_clean_dataset(n_clients=SCALE_ROWS, seed=5), profile)


def test_pipeline_completes_within_a_sane_budget(large_prepared, profile):
    """A tripwire for accidental quadratic behaviour, not a performance target."""
    start = time.perf_counter()
    audit = run_audit(large_prepared, profile)
    analytics = compute_analytics(large_prepared, profile)
    elapsed = time.perf_counter() - start

    assert elapsed < TIME_BUDGET_SECONDS, f"pipeline took {elapsed:.1f}s at {SCALE_ROWS} rows"
    assert audit.total_rows == len(large_prepared.df)
    assert analytics.total_enrollments > 0


def test_aggregates_reconcile_on_clean_data_at_scale(large_clean_prepared, profile):
    """Sums that must balance, checked where the data is not deliberately broken."""
    analytics = compute_analytics(large_clean_prepared, profile)

    assert analytics.total_adults + analytics.total_children == analytics.total_individuals
    assert sum(p.enrollments for p in analytics.programs) == analytics.total_enrollments


def test_results_stay_self_consistent_at_scale(large_prepared, profile):
    """Bounds that hold on any dataset, however flawed."""
    analytics = compute_analytics(large_prepared, profile)

    assert analytics.successful_exits <= analytics.total_exits
    assert analytics.total_exits + analytics.active_enrollments <= analytics.total_enrollments
    assert sum(p.enrollments for p in analytics.programs) <= analytics.total_enrollments
    if analytics.successful_exit_rate is not None:
        assert 0.0 <= analytics.successful_exit_rate <= 100.0


def test_every_finding_points_at_a_real_row(large_prepared, profile):
    """Row numbers are 1-based and must stay inside the dataset."""
    audit = run_audit(large_prepared, profile)
    row_count = len(large_prepared.df)
    for issue in audit.issues:
        for record in issue.records:
            assert 1 <= record.row <= row_count, f"{issue.rule_id} points at row {record.row}"


def test_scoring_stays_in_range_at_scale(large_prepared, profile):
    audit = run_audit(large_prepared, profile)
    assert 0.0 <= audit.overall_score <= 100.0
    assert all(0.0 <= score <= 100.0 for score in audit.score_by_category.values())
    assert all(0.0 <= score <= 100.0 for score in audit.score_by_program.values())
