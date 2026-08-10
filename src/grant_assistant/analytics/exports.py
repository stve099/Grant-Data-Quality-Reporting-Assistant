"""Tabular exports derived from typed analytics results."""

from __future__ import annotations

from typing import Any

import pandas as pd

from grant_assistant import schema
from grant_assistant.analytics.models import AnalyticsResult


def available_measure_metrics() -> list[str]:
    """Metric keys a profile's performance_measures may reference."""
    static = [
        "total_enrollments",
        "households_served",
        "total_exits",
        "exit_rate",
        "successful_exit_rate",
        "permanent_housing_rate",
        "pct_income_increased",
        "avg_income_change",
        "median_income_change",
        "assessment_completion_rate",
        "exit_plan_completion_rate",
        "overall_followup_completion_rate",
    ]
    return [*static, "followup_<key>_completion_rate"]


def analytics_to_flat_frames(result: AnalyticsResult) -> dict[str, pd.DataFrame]:
    """Convert the analytics result into tidy DataFrames for Excel export."""
    overview_rows: list[dict[str, Any]] = [
        {"Metric": "Total enrollments", "Value": result.total_enrollments},
        {"Metric": "Households served", "Value": result.households_served},
        {"Metric": "Total individuals", "Value": result.total_individuals},
        {"Metric": "Total adults", "Value": result.total_adults},
        {"Metric": "Total children", "Value": result.total_children},
        {"Metric": "Active enrollments", "Value": result.active_enrollments},
        {"Metric": "Total exits", "Value": result.total_exits},
        {"Metric": "Exit rate (%)", "Value": result.exit_rate},
        {"Metric": "Successful exits", "Value": result.successful_exits},
        {"Metric": "Successful exit rate (%)", "Value": result.successful_exit_rate},
        {"Metric": "Permanent housing exits", "Value": result.permanent_housing_exits},
        {"Metric": "Permanent housing rate (%)", "Value": result.permanent_housing_rate},
        {"Metric": "Average entry income ($)", "Value": result.avg_entry_income},
        {"Metric": "Average exit income ($)", "Value": result.avg_exit_income},
        {"Metric": "Average income change ($)", "Value": result.avg_income_change},
        {"Metric": "Median income change ($)", "Value": result.median_income_change},
        {"Metric": "% households with income increase", "Value": result.pct_income_increased},
        {
            "Metric": "Follow-up completion rate (%)",
            "Value": result.overall_followup_completion_rate,
        },
        {"Metric": "Overdue follow-ups", "Value": result.total_overdue_followups},
        {"Metric": "Assessment completion rate (%)", "Value": result.assessment_completion_rate},
        {"Metric": "Exit plan completion rate (%)", "Value": result.exit_plan_completion_rate},
    ]
    frames: dict[str, pd.DataFrame] = {"Overview": pd.DataFrame(overview_rows)}

    if result.programs:
        frames["Programs"] = pd.DataFrame([p.model_dump() for p in result.programs])
    if result.measures:
        frames["Performance Measures"] = pd.DataFrame([m.model_dump() for m in result.measures])
    if result.followups:
        frames["Follow-Ups"] = pd.DataFrame([f.model_dump() for f in result.followups])

    demo_rows = []
    for field_name, counts in result.demographics.items():
        for value, count in counts.items():
            demo_rows.append(
                {"Field": schema.label_for(field_name), "Value": value, "Count": count}
            )
    for label, count in result.age_groups.items():
        demo_rows.append({"Field": "Age Group", "Value": label, "Count": count})
    if demo_rows:
        frames["Demographics"] = pd.DataFrame(demo_rows)

    dest_rows = [
        {"Destination": k, "Count": v} for k, v in result.exit_destination_breakdown.items()
    ]
    if dest_rows:
        frames["Exit Destinations"] = pd.DataFrame(dest_rows)

    trend_rows = []
    months = sorted(set(result.monthly_enrollments) | set(result.monthly_exits))
    for month in months:
        trend_rows.append(
            {
                "Month": month,
                "Enrollments": result.monthly_enrollments.get(month, 0),
                "Exits": result.monthly_exits.get(month, 0),
            }
        )
    if trend_rows:
        frames["Monthly Trends"] = pd.DataFrame(trend_rows)
    return frames
