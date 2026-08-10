"""Which records changed between two extracts, not just which totals.

``compare_analytics`` answers "the permanent housing rate fell 4 points". The
next question is always "which records moved?", and until now the only way to
answer it was to open both files side by side.

Records are matched on client ID, which is the only stable key these extracts
carry. That has a consequence worth stating: a re-keyed export looks like every
client left and a different set arrived. The summary reports added and removed
counts plainly so that case is visible rather than mistaken for churn.

Values are compared as the *raw* strings, so "01/05/2025" and "2025-01-05" show
as a change. That is deliberate — a reformatted export is a real difference a
data manager wants to know about, even when the parsed dates agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from grant_assistant import schema
from grant_assistant.ingestion import PreparedData


@dataclass
class FieldChange:
    """One field that differs for one client."""

    client_id: str
    field_name: str
    before: str
    after: str


@dataclass
class RecordDiff:
    """Record-level differences between two extracts."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[FieldChange] = field(default_factory=list)
    unchanged_count: int = 0

    @property
    def changed_clients(self) -> list[str]:
        return sorted({c.client_id for c in self.changed})

    @property
    def total_differences(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed_clients)

    def changes_by_field(self) -> dict[str, int]:
        """How many clients changed in each field, commonest first.

        Usually the most useful view: one field accounting for most of the
        changes points at a systematic export difference rather than data entry.
        """
        counts: dict[str, int] = {}
        for change in self.changed:
            counts[change.field_name] = counts.get(change.field_name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Client ID": c.client_id,
                    "Field": c.field_name,
                    "Before": c.before,
                    "After": c.after,
                }
                for c in self.changed
            ],
            columns=["Client ID", "Field", "Before", "After"],
        )

    def summary_lines(self) -> list[str]:
        lines = [
            f"{len(self.added)} client(s) added, {len(self.removed)} removed",
            f"{len(self.changed_clients)} client(s) changed ({len(self.changed)} field change(s))",
            f"{self.unchanged_count} client(s) identical",
        ]
        by_field = self.changes_by_field()
        if by_field:
            top = ", ".join(f"{name} ({count})" for name, count in list(by_field.items())[:5])
            lines.append(f"Fields most often changed: {top}")
        return lines


def _keyed_raw(data: PreparedData) -> dict[str, dict[str, str]]:
    """client_id -> {field: raw value}, keeping the first row per client.

    Duplicate client rows are an audit finding in their own right (DQ-010); this
    module reports on the first and leaves the duplication to the audit rather
    than guessing which row is authoritative.
    """
    frame = data.raw
    records: dict[str, dict[str, str]] = {}
    for _, row in frame.iterrows():
        raw_client = row.get(schema.CLIENT_ID)
        # pd.isna first: a missing id becomes NaN, and str(nan) is the non-empty
        # "nan", which would otherwise read as a client of that name.
        client = "" if pd.isna(raw_client) else str(raw_client).strip()
        if not client or client in records:
            continue
        records[client] = {
            str(column): ("" if pd.isna(value) else str(value).strip())
            for column, value in row.items()
        }
    return records


def diff_records(
    current: PreparedData,
    prior: PreparedData,
    fields: list[str] | None = None,
) -> RecordDiff:
    """Compare two prepared extracts record by record.

    ``fields`` limits the comparison to named canonical columns; by default
    every column both extracts share is compared. Columns present in only one
    extract are skipped rather than reported as a change for every client, since
    that is a schema difference and not a data one.
    """
    before = _keyed_raw(prior)
    after = _keyed_raw(current)

    shared_columns = set(current.raw.columns) & set(prior.raw.columns)
    if fields:
        shared_columns &= set(fields)
    comparable = sorted(shared_columns - {schema.CLIENT_ID})

    diff = RecordDiff(
        added=sorted(set(after) - set(before)),
        removed=sorted(set(before) - set(after)),
    )

    for client in sorted(set(before) & set(after)):
        changes = [
            FieldChange(
                client_id=client,
                field_name=column,
                before=before[client].get(column, ""),
                after=after[client].get(column, ""),
            )
            for column in comparable
            if before[client].get(column, "") != after[client].get(column, "")
        ]
        if changes:
            diff.changed.extend(changes)
        else:
            diff.unchanged_count += 1
    return diff
