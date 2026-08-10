"""Proactive Senior-Analyst insights.

The insight engine is deterministic: it inspects the calculated analytics and
audit results and produces structured findings (anomalies, trends, risks,
recommendations) without any AI call, so proactive review works in non-AI
mode. When an AI provider is available, the deterministic report can
additionally be narrated into polished prose — grounded on these same facts.
"""

from __future__ import annotations

import statistics

from pydantic import BaseModel, Field

from grant_assistant.analytics import AnalyticsResult
from grant_assistant.configuration import GrantProfile
from grant_assistant.models import AuditResult, Severity
from grant_assistant.security import sanitize_text

# Program and measure names are data-derived: a draft profile pulls them
# straight from uploaded cell values (configuration/generator.py), and this
# report is interpolated into the *user message* of the AI narration/summary
# prompt (analyst.py) — the channel the system prompt treats as instructions,
# not the fact-sheet delimiters it treats as data. The fact sheet and tool
# results already sanitize these same values; every one interpolated here must
# pass through sanitize_text too, or an attacker-controlled cell value reaches
# the model as an instruction. Rule name/explanation/recommendation are
# code-authored constants, so they are left as-is.


class InsightReport(BaseModel):
    """Structured proactive review of the dataset, senior-analyst style."""

    key_findings: list[str] = Field(default_factory=list)
    notable_trends: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    data_quality_risks: list[str] = Field(default_factory=list)
    program_strengths: list[str] = Field(default_factory=list)
    program_concerns: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    questions_for_investigation: list[str] = Field(default_factory=list)
    executive_takeaways: list[str] = Field(default_factory=list)

    def sections(self) -> dict[str, list[str]]:
        return {
            "Key Findings": self.key_findings,
            "Notable Trends": self.notable_trends,
            "Anomalies Detected": self.anomalies,
            "Data Quality Risks": self.data_quality_risks,
            "Program Strengths": self.program_strengths,
            "Program Concerns": self.program_concerns,
            "Recommended Actions": self.recommended_actions,
            "Questions Requiring Further Investigation": self.questions_for_investigation,
            "Executive Takeaways": self.executive_takeaways,
        }

    def as_markdown(self) -> str:
        parts: list[str] = []
        for title, items in self.sections().items():
            if not items:
                continue
            parts.append(f"### {title}")
            parts.extend(f"- {item}" for item in items)
            parts.append("")
        return "\n".join(parts).strip()


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _fmt_usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


