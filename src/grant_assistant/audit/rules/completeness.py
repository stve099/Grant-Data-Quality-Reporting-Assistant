"""Rules for fields that should be present and are not."""

from __future__ import annotations

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.audit.rules._helpers import _exited, _issue, _records
from grant_assistant.models import AuditIssue, IssueRecord, Severity


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
