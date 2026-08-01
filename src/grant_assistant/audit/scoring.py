"""Data quality scoring model.

The score starts at 100 and loses points proportional to the share of rows
affected by findings, weighted by severity. A dataset where every row has a
critical finding scores 0; informational findings never reduce the score.
The same formula is applied overall, per category, and per program so the
numbers are directly comparable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from grant_assistant.models import AuditIssue, Severity

if TYPE_CHECKING:
    from grant_assistant.configuration import GrantProfile
    from grant_assistant.ingestion import PreparedData

MAX_WEIGHT = Severity.CRITICAL.weight


def _penalty(issues: list[AuditIssue], n_rows: int) -> float:
    if n_rows == 0:
        return 0.0
    total = 0.0
    for issue in issues:
        unique_rows = len({r.row for r in issue.records})
        total += issue.severity.weight * unique_rows
    return total / (MAX_WEIGHT * n_rows)


def score_from_issues(issues: list[AuditIssue], n_rows: int) -> float:
    """Score a set of issues against a row count: 100 = clean, 0 = fully critical."""
    return round(max(0.0, 100.0 * (1.0 - _penalty(issues, n_rows))), 1)


def grade_for(score: float) -> str:
    """Letter grade for a data quality score."""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def compute_scores(
    issues: list[AuditIssue],
    n_rows: int,
    data: PreparedData,
    profile: GrantProfile,
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Compute (overall, by-category, by-program) data quality scores."""
    overall = score_from_issues(issues, n_rows)

    categories = sorted({i.category for i in issues})
    by_category = {
        cat: score_from_issues([i for i in issues if i.category == cat], n_rows)
        for cat in categories
    }

    from grant_assistant import schema  # local import to avoid cycle at module load

    program_rows = data.df[schema.PROGRAM].value_counts(dropna=True).to_dict()
    by_program: dict[str, float] = {}
    for program in profile.program_names:
        prog_n = int(program_rows.get(program, 0))
        if prog_n == 0:
            continue
        prog_issues: list[AuditIssue] = []
        for issue in issues:
            recs = [r for r in issue.records if r.program == program]
            if recs:
                prog_issues.append(issue.model_copy(update={"records": recs}))
        by_program[program] = score_from_issues(prog_issues, prog_n)
    return overall, by_category, by_program
