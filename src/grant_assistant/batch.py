"""Audit a folder of extracts in one pass and roll the results up.

Programs rarely produce one file. A multi-site agency exports per site, or per
month, and the person assembling the grant report runs the same command a dozen
times and retypes the numbers into a spreadsheet.

One bad file must not cost the batch: a load or profile error is recorded
against that file and the run continues, because the twelve that parsed are
still worth seeing. The rollup therefore always reports how many files failed
alongside the totals — a summary that silently covered eleven of twelve would be
worse than no summary.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from grant_assistant.workflow import run_pipeline

logger = logging.getLogger(__name__)

#: Extensions the ingestion layer can load.
DATA_SUFFIXES = (".csv", ".xlsx", ".xls", ".tsv", ".txt")


@dataclass
class BatchEntry:
    """One file's outcome. ``error`` set means nothing else here is meaningful."""

    path: Path
    ok: bool = True
    error: str = ""
    rows: int = 0
    score: float = 0.0
    grade: str = ""
    findings: int = 0
    blocking: int = 0
    enrollments: int = 0
    exits: int = 0
    successful_exit_rate: float | None = None


@dataclass
class BatchResult:
    """Every file's outcome plus the rolled-up totals."""

    entries: list[BatchEntry] = field(default_factory=list)

    @property
    def succeeded(self) -> list[BatchEntry]:
        return [e for e in self.entries if e.ok]

    @property
    def failed(self) -> list[BatchEntry]:
        return [e for e in self.entries if not e.ok]

    @property
    def total_rows(self) -> int:
        return sum(e.rows for e in self.succeeded)

    @property
    def total_findings(self) -> int:
        return sum(e.findings for e in self.succeeded)

    @property
    def total_blocking(self) -> int:
        return sum(e.blocking for e in self.succeeded)

    @property
    def weighted_score(self) -> float | None:
        """Score across the batch, weighted by rows.

        A plain mean would let a 5-row file swing the figure as hard as a
        5,000-row one, which is not what "our data quality" means.
        """
        rows = self.total_rows
        if not rows:
            return None
        return round(sum(e.score * e.rows for e in self.succeeded) / rows, 1)

    @property
    def worst(self) -> BatchEntry | None:
        """The file most in need of attention."""
        return min(self.succeeded, key=lambda e: e.score, default=None)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "File": e.path.name,
                    "Status": "OK" if e.ok else "FAILED",
                    "Rows": e.rows,
                    "Score": e.score if e.ok else None,
                    "Grade": e.grade,
                    "Findings": e.findings,
                    "Blocking": e.blocking,
                    "Enrollments": e.enrollments,
                    "Exits": e.exits,
                    "Successful exit rate": e.successful_exit_rate,
                    "Error": e.error,
                }
                for e in self.entries
            ]
        )


def discover_datasets(directory: str | Path, pattern: str = "*") -> list[Path]:
    """Loadable data files in a directory, sorted for a stable report order.

    Excel lock files (``~$...``) are skipped: they are not data, and a user who
    left a workbook open should not get a spurious failure.
    """
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    return sorted(
        path
        for path in root.glob(pattern)
        if path.is_file()
        and path.suffix.lower() in DATA_SUFFIXES
        and not path.name.startswith("~$")
    )


def run_batch(
    paths: Iterable[str | Path],
    profile: str,
    config_dir: str | Path | None = None,
    today: date | None = None,
) -> BatchResult:
    """Audit each file, collecting failures rather than raising on the first."""
    result = BatchResult()
    for raw_path in paths:
        path = Path(raw_path)
        try:
            run = run_pipeline(path, profile, config_dir, today=today)
        except Exception as exc:
            logger.warning("Batch: %s failed: %s", path.name, exc)
            result.entries.append(BatchEntry(path=path, ok=False, error=str(exc)[:200]))
            continue
        analytics = run.analytics
        result.entries.append(
            BatchEntry(
                path=path,
                rows=run.audit.total_rows,
                score=run.audit.overall_score,
                grade=run.audit.grade,
                findings=run.audit.total_findings,
                blocking=len(run.audit.blocking_issues),
                enrollments=analytics.total_enrollments,
                exits=analytics.total_exits,
                successful_exit_rate=analytics.successful_exit_rate,
            )
        )
    return result


def write_batch_summary(result: BatchResult, path: str | Path) -> Path:
    """Write the rollup as CSV or Excel, chosen by extension."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = result.to_frame()
    if path.suffix.lower() in {".xlsx", ".xls"}:
        frame.to_excel(path, index=False, sheet_name="Batch")
    else:
        frame.to_csv(path, index=False)
    return path


def batch_summary_lines(result: BatchResult) -> Sequence[str]:
    """Plain-language rollup, used by the CLI and safe to log."""
    lines = [
        f"{len(result.succeeded)} file(s) audited, {result.total_rows:,} rows",
        f"{result.total_findings:,} finding(s), {result.total_blocking} blocking",
    ]
    score = result.weighted_score
    if score is not None:
        lines.append(f"Weighted data quality score: {score:.1f}")
    worst = result.worst
    if worst is not None and len(result.succeeded) > 1:
        lines.append(f"Lowest scoring file: {worst.path.name} ({worst.score:.1f})")
    if result.failed:
        lines.append(f"{len(result.failed)} file(s) could not be processed")
    return lines
