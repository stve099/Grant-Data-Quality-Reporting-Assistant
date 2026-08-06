"""How long each finding has been open.

A count says "6 duplicate enrollments". Aging says "6 duplicate enrollments,
open for four periods" — which is a different conversation, because the first
reads as a data entry slip and the second as a process that is not working.

Aging needs the finding history, so :func:`record_run` now stores per-rule
counts alongside the metrics. Runs recorded before that simply have no rule rows
and are treated as unknown rather than as zero: claiming a finding was absent
when it was merely unrecorded would invent a resolution that never happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from grant_assistant.history.store import HistoryEntry
from grant_assistant.models import AuditResult


@dataclass
class RuleAge:
    """One rule's history across recorded runs."""

    rule_id: str
    rule_name: str
    current_count: int
    #: Consecutive runs ending with the most recent in which this rule appeared.
    consecutive_runs: int
    first_seen_label: str
    #: Change in record count since the previous run, or None without one.
    change: int | None

    @property
    def is_new(self) -> bool:
        return self.consecutive_runs <= 1

    @property
    def is_persistent(self) -> bool:
        """Open long enough that the cause is a process, not an accident."""
        return self.consecutive_runs >= 3

    def describe(self) -> str:
        if self.is_new:
            return f"{self.rule_name}: {self.current_count} record(s), new this run"
        run_word = "run" if self.consecutive_runs == 1 else "runs"
        text = (
            f"{self.rule_name}: {self.current_count} record(s), open for "
            f"{self.consecutive_runs} consecutive {run_word} (since {self.first_seen_label})"
        )
        if self.change is not None and self.change != 0:
            direction = "up" if self.change > 0 else "down"
            text += f", {direction} {abs(self.change)} since the previous run"
        return text


def rule_ages(entries: list[HistoryEntry], audit: AuditResult) -> list[RuleAge]:
    """Age every rule in the current audit against the recorded history.

    ``entries`` are oldest-first, as :func:`load_history` returns them. Only runs
    that recorded rule counts participate; older rows are skipped rather than
    counted as clean.
    """
    usable = [e for e in entries if e.rules_recorded]
    ages: list[RuleAge] = []

    for issue in audit.issues_sorted():
        if not issue.record_count:
            continue
        consecutive = 1  # the current audit itself
        first_label = "this run"
        for entry in reversed(usable):
            if entry.rule_counts.get(issue.rule_id):
                consecutive += 1
                first_label = entry.label or f"{entry.recorded_at:%Y-%m-%d}"
            else:
                break

        previous = usable[-1].rule_counts.get(issue.rule_id) if usable else None
        change = None if previous is None else issue.record_count - previous
        ages.append(
            RuleAge(
                rule_id=issue.rule_id,
                rule_name=issue.rule_name,
                current_count=issue.record_count,
                consecutive_runs=consecutive,
                first_seen_label=first_label,
                change=change,
            )
        )
    return ages


def resolved_since_last_run(entries: list[HistoryEntry], audit: AuditResult) -> list[str]:
    """Rules that were present in the previous run and are now clear.

    Worth reporting: cleanup work that succeeded is otherwise invisible, since a
    resolved finding simply stops appearing.
    """
    usable = [e for e in entries if e.rules_recorded]
    if not usable:
        return []
    previous = usable[-1].rule_counts
    current = {i.rule_id for i in audit.issues if i.record_count}
    return sorted(
        rule_id for rule_id, count in previous.items() if count and rule_id not in current
    )
