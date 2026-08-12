"""What a round of corrections actually changed.

Applying a worksheet is only half the answer; the question a data manager has is
"did that help, and by how much". Both the CLI and the web app re-audit the
corrected extract and report the same three figures against the same three
before-values, so the comparison lives here rather than being written out twice
and drifting.
"""

from __future__ import annotations

from dataclasses import dataclass

from grant_assistant.models import AuditResult


@dataclass(frozen=True)
class CorrectionImpact:
    """The before/after of one correction round, already differenced."""

    before_score: float
    after_score: float
    before_findings: int
    after_findings: int
    before_blocking: int
    after_blocking: int
    #: Names of rules that fired before and no longer do. Cleanup that worked is
    #: otherwise invisible, since a resolved finding simply stops appearing.
    cleared_rules: tuple[str, ...] = ()

    @classmethod
    def between(cls, before: AuditResult, after: AuditResult) -> CorrectionImpact:
        remaining = {issue.rule_id for issue in after.issues if issue.record_count}
        cleared = tuple(
            issue.rule_name
            for issue in before.issues_sorted()
            if issue.record_count and issue.rule_id not in remaining
        )
        return cls(
            before_score=before.overall_score,
            after_score=after.overall_score,
            before_findings=before.total_findings,
            after_findings=after.total_findings,
            before_blocking=len(before.blocking_issues),
            after_blocking=len(after.blocking_issues),
            cleared_rules=cleared,
        )

    @property
    def score_delta(self) -> float:
        return round(self.after_score - self.before_score, 1)

    @property
    def findings_delta(self) -> int:
        return self.after_findings - self.before_findings

    @property
    def blocking_delta(self) -> int:
        return self.after_blocking - self.before_blocking

    @property
    def improved(self) -> bool:
        return self.score_delta > 0

    def lines(self) -> list[str]:
        """One aligned line per figure, for a terminal or a caption."""
        return [
            f"Data quality score  {self.before_score:.1f} -> {self.after_score:.1f} "
            f"({self.score_delta:+.1f})",
            f"Findings            {self.before_findings} -> {self.after_findings} "
            f"({self.findings_delta:+d})",
            f"Blocking issues     {self.before_blocking} -> {self.after_blocking} "
            f"({self.blocking_delta:+d})",
        ]
