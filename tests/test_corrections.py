"""Correction round-trip tests.

The round trip only earns trust if applying a worksheet is safe. Writing a
correction to the wrong row would corrupt data silently and be far worse than
refusing, so the mismatch cases carry as much weight here as the happy path.
"""

from __future__ import annotations

import pandas as pd
import pytest

from grant_assistant.audit import run_audit
from grant_assistant.corrections import (
    CLEAR_TOKEN,
    SHEET_NAME,
    WORKSHEET_COLUMNS,
    Correction,
    apply_corrections,
    build_worksheet,
    read_worksheet,
    write_worksheet,
)
from grant_assistant.corrections.worksheet import (
    CLIENT_ID,
    CORRECTED_VALUE,
    FIELD,
    ROW,
)
from grant_assistant.ingestion import prepare_dataset


@pytest.fixture()
def flawed_source(flawed) -> pd.DataFrame:
    return flawed[0].copy()


# -- Building ----------------------------------------------------------------


def test_worksheet_has_one_row_per_correctable_record(audit_flawed):
    frame = build_worksheet(audit_flawed)
    assert not frame.empty
    assert list(frame.columns) == WORKSHEET_COLUMNS
    expected = sum(1 for i in audit_flawed.issues for r in i.records if r.field)
    assert len(frame) == expected


def test_dataset_level_findings_are_excluded(audit_flawed):
    """A finding with no field has no cell to correct."""
    frame = build_worksheet(audit_flawed)
    assert (frame["Field"].astype(str).str.strip() != "").all()


def test_corrected_value_starts_empty(audit_flawed):
    frame = build_worksheet(audit_flawed)
    assert (frame[CORRECTED_VALUE] == "").all()


def test_blocking_issues_are_marked(audit_flawed):
    frame = build_worksheet(audit_flawed)
    blocking_rules = {i.rule_id for i in audit_flawed.issues if i.blocking}
    if blocking_rules:
        marked = set(frame.loc[frame["Blocking"] == "Yes", "Rule"])
        assert marked <= blocking_rules


# -- Writing and reading -----------------------------------------------------


def test_write_then_read_round_trips(audit_flawed, tmp_path):
    path = write_worksheet(audit_flawed, tmp_path / "corrections.xlsx")
    assert path.exists()
    frame = pd.read_excel(path, sheet_name=SHEET_NAME, dtype=str)
    assert list(frame.columns) == WORKSHEET_COLUMNS
    # Nothing filled in yet, so nothing to apply.
    assert read_worksheet(path) == []


def test_blank_rows_are_ignored(audit_flawed, tmp_path):
    path = write_worksheet(audit_flawed, tmp_path / "c.xlsx")
    frame = pd.read_excel(path, sheet_name=SHEET_NAME, dtype=str)
    frame.loc[0, CORRECTED_VALUE] = "Rental by client, no subsidy"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name=SHEET_NAME, index=False)

    corrections = read_worksheet(path)
    assert len(corrections) == 1
    assert corrections[0].corrected_value == "Rental by client, no subsidy"


