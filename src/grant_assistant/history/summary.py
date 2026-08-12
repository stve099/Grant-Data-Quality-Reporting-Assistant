"""The recorded history of a grant, reduced to what a report or an analyst needs.

The store keeps every run; a funder submission wants the shape of the change and
nothing else — how many periods, which way the score moved, what has been open
long enough to be a process rather than an accident, and what got fixed. That
reduction was previously performed nowhere, which is why the trend reached the
CLI and the app and never reached the report that goes to the funder.

Deterministic and serializable on purpose: the same object feeds the four report
renderers and the AI analyst's fact sheet, so a narrative sentence and a table
cannot disagree about the trend.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from grant_assistant.history.aging import resolved_since_last_run, rule_ages
from grant_assistant.history.store import HistoryEntry, default_db_path, load_history
from grant_assistant.models import AuditResult


class TrendPoint(BaseModel):
    """One recorded run, as it appears on a trend line."""

    label: str
    recorded_at: str
    score: float
    findings: int
    blocking: int


class AgedFinding(BaseModel):
    """A current finding with how long it has been open."""

    rule_id: str
    rule_name: str
    records: int
    consecutive_runs: int
    first_seen: str
    #: Change in record count since the previous run; None without one.
    change: int | None = None

    def describe(self) -> str:
        text = (
            f"{self.rule_name}: {self.records} record(s), open for "
            f"{self.consecutive_runs} consecutive runs (since {self.first_seen})"
        )
        if self.change:
            direction = "up" if self.change > 0 else "down"
            text += f", {direction} {abs(self.change)} since the previous run"
        return text


class HistorySummary(BaseModel):
    """What the recorded runs say about this grant's data quality over time."""

    profile_id: str
    runs: int
    points: list[TrendPoint] = Field(default_factory=list)
    #: First-to-last change in data quality score; None with fewer than two runs.
    score_delta: float | None = None
    #: Score of the most recent recorded run, for stating the trend's endpoint.
    latest_score: float | None = None
    #: Change from the previous run to the current audit, which is the figure a
    #: reader wants: "since we last reported", not "since we started".
    since_previous: float | None = None
    persistent_findings: list[AgedFinding] = Field(default_factory=list)
    resolved_rule_ids: list[str] = Field(default_factory=list)

    @property
    def has_trend(self) -> bool:
        """Whether there is enough history to state a direction at all."""
        return self.runs >= 1

    def headline(self) -> str:
        """One sentence stating the movement, or that there is not enough history."""
        if not self.runs:
            return "No previous runs have been recorded for this grant."
        if self.since_previous is None:
            return f"{self.runs} previous run(s) recorded."
        direction = "up" if self.since_previous > 0 else "down"
        if self.since_previous == 0:
            return (
                f"Data quality is unchanged since the previous recorded run, across "
                f"{self.runs} recorded run(s)."
            )
        return (
            f"Data quality is {direction} {abs(self.since_previous):.1f} points since the "
            f"previous recorded run, across {self.runs} recorded run(s)."
        )


def load_history_summary(
    db_path: str | Path | None,
    profile_id: str,
    audit: AuditResult | None,
    exclude_run_ids: set[int] | frozenset[int] = frozenset(),
) -> HistorySummary | None:
    """Summarize a profile's recorded runs, or None when there are none.

    Both entry points call this before building a report, so "there is no history
    database yet" and "this profile has never been recorded" produce the same
    quiet absence rather than an error or an empty section.
    """
    path = Path(db_path) if db_path is not None else default_db_path()
    if not path.exists():
        return None
    entries = load_history(path, profile_id)
    if not entries:
        return None
    return build_history_summary(entries, audit, profile_id, exclude_run_ids)


def build_history_summary(
    entries: list[HistoryEntry],
    audit: AuditResult | None,
    profile_id: str = "",
    exclude_run_ids: set[int] | frozenset[int] = frozenset(),
) -> HistorySummary:
    """Reduce recorded runs, plus the current audit, to a reportable summary.

    ``entries`` are prior runs, oldest first, as :func:`load_history` returns
    them. ``exclude_run_ids`` drops rows that *are* the current audit rather than
    observations before it: aging counts the current audit as one run already, so
    a run recorded from this same dataset would age every finding by one.
    """
    usable = [entry for entry in entries if entry.run_id not in exclude_run_ids]
    summary = HistorySummary(
        profile_id=profile_id or (usable[-1].profile_id if usable else ""),
        runs=len(usable),
        points=[
            TrendPoint(
                label=entry.label or f"{entry.recorded_at:%Y-%m-%d}",
                recorded_at=entry.recorded_at.isoformat(timespec="seconds"),
                score=round(entry.score, 1),
                findings=entry.findings,
                blocking=entry.blocking,
            )
            for entry in usable
        ],
    )
    if usable:
        summary.latest_score = round(usable[-1].score, 1)
    if len(usable) >= 2:
        summary.score_delta = round(usable[-1].score - usable[0].score, 1)
    if audit is None or not usable:
        return summary

    summary.since_previous = round(audit.overall_score - usable[-1].score, 1)
    summary.resolved_rule_ids = resolved_since_last_run(usable, audit)
    summary.persistent_findings = [
        AgedFinding(
            rule_id=age.rule_id,
            rule_name=age.rule_name,
            records=age.current_count,
            consecutive_runs=age.consecutive_runs,
            first_seen=age.first_seen_label,
            change=age.change,
        )
        for age in rule_ages(usable, audit)
        if age.is_persistent
    ]
    return summary