def generate_insights(
    analytics: AnalyticsResult,
    audit: AuditResult | None,
    profile: GrantProfile,
) -> InsightReport:
    """Deterministically derive a proactive insight report from calculated results."""
    r = InsightReport()

    # --- Key findings -------------------------------------------------------
    r.key_findings.append(
        f"{analytics.total_enrollments} enrollments across {len(analytics.programs)} program(s) "
        f"served {analytics.households_served} households "
        f"({analytics.total_individuals} individuals: {analytics.total_adults} adults, "
        f"{analytics.total_children} children)."
    )
    r.key_findings.append(
        f"{analytics.total_exits} clients exited ({_fmt_pct(analytics.exit_rate)} of enrollments); "
        f"{analytics.successful_exits} were successful exits "
        f"({_fmt_pct(analytics.successful_exit_rate)}) and "
        f"{analytics.permanent_housing_exits} went to permanent housing "
        f"({_fmt_pct(analytics.permanent_housing_rate)})."
    )
    if analytics.n_income_pairs:
        r.key_findings.append(
            f"Among {analytics.n_income_pairs} exits with complete income data, median income "
            f"change was {_fmt_usd(analytics.median_income_change)} and "
            f"{_fmt_pct(analytics.pct_income_increased)} of households increased income."
        )

    met = [m for m in analytics.measures if m.met is True]
    missed = [m for m in analytics.measures if m.met is False]
    if analytics.measures:
        r.key_findings.append(
            f"{len(met)} of {len(analytics.measures)} performance measures met their targets."
        )

    # --- Trends -------------------------------------------------------------
    if analytics.month_over_month_enrollment_change is not None:
        direction = "up" if analytics.month_over_month_enrollment_change >= 0 else "down"
        r.notable_trends.append(
            f"Enrollments are {direction} "
            f"{abs(analytics.month_over_month_enrollment_change):.1f}% month-over-month "
            "in the most recent month."
        )
    if analytics.monthly_enrollments:
        peak_month = max(analytics.monthly_enrollments, key=analytics.monthly_enrollments.get)  # type: ignore[arg-type]
        low_month = min(analytics.monthly_enrollments, key=analytics.monthly_enrollments.get)  # type: ignore[arg-type]
        r.notable_trends.append(
            f"Enrollment peaked in {peak_month} ({analytics.monthly_enrollments[peak_month]}) "
            f"and was lowest in {low_month} ({analytics.monthly_enrollments[low_month]})."
        )

    # --- Anomalies ----------------------------------------------------------
    rates = [
        p.successful_exit_rate for p in analytics.programs if p.successful_exit_rate is not None
    ]
    if len(rates) >= 2:
        mean_rate = statistics.mean(rates)
        for p in analytics.programs:
            if p.successful_exit_rate is None:
                continue
            gap = p.successful_exit_rate - mean_rate
            if abs(gap) >= 20 and not p.small_sample:
                verb = "above" if gap > 0 else "below"
                r.anomalies.append(
                    f"{sanitize_text(p.program)}'s successful-exit rate ({_fmt_pct(p.successful_exit_rate)}) is "
                    f"{abs(gap):.0f} points {verb} the cross-program average "
                    f"({mean_rate:.1f}%) — worth explaining before publication."
                )
    if audit is not None:
        for issue in audit.issues:
            if issue.category == "statistical" and issue.record_count:
                r.anomalies.append(f"{issue.rule_name}: {issue.explanation}")
    small = [p for p in analytics.programs if p.small_sample and p.exits > 0]
    for p in small:
        r.anomalies.append(
            f"{sanitize_text(p.program)} has only {p.exits} exits — its outcome rates are unstable and a "
            "single client changes them by several points. Treat comparisons with caution."
        )

    # --- Data quality risks -------------------------------------------------
    if audit is not None:
        r.data_quality_risks.append(
            f"Overall data quality score is {audit.overall_score:.1f}/100 (grade {audit.grade}) "
            f"across {audit.total_rows} records."
        )
        for issue in audit.blocking_issues:
            r.data_quality_risks.append(
                f"Blocking: {issue.rule_name} affects {issue.record_count} record(s) — "
                f"{issue.explanation}"
            )
        dest_issue = next(
            (i for i in audit.issues if i.rule_id == "DQ-004" and i.record_count), None
        )
        if dest_issue and analytics.total_exits:
            share = 100.0 * len({rec.row for rec in dest_issue.records}) / analytics.total_exits
            r.data_quality_risks.append(
                f"{share:.0f}% of exits have no destination recorded, so the true "
                "successful-exit and permanent-housing rates are likely understated."
            )
        if audit.pii_warnings:
            r.data_quality_risks.append(
                f"{len(audit.pii_warnings)} column(s) appear to contain personal information; "
                "this dataset should hold pseudonymous identifiers only."
            )
        if audit.injection_warnings:
            r.data_quality_risks.append(
                f"{len(audit.injection_warnings)} cell(s) contain text resembling prompt-"
                "injection attempts; they are neutralized before any AI processing."
            )
    if analytics.duplicates_removed:
        r.data_quality_risks.append(
            f"{analytics.duplicates_removed} duplicate enrollment(s) were excluded from "
            "analytics; source data should be deduplicated."
        )

    # --- Program strengths / concerns --------------------------------------
    ranked = [
        p for p in analytics.programs if p.successful_exit_rate is not None and not p.small_sample
    ]
    ranked.sort(key=lambda p: p.successful_exit_rate or 0, reverse=True)
    if ranked:
        best = ranked[0]
        r.program_strengths.append(
            f"{sanitize_text(best.program)} leads on successful exits: {_fmt_pct(best.successful_exit_rate)} "
            f"of {best.exits} exits."
        )
        if best.avg_income_change is not None and best.avg_income_change > 0:
            r.program_strengths.append(
                f"{sanitize_text(best.program)} exits also show positive average income change "
                f"({_fmt_usd(best.avg_income_change)})."
            )
    if len(ranked) >= 2:
        worst = ranked[-1]
        r.program_concerns.append(
            f"{sanitize_text(worst.program)} trails on successful exits "
            f"({_fmt_pct(worst.successful_exit_rate)} of {worst.exits} exits); review exit "
            "planning and destination documentation."
        )
    for m in missed:
        r.program_concerns.append(
            f"Below target: {sanitize_text(m.name)} at {m.actual}{'%' if m.unit == 'percent' else ''} vs. "
            f"target {m.target}{'%' if m.unit == 'percent' else ''}"
            + (" (small sample — interpret with caution)." if m.small_sample else ".")
        )

    # --- Recommended actions ------------------------------------------------
    if analytics.total_overdue_followups:
        r.recommended_actions.append(
            f"Complete the {analytics.total_overdue_followups} overdue follow-up(s); "
            "follow-up completion is a funder performance measure."
        )
    if audit is not None:
        for issue in audit.issues_sorted():
            if issue.severity in (Severity.CRITICAL, Severity.HIGH) and issue.record_count:
                r.recommended_actions.append(
                    f"Fix {issue.rule_name.lower()} ({issue.record_count} record(s)): "
                    f"{issue.recommendation}"
                )
            if len(r.recommended_actions) >= 6:
                break
    for m in missed[:3]:
        r.recommended_actions.append(
            f"Develop an improvement plan for '{sanitize_text(m.name)}' (actual {m.actual} vs target {m.target})."
        )

    # --- Questions for investigation ---------------------------------------
    if (
        analytics.month_over_month_enrollment_change is not None
        and abs(analytics.month_over_month_enrollment_change) > 30
    ):
        r.questions_for_investigation.append(
            "What drove the sharp month-over-month enrollment change — referrals, capacity, "
            "or a data entry backlog?"
        )
    unmapped = analytics.exit_category_breakdown.get("other_unmapped", 0)
    if unmapped:
        r.questions_for_investigation.append(
            f"{unmapped} exit(s) have destinations not mapped to any outcome category — "
            "should the profile's destination mappings be extended?"
        )
    if (
        analytics.n_income_pairs
        and analytics.total_exits
        and (analytics.n_income_pairs < 0.8 * analytics.total_exits)
    ):
        r.questions_for_investigation.append(
            "Income change covers only "
            f"{analytics.n_income_pairs}/{analytics.total_exits} exits — is exit income "
            "collection failing at specific programs?"
        )
    r.questions_for_investigation.append(
        "Note: differences between programs are associations, not causal effects — programs "
        "serve different populations, so outcome gaps may reflect intake mix rather than "
        "program performance."
    )

    # --- Executive takeaways ------------------------------------------------
    if analytics.successful_exit_rate is not None:
        r.executive_takeaways.append(
            f"Headline: {_fmt_pct(analytics.successful_exit_rate)} of the "
            f"{analytics.total_exits} exits this period were successful, against "
            f"{len(analytics.measures)} tracked measures ({len(met)} met, {len(missed)} missed)."
        )
    if audit is not None and audit.blocking_issues:
        r.executive_takeaways.append(
            "Data quality: resolve the blocking issues before submitting this report to the "
            "funder — several headline rates are currently understated or unreliable."
        )
    elif audit is not None:
        r.executive_takeaways.append(
            f"Data quality is acceptable (score {audit.overall_score:.1f}); remaining findings "
            "are non-blocking."
        )
    if analytics.total_overdue_followups:
        r.executive_takeaways.append(
            f"Operational priority: {analytics.total_overdue_followups} overdue follow-ups "
            "are the fastest lever to improve reported outcomes."
        )
    return r
