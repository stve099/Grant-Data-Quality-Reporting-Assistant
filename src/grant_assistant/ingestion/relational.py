"""Safe many-to-one flattening for related grant-data extracts.

The frame-level :func:`merge_related_frames` is the implementation; the path-based
and upload-based wrappers only differ in how they read their inputs. Both entry
points therefore enforce identical join rules, which is the point — a merge that
the CLI rejects must not silently succeed in the web app.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from grant_assistant import schema
from grant_assistant.configuration import GrantProfile
from grant_assistant.ingestion.loader import IngestionError, load_dataset, normalize_header


def _source_column(frame: pd.DataFrame, profile: GrantProfile, canonical: str) -> str:
    """Find the source column that maps to one canonical join key."""
    candidates = {
        normalize_header(source)
        for source, target in profile.field_mappings.items()
        if target == canonical
    }
    candidates.add(normalize_header(canonical))
    matches = [column for column in frame.columns if normalize_header(column) in candidates]
    if len(matches) != 1:
        raise IngestionError(
            f"Expected exactly one column mapping to '{canonical}', found {matches or 'none'}."
        )
    return matches[0]


def merge_related_frames(
    primary: pd.DataFrame,
    related_frames: Iterable[tuple[str, pd.DataFrame]],
    profile: GrantProfile,
    join_on: str = schema.CLIENT_ID,
) -> pd.DataFrame:
    """Flatten already-loaded related frames into a primary frame.

    Related tables must contain one row per join key. The primary may contain
    repeated keys (for example, multiple program stays for one client), making
    the merge many-to-one. Existing primary columns always win; related tables
    only add columns that are not already present.

    Each related frame is paired with a display name used in error messages, so a
    rejected merge names the file the operator has to fix.
    """
    if join_on not in schema.CANONICAL_COLUMNS:
        raise IngestionError(f"Unknown canonical join key: {join_on}")

    merged = primary
    primary_key = _source_column(merged, profile, join_on)

    for name, related in related_frames:
        related_key = _source_column(related, profile, join_on)
        key_text = related[related_key].astype("string").str.strip()
        missing_keys = key_text.isna() | key_text.eq("")
        if missing_keys.any():
            raise IngestionError(
                f"Related file '{name}' has "
                f"{int(missing_keys.sum())} missing join key value(s) for '{join_on}'."
            )
        non_missing_keys = key_text[~missing_keys]
        duplicates = non_missing_keys[non_missing_keys.duplicated(keep=False)]
        if not duplicates.empty:
            sample = sorted(duplicates.unique().tolist())[:5]
            raise IngestionError(
                f"Related file '{name}' has duplicate join key value(s) for '{join_on}': {sample}"
            )

        additions = [
            column for column in related.columns if column != related_key and column not in merged
        ]
        if not additions:
            continue
        merge_key = "__grant_assistant_join_key__"
        while merge_key in merged.columns or merge_key in related.columns:
            merge_key = f"_{merge_key}"
        left = merged.assign(**{merge_key: merged[primary_key].astype("string").str.strip()})
        right = related[[related_key, *additions]].assign(**{merge_key: key_text})
        right = right.drop(columns=related_key)
        try:
            merged = left.merge(right, on=merge_key, how="left", validate="many_to_one").drop(
                columns=merge_key
            )
        except pd.errors.MergeError as exc:
            raise IngestionError(f"Could not merge related file '{name}': {exc}") from exc

    return merged


def merge_related_datasets(
    primary_source: str | Path,
    related_sources: Iterable[str | Path],
    profile: GrantProfile,
    join_on: str = schema.CLIENT_ID,
) -> pd.DataFrame:
    """Flatten related CSV/Excel extracts on disk into a primary source frame."""
    return merge_related_frames(
        load_dataset(primary_source),
        ((Path(source).name, load_dataset(source)) for source in related_sources),
        profile,
        join_on,
    )


def merge_uploaded_datasets(
    primary: pd.DataFrame,
    uploads: Iterable[tuple[str, bytes]],
    profile: GrantProfile,
    join_on: str = schema.CLIENT_ID,
) -> pd.DataFrame:
    """Flatten in-memory uploads into an already-loaded primary frame."""
    return merge_related_frames(
        primary,
        ((name, load_dataset(io.BytesIO(payload), filename=name)) for name, payload in uploads),
        profile,
        join_on,
    )