def test_reading_a_file_that_is_not_a_worksheet_is_a_clear_error(tmp_path):
    path = tmp_path / "wrong.csv"
    pd.DataFrame({"a": [1]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="not a correction worksheet"):
        read_worksheet(path)


def test_csv_worksheets_are_accepted(tmp_path):
    path = tmp_path / "c.csv"
    pd.DataFrame(
        [{ROW: "3", CLIENT_ID: "C-1003", FIELD: "exit_destination", CORRECTED_VALUE: "Fixed"}]
    ).to_csv(path, index=False)
    assert read_worksheet(path)[0].row == 3


# -- Applying ----------------------------------------------------------------


def test_correction_is_written_to_the_right_cell(flawed_source, profile):
    prepared = prepare_dataset(flawed_source, profile)
    client = str(flawed_source.iloc[4]["Client ID"])
    correction = Correction(
        row=5, client_id=client, field_name="exit_destination", corrected_value="Fixed value"
    )
    corrected, report = apply_corrections(flawed_source, [correction], prepared)

    assert report.applied == 1
    assert not report.skipped
    assert corrected.iloc[4]["Exit Destination"] == "Fixed value"
    # The original frame is untouched.
    assert flawed_source.iloc[4]["Exit Destination"] != "Fixed value"


def test_clear_token_empties_a_field(flawed_source, profile):
    prepared = prepare_dataset(flawed_source, profile)
    client = str(flawed_source.iloc[2]["Client ID"])
    correction = Correction(
        row=3, client_id=client, field_name="exit_destination", corrected_value=CLEAR_TOKEN
    )
    corrected, report = apply_corrections(flawed_source, [correction], prepared)
    assert report.applied == 1
    assert corrected.iloc[2]["Exit Destination"] == ""


def test_client_mismatch_is_refused(flawed_source, profile):
    """The safety property: never write to a row the worksheet did not mean."""
    prepared = prepare_dataset(flawed_source, profile)
    correction = Correction(
        row=5, client_id="C-DOES-NOT-MATCH", field_name="exit_destination", corrected_value="X"
    )
    corrected, report = apply_corrections(flawed_source, [correction], prepared)

    assert report.applied == 0
    assert len(report.skipped) == 1
    assert "does not match" in report.skipped[0]
    assert corrected.equals(flawed_source)


def test_row_outside_the_data_is_refused(flawed_source, profile):
    prepared = prepare_dataset(flawed_source, profile)
    correction = Correction(
        row=len(flawed_source) + 50,
        client_id="",
        field_name="exit_destination",
        corrected_value="X",
    )
    _, report = apply_corrections(flawed_source, [correction], prepared)
    assert report.applied == 0
    assert "outside the data" in report.skipped[0]


def test_unknown_field_is_refused(flawed_source, profile):
    prepared = prepare_dataset(flawed_source, profile)
    client = str(flawed_source.iloc[0]["Client ID"])
    correction = Correction(row=1, client_id=client, field_name="not_a_field", corrected_value="X")
    _, report = apply_corrections(flawed_source, [correction], prepared)
    assert report.applied == 0
    assert "no column for field" in report.skipped[0]


def test_a_partly_valid_worksheet_applies_what_it_can(flawed_source, profile):
    prepared = prepare_dataset(flawed_source, profile)
    good = Correction(
        row=1,
        client_id=str(flawed_source.iloc[0]["Client ID"]),
        field_name="exit_destination",
        corrected_value="Good",
    )
    bad = Correction(
        row=2, client_id="C-WRONG", field_name="exit_destination", corrected_value="Bad"
    )
    _, report = apply_corrections(flawed_source, [good, bad], prepared)
    assert report.applied == 1
    assert len(report.skipped) == 1
    assert report.total_requested == 2


# -- The point of the whole thing --------------------------------------------


def test_applying_real_corrections_improves_the_audit(flawed_source, profile):
    """Fixing what the worksheet flags must actually clear the findings."""
    prepared = prepare_dataset(flawed_source, profile)
    audit = run_audit(prepared, profile)
    frame = build_worksheet(audit)

    missing_dest = frame[frame["Field"] == "exit_destination"]
    if missing_dest.empty:
        pytest.skip("sample has no exit-destination findings")

    corrections = [
        Correction(
            row=int(record[ROW]),
            client_id=str(record[CLIENT_ID]),
            field_name="exit_destination",
            corrected_value="Rental by client, no ongoing subsidy",
        )
        for _, record in missing_dest.iterrows()
    ]
    corrected, report = apply_corrections(flawed_source, corrections, prepared)
    assert report.applied > 0

    after = run_audit(prepare_dataset(corrected, profile), profile)
    before_dest = sum(
        i.record_count for i in audit.issues if "destination" in i.rule_name.casefold()
    )
    after_dest = sum(
        i.record_count for i in after.issues if "destination" in i.rule_name.casefold()
    )
    assert after_dest < before_dest
    assert after.overall_score >= audit.overall_score
