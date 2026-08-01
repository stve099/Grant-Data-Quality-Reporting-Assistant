"""Security utilities: prompt-injection defense and safe handling of untrusted data."""

from grant_assistant.security.sanitize import (
    contains_injection,
    sanitize_mapping,
    sanitize_text,
    scan_dataframe_for_injection,
)

__all__ = [
    "contains_injection",
    "sanitize_mapping",
    "sanitize_text",
    "scan_dataframe_for_injection",
]
