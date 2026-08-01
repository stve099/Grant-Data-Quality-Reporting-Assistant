"""Synthetic data generation tests."""

from __future__ import annotations

from grant_assistant.datagen import generate_clean_dataset, inject_issues, write_sample_files
from grant_assistant.datagen.generator import PROGRAMS, H


def test_clean_dataset_shape_and_columns(clean_df):
    assert len(clean_df) == 180
    assert list(clean_df.columns) == list(H.values())
    assert set(clean_df[H["program"]].unique()) <= set(PROGRAMS)


def test_generation_is_reproducible():
    a = generate_clean_dataset(n_clients=50, seed=99)
    b = generate_clean_dataset(n_clients=50, seed=99)
    assert a.equals(b)


def test_different_seeds_differ():
    a = generate_clean_dataset(n_clients=50, seed=1)
    b = generate_clean_dataset(n_clients=50, seed=2)
    assert not a.equals(b)


def test_injection_is_reproducible(clean_df):
    a_df, a_manifest = inject_issues(clean_df, seed=5)
    b_df, b_manifest = inject_issues(clean_df, seed=5)
    assert a_df.equals(b_df)
    assert a_manifest == b_manifest


def test_manifest_covers_expected_rule_families(flawed):
    _, manifest = flawed
    all_rules = {rule for entry in manifest for rule in entry["expected_rules"]}
    expected_families = {
        "DQ-001",
        "DQ-003",
        "DQ-004",
        "DQ-005",
        "DQ-010",
        "DQ-020",
        "DQ-022",
        "DQ-023",
        "DQ-024",
        "DQ-025",
        "DQ-026",
        "DQ-027",
        "DQ-028",
        "DQ-030",
        "DQ-031",
        "DQ-032",
        "DQ-033",
        "DQ-040",
        "DQ-041",
        "DQ-050",
        "DQ-051",
        "DQ-052",
        "DQ-060",
        "DQ-061",
    }
    assert expected_families <= all_rules


def test_manifest_rows_are_valid(flawed):
    flawed_df, manifest = flawed
    for entry in manifest:
        assert entry["rows"], entry["description"]
        for row in entry["rows"]:
            assert 1 <= row <= len(flawed_df)


def test_write_sample_files(tmp_path):
    paths = write_sample_files(tmp_path, seed=3)
    for name in (
        "housing_program_clean.csv",
        "housing_program_clean.xlsx",
        "housing_program_flawed.csv",
        "housing_program_flawed.xlsx",
        "issues_manifest.json",
        "ISSUES_MANIFEST.md",
    ):
        assert paths[name].exists(), name
        assert paths[name].stat().st_size > 0


def test_no_real_pii_fields(clean_df):
    # Synthetic data must not include name/SSN/DOB-style fields.
    lowered = {c.lower() for c in clean_df.columns}
    for banned in (
        "first name",
        "last name",
        "ssn",
        "social",
        "birth",
        "dob",
        "phone",
        "email",
        "address",
    ):
        assert not any(banned in col for col in lowered), banned
