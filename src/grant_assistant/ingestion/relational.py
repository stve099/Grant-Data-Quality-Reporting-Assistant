"""Safe many-to-one flattening for related grant-data extracts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from grant_assistant import schema
from grant_assistant.configuration import GrantProfile
from grant_assistant.ingestion.loader import IngestionError, _normalize_header, load_dataset


def _source_column(frame: pd.DataFrame, profile: GrantProfile, canonical: str) -> str:
    """Find the source column that maps to one canonical join key."""
    candidates = {
        _normalize_header(source)
        for source, target in profile.field_mappings.items()
        if target == canonical
    }
    candidates.add(_normalize_header(canonical))
    matches = [column for column in frame.columns if _normalize_header(column) in candidates]
    if len(matches) != 1:
        raise IngestionError(
            f"Expected exactly one column mapping to '{canonical}', found {matches or 'none'}."
        )
    return matches[0]


def merge_related_datasets(
    primary_source: str | Path,
    related_sources: Iterable[str | Path],
    profile: GrantProfile,
    join_on: str = schema.CLIENT_ID,
) -> pd.DataFrame:
    """Flatten related CSV/Excel extracts into a primary source frame.

    Related tables must contain one row per join key. The primary may contain
    repeated keys (for example, multiple program stays for one client), making
    the merge many-to-one. Existing primary columns always win; related tables
    only add columns that are not already present.
    """
    if join_on not in schema.CANONICAL_COLUMNS:
        raise IngestionError(f"Unknown canonical join key: {join_on}")

    merged = load_dataset(primary_source)
    primary_key = _source_column(merged, profile, join_on)

    for related_source in related_sources:
        related = load_dataset(related_source)
        related_key = _source_column(related, profile, join_on)
        key_text = related[related_key].astype("string").str.strip()
        missing_keys = key_text.isna() | key_text.eq("")
        if missing_keys.any():
            raise IngestionError(
                f"Related file '{Path(related_source).name}' has "
                f"{int(missing_keys.sum())} missing join key value(s) for '{join_on}'."
            )
        non_missing_keys = key_text[~missing_keys]
        duplicates = non_missing_keys[non_missing_keys.duplicated(keep=False)]
        if not duplicates.empty:
            sample = sorted(duplicates.unique().tolist())[:5]
            raise IngestionError(
                f"Related file '{Path(related_source).name}' has duplicate join key "
                f"value(s) for '{join_on}': {sample}"
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
            raise IngestionError(
                f"Could not merge related file '{Path(related_source).name}': {exc}"
            ) from exc

    return merged
