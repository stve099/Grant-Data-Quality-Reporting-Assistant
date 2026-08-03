"""Deterministic analytics calculations.

Every number that appears in dashboards, reports, or AI answers is computed
here in plain, testable pandas code. The AI agent only ever narrates these
results — it never computes metrics itself.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from grant_assistant import schema
from grant_assistant.configuration import GrantProfile
from grant_assistant.followups import followup_status
from grant_assistant.ingestion import PreparedData

logger = logging.getLogger(__name__)

SMALL_SAMPLE_N = 10

#: Responses that record an absence of data rather than a demographic value.
#: Reports routinely quote these as one "not reported" figure per field. Without
#: a calculated total the model has to add the categories itself, which is the
#: arithmetic the grounding contract forbids — so the sum is computed here.
NOT_REPORTED_VALUES = frozenset(
    {
        "missing",
        "unknown",
        "declined",
        "refused",
        "client refused",
        "client doesn't know",
        "data not collected",
        "not collected",
        "prefer not to say",
    }
)


def _rate(numerator: int, denominator: int) -> float | None:
    """Percentage rate, or None when the denominator is zero."""
    if denominator == 0:
        return None
    return round(100.0 * numerator / denominator, 1)


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
        }
        for fu in self.followups:
            out[f"followup_{fu.key}_completion_rate"] = fu.completion_rate
            out[f"followup_{fu.key}_overdue"] = fu.overdue
        for field_name, count in self.unreported_demographics.items():
            out[f"unreported_{field_name}"] = count
        return out


def _age_group_labels(bounds: list[int]) -> list[tuple[str, int, int | None]]:
    """Build (label, low, high_exclusive) age bands from configured bounds."""
    bands: list[tuple[str, int, int | None]] = []
    low = 0
    for bound in bounds:
        bands.append((f"{low}–{bound - 1}", low, bound))
        low = bound
    bands.append((f"{low}+", low, None))
    return bands


def compute_analytics(
    data: PreparedData,
    profile: GrantProfile,
    as_of: date | None = None,
) -> AnalyticsResult:
    """Compute the full analytics result for a prepared dataset."""
    as_of = as_of or date.today()
    df = data.df

    # Deduplicate exact duplicate enrollments so counts are not inflated.
    before = len(df)
    df = df.drop_duplicates(subset=[schema.CLIENT_ID, schema.PROGRAM, schema.ENROLLMENT_DATE])
    duplicates_removed = before - len(df)

    notes: list[str] = []
    if duplicates_removed:
        notes.append(
            f"{duplicates_removed} duplicate enrollment record(s) were excluded from analytics."
        )

    total = len(df)
    exited = df[df[schema.EXIT_DATE].notna()]
    active = total - len(exited)

    # Household / individual totals (first record per household).
    hh = df[df[schema.HOUSEHOLD_ID].notna()].drop_duplicates(subset=[schema.HOUSEHOLD_ID])
    cap = profile.max_household_size
    valid_size = hh[schema.HOUSEHOLD_SIZE].where(
        (hh[schema.HOUSEHOLD_SIZE] >= 1) & (hh[schema.HOUSEHOLD_SIZE] <= cap)
    )
    valid_adults = hh[schema.ADULTS].where((hh[schema.ADULTS] >= 0) & (hh[schema.ADULTS] <= cap))
    valid_children = hh[schema.CHILDREN].where(
        (hh[schema.CHILDREN] >= 0) & (hh[schema.CHILDREN] <= cap)
    )
    if valid_size.isna().any():
        notes.append(
            f"{int(valid_size.isna().sum())} household(s) had missing or implausible "
            "household size and were excluded from individual counts."
        )

    # Exit destinations.
    dest = exited[schema.EXIT_DESTINATION].dropna().astype(str).str.strip()
    dest_counts: dict[str, int] = {str(k): int(v) for k, v in dest.value_counts().to_dict().items()}
    cat_counts: dict[str, int] = {}
    for value, count in dest_counts.items():
        category = profile.destination_category(value) or "other_unmapped"
        cat_counts[category] = cat_counts.get(category, 0) + count
    successful_dest = {d.casefold() for d in profile.successful_destinations}
    successful = int(dest.str.casefold().isin(successful_dest).sum())
    perm_values = {
        d.casefold() for d in profile.exit_destination_categories.get("permanent_housing", [])
    }
    permanent = int(dest.str.casefold().isin(perm_values).sum())

    # Income outcomes (exited clients with valid entry and exit income).
    inc = exited[
        exited[schema.ENTRY_INCOME].notna()
        & exited[schema.EXIT_INCOME].notna()
        & (exited[schema.ENTRY_INCOME] >= 0)
        & (exited[schema.EXIT_INCOME] >= 0)
        & (exited[schema.ENTRY_INCOME] <= profile.income_cap)
        & (exited[schema.EXIT_INCOME] <= profile.income_cap)
    ]
    changes = (inc[schema.EXIT_INCOME] - inc[schema.ENTRY_INCOME]).astype(float)
    n_pairs = len(inc)
    if len(exited) and n_pairs < len(exited):
        notes.append(
            f"Income change is based on {n_pairs} of {len(exited)} exits; the rest were "
            "missing or had invalid entry/exit income."
        )

    all_entry = df[schema.ENTRY_INCOME]
    all_entry = all_entry[
        (all_entry.notna()) & (all_entry >= 0) & (all_entry <= profile.income_cap)
    ]
    all_exit = exited[schema.EXIT_INCOME]
    all_exit = all_exit[(all_exit.notna()) & (all_exit >= 0) & (all_exit <= profile.income_cap)]

    # Follow-ups.
    followups: list[FollowUpMetrics] = []
    total_due = total_completed = total_overdue = 0
    for fu in profile.followup_schedule:
        status = followup_status(df, fu, as_of)
        due = int(status["due"].sum())
        completed_of_due = int((status["due"] & status["completed"]).sum())
        overdue = int(status["overdue"].sum())
        total_due += due
        total_completed += completed_of_due
        total_overdue += overdue
        followups.append(
            FollowUpMetrics(
                key=fu.key,
                label=fu.label,
                due=due,
                completed_of_due=completed_of_due,
                overdue=overdue,
                completion_rate=_rate(completed_of_due, due),
            )
        )

    # Case management.
    assess = df[schema.ASSESSMENT_STATUS].astype("string").str.strip().str.casefold()
    assess_rate = _rate(int(assess.isin(["completed", "complete"]).sum()), total)
    plan = exited[schema.EXIT_PLAN_STATUS].astype("string").str.strip().str.casefold()
    plan_rate = _rate(int(plan.isin(["completed", "complete"]).sum()), len(exited))

    # Demographics.
    demographics: dict[str, dict[str, int]] = {}
    for col in profile.demographic_fields:
        counts = (
            (df[col].astype("string").str.strip().fillna("Missing").replace("", "Missing"))
            .value_counts()
            .to_dict()
        )
        demographics[col] = {str(k): int(v) for k, v in counts.items()}

    unreported_demographics = {
        field_name: sum(
            count
            for value, count in counts.items()
            if value.strip().casefold() in NOT_REPORTED_VALUES
        )
        for field_name, counts in demographics.items()
    }

    age_groups: dict[str, int] = {}
    ages = df[schema.AGE]
    valid_ages = ages[(ages.notna()) & (ages >= 0) & (ages <= profile.max_age)]
    for label, low, high in _age_group_labels(profile.age_group_bounds):
        if high is None:
            age_groups[label] = int((valid_ages >= low).sum())
        else:
            age_groups[label] = int(((valid_ages >= low) & (valid_ages < high)).sum())
    if len(valid_ages) < total:
        age_groups["Unknown"] = total - len(valid_ages)

    sizes = df[schema.HOUSEHOLD_SIZE]
    valid_sizes = sizes[(sizes.notna()) & (sizes >= 1) & (sizes <= cap)]
    size_dist = {
        str(int(float(str(k)))): int(v) for k, v in sorted(valid_sizes.value_counts().items())
    }

    # Program comparison.
    programs: list[ProgramMetrics] = []
    for program in profile.program_names:
        sub = df[df[schema.PROGRAM] == program]
        if sub.empty:
            continue
        sub_exited = sub[sub[schema.EXIT_DATE].notna()]
        sub_dest = sub_exited[schema.EXIT_DESTINATION].dropna().astype(str).str.strip()
        sub_successful = int(sub_dest.str.casefold().isin(successful_dest).sum())
        sub_perm = int(sub_dest.str.casefold().isin(perm_values).sum())
        sub_inc = sub_exited[
            sub_exited[schema.ENTRY_INCOME].notna()
            & sub_exited[schema.EXIT_INCOME].notna()
            & (sub_exited[schema.ENTRY_INCOME] >= 0)
            & (sub_exited[schema.EXIT_INCOME] >= 0)
            & (sub_exited[schema.ENTRY_INCOME] <= profile.income_cap)
            & (sub_exited[schema.EXIT_INCOME] <= profile.income_cap)
        ]
        sub_changes = (sub_inc[schema.EXIT_INCOME] - sub_inc[schema.ENTRY_INCOME]).astype(float)
        programs.append(
            ProgramMetrics(
                program=program,
                enrollments=len(sub),
                active=int(sub[schema.EXIT_DATE].isna().sum()),
                exits=len(sub_exited),
                exit_rate=_rate(len(sub_exited), len(sub)),
                successful_exits=sub_successful,
                successful_exit_rate=_rate(sub_successful, len(sub_exited)),
                permanent_housing_exits=sub_perm,
                permanent_housing_rate=_rate(sub_perm, len(sub_exited)),
                avg_income_change=(
                    round(float(sub_changes.mean()), 2) if len(sub_changes) else None
                ),
                median_income_change=(
                    round(float(sub_changes.median()), 2) if len(sub_changes) else None
                ),
                n_income_pairs=len(sub_inc),
                small_sample=len(sub_exited) < SMALL_SAMPLE_N,
            )
        )

    # Monthly trends.
    enroll_months = df[schema.ENROLLMENT_DATE].dropna().dt.to_period("M")
    exit_months = df[schema.EXIT_DATE].dropna().dt.to_period("M")
    monthly_enroll = {str(k): int(v) for k, v in enroll_months.value_counts().sort_index().items()}
    monthly_exit = {str(k): int(v) for k, v in exit_months.value_counts().sort_index().items()}
    mom_change: float | None = None
    if len(monthly_enroll) >= 2:
        values = list(monthly_enroll.values())
        prev, last = values[-2], values[-1]
        if prev:
            mom_change = round(100.0 * (last - prev) / prev, 1)

    result = AnalyticsResult(
        profile_id=profile.profile_id,
        grant_name=profile.grant_name,
        period_start=profile.reporting_period.start,
        period_end=profile.reporting_period.end,
        as_of=as_of,
        total_enrollments=total,
        households_served=int(hh[schema.HOUSEHOLD_ID].nunique()),
        total_individuals=int(valid_size.sum()) if valid_size.notna().any() else 0,
        total_adults=int(valid_adults.sum()) if valid_adults.notna().any() else 0,
        total_children=int(valid_children.sum()) if valid_children.notna().any() else 0,
        active_enrollments=active,
        total_exits=len(exited),
        exit_rate=_rate(len(exited), total),
        exits_with_known_destination=int(dest.shape[0]),
        successful_exits=successful,
        successful_exit_rate=_rate(successful, len(exited)),
        permanent_housing_exits=permanent,
        permanent_housing_rate=_rate(permanent, len(exited)),
        exit_destination_breakdown={str(k): int(v) for k, v in dest_counts.items()},
        exit_category_breakdown=cat_counts,
        n_income_pairs=n_pairs,
        avg_entry_income=round(float(all_entry.mean()), 2) if len(all_entry) else None,
        avg_exit_income=round(float(all_exit.mean()), 2) if len(all_exit) else None,
        median_entry_income=round(float(all_entry.median()), 2) if len(all_entry) else None,
        median_exit_income=round(float(all_exit.median()), 2) if len(all_exit) else None,
        avg_income_change=round(float(changes.mean()), 2) if n_pairs else None,
        median_income_change=round(float(changes.median()), 2) if n_pairs else None,
        pct_income_increased=_rate(int((changes > 0).sum()), n_pairs),
        income_changes=[round(float(c), 2) for c in changes],
        followups=followups,
        overall_followup_completion_rate=_rate(total_completed, total_due),
        total_overdue_followups=total_overdue,
        assessment_completion_rate=assess_rate,
        exit_plan_completion_rate=plan_rate,
        demographics=demographics,
        unreported_demographics=unreported_demographics,
        age_groups=age_groups,
        household_size_distribution=size_dist,
        programs=programs,
        monthly_enrollments=monthly_enroll,
        monthly_exits=monthly_exit,
        month_over_month_enrollment_change=mom_change,
        duplicates_removed=duplicates_removed,
        notes=notes,
    )
    result.measures = _evaluate_measures(result, profile)
    logger.info(
        "Analytics complete: %d enrollments, %d exits, %d measures evaluated",
        total,
        len(exited),
        len(result.measures),
    )
    return result


def _evaluate_measures(result: AnalyticsResult, profile: GrantProfile) -> list[MeasureResult]:
    """Compare configured performance measures against computed metrics."""
    lookup: dict[str, tuple[float | int | None, int]] = {
        "total_enrollments": (result.total_enrollments, result.total_enrollments),
        "households_served": (result.households_served, result.households_served),
        "total_exits": (result.total_exits, result.total_exits),
        "exit_rate": (result.exit_rate, result.total_enrollments),
        "successful_exit_rate": (result.successful_exit_rate, result.total_exits),
        "permanent_housing_rate": (result.permanent_housing_rate, result.total_exits),
        "pct_income_increased": (result.pct_income_increased, result.n_income_pairs),
        "avg_income_change": (result.avg_income_change, result.n_income_pairs),
        "median_income_change": (result.median_income_change, result.n_income_pairs),
        "assessment_completion_rate": (
            result.assessment_completion_rate,
            result.total_enrollments,
        ),
        "exit_plan_completion_rate": (result.exit_plan_completion_rate, result.total_exits),
        "overall_followup_completion_rate": (
            result.overall_followup_completion_rate,
            sum(f.due for f in result.followups),
        ),
    }
    for fu in result.followups:
        lookup[f"followup_{fu.key}_completion_rate"] = (fu.completion_rate, fu.due)

    programs_by_name = {p.program: p for p in result.programs}

    def program_lookup(program: str, metric: str) -> tuple[float | int | None, int]:
        pm_metrics = programs_by_name.get(program)
        if pm_metrics is None:
            return None, 0
        scoped: dict[str, tuple[float | int | None, int]] = {
            "total_enrollments": (pm_metrics.enrollments, pm_metrics.enrollments),
            "enrollments": (pm_metrics.enrollments, pm_metrics.enrollments),
            "total_exits": (pm_metrics.exits, pm_metrics.exits),
            "exits": (pm_metrics.exits, pm_metrics.exits),
            "exit_rate": (pm_metrics.exit_rate, pm_metrics.enrollments),
            "successful_exit_rate": (pm_metrics.successful_exit_rate, pm_metrics.exits),
            "permanent_housing_rate": (pm_metrics.permanent_housing_rate, pm_metrics.exits),
            "avg_income_change": (pm_metrics.avg_income_change, pm_metrics.n_income_pairs),
            "median_income_change": (pm_metrics.median_income_change, pm_metrics.n_income_pairs),
        }
        return scoped.get(metric, (None, 0))

    measures: list[MeasureResult] = []
    for pm in profile.performance_measures:
        if pm.program is not None:
            actual, denominator = program_lookup(pm.program, pm.metric)
        else:
            actual, denominator = lookup.get(pm.metric, (None, 0))
        met: bool | None = None
        if actual is not None:
            met = actual >= pm.target if pm.direction == "at_least" else actual <= pm.target
        measures.append(
            MeasureResult(
                id=pm.id,
                name=pm.name,
                metric=pm.metric,
                unit=pm.unit,
                direction=pm.direction,
                target=pm.target,
                actual=actual if actual is None else float(actual),
                denominator=int(denominator),
                met=met,
                small_sample=0 < denominator < SMALL_SAMPLE_N,
                program=pm.program,
                description=pm.description,
            )
        )
    return measures


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
