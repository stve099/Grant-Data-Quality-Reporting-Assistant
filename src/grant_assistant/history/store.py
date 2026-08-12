"""Persist a snapshot of each run so quality and outcomes can be tracked over time.

``compare`` answers "how does this extract differ from that one?" for two files
a user happens to have. It cannot answer "is our data quality improving?", which
is what a funder asks and what tells a data manager whether the work is paying
off. That needs a record kept across runs.

SQLite because the answer must survive the process, needs no server, and travels
as one file next to the reports. Metrics are stored long — one row per metric per
run — so a profile that adds a measure next quarter does not require a migration.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from grant_assistant.analytics import AnalyticsResult
from grant_assistant.configuration import GrantProfile
from grant_assistant.models import AuditResult

DEFAULT_DB_NAME = "history.db"

#: Where the web app records runs when nothing else says otherwise. The CLI
#: takes a --db path per invocation; a browser session has nowhere to type one,
#: so it needs a default that an operator can still redirect.
DB_PATH_ENV_VAR = "GRANT_ASSISTANT_HISTORY_DB"


def default_db_path() -> Path:
    """The history database to use when the caller names none."""
    configured = os.environ.get(DB_PATH_ENV_VAR, "").strip()
    return Path(configured) if configured else Path("output") / DEFAULT_DB_NAME


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at   TEXT    NOT NULL,
    profile_id    TEXT    NOT NULL,
    grant_name    TEXT    NOT NULL,
    label         TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    period_start  TEXT    NOT NULL,
    period_end    TEXT    NOT NULL,
    total_rows    INTEGER NOT NULL,
    score         REAL    NOT NULL,
    grade         TEXT    NOT NULL,
    findings      INTEGER NOT NULL,
    blocking      INTEGER NOT NULL,
    -- 1 once per-rule counts are stored. Distinguishes a clean run (counts
    -- recorded, none present) from a run recorded before aging existed
    -- (nothing recorded). Both have an empty rule_counts mapping otherwise.
    rules_recorded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_metrics (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name   TEXT    NOT NULL,
    value  REAL,
    PRIMARY KEY (run_id, name)
);

CREATE TABLE IF NOT EXISTS run_rule_counts (
    run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rule_id TEXT    NOT NULL,
    count   INTEGER NOT NULL,
    PRIMARY KEY (run_id, rule_id)
);

CREATE INDEX IF NOT EXISTS idx_runs_profile ON runs(profile_id, recorded_at);
"""


@dataclass
class HistoryEntry:
    """One recorded run."""

    run_id: int
    recorded_at: datetime
    profile_id: str
    grant_name: str
    label: str
    source: str
    period_start: str
    period_end: str
    total_rows: int
    score: float
    grade: str
    findings: int
    blocking: int
    metrics: dict[str, float | None] = field(default_factory=dict)
    #: rule id -> record count, for rules that fired. Empty both for a clean run
    #: and for one recorded before aging existed, so never read it alone.
    rule_counts: dict[str, int] = field(default_factory=dict)
    #: Whether per-rule counts were recorded at all. False means "unknown", not
    #: "clean" — aging must not report a resolution that never happened.
    rules_recorded: bool = False


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database may already have been created."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    if "rules_recorded" not in existing:
        conn.execute("ALTER TABLE runs ADD COLUMN rules_recorded INTEGER NOT NULL DEFAULT 0")


