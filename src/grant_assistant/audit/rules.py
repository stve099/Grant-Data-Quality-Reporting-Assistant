"""Audit rule implementations.

Every rule is registered with the engine via the :func:`~grant_assistant.audit.engine.rule`
decorator and returns a list of :class:`~grant_assistant.models.AuditIssue`.
Rules read raw values (pre-coercion) when distinguishing "missing" from
"present but invalid".
"""

from __future__ import annotations

import pandas as pd

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.followups import followup_status
from grant_assistant.models import AuditIssue, IssueRecord, Severity

# -- Helpers -----------------------------------------------------------------


def _s(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return ""
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return str(value)


def _records(
    ctx: RuleContext,
    mask: pd.Series,
    field: str = "",
    value_col: str | None = None,
    values: pd.Series | None = None,
) -> list[IssueRecord]:
    """Build issue records from a boolean mask aligned to the prepared frame."""
    df, raw = ctx.data.df, ctx.data.raw
    rows = ctx.data.row_numbers
    records: list[IssueRecord] = []
    for idx in df.index[mask.fillna(False)]:
        if values is not None:
            value = values.loc[idx]
        elif value_col is not None:
            value = raw.at[idx, value_col]
        else:
            value = None
        records.append(
            IssueRecord(
                row=int(str(rows.at[idx])),
                client_id=_s(raw.at[idx, schema.CLIENT_ID]),
                program=_s(df.at[idx, schema.PROGRAM]),
                field=field,
                value=_s(value),
            )
        )
    return records


def _issue(
    rule_id: str,
    name: str,
    category: str,
    severity: Severity,
    blocking: bool,
    explanation: str,
    recommendation: str,
    records: list[IssueRecord],
) -> AuditIssue:
    return AuditIssue(
        rule_id=rule_id,
        rule_name=name,
        category=category,
        severity=severity,
        blocking=blocking,
        explanation=explanation,
        recommendation=recommendation,
        records=records,
    )


def _exited(ctx: RuleContext) -> pd.Series:
    return ctx.data.df[schema.EXIT_DATE].notna()


# -- Completeness ------------------------------------------------------------


@rule(
    "DQ-001",
    "Missing required fields",
    "completeness",
    Severity.HIGH,
    blocking=True,
    description="Fields the grant profile marks as required are empty.",
)
def missing_required(ctx: RuleContext) -> list[AuditIssue]:
    records: list[IssueRecord] = []
    for col in ctx.profile.required_fields:
        mask = ctx.data.raw[col].isna()
        records.extend(_records(ctx, mask, field=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-001",
            "Missing required fields",
            "completeness",
            Severity.HIGH,
            True,
            "Required fields defined by the grant profile are empty. Reports built on "
            "incomplete required data may be rejected by the funder.",
            "Fill in the missing values from case files or the source system, then re-upload.",
            records,
        )
    ]


@rule(
    "DQ-002",
    "Missing entry income",
    "completeness",
    Severity.LOW,
    description="Entry income is not recorded.",
)
def missing_entry_income(ctx: RuleContext) -> list[AuditIssue]:
    mask = ctx.data.raw[schema.ENTRY_INCOME].isna()
    records = _records(ctx, mask, field=schema.ENTRY_INCOME)
    if not records:
        return []
    return [
        _issue(
            "DQ-002",
            "Missing entry income",
            "completeness",
            Severity.LOW,
            False,
            "Entry income is blank. Income-change outcomes cannot include these households.",
            "Record entry income at intake (use 0 for no income rather than leaving blank).",
            records,
        )
    ]


@rule(
    "DQ-003",
    "Missing exit income",
    "completeness",
    Severity.MEDIUM,
    description="Exited clients with no exit income recorded.",
)
def missing_exit_income(ctx: RuleContext) -> list[AuditIssue]:
    mask = _exited(ctx) & ctx.data.raw[schema.EXIT_INCOME].isna()
    records = _records(ctx, mask, field=schema.EXIT_INCOME)
    if not records:
        return []
    return [
        _issue(
            "DQ-003",
            "Missing exit income",
            "completeness",
            Severity.MEDIUM,
            False,
            "Clients have exited but no exit income was recorded, understating "
            "income-change performance measures.",
            "Collect exit income during the exit interview; update records for recent exits.",
            records,
        )
    ]


@rule(
    "DQ-004",
    "Missing exit destination",
    "completeness",
    Severity.HIGH,
    blocking=True,
    description="Exited clients with no exit destination.",
)
def missing_exit_destination(ctx: RuleContext) -> list[AuditIssue]:
    mask = _exited(ctx) & ctx.data.raw[schema.EXIT_DESTINATION].isna()
    records = _records(ctx, mask, field=schema.EXIT_DESTINATION)
    if not records:
        return []
    return [
        _issue(
            "DQ-004",
            "Missing exit destination",
            "completeness",
            Severity.HIGH,
            True,
            "Exited clients have no destination recorded. Housing outcome measures "
            "(including permanent housing rate) exclude these exits.",
            "Determine the destination from exit paperwork and record it before reporting.",
            records,
        )
    ]


@rule(
    "DQ-005",
    "Missing demographic fields",
    "completeness",
    Severity.LOW,
    description="Demographic fields used in report breakdowns are empty.",
)
def missing_demographics(ctx: RuleContext) -> list[AuditIssue]:
    records: list[IssueRecord] = []
    for col in ctx.profile.demographic_fields:
        mask = ctx.data.raw[col].isna()
        records.extend(_records(ctx, mask, field=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-005",
            "Missing demographic fields",
            "completeness",
            Severity.LOW,
            False,
            "Demographic fields are blank, so demographic breakdowns in the report "
            "will undercount these clients.",
            "Capture missing demographics at the next client contact; use the funder's "
            "'unknown/declined' codes instead of leaving cells empty.",
            records,
        )
    ]


# -- Uniqueness --------------------------------------------------------------


@rule(
    "DQ-010",
    "Duplicate client enrollment",
    "uniqueness",
    Severity.CRITICAL,
    blocking=True,
    description="Same client enrolled in the same program on the same date more than once.",
)
def duplicate_client(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    subset = [schema.CLIENT_ID, schema.PROGRAM, schema.ENROLLMENT_DATE]
    mask = df[schema.CLIENT_ID].notna() & df.duplicated(subset=subset, keep=False)
    records = _records(ctx, mask, field=schema.CLIENT_ID, value_col=schema.CLIENT_ID)
    if not records:
        return []
    return [
        _issue(
            "DQ-010",
            "Duplicate client enrollment",
            "uniqueness",
            Severity.CRITICAL,
            True,
            "The same client ID appears more than once for the same program and enrollment "
            "date. Duplicates inflate enrollment counts and distort every rate.",
            "Keep one record per client per enrollment; merge or delete the duplicates.",
            records,
        )
    ]


@rule(
    "DQ-011",
    "Duplicate enrollment record",
    "uniqueness",
    Severity.HIGH,
    description="Entire rows duplicated in the file.",
)
def duplicate_rows(ctx: RuleContext) -> list[AuditIssue]:
    raw = ctx.data.raw
    mask = raw.duplicated(keep=False)
    # Avoid double-reporting rows already caught as duplicate client enrollments.
    df = ctx.data.df
    dup_client = df[schema.CLIENT_ID].notna() & df.duplicated(
        subset=[schema.CLIENT_ID, schema.PROGRAM, schema.ENROLLMENT_DATE], keep=False
    )
    mask = mask & ~dup_client
    records = _records(ctx, mask)
    if not records:
        return []
    return [
        _issue(
            "DQ-011",
            "Duplicate enrollment record",
            "uniqueness",
            Severity.HIGH,
            False,
            "Rows are exact duplicates of other rows, typically caused by a double export "
            "or copy-paste error.",
            "Remove the duplicated rows from the source export.",
            records,
        )
    ]


# -- Validity ----------------------------------------------------------------


@rule(
    "DQ-020",
    "Invalid date value",
    "validity",
    Severity.HIGH,
    description="Date fields containing values that cannot be parsed as dates.",
)
def invalid_dates(ctx: RuleContext) -> list[AuditIssue]:
    records: list[IssueRecord] = []
    for col in schema.DATE_COLUMNS:
        mask = ctx.data.raw[col].notna() & ctx.data.df[col].isna()
        records.extend(_records(ctx, mask, field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-020",
            "Invalid date value",
            "validity",
            Severity.HIGH,
            False,
            "Date fields contain values that are not valid dates (for example text or "
            "impossible calendar dates). These records are excluded from date-based metrics.",
            "Correct the values to real dates in a consistent format (YYYY-MM-DD recommended).",
            records,
        )
    ]


@rule(
    "DQ-021",
    "Invalid numeric value",
    "validity",
    Severity.HIGH,
    description="Numeric fields containing non-numeric values.",
)
def invalid_numeric(ctx: RuleContext) -> list[AuditIssue]:
    records: list[IssueRecord] = []
    for col in schema.NUMERIC_COLUMNS:
        mask = ctx.data.raw[col].notna() & ctx.data.df[col].isna()
        records.extend(_records(ctx, mask, field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-021",
            "Invalid numeric value",
            "validity",
            Severity.HIGH,
            False,
            "Numeric fields (income, ages, household counts) contain text that cannot be "
            "read as a number, so these values are treated as missing.",
            "Replace the text with numeric values; remove currency symbols and notes.",
            records,
        )
    ]


@rule(
    "DQ-022",
    "Invalid age",
    "validity",
    Severity.MEDIUM,
    description="Ages outside the plausible range.",
)
def invalid_age(ctx: RuleContext) -> list[AuditIssue]:
    age = ctx.data.df[schema.AGE]
    mask = age.notna() & ((age < 0) | (age > ctx.profile.max_age))
    records = _records(ctx, mask, field=schema.AGE, value_col=schema.AGE)
    if not records:
        return []
    return [
        _issue(
            "DQ-022",
            "Invalid age",
            "validity",
            Severity.MEDIUM,
            False,
            f"Ages are negative or above {ctx.profile.max_age}, which indicates data entry "
            "errors. Age-group breakdowns will misclassify these clients.",
            "Verify each client's date of birth and correct the age.",
            records,
        )
    ]


@rule(
    "DQ-023",
    "Invalid household counts",
    "validity",
    Severity.MEDIUM,
    description="Household size, adult, or child counts outside plausible ranges.",
)
def invalid_household(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    size = df[schema.HOUSEHOLD_SIZE]
    adults = df[schema.ADULTS]
    children = df[schema.CHILDREN]
    cap = ctx.profile.max_household_size
    records: list[IssueRecord] = []
    records.extend(
        _records(
            ctx,
            size.notna() & ((size < 1) | (size > cap)),
            field=schema.HOUSEHOLD_SIZE,
            value_col=schema.HOUSEHOLD_SIZE,
        )
    )
    records.extend(
        _records(ctx, adults.notna() & (adults < 0), field=schema.ADULTS, value_col=schema.ADULTS)
    )
    records.extend(
        _records(
            ctx, children.notna() & (children < 0), field=schema.CHILDREN, value_col=schema.CHILDREN
        )
    )
    if not records:
        return []
    return [
        _issue(
            "DQ-023",
            "Invalid household counts",
            "validity",
            Severity.MEDIUM,
            False,
            f"Household size must be between 1 and {cap}, and adult/child counts cannot be "
            "negative. These values distort household and population counts.",
            "Correct the household composition from intake records.",
            records,
        )
    ]


@rule(
    "DQ-024",
    "Negative income",
    "validity",
    Severity.HIGH,
    description="Negative entry or exit income values.",
)
def negative_income(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    records: list[IssueRecord] = []
    for col in (schema.ENTRY_INCOME, schema.EXIT_INCOME):
        vals = df[col]
        records.extend(_records(ctx, vals.notna() & (vals < 0), field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-024",
            "Negative income",
            "validity",
            Severity.HIGH,
            False,
            "Income cannot be negative. Negative values corrupt average and median income "
            "calculations and income-change measures.",
            "Correct the sign or re-enter the amount; use 0 for no income.",
            records,
        )
    ]


@rule(
    "DQ-025",
    "Unrealistic income",
    "validity",
    Severity.MEDIUM,
    description="Income values above the configured plausibility cap.",
)
def unrealistic_income(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    cap = ctx.profile.income_cap
    records: list[IssueRecord] = []
    for col in (schema.ENTRY_INCOME, schema.EXIT_INCOME):
        vals = df[col]
        records.extend(_records(ctx, vals.notna() & (vals > cap), field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-025",
            "Unrealistic income",
            "validity",
            Severity.MEDIUM,
            False,
            f"Income values exceed the plausibility cap of ${cap:,.0f} configured for this "
            "grant. These are usually typos (extra digits) and skew income averages badly.",
            "Verify against pay documentation; correct the amount or the units (monthly vs annual).",
            records,
        )
    ]


@rule(
    "DQ-026",
    "Unknown program",
    "validity",
    Severity.HIGH,
    blocking=True,
    description="Program labels that match no program or alias in the profile.",
)
def unknown_program(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    known = set(ctx.profile.program_names)
    prog = df[schema.PROGRAM]
    mask = prog.notna() & ~prog.isin(known)
    records = _records(ctx, mask, field=schema.PROGRAM, value_col=schema.PROGRAM)
    if not records:
        return []
    return [
        _issue(
            "DQ-026",
            "Unknown program",
            "validity",
            Severity.HIGH,
            True,
            "Program labels do not match any program or alias defined in the grant profile. "
            "These records cannot be attributed to a funded program.",
            "Fix the program name in the data, or add the label as an alias in the profile "
            "if it is legitimate.",
            records,
        )
    ]


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
    "DQ-028",
    "Unexpected value in controlled field",
    "validity",
    Severity.MEDIUM,
    description="Values outside the controlled vocabulary defined by the profile.",
)
def controlled_values(ctx: RuleContext) -> list[AuditIssue]:
    raw = ctx.data.raw
    records: list[IssueRecord] = []
    for col, allowed in ctx.profile.controlled_values.items():
        allowed_fold = {a.strip().casefold() for a in allowed}
        series = raw[col]
        mask = series.notna() & ~series.astype(str).str.strip().str.casefold().isin(allowed_fold)
        records.extend(_records(ctx, mask, field=col, value_col=col))
    if not records:
        return []
    return [
        _issue(
            "DQ-028",
            "Unexpected value in controlled field",
            "validity",
            Severity.MEDIUM,
            False,
            "Fields with controlled vocabularies (statuses, destinations, demographic codes) "
            "contain values outside the allowed list, so they cannot be categorized correctly.",
            "Map each unexpected value to an allowed option, or update the profile's "
            "controlled_values if the option is legitimate.",
            records,
        )
    ]


# -- Consistency -------------------------------------------------------------


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


# -- Case management ---------------------------------------------------------


@rule(
    "DQ-040",
    "Missing required assessment",
    "case_management",
    Severity.MEDIUM,
    description="Clients without a completed assessment.",
)
def missing_assessment(ctx: RuleContext) -> list[AuditIssue]:
    raw = ctx.data.raw
    status = raw[schema.ASSESSMENT_STATUS].astype("string").str.strip().str.casefold()
    mask = (~status.isin(["completed", "complete"])) | raw[schema.ASSESSMENT_STATUS].isna()
    records = _records(
        ctx, mask.fillna(True), field=schema.ASSESSMENT_STATUS, value_col=schema.ASSESSMENT_STATUS
    )
    if not records:
        return []
    return [
        _issue(
            "DQ-040",
            "Missing required assessment",
            "case_management",
            Severity.MEDIUM,
            False,
            "Clients do not have a completed required assessment on file.",
            "Schedule and complete the assessment; record its status in the source system.",
            records,
        )
    ]


@rule(
    "DQ-041",
    "Missing exit plan",
    "case_management",
    Severity.MEDIUM,
    description="Exited clients without a completed exit plan.",
)
def missing_exit_plan(ctx: RuleContext) -> list[AuditIssue]:
    raw = ctx.data.raw
    status = raw[schema.EXIT_PLAN_STATUS].astype("string").str.strip().str.casefold()
    incomplete = (~status.isin(["completed", "complete"])) | raw[schema.EXIT_PLAN_STATUS].isna()
    mask = _exited(ctx) & incomplete.fillna(True)
    records = _records(ctx, mask, field=schema.EXIT_PLAN_STATUS, value_col=schema.EXIT_PLAN_STATUS)
    if not records:
        return []
    return [
        _issue(
            "DQ-041",
            "Missing exit plan",
            "case_management",
            Severity.MEDIUM,
            False,
            "Clients exited the program without a completed exit plan, which many funders "
            "require for every exit.",
            "Complete and file exit plans for the flagged clients where possible; review "
            "exit procedures with case managers.",
            records,
        )
    ]


# -- Timeliness (follow-ups) -------------------------------------------------


@rule(
    "DQ-050",
    "Overdue follow-ups",
    "timeliness",
    Severity.HIGH,
    description="Clients past due for scheduled post-exit follow-ups.",
)
def overdue_followups(ctx: RuleContext) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for i, fu in enumerate(ctx.profile.followup_schedule):
        rule_id = f"DQ-05{i}"
        status = followup_status(ctx.data.df, fu, ctx.today)
        due_values = status["due_date"].dt.date.astype("string")
        records = _records(ctx, status["overdue"], field=fu.completion_field, values=due_values)
        if not records:
            continue
        issues.append(
            _issue(
                rule_id,
                f"Overdue {fu.label.lower()}",
                "timeliness",
                Severity.HIGH,
                False,
                f"Clients are past due for their {fu.label.lower()} "
                f"(due {fu.months_after_exit} months after exit, "
                f"{fu.grace_days}-day grace period). The flagged value shows the due date. "
                "Low follow-up completion directly lowers funder performance measures.",
                f"Contact the flagged clients to complete the {fu.label.lower()}, and record "
                "the completion date.",
                records,
            )
        )
    return issues


# -- Statistical -------------------------------------------------------------


@rule(
    "DQ-060",
    "Statistical income outlier",
    "statistical",
    Severity.INFO,
    description="Entry incomes far outside the typical range (IQR fence).",
)
def income_outliers(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    vals = df[schema.ENTRY_INCOME]
    valid = vals[(vals.notna()) & (vals >= 0) & (vals <= ctx.profile.income_cap)]
    if len(valid) < ctx.threshold("income_outlier_min_sample", 20):
        return []
    q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return []
    upper = q3 + ctx.threshold("income_outlier_iqr_multiplier", 3.0) * iqr
    mask = vals.notna() & (vals <= ctx.profile.income_cap) & (vals > upper)
    records = _records(ctx, mask, field=schema.ENTRY_INCOME, value_col=schema.ENTRY_INCOME)
    if not records:
        return []
    return [
        _issue(
            "DQ-060",
            "Statistical income outlier",
            "statistical",
            Severity.INFO,
            False,
            f"Entry incomes are far above the typical range for this dataset "
            f"(above ${upper:,.0f}, the 3×IQR fence). They may be legitimate but can pull "
            "average income figures upward.",
            "Spot-check these values; prefer median income when reporting if they are real.",
            records,
        )
    ]


@rule(
    "DQ-061",
    "Enrollment volume anomaly",
    "statistical",
    Severity.INFO,
    description="Months with unusually high or low enrollment counts.",
)
def enrollment_volume_anomaly(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    dates = df[schema.ENROLLMENT_DATE].dropna()
    if dates.empty:
        return []
    monthly = dates.dt.to_period("M").value_counts().sort_index()
    if len(monthly) < ctx.threshold("anomaly_min_months", 6):
        return []
    mean, std = float(monthly.mean()), float(monthly.std())
    if std == 0:
        return []
    z_limit = ctx.threshold("enrollment_anomaly_zscore", 2.0)
    anomalous = [p for p, c in monthly.items() if abs((c - mean) / std) > z_limit]
    if not anomalous:
        return []
    mask = df[schema.ENROLLMENT_DATE].dt.to_period("M").isin(anomalous)
    month_names = df[schema.ENROLLMENT_DATE].dt.strftime("%Y-%m")
    records = _records(ctx, mask.fillna(False), field=schema.ENROLLMENT_DATE, values=month_names)
    return [
        _issue(
            "DQ-061",
            "Enrollment volume anomaly",
            "statistical",
            Severity.INFO,
            False,
            "Some months have enrollment counts more than two standard deviations from the "
            f"monthly average ({mean:.1f}). This can indicate missing exports, backlogged "
            "data entry, or a real programmatic change worth explaining in the report.",
            "Confirm whether the spike/dip reflects reality or a data pipeline gap.",
            records,
        )
    ]


@rule(
    "DQ-062",
    "Program-level trend anomaly",
    "statistical",
    Severity.INFO,
    description="A single program's monthly enrollments spiking or collapsing.",
)
def program_trend_anomaly(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    records: list[IssueRecord] = []
    details: list[str] = []
    for program in ctx.profile.program_names:
        sub = df[(df[schema.PROGRAM] == program) & df[schema.ENROLLMENT_DATE].notna()]
        if sub.empty:
            continue
        monthly = sub[schema.ENROLLMENT_DATE].dt.to_period("M").value_counts().sort_index()
        if len(monthly) < ctx.threshold("anomaly_min_months", 6):
            continue
        mean, std = float(monthly.mean()), float(monthly.std())
        if std == 0:
            continue
        z_limit = ctx.threshold("program_anomaly_zscore", 2.5)
        anomalous = [p for p, c in monthly.items() if abs((c - mean) / std) > z_limit]
        if not anomalous:
            continue
        details.append(f"{program}: {', '.join(str(p) for p in anomalous)}")
        mask = df[schema.PROGRAM].eq(program) & df[schema.ENROLLMENT_DATE].dt.to_period("M").isin(
            anomalous
        )
        month_names = df[schema.ENROLLMENT_DATE].dt.strftime("%Y-%m")
        records.extend(
            _records(ctx, mask.fillna(False), field=schema.ENROLLMENT_DATE, values=month_names)
        )
    if not records:
        return []
    return [
        _issue(
            "DQ-062",
            "Program-level trend anomaly",
            "statistical",
            Severity.INFO,
            False,
            "Individual programs show months with enrollment counts far outside their own "
            f"typical volume ({'; '.join(details)}). Verify whether this reflects real "
            "program changes or incomplete data.",
            "Review the flagged months with program managers before publishing trends.",
            records,
        )
    ]
