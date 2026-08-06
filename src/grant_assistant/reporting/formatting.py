"""Value formatting shared by every renderer.

Word and PowerPoint each carried a private copy of this function. Two copies of
a formatter drift — one gains thousands separators, the other does not — and the
result is the same figure printed two ways in two documents generated from one
calculation. That is precisely the class of inconsistency the single-ReportData
design exists to prevent, so the formatter is single too.
"""

from __future__ import annotations


def format_value(value: float | int | None, unit: str = "") -> str:
    """Render a metric for a document.

    ``unit`` follows the profile's vocabulary: ``percent``, ``currency``, or
    empty for a plain count. ``None`` is rendered as "n/a" rather than omitted,
    because a blank cell reads as zero.
    """
    if value is None:
        return "n/a"
    if unit == "percent":
        return f"{value}%"
    if unit == "currency":
        return f"${value:,.0f}"
    if isinstance(value, float):
        return f"{value:,.1f}"
    return f"{value:,}"
