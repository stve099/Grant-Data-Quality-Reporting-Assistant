"""Typed tools the AI analyst can call.

Each tool is a thin, read-only view over the deterministic analytics/audit
results — the model retrieves exact numbers instead of relying only on the
static fact sheet. Tool outputs are aggregated, sanitized JSON; no tool ever
returns client-level records.
"""

from __future__ import annotations

import json
from typing import Any

from grant_assistant.agents.context import history_facts
from grant_assistant.analytics import AnalyticsResult
from grant_assistant.configuration import GrantProfile
from grant_assistant.history import HistorySummary
from grant_assistant.models import AuditResult
from grant_assistant.security import sanitize_mapping, sanitize_text


class ToolError(Exception):
    """Raised for unknown tools or invalid tool input."""


class AnalystTools:
    """Executor for the analyst tool set."""

    def __init__(
        self,
        analytics: AnalyticsResult,
        audit: AuditResult | None,
        profile: GrantProfile,
        history: HistorySummary | None = None,
    ) -> None:
        self.analytics = analytics
        self.audit = audit
        self.profile = profile
        self.history = history

    # -- Tool schemas (Anthropic tool format) --------------------------------

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return [
            {
                "name": "get_metric",
                "description": (
                    "Look up one calculated headline metric by name. Use list_metrics "
                    "first if unsure of the exact name."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
            {
                "name": "list_metrics",
                "description": "List every available headline metric name and its value.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "compare_programs",
                "description": (
                    "Program-level comparison table: enrollments, exits, successful-exit "
                    "rate, permanent-housing rate, income change, small-sample flags."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_measures",
                "description": "Performance measures vs targets, with met/not-met status.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_issue_summary",
                "description": (
                    "Data quality audit summary: score, findings by severity, and per-rule "
                    "counts with blocking flags. Aggregated only — no client rows."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_quality_history",
                "description": (
                    "Data quality across previously recorded runs: the score at each one, "
                    "how far it moved since the previous run, findings open for three or "
                    "more consecutive runs, and rules resolved since the last run. Every "
                    "change is already calculated — use these values rather than "
                    "subtracting scores yourself. Returns a note when no runs are recorded."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_trends",
                "description": "Monthly enrollment and exit counts across the dataset.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_demographics",
                "description": (
                    "Aggregated demographic breakdown for one field: gender, race, "
                    "ethnicity, veteran_status, disability_status, age_groups, or "
                    "household_size. Includes 'not_reported', the calculated total of "
                    "the missing/unknown/declined categories — use it instead of adding "
                    "those categories together yourself."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"field": {"type": "string"}},
                    "required": ["field"],
                },
            },
        ]

    # -- Execution -----------------------------------------------------------

    def execute(self, name: str, tool_input: dict[str, Any] | None) -> str:
        """Run a tool and return its JSON result string."""
        tool_input = tool_input or {}
        handlers = {
            "get_metric": self._get_metric,
            "list_metrics": self._list_metrics,
            "compare_programs": self._compare_programs,
            "get_measures": self._get_measures,
            "get_issue_summary": self._get_issue_summary,
            "get_quality_history": self._get_quality_history,
            "get_trends": self._get_trends,
            "get_demographics": self._get_demographics,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolError(f"Unknown tool: {name}")
        result = handler(tool_input)
        return json.dumps(result, default=str, ensure_ascii=False)

    def _get_metric(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        name = sanitize_text(str(tool_input.get("name", "")), max_length=80)
        lookup = self.analytics.metric_lookup()
        if name not in lookup:
            return {
                "error": f"No metric named '{name}'.",
                "available": sorted(lookup),
            }
        return {"name": name, "value": lookup[name]}

    def _list_metrics(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"metrics": self.analytics.metric_lookup()}

    def _compare_programs(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "programs": [
                {
                    "program": sanitize_text(p.program),
                    "enrollments": p.enrollments,
                    "active": p.active,
                    "exits": p.exits,
                    "successful_exit_rate_pct": p.successful_exit_rate,
                    "permanent_housing_rate_pct": p.permanent_housing_rate,
                    "avg_income_change_usd": p.avg_income_change,
                    "small_sample_caution": p.small_sample,
                }
                for p in self.analytics.programs
            ]
        }

    def _get_measures(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "measures": [
                {
                    "id": m.id,
                    "name": sanitize_text(m.name),
                    "program": sanitize_text(m.program) if m.program else None,
                    "target": m.target,
                    "actual": m.actual,
                    "unit": m.unit,
                    "met": m.met,
                    "small_sample_caution": m.small_sample,
                }
                for m in self.analytics.measures
            ]
        }

    def _get_issue_summary(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.audit is None:
            return {"error": "No audit has been run in this session."}
        return {
            "overall_score": self.audit.overall_score,
            "grade": self.audit.grade,
            "total_rows": self.audit.total_rows,
            "findings_by_severity": self.audit.issue_count_by_severity,
            "issues": [
                {
                    "rule_id": i.rule_id,
                    "name": sanitize_text(i.rule_name),
                    "severity": i.severity.value,
                    "records": i.record_count,
                    "blocking": i.blocking,
                }
                for i in self.audit.issues_sorted()
            ],
        }

    def _get_quality_history(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.history is None or not self.history.runs:
            return {
                "recorded_runs": 0,
                "note": "No previous runs are recorded, so no trend can be stated.",
            }
        return history_facts(self.history)

    def _get_trends(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "monthly_enrollments": dict(self.analytics.monthly_enrollments),
            "monthly_exits": dict(self.analytics.monthly_exits),
            "month_over_month_enrollment_change_pct": (
                self.analytics.month_over_month_enrollment_change
            ),
        }

    def _get_demographics(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        field = sanitize_text(str(tool_input.get("field", "")), max_length=40)
        if field == "age_groups":
            return {"field": field, "counts": dict(self.analytics.age_groups)}
        if field == "household_size":
            return {
                "field": field,
                "counts": dict(self.analytics.household_size_distribution),
            }
        counts = self.analytics.demographics.get(field)
        if counts is None:
            return {
                "error": f"No demographic field '{field}'.",
                "available": [*self.analytics.demographics, "age_groups", "household_size"],
            }
        return {
            "field": field,
            "counts": sanitize_mapping(dict(counts)),  # type: ignore[arg-type]
            # Supplied so the model never has to sum the categories itself.
            "not_reported": self.analytics.unreported_demographics.get(field, 0),
        }
