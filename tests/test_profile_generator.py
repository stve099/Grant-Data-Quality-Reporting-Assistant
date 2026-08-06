"""Profile generator tests.

A generator that emits a confident-looking wrong profile costs more time than
writing one by hand, so the tests care as much about what it refuses to assume
as about what it infers.
"""

from __future__ import annotations

import pandas as pd
import pytest
import yaml

from grant_assistant.configuration.generator import (
    CONFIDENT_THRESHOLD,
    draft_profile,
    draft_to_yaml,
)


@pytest.fixture()
def sample_extract() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Client ID": ["C-1", "C-2", "C-3"],
            "Household ID": ["H-1", "H-1", "H-2"],
            "Program Name": ["Shelter", "Rapid Re-Housing", "Shelter"],
            "Entry Date": ["2024-08-01", "2024-09-15", "2025-01-10"],
            "Exit Date": ["2025-02-01", "", "2025-03-01"],
            "Enrollment Status": ["Exited", "Active", "Exited"],
            "Gender": ["Female", "Male", "Declined"],
            "Some Agency Field": ["x", "y", "z"],
        }
    )


# -- Mapping -----------------------------------------------------------------


def test_obvious_headers_map_confidently(sample_extract):
    draft = draft_profile(sample_extract)
    mapped = {g.source_header: g.canonical for g in draft.confident}
    assert mapped["Client ID"] == "client_id"
    assert mapped["Household ID"] == "household_id"
    assert mapped["Enrollment Status"] == "enrollment_status"


def test_domain_synonyms_are_recognized(sample_extract):
    """ "Entry Date" is enrollment_date; no similarity measure would say so."""
    draft = draft_profile(sample_extract)
    mapped = {g.source_header: g.canonical for g in draft.mappings}
    assert mapped["Entry Date"] == "enrollment_date"
    assert mapped["Exit Date"] == "exit_date"
    assert mapped["Program Name"] == "program"


def test_unrecognized_columns_are_reported_not_guessed(sample_extract):
    draft = draft_profile(sample_extract)
    assert "Some Agency Field" in draft.unmapped_headers


def test_two_headers_cannot_claim_one_field():
    """The weaker guess is reported as unmapped rather than overwriting."""
    frame = pd.DataFrame({"client_id": ["C-1"], "Client Identifier": ["C-1"]})
    draft = draft_profile(frame)
    canonicals = [g.canonical for g in draft.mappings]
    assert canonicals.count("client_id") == 1
    assert len(draft.unmapped_headers) == 1


def test_missing_required_fields_are_flagged():
    frame = pd.DataFrame({"Gender": ["Female"]})
    draft = draft_profile(frame)
    assert "client_id" in draft.missing_required
    assert "program" in draft.missing_required


def test_confidence_threshold_separates_certain_from_uncertain(sample_extract):
    draft = draft_profile(sample_extract)
    assert all(g.confidence >= CONFIDENT_THRESHOLD for g in draft.confident)
    assert all(g.confidence < CONFIDENT_THRESHOLD for g in draft.uncertain)


# -- Reading the data --------------------------------------------------------


def test_programs_are_read_from_the_data(sample_extract):
    draft = draft_profile(sample_extract)
    assert draft.programs == ["Rapid Re-Housing", "Shelter"]


def test_controlled_values_are_transcribed(sample_extract):
    draft = draft_profile(sample_extract)
    assert draft.vocabularies["gender"] == ["Declined", "Female", "Male"]


def test_free_text_columns_do_not_become_vocabularies():
    """Beyond a handful of distinct values it is not a controlled list."""
    frame = pd.DataFrame(
        {
            "Client ID": [f"C-{i}" for i in range(60)],
            "Exit Destination": [f"Destination {i}" for i in range(60)],
        }
    )
    draft = draft_profile(frame)
    assert "exit_destination" not in draft.vocabularies


def test_reporting_period_is_inferred_from_dates(sample_extract):
    draft = draft_profile(sample_extract)
    assert draft.period_start == "2024-08-01"
    assert draft.period_end == "2025-03-01"


def test_no_dates_leaves_the_period_empty():
    draft = draft_profile(pd.DataFrame({"Client ID": ["C-1"]}))
    assert draft.period_start == ""


# -- The YAML ----------------------------------------------------------------


def test_yaml_parses(sample_extract):
    text = draft_to_yaml(draft_profile(sample_extract, profile_id="test_grant"))
    parsed = yaml.safe_load(text)
    assert parsed["profile_id"] == "test_grant"
    assert parsed["field_mappings"]["Client ID"] == "client_id"


def test_uncertain_mappings_are_commented_out_not_applied():
    """A guess must not become a silent mapping."""
    frame = pd.DataFrame({"Client ID": ["C-1"], "Hshld Sz": [2]})
    draft = draft_profile(frame)
    text = draft_to_yaml(draft)
    parsed = yaml.safe_load(text)
    for guess in draft.uncertain:
        assert guess.source_header not in parsed["field_mappings"]
        assert f"# {guess.source_header}" in text or f'# "{guess.source_header}"' in text


def test_yaml_warns_about_missing_required_fields():
    text = draft_to_yaml(draft_profile(pd.DataFrame({"Gender": ["Female"]})))
    assert "WARNING" in text
    assert "client_id" in text


def test_yaml_lists_unmapped_columns(sample_extract):
    """Nothing is dropped without saying so."""
    text = draft_to_yaml(draft_profile(sample_extract))
    assert "Some Agency Field" in text


def test_yaml_says_it_is_a_draft(sample_extract):
    text = draft_to_yaml(draft_profile(sample_extract))
    assert "not a finished profile" in text
    assert "validate-config" in text


def test_measures_are_left_empty_rather_than_invented(sample_extract):
    """Targets come from the funder and cannot be read off a data file."""
    parsed = yaml.safe_load(draft_to_yaml(draft_profile(sample_extract)))
    assert parsed["performance_measures"] == []
    assert parsed["followup_schedule"] == []


def test_real_sample_data_maps_cleanly(clean_df):
    """The shipped extract should map with no uncertain guesses at all."""
    draft = draft_profile(clean_df)
    assert not draft.missing_required
    assert draft.programs
