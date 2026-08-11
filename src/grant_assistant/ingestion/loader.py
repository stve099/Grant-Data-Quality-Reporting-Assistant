"""Load CSV/Excel files and normalize them onto the canonical schema.

The pipeline is: ``load_dataset`` (read file) -> ``prepare_dataset``
(map headers via the profile, coerce types, normalize program labels).
The prepared result keeps both the normalized frame and the raw values so
audit rules can distinguish "missing" from "present but invalid".
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from grant_assistant import schema
from grant_assistant.configuration import GrantProfile
from grant_assistant.security.pii import pii_warnings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm"}
MAX_FILE_SIZE_MB = 200


class IngestionError(Exception):
    """Raised when an uploaded file cannot be read or prepared."""


def normalize_header(header: str) -> str:
    """Canonical form for header matching: case, spacing, and separators folded.

    Public because relational merging matches join-key columns the same way
    header mapping does; the two must never disagree about what a header means.
    """
    return str(header).strip().casefold().replace("-", " ").replace("_", " ")


def load_dataset(source: str | Path | io.BytesIO, filename: str | None = None) -> pd.DataFrame:
    """Read a CSV or Excel file into a raw DataFrame (all values as-is).

    Args:
        source: File path or in-memory buffer (e.g. a Streamlit upload).
        filename: Original file name; required when ``source`` is a buffer.

    Raises:
        IngestionError: unsupported type, unreadable file, or empty dataset.
    """
    if isinstance(source, str | Path):
        path = Path(source)
        if not path.exists():
            raise IngestionError(f"File not found: {path}")
        if path.stat().st_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise IngestionError(f"File exceeds the {MAX_FILE_SIZE_MB} MB limit: {path.name}")
        name = path.name
        handle: str | Path | io.BytesIO = path
    else:
        if not filename:
            raise IngestionError("A filename is required when loading from a buffer.")
        name = filename
        handle = source

    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise IngestionError(
            f"Unsupported file type '{suffix}'. Supported types: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )

    try:
        if suffix == ".csv":
            df = pd.read_csv(handle, dtype=str, keep_default_na=True, skipinitialspace=True)
        else:
            df = pd.read_excel(handle, dtype=str)
    except Exception as exc:
        raise IngestionError(f"Could not read '{name}': {exc}") from exc

    if df.empty:
        raise IngestionError(f"'{name}' contains no data rows.")

    df.columns = [str(c).strip() for c in df.columns]
    logger.info("Loaded %s: %d rows, %d columns", name, len(df), len(df.columns))
    return df


@dataclass
class PreparedData:
    """A dataset mapped to the canonical schema and type-normalized.

    Attributes:
        df: Normalized frame — canonical columns, parsed dates, numeric types,
            canonical program labels in ``program``.
        raw: Same shape/index as ``df`` but with original string values,
            used by audit rules to detect invalid (vs. missing) entries.
        mapped_columns: Source header -> canonical column actually applied.
        unmapped_source_columns: Source headers not used by the profile.
        missing_canonical_columns: Canonical columns absent from the upload.
        pii_warnings: Columns in the *source* file that look like direct
            identifiers. Computed here rather than downstream because mapping
            drops unmapped columns, and a stray name or SSN column is unmapped
            by definition — scanning after the drop would never see it.
    """

    df: pd.DataFrame
    raw: pd.DataFrame
    mapped_columns: dict[str, str] = field(default_factory=dict)
    unmapped_source_columns: list[str] = field(default_factory=list)
    missing_canonical_columns: list[str] = field(default_factory=list)
    pii_warnings: list[str] = field(default_factory=list)

    @property
    def row_numbers(self) -> pd.Series:
        """1-based data row numbers aligned with ``df`` (row 1 = first data row)."""
        return pd.Series(range(1, len(self.df) + 1), index=self.df.index)


def prepare_dataset(df: pd.DataFrame, profile: GrantProfile) -> PreparedData:
    """Map source headers to canonical columns and normalize types.

    Header matching is case/spacing-insensitive. Canonical columns that the
    upload lacks entirely are created as empty so downstream code can rely on
    the full schema; they are also reported in ``missing_canonical_columns``.
    """
    lookup: dict[str, str] = {}
    for source_header, canonical in profile.field_mappings.items():
        lookup[normalize_header(source_header)] = canonical
    # Also accept canonical names themselves as headers.
    for canonical in schema.CANONICAL_COLUMNS:
        lookup.setdefault(normalize_header(canonical), canonical)

    mapped: dict[str, str] = {}
    unmapped: list[str] = []
    renames: dict[str, str] = {}
    seen_targets: set[str] = set()
    for col in df.columns:
        target = lookup.get(normalize_header(col))
        if target and target not in seen_targets:
            renames[col] = target
            mapped[col] = target
            seen_targets.add(target)
        else:
            unmapped.append(col)

    if schema.CLIENT_ID not in seen_targets:
        raise IngestionError(
            "The uploaded file has no column mapping to 'client_id'. "
            "Check the profile's field_mappings against the file headers. "
            f"File headers: {list(df.columns)[:15]}"
        )

    work = df.rename(columns=renames).copy()
    work = work[[c for c in schema.CANONICAL_COLUMNS if c in work.columns]]

    missing = [c for c in schema.CANONICAL_COLUMNS if c not in work.columns]
    for col in missing:
        work[col] = pd.NA
    work = work[list(schema.CANONICAL_COLUMNS)]
    work = work.reset_index(drop=True)

    # Trim whitespace on all text values; blank strings become missing.
    for col in work.columns:
        work[col] = work[col].map(lambda v: (v.strip() or pd.NA) if isinstance(v, str) else v)

    raw = work.copy()

    for col in schema.DATE_COLUMNS:
        work[col] = pd.to_datetime(work[col], errors="coerce", format="mixed")
    for col in schema.NUMERIC_COLUMNS:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    # Normalize program labels via profile aliases; keep raw label alongside.
    alias_map = profile.program_alias_map()
    work[schema.PROGRAM_RAW] = raw[schema.PROGRAM]
    work[schema.PROGRAM] = raw[schema.PROGRAM].map(
        lambda v: alias_map.get(str(v).strip().casefold(), v) if pd.notna(v) else v
    )

    logger.info(
        "Prepared dataset: %d rows; %d columns mapped, %d unmapped, %d missing canonical",
        len(work),
        len(mapped),
        len(unmapped),
        len(missing),
    )
    return PreparedData(
        df=work,
        raw=raw,
        mapped_columns=mapped,
        unmapped_source_columns=unmapped,
        missing_canonical_columns=missing,
        # Scanned against the source frame, before unmapped columns are dropped.
        pii_warnings=pii_warnings(df),
    )
