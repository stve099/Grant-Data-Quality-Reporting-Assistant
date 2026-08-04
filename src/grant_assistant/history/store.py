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

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from grant_assistant.analytics import AnalyticsResult
from grant_assistant.configuration import GrantProfile
from grant_assistant.models import AuditResult

DEFAULT_DB_NAME = "history.db"

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
    blocking      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS run_metrics (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name   TEXT    NOT NULL,
    value  REAL,
    PRIMARY KEY (run_id, name)
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


@contextmanager
def _connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
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
            "period_start, period_end, total_rows, score, grade, findings, blocking) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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


def score_trend(entries: list[HistoryEntry]) -> float | None:
    """Change in data quality score from the first recorded run to the last."""
    if len(entries) < 2:
        return None
    return round(entries[-1].score - entries[0].score, 1)
