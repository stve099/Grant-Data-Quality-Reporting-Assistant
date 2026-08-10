"""Rules for follow-ups that have come due and not been done."""

from __future__ import annotations

from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.audit.rules._helpers import _issue, _records
from grant_assistant.followups import followup_status
from grant_assistant.models import AuditIssue, Severity


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
