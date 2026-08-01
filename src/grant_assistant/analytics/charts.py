"""Interactive Plotly charts built from deterministic analytics results.

Every chart takes a computed :class:`AnalyticsResult` or
:class:`AuditResult` — charts never re-derive numbers from raw data.
"""

from __future__ import annotations

import plotly.graph_objects as go

from grant_assistant import schema
from grant_assistant.analytics.metrics import AnalyticsResult
from grant_assistant.models import SEVERITY_ORDER, AuditResult

# Consistent, colorblind-safe palette used across all charts.
PALETTE = {
    "primary": "#2563eb",  # blue
    "secondary": "#0d9488",  # teal
    "accent": "#d97706",  # amber
    "positive": "#16a34a",  # green
    "negative": "#dc2626",  # red
    "neutral": "#64748b",  # slate
    "muted": "#cbd5e1",
}

SEVERITY_COLORS = {
    "critical": "#991b1b",
    "high": "#dc2626",
    "medium": "#d97706",
    "low": "#eab308",
    "info": "#64748b",
}

_LAYOUT = {
    "template": "plotly_white",
    "font": {"family": "Segoe UI, Arial, sans-serif", "size": 13},
    "margin": {"l": 60, "r": 30, "t": 60, "b": 60},
    "hoverlabel": {"bgcolor": "white"},
}


def _base(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(title={"text": title, "x": 0.02}, **_LAYOUT)
    return fig


def program_comparison_chart(analytics: AnalyticsResult) -> go.Figure:
    """Grouped bars: enrollments, exits, and successful exits per program."""
    programs = [p.program for p in analytics.programs]
    fig = go.Figure(
        [
            go.Bar(
                name="Enrollments",
                x=programs,
                y=[p.enrollments for p in analytics.programs],
                marker_color=PALETTE["primary"],
            ),
            go.Bar(
                name="Exits",
                x=programs,
                y=[p.exits for p in analytics.programs],
                marker_color=PALETTE["secondary"],
            ),
            go.Bar(
                name="Successful exits",
                x=programs,
                y=[p.successful_exits for p in analytics.programs],
                marker_color=PALETTE["positive"],
            ),
        ]
    )
    fig.update_layout(barmode="group", yaxis_title="Clients")
    return _base(fig, "Program Comparison")


def outcome_rate_chart(analytics: AnalyticsResult) -> go.Figure:
    """Successful-exit and permanent-housing rates per program."""
    programs = [p.program for p in analytics.programs]
    fig = go.Figure(
        [
            go.Bar(
                name="Successful exit rate",
                x=programs,
                y=[p.successful_exit_rate for p in analytics.programs],
                marker_color=PALETTE["positive"],
            ),
            go.Bar(
                name="Permanent housing rate",
                x=programs,
                y=[p.permanent_housing_rate for p in analytics.programs],
                marker_color=PALETTE["primary"],
            ),
        ]
    )
    fig.update_layout(barmode="group", yaxis_title="% of exits", yaxis_range=[0, 100])
    return _base(fig, "Outcome Rates by Program")


def enrollment_trend_chart(analytics: AnalyticsResult) -> go.Figure:
    """Monthly enrollments and exits over time."""
    months = sorted(set(analytics.monthly_enrollments) | set(analytics.monthly_exits))
    fig = go.Figure(
        [
            go.Scatter(
                name="Enrollments",
                x=months,
                y=[analytics.monthly_enrollments.get(m, 0) for m in months],
                mode="lines+markers",
                line={"color": PALETTE["primary"], "width": 3},
            ),
            go.Scatter(
                name="Exits",
                x=months,
                y=[analytics.monthly_exits.get(m, 0) for m in months],
                mode="lines+markers",
                line={"color": PALETTE["accent"], "width": 3},
            ),
        ]
    )
    fig.update_layout(yaxis_title="Clients per month", xaxis_title="Month")
    return _base(fig, "Enrollment and Exit Trends")


def exit_destination_chart(analytics: AnalyticsResult) -> go.Figure:
    """Horizontal bar of exit destinations, most common first."""
    items = sorted(analytics.exit_destination_breakdown.items(), key=lambda kv: kv[1])
    fig = go.Figure(
        go.Bar(
            x=[v for _, v in items],
            y=[k for k, _ in items],
            orientation="h",
            marker_color=PALETTE["secondary"],
        )
    )
    fig.update_layout(xaxis_title="Exits", height=max(360, 40 * len(items) + 120))
    return _base(fig, "Exit Destination Breakdown")


def demographic_chart(analytics: AnalyticsResult, field: str) -> go.Figure:
    """Bar chart for one demographic field (or 'age_groups')."""
    if field == "age_groups":
        counts = analytics.age_groups
        title = "Clients by Age Group"
    elif field == "household_size":
        counts = analytics.household_size_distribution
        title = "Household Size Distribution"
    else:
        counts = analytics.demographics.get(field, {})
        title = f"Clients by {schema.label_for(field)}"
    fig = go.Figure(
        go.Bar(
            x=list(counts.keys()),
            y=list(counts.values()),
            marker_color=PALETTE["primary"],
        )
    )
    fig.update_layout(yaxis_title="Clients")
    return _base(fig, title)


def income_change_chart(analytics: AnalyticsResult) -> go.Figure:
    """Histogram of per-household income change from entry to exit."""
    fig = go.Figure(
        go.Histogram(
            x=analytics.income_changes,
            nbinsx=30,
            marker_color=PALETTE["primary"],
        )
    )
    fig.add_vline(x=0, line_dash="dash", line_color=PALETTE["neutral"])
    if analytics.median_income_change is not None:
        fig.add_vline(
            x=analytics.median_income_change,
            line_color=PALETTE["positive"],
            annotation_text=f"Median: ${analytics.median_income_change:,.0f}",
        )
    fig.update_layout(xaxis_title="Income change ($, exit − entry)", yaxis_title="Households")
    return _base(fig, "Income Change at Exit")


def followup_chart(analytics: AnalyticsResult) -> go.Figure:
    """Completion vs overdue counts for each follow-up milestone."""
    labels = [f.label for f in analytics.followups]
    fig = go.Figure(
        [
            go.Bar(
                name="Completed",
                x=labels,
                y=[f.completed_of_due for f in analytics.followups],
                marker_color=PALETTE["positive"],
            ),
            go.Bar(
                name="Overdue",
                x=labels,
                y=[f.overdue for f in analytics.followups],
                marker_color=PALETTE["negative"],
            ),
        ]
    )
    fig.update_layout(barmode="stack", yaxis_title="Clients due")
    return _base(fig, "Follow-Up Completion")


def dq_severity_chart(audit: AuditResult) -> go.Figure:
    """Findings by severity level."""
    counts = audit.issue_count_by_severity
    labels = [s.label for s in SEVERITY_ORDER]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=[counts[s.value] for s in SEVERITY_ORDER],
            marker_color=[SEVERITY_COLORS[s.value] for s in SEVERITY_ORDER],
        )
    )
    fig.update_layout(yaxis_title="Findings")
    return _base(fig, "Data Quality Findings by Severity")


