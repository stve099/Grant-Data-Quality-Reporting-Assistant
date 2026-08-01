"""Dataset ingestion: safe file loading, field mapping, and normalization."""

from grant_assistant.ingestion.loader import (
    IngestionError,
    PreparedData,
    load_dataset,
    prepare_dataset,
)

__all__ = ["IngestionError", "PreparedData", "load_dataset", "prepare_dataset"]
