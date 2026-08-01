"""Period-over-period comparison of two analytics results.

Compares a current-period dataset against a prior-period dataset (two extracts
analyzed with the same profile) and produces headline and per-program deltas
plus deterministic narrative sentences. Like everything else, comparisons are
computed here — never by the AI.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from grant_assistant.analytics.metrics import SMALL_SAMPLE_N, AnalyticsResult


class MetricDelta(BaseModel):
    """One headline metric compared across periods."""

    key: str
    label: str
    unit: str  # count | percent | currency
    current: float | None
    prior: float | None
    delta: float | None
    pct_change: float | None
    improved: bool | None = None

    def format_value(self, value: float | None) -> str:
        if value is None:
            return "n/a"
        if self.unit == "percent":
            return f"{value:.1f}%"
        if self.unit == "currency":
            return f"${value:,.0f}"
        return f"{value:,.0f}"


class ProgramDelta(BaseModel):
    """Per-program successful-exit-rate movement across periods."""

    program: str
    current_exits: int
    prior_exits: int
    current_rate: float | None
    prior_rate: float | None
    delta: float | None
    small_sample: bool


class ComparisonResult(BaseModel):
    """Complete period-over-period comparison."""

    current_label: str
    prior_label: str
    headline: list[MetricDelta] = Field(default_factory=list)
    programs: list[ProgramDelta] = Field(default_factory=list)
    narrative: list[str] = Field(default_factory=list)


_HEADLINE_SPECS: list[tuple[str, str, str, bool]] = [
    # (metric key, label, unit, higher_is_better)
    ("total_enrollments", "Total enrollments", "count", True),
    ("total_exits", "Total exits", "count", True),
    ("successful_exit_rate", "Successful exit rate", "percent", True),
    ("permanent_housing_rate", "Permanent housing rate", "percent", True),
    ("pct_income_increased", "Households increasing income", "percent", True),
    ("median_income_change", "Median income change", "currency", True),
    ("overall_followup_completion_rate", "Follow-up completion rate", "percent", True),
    ("total_overdue_followups", "Overdue follow-ups", "count", False),
]


def _delta(current: float | None, prior: float | None) -> tuple[float | None, float | None]:
    if current is None or prior is None:
        return None, None
    delta = round(current - prior, 2)
    pct = round(100.0 * delta / prior, 1) if prior else None
    return delta, pct


def compare_analytics(
    current: AnalyticsResult,
    prior: AnalyticsResult,
    current_label: str = "Current period",
    prior_label: str = "Prior period",
) -> ComparisonResult:
    """Compare two analytics results computed with the same profile."""
    cur_lookup = current.metric_lookup()
    pri_lookup = prior.metric_lookup()

    headline: list[MetricDelta] = []
    for key, label, unit, higher_better in _HEADLINE_SPECS:
        cur = cur_lookup.get(key)
        pri = pri_lookup.get(key)
        cur_f = float(cur) if cur is not None else None
        pri_f = float(pri) if pri is not None else None
        delta, pct = _delta(cur_f, pri_f)
        improved: bool | None = None
        if delta is not None and delta != 0:
            improved = (delta > 0) == higher_better
        headline.append(
            MetricDelta(
                key=key,
                label=label,
                unit=unit,
                current=cur_f,
                prior=pri_f,
                delta=delta,
                pct_change=pct,
                improved=improved,
            )
        )

    prior_programs = {p.program: p for p in prior.programs}
    programs: list[ProgramDelta] = []
    for cur_prog in current.programs:
        pri_prog = prior_programs.get(cur_prog.program)
        delta = None
        if (
            pri_prog is not None
            and cur_prog.successful_exit_rate is not None
            and pri_prog.successful_exit_rate is not None
        ):
            delta = round(cur_prog.successful_exit_rate - pri_prog.successful_exit_rate, 1)
        programs.append(
            ProgramDelta(
                program=cur_prog.program,
                current_exits=cur_prog.exits,
                prior_exits=pri_prog.exits if pri_prog else 0,
                current_rate=cur_prog.successful_exit_rate,
                prior_rate=pri_prog.successful_exit_rate if pri_prog else None,
                delta=delta,
                small_sample=(
                    cur_prog.exits < SMALL_SAMPLE_N
                    or (pri_prog is not None and pri_prog.exits < SMALL_SAMPLE_N)
                ),
            )
        )

    result = ComparisonResult(
        current_label=current_label,
        prior_label=prior_label,
        headline=headline,
        programs=programs,
    )
    result.narrative = _narrate(result)
    return result


def _narrate(comparison: ComparisonResult) -> list[str]:
    lines: list[str] = []
    improved = [d for d in comparison.headline if d.improved is True]
    declined = [d for d in comparison.headline if d.improved is False]
    if improved:
        lines.append(
            "Improved vs. prior period: "
            + "; ".join(
                f"{d.label} {d.format_value(d.prior)} → {d.format_value(d.current)}"
                for d in improved
            )
            + "."
        )
    if declined:
        lines.append(
            "Declined vs. prior period: "
            + "; ".join(
                f"{d.label} {d.format_value(d.prior)} → {d.format_value(d.current)}"
                for d in declined
            )
            + "."
        )
    if not improved and not declined:
        lines.append("No headline metric moved between the two periods.")

    movers = [p for p in comparison.programs if p.delta is not None and abs(p.delta) >= 5]
    for p in sorted(movers, key=lambda x: -(abs(x.delta or 0))):
        direction = "up" if (p.delta or 0) > 0 else "down"
        caution = " (small sample — interpret with caution)" if p.small_sample else ""
        lines.append(
            f"{p.program}: successful-exit rate {direction} {abs(p.delta or 0):.1f} points "
            f"({p.prior_rate}% → {p.current_rate}%){caution}."
        )
    lines.append(
        "Period differences are associations, not causal effects; intake mix, seasonality, "
        "and data completeness can all move these numbers."
    )
    return lines
