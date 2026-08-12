"""Correction round-trip: export what is wrong, take back the fixes, prove them.

The audit already names every flawed record and recommends a correction, but the
loop never closed — a user read the findings and retyped fixes into their case
management system with nothing checking the result. This module exports a
worksheet keyed by row, accepts it back with a ``Corrected Value`` column filled
in, applies it to the *source* file, and lets the caller re-audit to show the
issues actually cleared.

Applying corrections to the wrong extract would silently corrupt data, so every
edit is verified against the client ID recorded at export time. A row that does
not match is skipped and reported, never guessed at.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from grant_assistant.ingestion import PreparedData
from grant_assistant.models import AuditResult

#: Worksheet columns. Order is the reading order for a person fixing data:
#: which record, what is wrong, what it says now, what to do, what it should be.
ROW = "Row"
CLIENT_ID = "Client ID"
PROGRAM = "Program"
RULE = "Rule"
ISSUE = "Issue"
SEVERITY = "Severity"
BLOCKING = "Blocking"
FIELD = "Field"
CURRENT_VALUE = "Current Value"
RECOMMENDED_ACTION = "Recommended Action"
CORRECTED_VALUE = "Corrected Value"

WORKSHEET_COLUMNS = [
    ROW,
    CLIENT_ID,
    PROGRAM,
    RULE,
    ISSUE,
    SEVERITY,
    BLOCKING,
    FIELD,
    CURRENT_VALUE,
    RECOMMENDED_ACTION,
    CORRECTED_VALUE,
]

SHEET_NAME = "Corrections"
INSTRUCTIONS_SHEET = "Instructions"

_INSTRUCTIONS = [
    ("Grant Data Quality & Reporting Assistant — correction worksheet", ""),
    ("", ""),
    ("1.", "Fill in the 'Corrected Value' column for the rows you want to fix."),
    ("2.", "Leave 'Corrected Value' blank to skip a row — blanks are never applied."),
    ("3.", "Do not edit any other column. 'Row' and 'Client ID' identify the record"),
    ("", "and are checked before a correction is applied."),
    ("4.", "To clear a value rather than replace it, enter: <BLANK>"),
    ("5.", "Save the file, then run:"),
    ("", "grant-assistant apply-corrections <data file> <this file>"),
    ("", ""),
    ("Note", "Corrections are written to a new file. Your original is never modified."),
]

#: Sentinel a user types to empty a field, since a blank cell means "skip".
CLEAR_TOKEN = "<BLANK>"


@dataclass
class Correction:
    """One requested edit, as read back from a worksheet."""

    row: int
    client_id: str
    field_name: str
    corrected_value: str


@dataclass
class ApplyReport:
    """Outcome of applying a worksheet, including everything refused."""

    applied: int = 0
    skipped: list[str] = field(default_factory=list)
    changed_fields: set[str] = field(default_factory=set)

    @property
    def total_requested(self) -> int:
        return self.applied + len(self.skipped)

    def summary(self) -> str:
        parts = [f"{self.applied} correction(s) applied"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        return ", ".join(parts)


def build_worksheet(audit: AuditResult) -> pd.DataFrame:
    """One row per flagged record, ready for a person to fill in.

    Rules that flag a dataset-level condition rather than a specific cell carry
    no field, so there is nothing to correct row by row; they are left out.
    """
    rows: list[dict[str, Any]] = []
    for issue in audit.issues_sorted():
        for record in issue.records:
            if not record.field:
                continue
            rows.append(
                {
                    ROW: record.row,
                    CLIENT_ID: record.client_id,
                    PROGRAM: record.program,
                    RULE: issue.rule_id,
                    ISSUE: issue.rule_name,
                    SEVERITY: issue.severity.label,
                    BLOCKING: "Yes" if issue.blocking else "",
                    FIELD: record.field,
                    CURRENT_VALUE: record.value,
                    RECOMMENDED_ACTION: issue.recommendation,
                    CORRECTED_VALUE: "",
                }
            )
    return pd.DataFrame(rows, columns=WORKSHEET_COLUMNS)


def write_worksheet(audit: AuditResult, path: str | Path) -> Path:
    """Write the correction worksheet as an Excel workbook with instructions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = build_worksheet(audit)
    instructions = pd.DataFrame(_INSTRUCTIONS, columns=["", " "])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        instructions.to_excel(writer, sheet_name=INSTRUCTIONS_SHEET, index=False)
        frame.to_excel(writer, sheet_name=SHEET_NAME, index=False)
        sheet = writer.sheets[SHEET_NAME]
        widths = {
            ROW: 6,
            CLIENT_ID: 12,
            PROGRAM: 24,
            RULE: 9,
            ISSUE: 30,
            SEVERITY: 13,
            BLOCKING: 9,
            FIELD: 20,
            CURRENT_VALUE: 22,
            RECOMMENDED_ACTION: 46,
            CORRECTED_VALUE: 22,
        }
        for index, column in enumerate(WORKSHEET_COLUMNS, start=1):
            sheet.column_dimensions[chr(64 + index)].width = widths[column]
        writer.sheets[INSTRUCTIONS_SHEET].column_dimensions["A"].width = 8
        writer.sheets[INSTRUCTIONS_SHEET].column_dimensions["B"].width = 78
    return path


