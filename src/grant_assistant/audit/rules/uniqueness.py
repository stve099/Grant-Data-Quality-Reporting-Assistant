"""Rules for records that appear more than they should."""

from __future__ import annotations

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.audit.rules._helpers import _issue, _records
from grant_assistant.models import AuditIssue, Severity


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
