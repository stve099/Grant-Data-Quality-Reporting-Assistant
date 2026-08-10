"""Dataset ingestion: safe file loading, field mapping, and normalization."""

from grant_assistant.ingestion.loader import (
    IngestionError,
    PreparedData,
    load_dataset,
    prepare_dataset,
)
from grant_assistant.ingestion.relational import merge_related_datasets

__all__ = [
    "IngestionError",
    "PreparedData",
    "load_dataset",
    "merge_related_datasets",
    "prepare_dataset",
]
