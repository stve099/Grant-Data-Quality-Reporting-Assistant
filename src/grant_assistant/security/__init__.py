"""Security utilities: prompt-injection defense and safe handling of untrusted data."""

from grant_assistant.security.pii import (
    PiiFinding,
    pii_warnings,
    scan_dataframe_for_pii,
)
from grant_assistant.security.sanitize import (
    contains_injection,
    sanitize_mapping,
    sanitize_text,
    scan_dataframe_for_injection,
)

__all__ = [
    "PiiFinding",
    "contains_injection",
    "pii_warnings",
    "sanitize_mapping",
    "sanitize_text",
    "scan_dataframe_for_injection",
    "scan_dataframe_for_pii",
]
