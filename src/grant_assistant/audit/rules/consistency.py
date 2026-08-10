"""Rules for fields that contradict each other."""

from __future__ import annotations

import pandas as pd

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.audit.rules._helpers import _issue, _records
from grant_assistant.models import AuditIssue, IssueRecord, Severity


@rule(
    "DQ-027",
    "Non-standard program label",
    "consistency",
    Severity.INFO,
    description="Program recorded under an alias rather than its canonical name.",
)
def program_alias_used(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    raw_label = df[schema.PROGRAM_RAW]
    canonical = df[schema.PROGRAM]
    mask = (
        raw_label.notna()
        & canonical.isin(ctx.profile.program_names)
        & (raw_label.astype(str) != canonical.astype(str))
    )
    records = _records(ctx, mask, field=schema.PROGRAM, values=raw_label)
    if not records:
        return []
    return [
        _issue(
            "DQ-027",
            "Non-standard program label",
            "consistency",
            Severity.INFO,
            False,
            "Program names were recorded under known aliases (for example abbreviations or "
            "legacy names). They were normalized automatically for this analysis.",
            "Standardize program names in the source system to the canonical labels.",
            records,
        )
    ]


@rule(
    "DQ-030",
    "Exit before enrollment",
    "consistency",
    Severity.CRITICAL,
    blocking=True,
    description="Exit dates earlier than the enrollment date.",
)
def exit_before_entry(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    mask = (
        df[schema.EXIT_DATE].notna()
        & df[schema.ENROLLMENT_DATE].notna()
        & (df[schema.EXIT_DATE] < df[schema.ENROLLMENT_DATE])
    )
    records = _records(ctx, mask, field=schema.EXIT_DATE, value_col=schema.EXIT_DATE)
    if not records:
        return []
    return [
        _issue(
            "DQ-030",
            "Exit before enrollment",
            "consistency",
            Severity.CRITICAL,
            True,
            "Exit dates fall before the enrollment date, which is impossible and produces "
            "negative lengths of stay.",
            "Check both dates against case notes and correct whichever was mis-entered.",
            records,
        )
    ]


@rule(
    "DQ-031",
    "Follow-up before exit",
    "consistency",
    Severity.HIGH,
    description="Follow-up completion dates earlier than the exit date.",
)
def followup_before_exit(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    records: list[IssueRecord] = []
    for fu in ctx.profile.followup_schedule:
        col = fu.completion_field
        mask = df[col].notna() & df[schema.EXIT_DATE].notna() & (df[col] < df[schema.EXIT_DATE])
        records.extend(_records(ctx, mask, field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-031",
            "Follow-up before exit",
            "consistency",
            Severity.HIGH,
            False,
            "Post-exit follow-up dates fall before the client's exit date, so they cannot "
            "be valid follow-up contacts.",
            "Verify the follow-up date; if the contact happened pre-exit it does not count "
            "as a post-exit follow-up.",
            records,
        )
    ]


@rule(
    "DQ-032",
    "Household composition mismatch",
    "consistency",
    Severity.MEDIUM,
    description="Adults plus children does not equal household size.",
)
def household_mismatch(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    mask = (
        df[schema.HOUSEHOLD_SIZE].notna()
        & df[schema.ADULTS].notna()
        & df[schema.CHILDREN].notna()
        & (df[schema.ADULTS] + df[schema.CHILDREN] != df[schema.HOUSEHOLD_SIZE])
    )
    values = (
        df[schema.ADULTS].astype("string")
        + " adults + "
        + df[schema.CHILDREN].astype("string")
        + " children ≠ size "
        + df[schema.HOUSEHOLD_SIZE].astype("string")
    )
    records = _records(ctx, mask, field=schema.HOUSEHOLD_SIZE, values=values)
    if not records:
        return []
    return [
        _issue(
            "DQ-032",
            "Household composition mismatch",
            "consistency",
            Severity.MEDIUM,
            False,
            "Adults plus children does not add up to the recorded household size, so adult/"
            "child population counts and household metrics disagree with each other.",
            "Recount household members and align the three fields.",
            records,
        )
    ]


@rule(
    "DQ-033",
    "Status contradicts exit date",
    "consistency",
    Severity.HIGH,
    description="Enrollment status inconsistent with presence of an exit date.",
)
def status_exit_mismatch(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    status = df[schema.ENROLLMENT_STATUS].astype("string").str.strip().str.casefold()
    has_exit = df[schema.EXIT_DATE].notna()
    active_with_exit = (status == "active") & has_exit
    exited_without_exit = (status == "exited") & ~has_exit
    records = _records(
        ctx,
        active_with_exit.fillna(False),
        field=schema.ENROLLMENT_STATUS,
        value_col=schema.ENROLLMENT_STATUS,
    )
    records += _records(
        ctx,
        exited_without_exit.fillna(False),
        field=schema.ENROLLMENT_STATUS,
        value_col=schema.ENROLLMENT_STATUS,
    )
    if not records:
        return []
    return [
        _issue(
            "DQ-033",
            "Status contradicts exit date",
            "consistency",
            Severity.HIGH,
            False,
            "Records are marked Active but have an exit date, or marked Exited with no exit "
            "date. Active/exit counts depend on which field you trust.",
            "Reconcile the enrollment status with the exit date for each flagged record.",
            records,
        )
    ]


@rule(
    "DQ-034",
    "Date outside reporting period",
    "consistency",
    Severity.INFO,
    description="Enrollment or exit dates after the reporting period end.",
)
def outside_period(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    end = pd.Timestamp(ctx.profile.reporting_period.end)
    records: list[IssueRecord] = []
    for col in (schema.ENROLLMENT_DATE, schema.EXIT_DATE):
        mask = df[col].notna() & (df[col] > end)
        records.extend(_records(ctx, mask, field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-034",
            "Date outside reporting period",
            "consistency",
            Severity.INFO,
            False,
            f"Dates fall after the reporting period end ({ctx.profile.reporting_period.end}). "
            "These records may belong to the next reporting period.",
            "Confirm the dates are correct; filter the export to the reporting period if not.",
            records,
        )
    ]


@rule(
    "DQ-035",
    "Future-dated event",
    "consistency",
    Severity.HIGH,
    description="Enrollment or exit dates later than the audit date.",
)
def future_dated(ctx: RuleContext) -> list[AuditIssue]:
    # DQ-020 catches dates that cannot be parsed; DQ-034 catches dates after
    # the reporting period *end*. Neither catches a date that is a valid
    # calendar date, inside the reporting period, but still in the future
    # relative to today — which can only happen mid-period, exactly when the
    # on-pace figures from v1.6.0 are reported. A future enrollment or exit
    # has not happened yet, so it inflates current counts and the pacing
    # derived from them.
    df = ctx.data.df
    today = pd.Timestamp(ctx.today)
    records: list[IssueRecord] = []
    for col in (schema.ENROLLMENT_DATE, schema.EXIT_DATE):
        mask = df[col].notna() & (df[col] > today)
        records.extend(_records(ctx, mask, field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-035",
            "Future-dated event",
            "consistency",
            Severity.HIGH,
            False,
            f"Enrollment or exit dates fall after the audit date ({ctx.today.isoformat()}). "
            "A future date cannot have happened yet, so it inflates current-period counts "
            "and the on-pace figures derived from them.",
            "Correct the date to the real value, or hold the record back until the event "
            "has occurred.",
            records,
        )
    ]


# -- Case management ---------------------------------------------------------
