"""Shared result models for the audit engine.

These models are deliberately plain and serializable: every downstream
consumer (CLI, Streamlit UI, report generators, the AI agent's fact sheet)
works from the same structures.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field


class Severity(StrEnum):
    """Severity levels for audit findings, ordered most to least severe."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def weight(self) -> int:
        """Penalty weight used by the data quality scoring model."""
        return {"critical": 8, "high": 5, "medium": 3, "low": 1, "info": 0}[self.value]

    @property
    def label(self) -> str:
        return {"info": "Informational"}.get(self.value, self.value.title())


SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
)


class IssueRecord(BaseModel):
    """A single flagged record within an audit issue."""

    row: int = Field(description="1-based data row number (matching the source spreadsheet).")
    client_id: str = ""
    program: str = ""
    field: str = ""
    value: str = ""


class AuditIssue(BaseModel):
    """One audit rule's findings across the dataset."""

    rule_id: str
    rule_name: str
    category: str
    severity: Severity
    blocking: bool
    explanation: str
    recommendation: str
    records: list[IssueRecord] = Field(default_factory=list)

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def affected_rows(self) -> list[int]:
        return sorted({r.row for r in self.records})

    @property
    def affected_client_ids(self) -> list[str]:
        return sorted({r.client_id for r in self.records if r.client_id})


class AuditResult(BaseModel):
    """Complete output of a data quality audit run."""

    profile_id: str
    grant_name: str
    total_rows: int
    issues: list[AuditIssue] = Field(default_factory=list)
    overall_score: float = 100.0
    grade: str = "A"
    score_by_category: dict[str, float] = Field(default_factory=dict)
    score_by_program: dict[str, float] = Field(default_factory=dict)
    injection_warnings: list[str] = Field(default_factory=list)
    #: Columns that look like direct identifiers. Advisory: a false positive must
    #: never block a legitimate upload, so these never affect the score or grade.
    pii_warnings: list[str] = Field(default_factory=list)

    @property
    def issue_count_by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in SEVERITY_ORDER}
        for issue in self.issues:
            counts[issue.severity.value] += issue.record_count
        return counts

    @property
    def issue_count_by_rule(self) -> dict[str, int]:
        return {i.rule_id: i.record_count for i in self.issues if i.record_count}

    @property
    def blocking_issues(self) -> list[AuditIssue]:
        return [i for i in self.issues if i.blocking and i.record_count]

    @property
    def total_findings(self) -> int:
        return sum(i.record_count for i in self.issues)

    @property
    def clean(self) -> bool:
        return self.total_findings == 0

    def issues_sorted(self) -> list[AuditIssue]:
        """Issues ordered by severity (most severe first), then by record count."""
        rank = {s: i for i, s in enumerate(SEVERITY_ORDER)}
        return sorted(
            (i for i in self.issues if i.record_count),
            key=lambda i: (rank[i.severity], -i.record_count),
        )

    def row_level_frame(self) -> pd.DataFrame:
        """Flatten all findings into one row-level DataFrame for export/review."""
        rows: list[dict[str, Any]] = []
        for issue in self.issues:
            for rec in issue.records:
                rows.append(
                    {
                        "rule_id": issue.rule_id,
                        "rule_name": issue.rule_name,
                        "category": issue.category,
                        "severity": issue.severity.label,
                        "blocking": issue.blocking,
                        "row": rec.row,
                        "client_id": rec.client_id,
                        "program": rec.program,
                        "field": rec.field,
                        "value": rec.value,
                        "explanation": issue.explanation,
                        "recommendation": issue.recommendation,
                    }
                )
        columns = [
            "rule_id",
            "rule_name",
            "category",
            "severity",
            "blocking",
            "row",
            "client_id",
            "program",
            "field",
            "value",
            "explanation",
            "recommendation",
        ]
        if not rows:
            return pd.DataFrame(columns=columns)
        return (
            pd.DataFrame(rows, columns=columns)
            .sort_values(["row", "rule_id"])
            .reset_index(drop=True)
        )

    def executive_summary(self) -> str:
        """Deterministic plain-language summary of the audit outcome."""
        counts = self.issue_count_by_severity
        parts = [
            f"Audited {self.total_rows} records for {self.grant_name}: "
            f"overall data quality score {self.overall_score:.1f}/100 (grade {self.grade})."
        ]
        if self.clean:
            parts.append("No data quality issues were detected.")
            return " ".join(parts)
        sev_bits = [
            f"{counts[s.value]} {s.label.lower()}" for s in SEVERITY_ORDER if counts[s.value]
        ]
        parts.append(f"Findings by severity: {', '.join(sev_bits)}.")
        blocking = self.blocking_issues
        if blocking:
            names = ", ".join(i.rule_name for i in blocking[:4])
            parts.append(
                f"{len(blocking)} blocking issue type(s) must be resolved before submission: {names}."
            )
        top = self.issues_sorted()[:3]
        if top:
            parts.append(
                "Largest issues: "
                + "; ".join(f"{i.rule_name} ({i.record_count} records)" for i in top)
                + "."
            )
        return " ".join(parts)

    def remediation_actions(self) -> list[str]:
        """Recommended remediation actions ordered by severity and impact."""
        actions: list[str] = []
        for issue in self.issues_sorted():
            actions.append(
                f"[{issue.severity.label}] {issue.rule_name} — {issue.record_count} record(s): "
                f"{issue.recommendation}"
            )
        return actions
