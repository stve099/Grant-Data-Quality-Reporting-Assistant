"""Synthetic sample data generation (clean and intentionally flawed)."""

from grant_assistant.datagen.generator import (
    generate_clean_dataset,
    inject_issues,
    write_sample_files,
)

__all__ = ["generate_clean_dataset", "inject_issues", "write_sample_files"]
