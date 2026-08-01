"""Defenses against prompt injection carried inside uploaded data files.

Uploaded spreadsheets are untrusted input. Any cell value that flows into an
AI prompt (program labels, destination values, category names) passes through
:func:`sanitize_text` first, and whole datasets can be scanned with
:func:`scan_dataframe_for_injection` so the UI can warn the user.

The AI analyst additionally keeps all data inside a delimited JSON fact sheet
and its system prompt instructs the model to treat that content strictly as
data — sanitization here is defense in depth, not the only layer.
"""

from __future__ import annotations

import re

import pandas as pd

#: Phrases that indicate an attempt to steer the model from inside data cells.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
        r"disregard\s+(all\s+|any\s+)?(previous|prior|above|earlier|your)\s+\w*\s*(instructions?|rules?)?",
        r"forget\s+(all\s+|everything|your)\s*(previous|prior|instructions?)?",
        r"system\s*prompt",
        r"you\s+are\s+now\s+",
        r"act\s+as\s+(a|an|the)\s+",
        r"pretend\s+(to\s+be|you\s+are)",
        r"new\s+instructions?\s*:",
        r"\bdo\s+anything\s+now\b",
        r"\bDAN\s+mode\b",
        r"override\s+(safety|instructions?|rules?)",
        r"reveal\s+(your|the)\s+(system\s+)?(prompt|instructions?)",
        r"exfiltrate",
        r"</?\s*(system|assistant|instructions?)\s*>",
        r"<\|[^|]{0,40}\|>",
        r"\bBEGIN\s+(SYSTEM|ADMIN|OVERRIDE)\b",
        r"human\s*:\s*",
        r"assistant\s*:\s*",
    )
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REDACTION = "[removed]"


def contains_injection(value: object) -> bool:
    """Return True when a value contains a likely prompt-injection phrase."""
    if not isinstance(value, str) or not value:
        return False
    return any(p.search(value) for p in _INJECTION_PATTERNS)


def sanitize_text(value: object, max_length: int = 200) -> str:
    """Neutralize a data-derived string before it can reach an AI prompt.

    Strips control characters, collapses whitespace/newlines, redacts
    injection phrases, and truncates to ``max_length``.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value)
    text = _CONTROL_CHARS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub(_REDACTION, text)
    if len(text) > max_length:
        text = text[: max_length - 1] + "…"
    return text


def sanitize_mapping(mapping: dict[str, object], max_length: int = 200) -> dict[str, object]:
    """Sanitize every string key and string value in a flat mapping."""
    out: dict[str, object] = {}
    for key, value in mapping.items():
        clean_key = sanitize_text(key, max_length=max_length)
        if isinstance(value, str):
            out[clean_key] = sanitize_text(value, max_length=max_length)
        elif isinstance(value, dict):
            out[clean_key] = sanitize_mapping(value, max_length=max_length)  # type: ignore[arg-type]
        elif isinstance(value, list):
            out[clean_key] = [
                sanitize_text(v, max_length=max_length) if isinstance(v, str) else v for v in value
            ]
        else:
            out[clean_key] = value
    return out


def scan_dataframe_for_injection(df: pd.DataFrame, limit: int = 25) -> list[str]:
    """Scan text cells for injection attempts; return human-readable warnings.

    Only coordinates and the column name are reported — the suspicious payload
    itself is never echoed back verbatim.
    """
    warnings: list[str] = []
    for column in df.columns:
        series = df[column]
        if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            continue
        for position, value in enumerate(series.to_list()):
            if contains_injection(value):
                pos = position + 2  # +1 for the header row, +1 for 1-based rows
                warnings.append(
                    f"Cell in column '{column}' (spreadsheet row ~{pos}) contains text that "
                    "resembles a prompt-injection attempt. It will be neutralized before any "
                    "AI processing."
                )
                if len(warnings) >= limit:
                    return warnings
    return warnings
