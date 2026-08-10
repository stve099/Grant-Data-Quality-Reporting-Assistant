"""Assemble everything a report needs into one serializable context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from grant_assistant import schema
from grant_assistant.agents import DataAnalystAgent, InsightReport
from grant_assistant.analytics import AnalyticsResult
from grant_assistant.configuration import GrantProfile
from grant_assistant.models import AuditResult

MEASURE_DEFINITIONS: dict[str, str] = {
    "total_enrollments": "Count of enrollment records after removing exact duplicates.",
    "households_served": "Count of distinct household IDs.",
    "total_exits": "Enrollments with a recorded exit date.",
    "exit_rate": "Exits as a percentage of enrollments.",
    "successful_exit_rate": "Exits to a destination in a category the profile defines as "
    "successful, as a percentage of all exits.",
    "permanent_housing_rate": "Exits to a permanent-housing destination as a percentage of "
    "all exits.",
    "pct_income_increased": "Share of exited households whose exit income exceeds entry "
    "income, among exits with both incomes recorded and valid.",
    "avg_income_change": "Mean of (exit income − entry income) across exits with valid "
    "entry and exit income.",
    "median_income_change": "Median of (exit income − entry income) across exits with "
    "valid entry and exit income.",
    "assessment_completion_rate": "Enrollments with a completed required assessment, as a "
    "percentage of all enrollments.",
    "exit_plan_completion_rate": "Exits with a completed exit plan, as a percentage of all exits.",
    "overall_followup_completion_rate": "Completed follow-ups as a percentage of follow-ups "
    "due, across all scheduled milestones.",
}


@dataclass
class ReportData:
    """Everything the HTML/Word report renderers consume."""

    profile: GrantProfile
    analytics: AnalyticsResult
    audit: AuditResult | None
    insights: InsightReport
    executive_summary: str
    generated_at: datetime = field(default_factory=datetime.now)
    ai_generated_narrative: bool = False

    @property
    def title(self) -> str:
        return self.profile.report.title

    @property
    def period_label(self) -> str:
        return self.profile.reporting_period.label

    def includes(self, section: str) -> bool:
        """Whether the profile selected a report section."""
        return section in self.profile.report.sections

    def measure_definitions(self) -> list[tuple[str, str]]:
        """(measure name, definition) pairs for the report appendix."""
        out: list[tuple[str, str]] = []
        for m in self.analytics.measures:
            definition = MEASURE_DEFINITIONS.get(m.metric, m.description or m.metric)
            out.append((m.name, definition))
        for fu in self.analytics.followups:
            out.append(
                (
                    f"{fu.label} completion rate",
                    f"Completed {fu.label.lower()}s as a percentage of clients whose "
                    f"{fu.label.lower()} has come due.",
                )
            )
        return out

    def data_limitations(self) -> list[str]:
        """Honest limitations for the methodology section."""
        limits = list(self.analytics.notes)
        if self.audit is not None:
            if self.audit.blocking_issues:
                limits.append(
                    "Blocking data quality issues were present at generation time; affected "
                    "metrics may be understated (see the Data Quality section)."
                )
            missing_dest = next(
                (i for i in self.audit.issues if i.rule_id == "DQ-004" and i.record_count), None
            )
            if missing_dest:
                limits.append(
                    f"{missing_dest.record_count} exit(s) lack a destination and are counted "
                    "as non-successful, which understates outcome rates."
                )
        small = [p.program for p in self.analytics.programs if p.small_sample]
        if small:
            limits.append(
                f"Small samples: {', '.join(small)} have fewer than 10 exits; their rates "
                "are volatile."
            )
        limits.append(
            "All figures are drawn from the uploaded extract and reflect data quality at "
            "the time of export; they may change as corrections are made."
        )
        return limits

    def demographic_tables(self) -> list[tuple[str, list[tuple[str, int]]]]:
        """(field label, [(value, count)]) for report tables."""
        tables: list[tuple[str, list[tuple[str, int]]]] = []
        for field_name, counts in self.analytics.demographics.items():
            ordered = sorted(counts.items(), key=lambda kv: -kv[1])
            tables.append((schema.label_for(field_name), ordered))
        if self.analytics.age_groups:
            tables.append(("Age Group", list(self.analytics.age_groups.items())))
        if self.analytics.household_size_distribution:
            tables.append(
                (
                    "Household Size",
                    [
                        (f"{k} person(s)", v)
                        for k, v in self.analytics.household_size_distribution.items()
                    ],
                )
            )
        return tables


def build_report_data(
    analytics: AnalyticsResult,
    audit: AuditResult | None,
    profile: GrantProfile,
    agent: DataAnalystAgent | None = None,
) -> ReportData:
    """Build the report context; uses the agent for narrative when provided."""
    agent = agent or DataAnalystAgent(analytics, audit, profile, provider=None)
    insights = agent.proactive_insights()
    summary = agent.executive_summary()
    return ReportData(
        profile=profile,
        analytics=analytics,
        audit=audit,
        insights=insights,
        executive_summary=summary,
        ai_generated_narrative=agent.ai_enabled,
    )
