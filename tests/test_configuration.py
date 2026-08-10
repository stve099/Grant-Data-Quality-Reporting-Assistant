"""Configuration loading and validation tests."""

from __future__ import annotations

import pytest
import yaml

from grant_assistant.configuration import (
    ProfileValidationError,
    list_profiles,
    load_profile,
    load_profile_file,
)
from tests.conftest import CONFIG_DIR


def test_list_profiles_finds_both_examples():
    profiles = list_profiles(CONFIG_DIR)
    assert {"housing_stability", "rapid_rehousing"} <= set(profiles)


def test_load_profile_by_id(profile):
    assert profile.profile_id == "housing_stability"
    assert profile.grant_name == "Stable Homes Grant"
    assert len(profile.programs) == 3
    assert profile.reporting_period.start.year == 2024


def test_unknown_profile_id_lists_available():
    with pytest.raises(ProfileValidationError, match="housing_stability"):
        load_profile("does_not_exist", CONFIG_DIR)


def test_program_alias_map_is_case_insensitive(profile):
    aliases = profile.program_alias_map()
    assert aliases["rrh"] == "Rapid Re-Housing"
    assert aliases["rapid rehousing"] == "Rapid Re-Housing"
    assert aliases["shelter"] == "Emergency Shelter"


def test_destination_category_lookup(profile):
    assert profile.destination_category("Rental by client, no subsidy") == "permanent_housing"
    assert profile.destination_category("HOMEOWNERSHIP") == "permanent_housing"
    assert profile.destination_category("Transitional housing") == "temporary_housing"
    assert profile.destination_category("Mystery destination") is None


def test_successful_destinations_follow_categories(rrh_profile):
    # rapid_rehousing counts temporary housing as successful too
    assert "Transitional housing" in rrh_profile.successful_destinations


def _base_profile_dict() -> dict:
    return yaml.safe_load((CONFIG_DIR / "housing_stability.yaml").read_text(encoding="utf-8"))


def _write_profile(tmp_path, data: dict):
    path = tmp_path / "test_profile.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_invalid_yaml_raises(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("grant_name: [unclosed", encoding="utf-8")
    with pytest.raises(ProfileValidationError, match="not valid YAML"):
        load_profile_file(path)


def test_missing_file_raises():
    with pytest.raises(ProfileValidationError, match="not found"):
        load_profile_file("nope/never.yaml")


def test_period_end_before_start_rejected(tmp_path):
    data = _base_profile_dict()
    data["reporting_period"] = {"start": "2025-06-30", "end": "2024-07-01"}
    with pytest.raises(ProfileValidationError, match="before"):
        load_profile_file(_write_profile(tmp_path, data))


def test_unknown_canonical_mapping_target_rejected(tmp_path):
    data = _base_profile_dict()
    data["field_mappings"]["Bad Column"] = "not_a_canonical_field"
    with pytest.raises(ProfileValidationError, match="not_a_canonical_field"):
        load_profile_file(_write_profile(tmp_path, data))


def test_unknown_required_field_rejected(tmp_path):
    data = _base_profile_dict()
    data["required_fields"].append("shoe_size")
    with pytest.raises(ProfileValidationError, match="shoe_size"):
        load_profile_file(_write_profile(tmp_path, data))


def test_undefined_successful_category_rejected(tmp_path):
    data = _base_profile_dict()
    data["successful_exit_categories"] = ["nonexistent_category"]
    with pytest.raises(ProfileValidationError, match="nonexistent_category"):
        load_profile_file(_write_profile(tmp_path, data))


def test_duplicate_measure_ids_rejected(tmp_path):
    data = _base_profile_dict()
    data["performance_measures"].append(dict(data["performance_measures"][0]))
    with pytest.raises(ProfileValidationError, match="duplicate"):
        load_profile_file(_write_profile(tmp_path, data))


def test_bad_followup_completion_field_rejected(tmp_path):
    data = _base_profile_dict()
    data["followup_schedule"][0]["completion_field"] = "gender"
    with pytest.raises(ProfileValidationError, match="gender"):
        load_profile_file(_write_profile(tmp_path, data))
