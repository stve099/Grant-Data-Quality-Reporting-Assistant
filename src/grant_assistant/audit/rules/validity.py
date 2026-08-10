"""Rules for values that are present but cannot be right."""

from __future__ import annotations

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.audit.rules._helpers import _issue, _records
from grant_assistant.models import AuditIssue, IssueRecord, Severity


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
