"""Detect direct identifiers in an uploaded extract, before anything else runs.

The project's premise is that no real client data enters it: the audit works on
pseudonymous IDs and aggregates, and the AI layer never sees a row. Nothing
enforced that. A user exporting from their case management system can easily
include a name or SSN column without noticing, and the first place it would
surface is a generated report.

This module answers one question — "does this file look like it contains direct
identifiers?" — before ingestion maps a single column. Detection is deliberately
two-sided: a column *named* like an identifier is reported even when empty, and
values that *look* like an SSN, email, phone or date of birth are reported even
when the column is named something bland.

Findings are warnings, not errors. A false positive must never block a
legitimate upload, so the caller decides what to do. Payloads are never echoed
back — only the column and how many cells matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

#: Column-name fragments that denote a direct identifier. Matched against the
#: normalized header, so "Client_First_Name" and "client first name" both hit.
_NAME_FRAGMENTS: dict[str, tuple[str, ...]] = {
    "name": ("name", "firstname", "lastname", "surname", "givenname", "middlename", "fullname"),
    "social security number": ("ssn", "socialsecurity", "social_security"),
    "date of birth": ("dob", "dateofbirth", "birthdate", "birthday"),
    "contact detail": ("email", "phone", "mobile", "telephone", "cell"),
    "address": ("address", "street", "zipcode", "postcode", "postalcode"),
}

#: Qualifiers that make a "name" column the name of a *thing*, not a person.
#: "Program Name" is a column every extract in this domain has, and flagging it
#: would train users to ignore the warning entirely.
_NON_PERSON_NAME_QUALIFIERS = (
    "program",
    "grant",
    "project",
    "agency",
    "organization",
    "org",
    "provider",
    "site",
    "facility",
    "funder",
    "vendor",
    "file",
    "column",
    "field",
    "report",
    "template",
    "destination",
)

#: Value shapes. Anchored and specific: a loose phone pattern would match IDs.
_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "social security number": re.compile(r"^\d{3}-\d{2}-\d{4}$"),
    "email address": re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),
    "phone number": re.compile(r"^\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$"),
}

#: How many cells to inspect per column. Direct identifiers are systematic, not
#: occasional, so a sample settles it without walking a 100k-row extract.
_SAMPLE_ROWS = 200
#: Fraction of sampled non-empty cells that must match before reporting.
_VALUE_HIT_RATIO = 0.20


@dataclass(frozen=True)
class PiiFinding:
    """One column that looks like it carries a direct identifier."""

    column: str
    kind: str
    #: "header" when the column name gave it away, "values" when the data did.
    detected_by: str
    match_count: int = 0

    @property
    def message(self) -> str:
        if self.detected_by == "header":
            return (
                f"Column '{self.column}' is named like a {self.kind}. Direct identifiers "
                "should be removed or pseudonymized before upload."
            )
        return (
            f"Column '{self.column}' contains values shaped like a {self.kind} "
            f"({self.match_count} of the sampled cells). Direct identifiers should be "
            "removed or pseudonymized before upload."
        )


def _normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header).casefold())


#: A value must look like a written date before it is parsed as one. Without
#: this, a bare income of "1207" parses as the year 1207 and every currency
#: column reads as a birth date.
_DATE_SHAPED = re.compile(r"^\d{1,4}[-/][A-Za-z0-9]{1,9}[-/][A-Za-z0-9]{1,4}$")
#: Plausible birth years. The upper bound keeps program dates out; the lower
#: bound keeps parser artifacts out.
_BIRTH_YEAR_RANGE = (1900, 2015)


def _looks_like_dob(series: pd.Series) -> bool:
    """A date column is only a birth date if its values predate the programs."""
    dated = series[series.str.match(_DATE_SHAPED).fillna(False)]
    if len(dated) < 5:
        return False
    parsed = pd.to_datetime(dated, errors="coerce", format="mixed")
    valid = parsed.dropna()
    if len(valid) < 5:
        return False
    low, high = _BIRTH_YEAR_RANGE
    # Enrollment and exit dates cluster in recent years; birth dates do not.
    return bool(valid.dt.year.between(low, high).mean() > 0.5)


def scan_dataframe_for_pii(df: pd.DataFrame, limit: int = 25) -> list[PiiFinding]:
    """Report columns that appear to hold direct identifiers.

    Header matches are reported even for empty columns — the schema itself is the
    signal. Value matches need a fifth of the sampled cells to agree, so a single
    stray email in a notes field does not trip it.
    """
    findings: list[PiiFinding] = []

    for column in df.columns:
        normalized = _normalize_header(column)
        for kind, fragments in _NAME_FRAGMENTS.items():
            if not any(fragment in normalized for fragment in fragments):
                continue
            if kind == "name" and any(q in normalized for q in _NON_PERSON_NAME_QUALIFIERS):
                continue  # "Program Name" names a thing, not a person.
            findings.append(PiiFinding(column=str(column), kind=kind, detected_by="header"))
            break
        if len(findings) >= limit:
            return findings[:limit]

    for column in df.columns:
        series = df[column]
        if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            continue
        sample = series.dropna().astype("string").str.strip()
        sample = sample[sample != ""].head(_SAMPLE_ROWS)
        if sample.empty:
            continue
        already = {f.column for f in findings}
        for kind, pattern in _VALUE_PATTERNS.items():
            hits = int(sample.str.match(pattern).sum())
            if hits and hits / len(sample) >= _VALUE_HIT_RATIO and str(column) not in already:
                findings.append(
                    PiiFinding(
                        column=str(column), kind=kind, detected_by="values", match_count=hits
                    )
                )
                break
        if str(column) not in already and _looks_like_dob(sample):
            findings.append(
                PiiFinding(
                    column=str(column),
                    kind="date of birth",
                    detected_by="values",
                    match_count=len(sample),
                )
            )
        if len(findings) >= limit:
            break

    return findings[:limit]


def pii_warnings(df: pd.DataFrame, limit: int = 25) -> list[str]:
    """Human-readable form of :func:`scan_dataframe_for_pii`."""
    return [finding.message for finding in scan_dataframe_for_pii(df, limit=limit)]
