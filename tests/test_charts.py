"""Chart figure functions that no report path reaches.

The report renderers exercise most of ``analytics/charts.py`` indirectly, but
``comparison_chart`` (the period-over-period view behind the ``compare``
command and the UI's Period Comparison page) and ``history_trend_chart`` (the
data-quality-over-time view behind the history UI) are never called by any
report -- so they sat at 0 coverage despite shipping. These call them
directly and assert the structure a reader relies on: the right traces, the
right series, and the optional metric overlay.
"""

from __future__ import annotations

from datetime import datetime

from grant_assistant.analytics.charts import comparison_chart, history_trend_chart
from grant_assistant.analytics.comparison import ComparisonResult, MetricDelta
from grant_assistant.history.store import HistoryEntry


def _entry(
    run_id: int, label: str, score: float, metric_value: float | None = None
) -> HistoryEntry:
    return HistoryEntry(
        run_id=run_id,
        recorded_at=datetime(2024, 7, 1),
        profile_id="housing_stability",
        grant_name="Stable Homes Grant",
        label=label,
        source="a.csv",
        period_start="2024-07-01",
        period_end="2024-09-30",
        total_rows=260,
        score=score,
        grade="B",
        findings=120,
        blocking=2,
        metrics={"successful_exit_rate": metric_value} if metric_value is not None else {},
    )


def test_comparison_chart_plots_percent_deltas_only():
    """Only percent metrics with a current value become bars; counts are dropped."""
    comparison = ComparisonResult(
        current_label="FY25",
        prior_label="FY24",
        headline=[
            MetricDelta(
                key="successful_exit_rate",
                label="Successful exit rate",
                unit="percent",
                current=64.1,
                prior=58.0,
                delta=6.1,
                pct_change=10.5,
            ),
            MetricDelta(
                key="permanent_housing_rate",
                label="Permanent housing rate",
                unit="percent",
                current=64.1,
                prior=60.0,
                delta=4.1,
                pct_change=6.8,
            ),
            # A count metric and a missing-current percent must both be filtered out.
            MetricDelta(
                key="total_enrollments",
                label="Total enrollments",
                unit="count",
                current=260,
                prior=240,
                delta=20,
                pct_change=8.3,
            ),
            MetricDelta(
                key="followup_completion_rate",
                label="Follow-up completion rate",
                unit="percent",
                current=None,
                prior=70.0,
                delta=None,
                pct_change=None,
            ),
        ],
    )
    fig = comparison_chart(comparison)
    assert fig.layout.title.text == "Period-over-Period Comparison"
    # Prior and current period bars only.
    assert len(fig.data) == 2
    assert fig.data[0].name == "FY24"
    assert fig.data[1].name == "FY25"
    # The two surviving percent rates, not the count or the missing-current one.
    assert len(fig.data[0].x) == 2
    assert set(fig.data[0].y) == {"Successful exit rate", "Permanent housing rate"}


def test_history_trend_chart_overlays_a_metric_with_values():
    """A score line always plots; a metric with points adds a second trace on y2."""
    entries = [
        _entry(1, "Q1", 80.0, metric_value=60.0),
        _entry(2, "", 82.0, metric_value=62.0),  # blank label falls back to the date
        _entry(3, "Q3", 85.1, metric_value=64.1),
    ]
    fig = history_trend_chart(entries, metric="successful_exit_rate")
    assert fig.layout.title.text == "Data Quality Over Time"
    # Score trace plus the metric overlay.
    assert len(fig.data) == 2
    assert list(fig.data[0].y) == [80.0, 82.0, 85.1]
    # The blank label fell back to the recorded-at date.
    assert "2024-07-01" in list(fig.data[0].x)
    # The overlay rides a secondary axis.
    assert "yaxis2" in fig.layout


def test_history_trend_chart_omits_a_metric_with_no_points():
    """A metric requested but absent from every run adds no trace, not a flat zero line."""
    entries = [_entry(1, "Q1", 80.0), _entry(2, "Q2", 85.1)]  # no metric values recorded
    fig = history_trend_chart(entries, metric="successful_exit_rate")
    assert len(fig.data) == 1  # score line only
    assert "yaxis2" not in fig.layout
