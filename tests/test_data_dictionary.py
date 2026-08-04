"""Data dictionary tests.

The document's whole value is that it cannot drift from what the engine
enforces, so the tests check that it reflects the profile and rule registry
rather than that it contains particular prose.
"""

from __future__ import annotations

import pytest

from grant_assistant.audit import list_rules
from grant_assistant.reporting import build_data_dictionary, write_data_dictionary


@pytest.fixture(scope="module")
def dictionary(profile) -> str:
    return build_data_dictionary(profile)


def test_every_mapped_column_is_documented(dictionary, profile):
    for source_header in profile.field_mappings:
        assert source_header in dictionary, source_header


def test_required_fields_are_marked(dictionary, profile):
    """A producer needs to know which columns cannot be omitted."""
    assert "Required" in dictionary
    for canonical in profile.required_fields:
        assert canonical in dictionary, canonical


def test_controlled_vocabularies_are_listed(dictionary, profile):
    for values in profile.controlled_values.values():
        for value in values:
            assert value in dictionary, value


def test_every_program_and_alias_appears(dictionary, profile):
    for program in profile.programs:
        assert program.name in dictionary
        for alias in program.aliases:
            assert alias in dictionary, alias


def test_every_performance_measure_appears(dictionary, profile):
    for measure in profile.performance_measures:
        assert measure.id in dictionary
        assert measure.name in dictionary


def test_every_audit_rule_appears(dictionary):
    """The handout must list what will actually be checked."""
    for meta in list_rules():
        assert meta.rule_id in dictionary, meta.rule_id


def test_blocking_rules_are_marked(dictionary, profile):
    assert "Blocking" in dictionary
    for rule_id in profile.blocking_rules:
        assert rule_id in dictionary


def test_followup_schedule_is_documented(dictionary, profile):
    for followup in profile.followup_schedule:
        assert followup.label in dictionary
        assert str(followup.months_after_exit) in dictionary


def test_successful_exit_categories_are_identified(dictionary, profile):
    assert "successful" in dictionary.casefold()
    for category in profile.exit_destination_categories:
        assert category.replace("_", " ").title() in dictionary


def test_severity_overrides_win_over_registry_defaults(profile):
    """The handout must show the severity this profile actually applies."""
    if not profile.severity_overrides:
        pytest.skip("profile defines no overrides")
    text = build_data_dictionary(profile)
    for rule_id, severity in profile.severity_overrides.items():
        line = next((r for r in text.splitlines() if r.startswith(f"| {rule_id} ")), None)
        assert line is not None
        assert severity.label in line


# -- Output formats ----------------------------------------------------------


def test_markdown_is_written(profile, tmp_path):
    path = write_data_dictionary(profile, tmp_path / "dd.md")
    assert path.read_text(encoding="utf-8").startswith("# ")


def test_html_is_self_contained(profile, tmp_path):
    path = write_data_dictionary(profile, tmp_path / "dd.html")
    html = path.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<table>" in html
    # No external requests: the handout has to open from an email attachment.
    assert "http://" not in html and "https://" not in html


def test_html_escapes_profile_text(profile, tmp_path):
    """Profile text is authored by users and must not become markup."""
    hostile = profile.model_copy(update={"grant_name": "A <script>alert(1)</script> Grant"})
    html = write_data_dictionary(hostile, tmp_path / "x.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_second_profile_renders(rrh_profile):
    """Nothing may be hardcoded to the housing profile."""
    text = build_data_dictionary(rrh_profile)
    assert rrh_profile.grant_name in text
    assert rrh_profile.profile_id in text
