"""PII pre-flight tests.

Two directions matter equally. A direct identifier must be reported, and a
legitimate extract must produce no warnings at all — a scanner that cries wolf
on the sample data would be switched off within a week.
"""

from __future__ import annotations

import pandas as pd
import pytest

from grant_assistant.security import scan_dataframe_for_pii
from grant_assistant.security.pii import pii_warnings


def _finding_kinds(df: pd.DataFrame) -> set[str]:
    return {f.kind for f in scan_dataframe_for_pii(df)}


# -- Header detection --------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("client_name", "name"),
        ("First Name", "name"),
        ("LastName", "name"),
        ("SSN", "social security number"),
        ("social_security_number", "social security number"),
        ("DOB", "date of birth"),
        ("date_of_birth", "date of birth"),
        ("email", "contact detail"),
        ("Phone Number", "contact detail"),
        ("street_address", "address"),
        ("zip_code", "address"),
    ],
)
def test_identifier_column_names_are_reported(column, expected):
    df = pd.DataFrame({"client_id": ["C-1"], column: ["x"]})
    findings = scan_dataframe_for_pii(df)
    assert [f.kind for f in findings] == [expected]
    assert findings[0].detected_by == "header"


def test_empty_identifier_column_is_still_reported():
    """The schema is the signal; an empty name column is still a name column."""
    df = pd.DataFrame({"client_name": [None, None, None]})
    assert _finding_kinds(df) == {"name"}


# -- Value detection ---------------------------------------------------------


def test_ssn_values_under_a_bland_header_are_reported():
    df = pd.DataFrame({"reference": ["123-45-6789", "987-65-4321", "555-11-2222"]})
    findings = scan_dataframe_for_pii(df)
    assert findings[0].kind == "social security number"
    assert findings[0].detected_by == "values"
    assert findings[0].match_count == 3


def test_email_and_phone_values_are_reported():
    emails = pd.DataFrame({"contact": ["a@b.com", "c@d.org", "e@f.net"]})
    phones = pd.DataFrame({"contact": ["555-123-4567", "(555) 987-6543", "5551112222"]})
    assert _finding_kinds(emails) == {"email address"}
    assert _finding_kinds(phones) == {"phone number"}


def test_birth_dates_are_distinguished_from_program_dates():
    """Enrollment dates cluster recently; birth dates do not."""
    births = pd.DataFrame(
        {"d": ["1962-04-11", "1975-09-02", "1948-01-30", "1981-06-15", "1955-03-03"]}
    )
    enrollments = pd.DataFrame(
        {"d": ["2024-08-01", "2024-09-15", "2025-01-20", "2024-11-02", "2025-03-11"]}
    )
    assert _finding_kinds(births) == {"date of birth"}
    assert scan_dataframe_for_pii(enrollments) == []


def test_one_stray_email_in_notes_does_not_trip_the_scan():
    """A scanner that fires on a single cell gets ignored, so it must not."""
    df = pd.DataFrame(
        {"notes": ["called client", "left voicemail", "ref a@b.com"] + ["no note"] * 7}
    )
    assert scan_dataframe_for_pii(df) == []


# -- No false positives on real extracts -------------------------------------


def test_clean_sample_data_produces_no_warnings(prepared_clean):
    assert pii_warnings(prepared_clean.raw) == []


def test_flawed_sample_data_produces_no_warnings(prepared_flawed):
    """The flawed sample carries every documented issue but no identifiers."""
    assert pii_warnings(prepared_flawed.raw) == []


@pytest.mark.parametrize(
    "column",
    ["Program Name", "Grant Name", "Agency Name", "Project Name", "File Name", "Provider Name"],
)
def test_columns_naming_a_thing_are_not_flagged(column):
    """ "Program Name" is in every extract in this domain.

    Flagging it teaches users to ignore the warning, which costs more than the
    identifier it would otherwise catch.
    """
    assert scan_dataframe_for_pii(pd.DataFrame({column: ["Rapid Re-Housing"]})) == []


def test_real_sample_file_headers_produce_no_warnings():
    """The generated frame uses canonical headers; the shipped CSV does not.

    Scanning only the generated form is how "Program Name" slipped through.
    """
    from pathlib import Path

    csv = Path(__file__).resolve().parents[1] / "sample_data" / "housing_program_flawed.csv"
    if not csv.exists():  # pragma: no cover - sample data is generated on demand
        pytest.skip("sample data not generated")
    assert pii_warnings(pd.read_csv(csv, dtype=str)) == []


def test_client_and_household_ids_are_not_flagged():
    """Pseudonymous IDs are the design; they must never be reported."""
    df = pd.DataFrame({"client_id": ["C-1001", "C-1002"], "household_id": ["H-1001", "H-1002"]})
    assert scan_dataframe_for_pii(df) == []


# -- Reporting behaviour -----------------------------------------------------


# -- Reaches the pipeline ----------------------------------------------------


def test_unmapped_identifier_columns_are_still_scanned(profile, clean_df):
    """The regression that end-to-end testing caught.

    Header mapping drops columns the profile does not know about, and a stray
    name or SSN column is unmapped by definition. Scanning after the drop would
    never see the very thing this exists to catch.
    """
    from grant_assistant.ingestion import prepare_dataset

    df = clean_df.copy()
    df["Client Name"] = "Jane Doe"
    df["SSN"] = "123-45-6789"
    prepared = prepare_dataset(df, profile)

    assert "Client Name" in prepared.unmapped_source_columns
    assert "Client Name" not in prepared.raw.columns
    kinds = " ".join(prepared.pii_warnings)
    assert "Client Name" in kinds
    assert "SSN" in kinds


def test_audit_result_carries_the_warnings(profile, clean_df):
    from grant_assistant.audit import run_audit
    from grant_assistant.ingestion import prepare_dataset

    df = clean_df.copy()
    df["client_email"] = "a@b.com"
    audit = run_audit(prepare_dataset(df, profile), profile)
    assert any("client_email" in w for w in audit.pii_warnings)
    # Advisory only: an identifier column must not change the score.
    clean_audit = run_audit(prepare_dataset(clean_df, profile), profile)
    assert audit.overall_score == clean_audit.overall_score


def test_payload_is_never_echoed_back():
    df = pd.DataFrame({"ssn": ["123-45-6789"] * 3})
    joined = " ".join(pii_warnings(df))
    assert "123-45-6789" not in joined
    assert "ssn" in joined


def test_limit_caps_the_number_of_findings():
    df = pd.DataFrame({f"name_{i}": ["x"] for i in range(30)})
    assert len(scan_dataframe_for_pii(df, limit=5)) == 5


def test_a_column_is_reported_once():
    """A column named 'email' holding emails is one finding, not two."""
    df = pd.DataFrame({"email": ["a@b.com", "c@d.org"]})
    assert len(scan_dataframe_for_pii(df)) == 1
