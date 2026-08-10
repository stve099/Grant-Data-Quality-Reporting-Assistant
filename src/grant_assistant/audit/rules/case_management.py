"""Rules for assessment and exit-planning workflow."""

from __future__ import annotations

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.audit.rules._helpers import _exited, _issue, _records
from grant_assistant.models import AuditIssue, Severity


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