def dq_category_chart(audit: AuditResult) -> go.Figure:
    """Data quality score by category."""
    items = sorted(audit.score_by_category.items(), key=lambda kv: kv[1])
    fig = go.Figure(
        go.Bar(
            x=[v for _, v in items],
            y=[k.replace("_", " ").title() for k, _ in items],
            orientation="h",
            marker_color=PALETTE["primary"],
        )
    )
    fig.update_layout(xaxis_title="Score (100 = clean)", xaxis_range=[0, 100])
    return _base(fig, "Data Quality Score by Category")


def goal_vs_actual_chart(analytics: AnalyticsResult) -> go.Figure:
    """Horizontal bars comparing each performance measure to its target."""
    measures = [m for m in analytics.measures if m.actual is not None]
    names = [m.name for m in measures]
    fig = go.Figure(
        [
            go.Bar(
                name="Actual",
                x=[m.actual for m in measures],
                y=names,
                orientation="h",
                marker_color=[
                    PALETTE["positive"] if m.met else PALETTE["negative"] for m in measures
                ],
            ),
            go.Bar(
                name="Target",
                x=[m.target for m in measures],
                y=names,
                orientation="h",
                marker_color=PALETTE["muted"],
            ),
        ]
    )
    fig.update_layout(
        barmode="group",
        xaxis_title="Value",
        height=max(360, 60 * len(names) + 120),
        legend={"traceorder": "normal"},
    )
    return _base(fig, "Performance Measures: Goal vs. Actual")


def standard_chart_set(
    analytics: AnalyticsResult, audit: AuditResult | None = None
) -> dict[str, go.Figure]:
    """The default chart set used by the report builder and export center."""
    charts: dict[str, go.Figure] = {}
    if analytics.programs:
        charts["program_comparison"] = program_comparison_chart(analytics)
        charts["outcome_rates"] = outcome_rate_chart(analytics)
    if analytics.monthly_enrollments:
        charts["enrollment_trends"] = enrollment_trend_chart(analytics)
    if analytics.exit_destination_breakdown:
        charts["exit_destinations"] = exit_destination_chart(analytics)
    if analytics.age_groups:
        charts["age_groups"] = demographic_chart(analytics, "age_groups")
    if analytics.income_changes:
        charts["income_change"] = income_change_chart(analytics)
    if analytics.followups:
        charts["followups"] = followup_chart(analytics)
    if analytics.measures:
        charts["goal_vs_actual"] = goal_vs_actual_chart(analytics)
    if audit is not None:
        charts["dq_severity"] = dq_severity_chart(audit)
        if audit.score_by_category:
            charts["dq_category"] = dq_category_chart(audit)
    return charts
