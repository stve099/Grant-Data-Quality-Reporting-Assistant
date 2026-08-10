"""Typed deterministic analytics results."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ProgramMetrics(BaseModel):
    """Outcome metrics for one program."""

    program: str
    enrollments: int
    active: int
    exits: int
    exit_rate: float | None
    successful_exits: int
    successful_exit_rate: float | None
    permanent_housing_exits: int
    permanent_housing_rate: float | None
    avg_income_change: float | None
    median_income_change: float | None
    n_income_pairs: int
    small_sample: bool
    #: Median days from enrollment to exit for this program's exited clients.
    #: None when no exit has both dates recorded.
    median_length_of_stay_days: float | None = None


class FollowUpMetrics(BaseModel):
    """Completion metrics for one follow-up milestone."""

    key: str
    label: str
    due: int
    completed_of_due: int
    overdue: int
    completion_rate: float | None


class MeasureResult(BaseModel):
    """A performance measure compared against its target."""

    id: str
    name: str
    metric: str
    unit: str
    direction: str
    target: float
    actual: float | None
    denominator: int
    met: bool | None
    small_sample: bool
    program: str | None = None
    description: str = ""
    #: Attainment as a percentage of target, alongside how far through the
    #: period the run falls. Together they answer "are we on pace?" mid-period,
    #: which a bare met/not-met cannot: 48% of target at 62% elapsed is behind,
    #: the same figure at 20% elapsed is ahead.
    attainment_pct: float | None = None
    period_elapsed_pct: float | None = None

    @property
    def on_pace(self) -> bool | None:
        """Whether attainment is keeping up with elapsed time.

        None once met is decided or the period has closed, because pacing is a
        mid-period question — after the period, met/not-met is the answer.
        """
        if self.attainment_pct is None or self.period_elapsed_pct is None:
            return None
        if self.period_elapsed_pct >= 100:
            return None
        return self.attainment_pct >= self.period_elapsed_pct


class AnalyticsResult(BaseModel):
    """Complete deterministic analytics for one dataset + profile."""

    profile_id: str
    grant_name: str
    period_start: date
    period_end: date
    as_of: date

    # Population totals
    total_enrollments: int
    households_served: int
    total_individuals: int
    total_adults: int
    total_children: int
    active_enrollments: int

    # Exits and outcomes
    total_exits: int
    exit_rate: float | None
    exits_with_known_destination: int
    successful_exits: int
    successful_exit_rate: float | None
    permanent_housing_exits: int
    permanent_housing_rate: float | None
    exit_destination_breakdown: dict[str, int]
    exit_category_breakdown: dict[str, int]

    # Length of stay. None when no exit has both an entry and an exit date;
    # a stay is never assumed to be zero just because a date is missing.
    median_length_of_stay_days: float | None = None
    avg_length_of_stay_days: float | None = None
    n_length_of_stay: int = 0
    #: Destination -> median days to that destination. Only destinations with at
    #: least SMALL_SAMPLE_N exits appear: a median over three stays is noise.
    median_length_of_stay_by_destination: dict[str, float] = Field(default_factory=dict)

    # Period pacing
    #: How far through the reporting period ``as_of`` falls, 0-100. Above 100
    #: when the report is generated after the period closed.
    period_elapsed_pct: float | None = None

    # Income
    n_income_pairs: int
    avg_entry_income: float | None
    avg_exit_income: float | None
    median_entry_income: float | None
    median_exit_income: float | None
    avg_income_change: float | None
    median_income_change: float | None
    pct_income_increased: float | None
    income_changes: list[float] = Field(default_factory=list)

    # Follow-ups
    followups: list[FollowUpMetrics] = Field(default_factory=list)
    overall_followup_completion_rate: float | None = None
    total_overdue_followups: int = 0

    # Case management
    assessment_completion_rate: float | None = None
    exit_plan_completion_rate: float | None = None

    # Demographics
    demographics: dict[str, dict[str, int]] = Field(default_factory=dict)
    #: field -> count of responses that record no demographic value.
    unreported_demographics: dict[str, int] = Field(default_factory=dict)
    age_groups: dict[str, int] = Field(default_factory=dict)
    household_size_distribution: dict[str, int] = Field(default_factory=dict)

    # Programs and trends
    programs: list[ProgramMetrics] = Field(default_factory=list)
    monthly_enrollments: dict[str, int] = Field(default_factory=dict)
    monthly_exits: dict[str, int] = Field(default_factory=dict)
    month_over_month_enrollment_change: float | None = None

    # Performance measures
    measures: list[MeasureResult] = Field(default_factory=list)

    # Methodology notes
    duplicates_removed: int = 0
    notes: list[str] = Field(default_factory=list)

    def metric_lookup(self) -> dict[str, float | int | None]:
        """Flat name -> value map of headline metrics (used for AI grounding)."""
        out: dict[str, float | int | None] = {
            "total_enrollments": self.total_enrollments,
            "households_served": self.households_served,
            "total_individuals": self.total_individuals,
            "total_adults": self.total_adults,
            "total_children": self.total_children,
            "active_enrollments": self.active_enrollments,
            "total_exits": self.total_exits,
            "exit_rate": self.exit_rate,
            "successful_exits": self.successful_exits,
            "successful_exit_rate": self.successful_exit_rate,
            "permanent_housing_exits": self.permanent_housing_exits,
            "permanent_housing_rate": self.permanent_housing_rate,
            "avg_entry_income": self.avg_entry_income,
            "avg_exit_income": self.avg_exit_income,
            "median_entry_income": self.median_entry_income,
            "median_exit_income": self.median_exit_income,
            "avg_income_change": self.avg_income_change,
            "median_income_change": self.median_income_change,
            "pct_income_increased": self.pct_income_increased,
            "overall_followup_completion_rate": self.overall_followup_completion_rate,
            "total_overdue_followups": self.total_overdue_followups,
            "assessment_completion_rate": self.assessment_completion_rate,
            "exit_plan_completion_rate": self.exit_plan_completion_rate,
            "month_over_month_enrollment_change": self.month_over_month_enrollment_change,
            "median_length_of_stay_days": self.median_length_of_stay_days,
            "avg_length_of_stay_days": self.avg_length_of_stay_days,
            "period_elapsed_pct": self.period_elapsed_pct,
        }
        for fu in self.followups:
            out[f"followup_{fu.key}_completion_rate"] = fu.completion_rate
            out[f"followup_{fu.key}_overdue"] = fu.overdue
        for field_name, count in self.unreported_demographics.items():
            out[f"unreported_{field_name}"] = count
        return out
