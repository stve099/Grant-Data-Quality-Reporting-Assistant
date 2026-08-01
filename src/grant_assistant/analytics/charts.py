"""Interactive Plotly charts built from deterministic analytics results.

Every chart takes a computed :class:`AnalyticsResult` or :class:`AuditResult`
— charts never re-derive numbers from raw data.

Styling follows a validated design system (see docs/design_system.md):
categorical hues are assigned in a fixed, colorblind-safe order and never
cycled; severity/status colors are reserved and never reused for series;
magnitude uses a single sequential hue; chrome (grid, axes, labels) stays
recessive. The categorical order passes CVD-separation and normal-vision
gates on the light surface (validated with the palette validator).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go

from grant_assistant import schema
from grant_assistant.analytics.metrics import AnalyticsResult
from grant_assistant.models import SEVERITY_ORDER, AuditResult

if TYPE_CHECKING:
    from grant_assistant.analytics.comparison import ComparisonResult

# -- Design tokens -----------------------------------------------------------

#: Categorical series slots — fixed order, colorblind-safe, never cycled.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")

#: Sequential single hue (magnitude), light -> dark steps.
SEQ = {"100": "#cde2fb", "250": "#86b6ef", "400": "#3987e5", "450": "#2a78d6", "550": "#1c5cab"}

#: Status colors — reserved for state, never used as series colors.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

#: Severity -> status mapping (state semantics, paired with axis labels).
SEVERITY_COLORS = {
    "critical": STATUS["critical"],
    "high": STATUS["serious"],
    "medium": STATUS["warning"],
    "low": INK_MUTED,
    "info": BASELINE,
}

_FONT = {"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "size": 13, "color": INK}

_AXIS = {
    "gridcolor": GRID,
    "linecolor": BASELINE,
    "zerolinecolor": BASELINE,
    "tickfont": {"color": INK_SECONDARY, "size": 12},
    "title_font": {"color": INK_SECONDARY, "size": 12},
}


def _base(fig: go.Figure, title: str, legend: bool = True) -> go.Figure:
    """Apply shared chrome: surface, ink, recessive grid, hover styling."""
    fig.update_layout(
        title={"text": title, "x": 0.02, "font": {"size": 16, "color": INK}},
        template="plotly_white",
        font=_FONT,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        margin={"l": 60, "r": 24, "t": 56, "b": 52},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": GRID, "font": {"color": INK}},
        showlegend=legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1.0},
        bargap=0.35,
        bargroupgap=0.12,
    )
    fig.update_xaxes(**_AXIS)
    fig.update_yaxes(**_AXIS)
    return fig


def _bar(name: str, x: list, y: list, color: str, horizontal: bool = False) -> go.Bar:
    """A bar trace with the 2px surface gap between fills."""
    return go.Bar(
        name=name,
        x=x,
        y=y,
        orientation="h" if horizontal else "v",
        marker={"color": color, "line": {"color": SURFACE, "width": 2}},
    )


# -- Charts ------------------------------------------------------------------


def program_comparison_chart(analytics: AnalyticsResult) -> go.Figure:
    """Grouped bars: enrollments, exits, and successful exits per program."""
    programs = [p.program for p in analytics.programs]
    fig = go.Figure(
        [
            _bar("Enrollments", programs, [p.enrollments for p in analytics.programs], SERIES[0]),
            _bar("Exits", programs, [p.exits for p in analytics.programs], SERIES[1]),
            _bar(
                "Successful exits",
                programs,
                [p.successful_exits for p in analytics.programs],
                SERIES[2],
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
            _bar(
                "Successful exit rate",
                programs,
                [p.successful_exit_rate for p in analytics.programs],
                SERIES[0],
            ),
            _bar(
                "Permanent housing rate",
                programs,
                [p.permanent_housing_rate for p in analytics.programs],
                SERIES[2],
            ),
        ]
    )
    fig.update_layout(barmode="group", yaxis_title="% of exits", yaxis_range=[0, 100])
    return _base(fig, "Outcome Rates by Program")


def enrollment_trend_chart(analytics: AnalyticsResult) -> go.Figure:
    """Monthly enrollments and exits over time with a unified crosshair hover."""
    months = sorted(set(analytics.monthly_enrollments) | set(analytics.monthly_exits))
    fig = go.Figure(
        [
            go.Scatter(
                name="Enrollments",
                x=months,
                y=[analytics.monthly_enrollments.get(m, 0) for m in months],
                mode="lines+markers",
                line={"color": SERIES[0], "width": 2},
                marker={"size": 8, "line": {"color": SURFACE, "width": 2}},
            ),
            go.Scatter(
                name="Exits",
                x=months,
                y=[analytics.monthly_exits.get(m, 0) for m in months],
                mode="lines+markers",
                line={"color": SERIES[1], "width": 2},
                marker={"size": 8, "line": {"color": SURFACE, "width": 2}},
            ),
        ]
    )
    fig.update_layout(yaxis_title="Clients per month", xaxis_title="Month", hovermode="x unified")
    return _base(fig, "Enrollment and Exit Trends")


def exit_destination_chart(analytics: AnalyticsResult) -> go.Figure:
    """Horizontal bar of exit destinations, most common first (single measure)."""
    items = sorted(analytics.exit_destination_breakdown.items(), key=lambda kv: kv[1])
    fig = go.Figure(
        _bar("Exits", [v for _, v in items], [k for k, _ in items], SEQ["450"], horizontal=True)
    )
    fig.update_layout(xaxis_title="Exits", height=max(360, 34 * len(items) + 120))
    return _base(fig, "Exit Destination Breakdown", legend=False)


def demographic_chart(analytics: AnalyticsResult, field: str) -> go.Figure:
    """Bar chart for one demographic field (or 'age_groups' / 'household_size')."""
    if field == "age_groups":
        counts = analytics.age_groups
        title = "Clients by Age Group"
    elif field == "household_size":
        counts = analytics.household_size_distribution
        title = "Household Size Distribution"
    else:
        counts = analytics.demographics.get(field, {})
        title = f"Clients by {schema.label_for(field)}"
    fig = go.Figure(_bar("Clients", list(counts.keys()), list(counts.values()), SEQ["450"]))
    fig.update_layout(yaxis_title="Clients")
    return _base(fig, title, legend=False)


def income_change_chart(analytics: AnalyticsResult) -> go.Figure:
    """Histogram of per-household income change from entry to exit."""
    fig = go.Figure(
        go.Histogram(
            x=analytics.income_changes,
            nbinsx=30,
            name="Households",
            marker={"color": SEQ["400"], "line": {"color": SURFACE, "width": 2}},
        )
    )
    fig.add_vline(x=0, line_dash="dash", line_color=INK_MUTED)
    if analytics.median_income_change is not None:
        fig.add_vline(
            x=analytics.median_income_change,
            line_color=INK,
            annotation_text=f"Median ${analytics.median_income_change:,.0f}",
            annotation_font_color=INK_SECONDARY,
        )
    fig.update_layout(xaxis_title="Income change ($, exit − entry)", yaxis_title="Households")
    return _base(fig, "Income Change at Exit", legend=False)


def followup_chart(analytics: AnalyticsResult) -> go.Figure:
    """Completed vs overdue vs pending counts for each follow-up milestone."""
    labels = [f.label for f in analytics.followups]
    completed = [f.completed_of_due for f in analytics.followups]
    overdue = [f.overdue for f in analytics.followups]
    pending = [f.due - f.completed_of_due - f.overdue for f in analytics.followups]
    fig = go.Figure(
        [
            _bar("Completed", labels, completed, SERIES[0]),
            _bar("In grace window", labels, pending, BASELINE),
            _bar("Overdue ⚠", labels, overdue, STATUS["critical"]),
        ]
    )
    fig.update_layout(barmode="stack", yaxis_title="Clients due")
    return _base(fig, "Follow-Up Completion")


def dq_severity_chart(audit: AuditResult) -> go.Figure:
    """Findings by severity level (status colors + explicit axis labels)."""
    counts = audit.issue_count_by_severity
    labels = [s.label for s in SEVERITY_ORDER]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=[counts[s.value] for s in SEVERITY_ORDER],
            marker={
                "color": [SEVERITY_COLORS[s.value] for s in SEVERITY_ORDER],
                "line": {"color": SURFACE, "width": 2},
            },
            text=[counts[s.value] or "" for s in SEVERITY_ORDER],
            textposition="outside",
            textfont={"color": INK_SECONDARY},
        )
    )
    fig.update_layout(yaxis_title="Findings")
    return _base(fig, "Data Quality Findings by Severity", legend=False)


def dq_category_chart(audit: AuditResult) -> go.Figure:
    """Data quality score by category (single sequential hue)."""
    items = sorted(audit.score_by_category.items(), key=lambda kv: kv[1])
    fig = go.Figure(
        _bar(
            "Score",
            [v for _, v in items],
            [k.replace("_", " ").title() for k, _ in items],
            SEQ["450"],
            horizontal=True,
        )
    )
    fig.update_layout(xaxis_title="Score (100 = clean)", xaxis_range=[0, 105])
    return _base(fig, "Data Quality Score by Category", legend=False)


def goal_vs_actual_chart(analytics: AnalyticsResult) -> go.Figure:
    """Actual vs target per performance measure.

    Status color carries met/not-met but never alone: the companion measures
    table and hover text state the status explicitly.
    """
    measures = [m for m in analytics.measures if m.actual is not None]
    names = [m.name for m in measures]
    fig = go.Figure(
        [
            go.Bar(
                name="Actual",
                x=[m.actual for m in measures],
                y=names,
                orientation="h",
                marker={
                    "color": [STATUS["good"] if m.met else STATUS["critical"] for m in measures],
                    "line": {"color": SURFACE, "width": 2},
                },
                text=[("✓ Met" if m.met else "✗ Not met") for m in measures],
                textposition="auto",
                hovertemplate="%{y}<br>Actual: %{x}<br>%{text}<extra></extra>",
            ),
            go.Bar(
                name="Target",
                x=[m.target for m in measures],
                y=names,
                orientation="h",
                marker={"color": GRID, "line": {"color": SURFACE, "width": 2}},
            ),
        ]
    )
    fig.update_layout(
        barmode="group",
        xaxis_title="Value",
        height=max(360, 60 * len(names) + 130),
        legend={"traceorder": "normal"},
    )
    return _base(fig, "Performance Measures: Goal vs. Actual")


def comparison_chart(comparison: ComparisonResult) -> go.Figure:
    """Current vs prior period for the headline rate metrics."""
    rates = [d for d in comparison.headline if d.unit == "percent" and d.current is not None]
    names = [d.label for d in rates]
    fig = go.Figure(
        [
            go.Bar(
                name=comparison.prior_label,
                x=[d.prior for d in rates],
                y=names,
                orientation="h",
                marker={"color": BASELINE, "line": {"color": SURFACE, "width": 2}},
            ),
            go.Bar(
                name=comparison.current_label,
                x=[d.current for d in rates],
                y=names,
                orientation="h",
                marker={"color": SERIES[0], "line": {"color": SURFACE, "width": 2}},
            ),
        ]
    )
    fig.update_layout(
        barmode="group",
        xaxis_title="%",
        height=max(360, 60 * len(names) + 130),
    )
    return _base(fig, "Period-over-Period Comparison")


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
