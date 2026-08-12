"""Grounded fact sheet for the AI analyst.

The fact sheet is the *only* data the AI model ever sees: aggregated,
deterministically calculated metrics with every data-derived string passed
through the prompt-injection sanitizer. No client-level rows, names, or
identifiers are included.
"""

from __future__ import annotations

import json
from typing import Any

from grant_assistant.analytics import AnalyticsResult
from grant_assistant.configuration import GrantProfile
from grant_assistant.history import HistorySummary
from grant_assistant.models import AuditResult
from grant_assistant.security import sanitize_mapping, sanitize_text


def history_facts(history: HistorySummary) -> dict[str, Any]:
    """The recorded trend, as grounded facts rather than something to infer.

    Every movement is pre-differenced here for the same reason no other number is
    left to the model: asked "are we improving?", a model without these values
    would subtract two scores itself, which the system prompt forbids and which
    is exactly how a wrong figure reaches a funder.
    """
    return {
        "recorded_runs": history.runs,
        "latest_recorded_score": history.latest_score,
        "score_change_since_previous_run": history.since_previous,
        "score_change_across_all_recorded_runs": history.score_delta,
        "trend": [
            {
                "label": sanitize_text(point.label),
                "recorded_at": point.recorded_at,
                "score": point.score,
                "findings": point.findings,
                "blocking": point.blocking,
            }
            for point in history.points
        ],
        "long_standing_findings": [
            {
                "rule_id": finding.rule_id,
                "name": sanitize_text(finding.rule_name),
                "records": finding.records,
                "consecutive_runs": finding.consecutive_runs,
                "first_seen": sanitize_text(finding.first_seen),
                "change_since_previous_run": finding.change,
            }
            for finding in history.persistent_findings
        ],
        "resolved_since_previous_run": list(history.resolved_rule_ids),
    }


def build_fact_sheet(
    analytics: AnalyticsResult,
    audit: AuditResult | None,
    profile: GrantProfile,
    history: HistorySummary | None = None,
) -> dict[str, Any]:
    """Assemble the aggregated, sanitized fact sheet for AI grounding."""
    sheet: dict[str, Any] = {
        "grant": {
            "name": sanitize_text(profile.grant_name),
            "grantor": sanitize_text(profile.grantor),
            "reporting_period": {
                "start": analytics.period_start.isoformat(),
                "end": analytics.period_end.isoformat(),
            },
            "as_of": analytics.as_of.isoformat(),
        },
        "headline_metrics": analytics.metric_lookup(),
        "programs": [
            {
                "program": sanitize_text(p.program),
                "enrollments": p.enrollments,
                "active": p.active,
                "exits": p.exits,
                "exit_rate_pct": p.exit_rate,
                "successful_exits": p.successful_exits,
                "successful_exit_rate_pct": p.successful_exit_rate,
                "permanent_housing_exits": p.permanent_housing_exits,
                "permanent_housing_rate_pct": p.permanent_housing_rate,
                "avg_income_change_usd": p.avg_income_change,
                "small_sample_caution": p.small_sample,
            }
            for p in analytics.programs
        ],
        "performance_measures": [
            {
                "id": m.id,
                "name": sanitize_text(m.name),
                "target": m.target,
                "actual": m.actual,
                "unit": m.unit,
                "direction": m.direction,
                "met": m.met,
                "denominator": m.denominator,
                "small_sample_caution": m.small_sample,
            }
            for m in analytics.measures
        ],
        "followups": [
            {
                "label": sanitize_text(f.label),
                "due": f.due,
                "completed": f.completed_of_due,
                "overdue": f.overdue,
                "completion_rate_pct": f.completion_rate,
            }
            for f in analytics.followups
        ],
        "exit_destinations": sanitize_mapping(
            dict(analytics.exit_destination_breakdown)  # type: ignore[arg-type]
        ),
        "demographics": {
            sanitize_text(field): sanitize_mapping(dict(counts))  # type: ignore[arg-type]
            for field, counts in analytics.demographics.items()
        },
        "age_groups": dict(analytics.age_groups),
        "monthly_enrollments": dict(analytics.monthly_enrollments),
        "monthly_exits": dict(analytics.monthly_exits),
        "methodology_notes": [sanitize_text(n) for n in analytics.notes],
    }
    if audit is not None:
        sheet["data_quality"] = {
            "overall_score": audit.overall_score,
            "grade": audit.grade,
            "total_rows": audit.total_rows,
            "findings_by_severity": audit.issue_count_by_severity,
            "score_by_category": dict(audit.score_by_category),
            "top_issues": [
                {
                    "rule_id": i.rule_id,
                    "name": sanitize_text(i.rule_name),
                    "severity": i.severity.value,
                    "records": i.record_count,
                    "blocking": i.blocking,
                }
                for i in audit.issues_sorted()[:10]
            ],
            "blocking_issue_count": len(audit.blocking_issues),
        }
    else:
        sheet["data_quality"] = "not audited in this session"
    if history is not None and history.runs:
        sheet["quality_history"] = history_facts(history)
    else:
        sheet["quality_history"] = "no previous runs recorded — do not describe a trend"
    return sheet


def fact_sheet_json(sheet: dict[str, Any]) -> str:
    """Serialize the fact sheet for embedding in a prompt."""
    return json.dumps(sheet, indent=1, default=str, ensure_ascii=False)
