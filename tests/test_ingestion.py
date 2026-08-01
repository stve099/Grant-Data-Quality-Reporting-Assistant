"""CSV/Excel ingestion, field mapping, and normalization tests."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from grant_assistant import schema
from grant_assistant.ingestion import IngestionError, load_dataset, prepare_dataset
from tests.conftest import VALID_ACTIVE, VALID_EXITED, make_row, make_source_df


def test_load_csv_from_path(tmp_path, clean_df):
    path = tmp_path / "data.csv"
    clean_df.to_csv(path, index=False)
    loaded = load_dataset(path)
    assert len(loaded) == len(clean_df)
    assert "Client ID" in loaded.columns


def test_load_excel_from_path(tmp_path, clean_df):
    path = tmp_path / "data.xlsx"
    clean_df.to_excel(path, index=False)
    loaded = load_dataset(path)
    assert len(loaded) == len(clean_df)


def test_load_csv_from_buffer_like_streamlit_upload(clean_df):
    buffer = io.BytesIO(clean_df.to_csv(index=False).encode("utf-8"))
    loaded = load_dataset(buffer, filename="upload.csv")
    assert len(loaded) == len(clean_df)


def test_load_excel_from_buffer(clean_df):
    buffer = io.BytesIO()
    clean_df.to_excel(buffer, index=False)
    buffer.seek(0)
    loaded = load_dataset(buffer, filename="upload.xlsx")
    assert len(loaded) == len(clean_df)


def test_buffer_without_filename_rejected(clean_df):
    with pytest.raises(IngestionError, match="filename"):
        load_dataset(io.BytesIO(b"a,b\n1,2\n"))


def test_unsupported_extension_rejected(tmp_path):
    path = tmp_path / "data.parquet"
    path.write_bytes(b"xx")
    with pytest.raises(IngestionError, match="Unsupported file type"):
        load_dataset(path)


def test_missing_file_rejected():
    with pytest.raises(IngestionError, match="not found"):
        load_dataset("no/such/file.csv")


def test_empty_file_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("Client ID,Program Name\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="no data rows"):
        load_dataset(path)


def test_field_mapping_produces_canonical_columns(prepared_clean):
    for col in schema.CANONICAL_COLUMNS:
        assert col in prepared_clean.df.columns
    assert not prepared_clean.missing_canonical_columns
    assert not prepared_clean.unmapped_source_columns


def test_field_mapping_is_header_case_insensitive(profile):
    df = make_source_df([dict(VALID_ACTIVE)])
    df.columns = [c.upper() for c in df.columns]
    prepared = prepare_dataset(df, profile)
    assert prepared.df.loc[0, schema.CLIENT_ID] == "C-1"


def test_missing_client_id_mapping_is_fatal(profile):
    df = pd.DataFrame({"Some Column": ["x"], "Another": ["y"]})
    with pytest.raises(IngestionError, match="client_id"):
        prepare_dataset(df, profile)


def test_dates_and_numbers_are_coerced(profile):
    prepared = prepare_dataset(make_source_df([dict(VALID_EXITED)]), profile)
    assert prepared.df.loc[0, schema.EXIT_DATE] == pd.Timestamp("2025-01-15")
    assert prepared.df.loc[0, schema.EXIT_INCOME] == 900.0


def test_invalid_values_kept_in_raw_but_nan_in_df(profile):
    row = make_row(VALID_EXITED, exit_date="13/45/2025", entry_income="lots")
    prepared = prepare_dataset(make_source_df([row]), profile)
    assert pd.isna(prepared.df.loc[0, schema.EXIT_DATE])
    assert prepared.raw.loc[0, schema.EXIT_DATE] == "13/45/2025"
    assert pd.isna(prepared.df.loc[0, schema.ENTRY_INCOME])
    assert prepared.raw.loc[0, schema.ENTRY_INCOME] == "lots"


def test_program_aliases_normalized(profile):
    rows = [
        make_row(program="RRH", client_id="C-10"),
        make_row(program="rapid rehousing", client_id="C-11"),
        make_row(program="Emergency Shelter", client_id="C-12"),
    ]
    prepared = prepare_dataset(make_source_df(rows), profile)
    assert list(prepared.df[schema.PROGRAM]) == [
        "Rapid Re-Housing",
        "Rapid Re-Housing",
        "Emergency Shelter",
    ]
    assert prepared.df.loc[0, schema.PROGRAM_RAW] == "RRH"


def test_whitespace_trimmed_and_blanks_become_na(profile):
    rows = [make_row(client_id="  C-77  ", gender="   ")]
    prepared = prepare_dataset(make_source_df(rows), profile)
    assert prepared.df.loc[0, schema.CLIENT_ID] == "C-77"
    assert pd.isna(prepared.df.loc[0, schema.GENDER])


def test_missing_canonical_columns_created_and_reported(profile):
    df = pd.DataFrame({"Client ID": ["C-1"], "Program Name": ["Rapid Re-Housing"]})
    prepared = prepare_dataset(df, profile)
    assert schema.EXIT_DATE in prepared.df.columns
    assert schema.AGE in prepared.missing_canonical_columns
