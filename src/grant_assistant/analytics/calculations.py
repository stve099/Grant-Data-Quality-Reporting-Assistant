"""Deterministic grant analytics calculations."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from grant_assistant import schema
from grant_assistant.analytics.models import (
    AnalyticsResult,
    FollowUpMetrics,
    MeasureResult,
    ProgramMetrics,
)
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


def _stay_days(frame: pd.DataFrame) -> pd.Series:
    """Days from enrollment to exit, for rows where the span is meaningful.

    A negative span means the exit predates the enrollment — an audit finding
    (DQ-030), not a length of stay — so those rows are dropped rather than
    allowed to pull a median downward.
    """
    entry = frame[schema.ENROLLMENT_DATE]
    exit_ = frame[schema.EXIT_DATE]
    span = (exit_ - entry).dt.days
    return span[span.notna() & (span >= 0)].astype(float)


def _rate(numerator: int, denominator: int) -> float | None:
    """Percentage rate, or None when the denominator is zero."""
    if denominator == 0:
        return None
    return round(100.0 * numerator / denominator, 1)


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
        sub_stay = _stay_days(sub_exited)
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
                median_length_of_stay_days=(
                    round(float(sub_stay.median()), 1) if len(sub_stay) else None
                ),
            )
        )

    # Length of stay. Computed from exits only: an active client's stay is not
    # yet a length, and treating "still enrolled" as a short stay would
    # understate every figure here.
    stay = _stay_days(exited)
    stay_by_destination: dict[str, float] = {}
    if len(stay):
        dest_series = exited[schema.EXIT_DESTINATION].astype(str).str.strip()
        for destination, group in exited.groupby(dest_series):
            group_stay = _stay_days(group)
            # A median over a handful of stays is noise, so the same
            # small-sample threshold that guards rates guards this too.
            if len(group_stay) >= SMALL_SAMPLE_N:
                stay_by_destination[str(destination)] = round(float(group_stay.median()), 1)

    # How far through the reporting period this run falls. Above 100 once the
    # period has closed, which is meaningful rather than an error: it says the
    # figures are final.
    period_days = (profile.reporting_period.end - profile.reporting_period.start).days
    elapsed_pct: float | None = None
    if period_days > 0:
        elapsed = (as_of - profile.reporting_period.start).days
        elapsed_pct = round(100.0 * elapsed / period_days, 1)

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
        median_length_of_stay_days=round(float(stay.median()), 1) if len(stay) else None,
        avg_length_of_stay_days=round(float(stay.mean()), 1) if len(stay) else None,
        n_length_of_stay=len(stay),
        median_length_of_stay_by_destination=stay_by_destination,
        period_elapsed_pct=elapsed_pct,
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
        # Pacing only makes sense for a target you climb toward. An "at most"
        # target is satisfied by staying low, so "62% of the way there" would be
        # backwards.
        attainment: float | None = None
        if actual is not None and pm.direction == "at_least" and pm.target:
            attainment = round(100.0 * actual / pm.target, 1)
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
                attainment_pct=attainment,
                period_elapsed_pct=result.period_elapsed_pct,
            )
        )
    return measures
