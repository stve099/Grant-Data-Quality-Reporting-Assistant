"""Shared helpers for the audit rules.

Split out so every category module imports the same record-building and issue-
construction code. These were private to a single 1,000-line module; they are
still private to the package.
"""

from __future__ import annotations

import pandas as pd

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext
from grant_assistant.models import AuditIssue, IssueRecord, Severity


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