@contextmanager
def _connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_run(
    profile: GrantProfile,
    audit: AuditResult,
    analytics: AnalyticsResult,
    db_path: str | Path,
    label: str = "",
    source: str = "",
    recorded_at: datetime | None = None,
) -> int:
    """Store one run and return its id.

    ``recorded_at`` is injectable so tests and backfills do not depend on the
    wall clock.
    """
    stamp = (recorded_at or datetime.now()).isoformat(timespec="seconds")
    with _connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO runs (recorded_at, profile_id, grant_name, label, source, "
            "period_start, period_end, total_rows, score, grade, findings, blocking, "
            "rules_recorded) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (
                stamp,
                profile.profile_id,
                profile.grant_name,
                label,
                str(source),
                profile.reporting_period.start.isoformat(),
                profile.reporting_period.end.isoformat(),
                audit.total_rows,
                audit.overall_score,
                audit.grade,
                audit.total_findings,
                len(audit.blocking_issues),
            ),
        )
        run_id = int(cursor.lastrowid or 0)
        conn.executemany(
            "INSERT INTO run_metrics (run_id, name, value) VALUES (?,?,?)",
            [
                (run_id, name, None if value is None else float(value))
                for name, value in analytics.metric_lookup().items()
            ],
        )
        conn.executemany(
            "INSERT INTO run_rule_counts (run_id, rule_id, count) VALUES (?,?,?)",
            [
                (run_id, issue.rule_id, issue.record_count)
                for issue in audit.issues
                if issue.record_count
            ],
        )
    return run_id


def load_history(
    db_path: str | Path, profile_id: str | None = None, limit: int = 100
) -> list[HistoryEntry]:
    """Recorded runs, oldest first, so a reader sees the trend in reading order."""
    path = Path(db_path)
    if not path.exists():
        return []
    with _connect(path) as conn:
        if profile_id:
            rows = conn.execute(
                "SELECT * FROM runs WHERE profile_id = ? ORDER BY recorded_at DESC, id DESC "
                "LIMIT ?",
                (profile_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY recorded_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()

        entries: list[HistoryEntry] = []
        for row in reversed(rows):
            metrics = {
                m["name"]: m["value"]
                for m in conn.execute(
                    "SELECT name, value FROM run_metrics WHERE run_id = ?", (row["id"],)
                )
            }
            rule_counts = {
                r["rule_id"]: r["count"]
                for r in conn.execute(
                    "SELECT rule_id, count FROM run_rule_counts WHERE run_id = ?", (row["id"],)
                )
            }
            entries.append(
                HistoryEntry(
                    run_id=row["id"],
                    recorded_at=datetime.fromisoformat(row["recorded_at"]),
                    profile_id=row["profile_id"],
                    grant_name=row["grant_name"],
                    label=row["label"],
                    source=row["source"],
                    period_start=row["period_start"],
                    period_end=row["period_end"],
                    total_rows=row["total_rows"],
                    score=row["score"],
                    grade=row["grade"],
                    findings=row["findings"],
                    blocking=row["blocking"],
                    metrics=metrics,
                    rule_counts=rule_counts,
                    rules_recorded=bool(row["rules_recorded"]),
                )
            )
    return entries


def metric_series(entries: list[HistoryEntry], metric: str) -> list[tuple[datetime, float]]:
    """(when, value) pairs for one metric, skipping runs that lack it.

    A metric added to a profile later simply has no earlier points, rather than
    forcing a decision about what its history should have been.
    """
    series: list[tuple[datetime, float]] = []
    for entry in entries:
        value = entry.metrics.get(metric)
        if value is not None:
            series.append((entry.recorded_at, float(value)))
    return series


def history_frame(entries: list[HistoryEntry]) -> pd.DataFrame:
    """Recorded runs as a table, oldest first, for display or export.

    Kept out of the presentation layer so the web app's table and any future
    export show the same columns with the same labels.
    """
    return pd.DataFrame(
        [
            {
                "Run": entry.run_id,
                "Recorded": entry.recorded_at.strftime("%Y-%m-%d %H:%M"),
                "Label": entry.label or "—",
                "Rows": entry.total_rows,
                "Score": round(entry.score, 1),
                "Grade": entry.grade,
                "Findings": entry.findings,
                "Blocking": entry.blocking,
                "Source": entry.source or "—",
            }
            for entry in entries
        ],
        columns=[
            "Run",
            "Recorded",
            "Label",
            "Rows",
            "Score",
            "Grade",
            "Findings",
            "Blocking",
            "Source",
        ],
    )


def score_trend(entries: list[HistoryEntry]) -> float | None:
    """Change in data quality score from the first recorded run to the last."""
    if len(entries) < 2:
        return None
    return round(entries[-1].score - entries[0].score, 1)