def read_worksheet(path: str | Path) -> list[Correction]:
    """Read filled-in corrections from a file, ignoring rows left blank.

    Raises:
        ValueError: the file is missing columns this module wrote, which almost
            always means the wrong file was passed.
    """
    path = Path(path)
    return _read_source(path, path.name, path.suffix)


def read_worksheet_bytes(payload: bytes, filename: str) -> list[Correction]:
    """Read filled-in corrections from an upload that never reaches disk.

    The web app receives the returned worksheet as bytes. Writing it to a
    temporary file first would only be a detour: the parsing, the column check,
    and the wrong-file error all have to behave identically either way, so both
    entry points share one implementation.
    """
    return _read_source(io.BytesIO(payload), filename, Path(filename).suffix)


def _read_source(source: Any, name: str, suffix: str) -> list[Correction]:
    # keep_default_na=False so an untouched cell reads as "" rather than NaN,
    # whose str() is the non-empty string "nan" and would look like a correction.
    try:
        if suffix.lower() in {".csv", ".txt"}:
            frame = pd.read_csv(source, dtype=str, keep_default_na=False)
        else:
            frame = pd.read_excel(source, sheet_name=SHEET_NAME, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        raise
    except Exception as exc:
        # Whatever the parser objects to — a missing sheet, a file that is not a
        # spreadsheet at all — the user's problem is the same one, and callers
        # already handle ValueError as "that is not the right file".
        raise ValueError(f"{name} could not be read as a correction worksheet: {exc}") from exc
    missing = [c for c in (ROW, CLIENT_ID, FIELD, CORRECTED_VALUE) if c not in frame.columns]
    if missing:
        raise ValueError(
            f"{name} is not a correction worksheet — missing column(s): {', '.join(missing)}."
        )

    corrections: list[Correction] = []
    for _, record in frame.iterrows():
        value = str(record.get(CORRECTED_VALUE) or "").strip()
        if not value:
            continue
        try:
            row_number = int(float(record[ROW]))
        except (TypeError, ValueError):
            continue
        corrections.append(
            Correction(
                row=row_number,
                client_id=str(record.get(CLIENT_ID) or "").strip(),
                field_name=str(record.get(FIELD) or "").strip(),
                corrected_value=value,
            )
        )
    return corrections


def _source_header(canonical: str, prepared: PreparedData, source: pd.DataFrame) -> str | None:
    """The source column a canonical field came from, if the upload had one."""
    for header, mapped_to in prepared.mapped_columns.items():
        if mapped_to == canonical and header in source.columns:
            return header
    return canonical if canonical in source.columns else None


def apply_corrections(
    source: pd.DataFrame,
    corrections: list[Correction],
    prepared: PreparedData,
) -> tuple[pd.DataFrame, ApplyReport]:
    """Apply corrections to a copy of the source frame.

    Each edit is verified against the client ID recorded at export time. A
    mismatch means the worksheet and the file have drifted apart — rows added or
    removed, or simply the wrong file — so the edit is refused rather than
    written to whatever row now sits at that position.
    """
    corrected = source.copy()
    report = ApplyReport()

    client_column = _source_header("client_id", prepared, source)

    for correction in corrections:
        position = correction.row - 1
        if position < 0 or position >= len(corrected):
            report.skipped.append(
                f"Row {correction.row}: outside the data ({len(corrected)} rows)."
            )
            continue

        if correction.client_id and client_column is not None:
            actual = str(corrected.iloc[position][client_column]).strip()
            if actual != correction.client_id:
                report.skipped.append(
                    f"Row {correction.row}: expected client {correction.client_id} but found "
                    f"{actual or 'a blank'} — worksheet does not match this file."
                )
                continue

        column = _source_header(correction.field_name, prepared, source)
        if column is None:
            report.skipped.append(
                f"Row {correction.row}: no column for field '{correction.field_name}'."
            )
            continue

        column_index = corrected.columns.get_loc(column)
        if not isinstance(column_index, int):
            # Duplicate headers make the target ambiguous; refuse rather than guess.
            report.skipped.append(
                f"Row {correction.row}: column '{column}' appears more than once."
            )
            continue

        value = "" if correction.corrected_value == CLEAR_TOKEN else correction.corrected_value
        corrected.iat[position, column_index] = value
        report.applied += 1
        report.changed_fields.add(correction.field_name)

    return corrected, report
