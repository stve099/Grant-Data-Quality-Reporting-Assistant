"""Record-level diff between two extracts.

"The rate fell 4 points" is answered by compare_analytics. "Which records
moved?" is this. The matching rule — client ID — has consequences worth pinning,
because a re-keyed export must look like churn rather than silently pairing the
wrong rows.
"""

from __future__ import annotations

import pytest

from grant_assistant.analytics import diff_records
from grant_assistant.ingestion import prepare_dataset
from tests.conftest import VALID_ACTIVE, make_row, make_source_df


@pytest.fixture()
def rows() -> list[dict]:
    return [
        make_row(VALID_ACTIVE, client_id="C-1", household_id="H-1"),
        make_row(VALID_ACTIVE, client_id="C-2", household_id="H-2"),
        make_row(VALID_ACTIVE, client_id="C-3", household_id="H-3"),
    ]


def _prepared(rows: list[dict], profile):
    return prepare_dataset(make_source_df(rows), profile)


# -- Nothing changed ---------------------------------------------------------


def test_identical_extracts_report_no_differences(rows, profile):
    data = _prepared(rows, profile)
    diff = diff_records(data, data)

    assert diff.total_differences == 0
    assert diff.unchanged_count == len(rows)
    assert diff.changed == []


# -- Membership --------------------------------------------------------------


def test_a_new_client_is_reported_as_added(rows, profile):
    current = _prepared(
        [*rows, make_row(VALID_ACTIVE, client_id="C-4", household_id="H-4")], profile
    )
    diff = diff_records(current, _prepared(rows, profile))

    assert diff.added == ["C-4"]
    assert diff.removed == []


def test_a_departed_client_is_reported_as_removed(rows, profile):
    diff = diff_records(_prepared(rows[:-1], profile), _prepared(rows, profile))
    assert diff.removed == ["C-3"]
    assert diff.added == []


def test_a_rekeyed_export_looks_like_full_churn(rows, profile):
    """A consequence of matching on client ID, and it must be visible.

    If every ID changes, every client reads as removed and a new set added.
    That is the honest report — silently pairing rows by position would be a
    guess, and a wrong one.
    """
    rekeyed = [dict(row) for row in rows]
    from grant_assistant.datagen.generator import H

    for index, row in enumerate(rekeyed):
        row[H["client_id"]] = f"NEW-{index}"

    diff = diff_records(_prepared(rekeyed, profile), _prepared(rows, profile))
    assert len(diff.added) == len(rows)
    assert len(diff.removed) == len(rows)
    assert diff.unchanged_count == 0


# -- Field changes -----------------------------------------------------------


def test_a_changed_field_is_reported_with_both_values(rows, profile):
    from grant_assistant.datagen.generator import H

    changed = [dict(row) for row in rows]
    changed[0][H["exit_destination"]] = "Homeownership"

    diff = diff_records(_prepared(changed, profile), _prepared(rows, profile))
    assert len(diff.changed) == 1
    change = diff.changed[0]
    assert change.client_id == "C-1"
    assert change.field_name == "exit_destination"
    assert change.after == "Homeownership"
    assert diff.changed_clients == ["C-1"]


def test_changes_by_field_ranks_the_commonest(rows, profile):
    """One field dominating points at a systematic export difference."""
    from grant_assistant.datagen.generator import H

    changed = [dict(row) for row in rows]
    for row in changed:
        row[H["exit_destination"]] = "Homeownership"
    changed[0][H["gender"]] = "Male"

    diff = diff_records(_prepared(changed, profile), _prepared(rows, profile))
    by_field = diff.changes_by_field()
    assert next(iter(by_field)) == "exit_destination"
    assert by_field["exit_destination"] == 3
    assert by_field["gender"] == 1


def test_reformatting_counts_as_a_change(rows, profile):
    """Raw values are compared: a reformatted export is a real difference."""
    from grant_assistant.datagen.generator import H

    changed = [dict(row) for row in rows]
    changed[0][H["enrollment_date"]] = "08/01/2024"

    diff = diff_records(_prepared(changed, profile), _prepared(rows, profile))
    assert any(c.field_name == "enrollment_date" for c in diff.changed)


def test_the_comparison_can_be_limited_to_named_fields(rows, profile):
    from grant_assistant.datagen.generator import H

    changed = [dict(row) for row in rows]
    changed[0][H["exit_destination"]] = "Homeownership"
    changed[0][H["gender"]] = "Male"

    diff = diff_records(_prepared(changed, profile), _prepared(rows, profile), fields=["gender"])
    assert [c.field_name for c in diff.changed] == ["gender"]


def test_columns_present_in_only_one_extract_are_not_a_change(rows, profile):
    """A schema difference is not a data difference for every client."""
    current_rows = [dict(row) for row in rows]
    for row in current_rows:
        row["Some New Column"] = "x"

    diff = diff_records(_prepared(current_rows, profile), _prepared(rows, profile))
    assert diff.changed == []
    assert diff.unchanged_count == len(rows)


# -- Output ------------------------------------------------------------------


def test_frame_has_a_row_per_change(rows, profile):
    from grant_assistant.datagen.generator import H

    changed = [dict(row) for row in rows]
    changed[0][H["exit_destination"]] = "Homeownership"

    frame = diff_records(_prepared(changed, profile), _prepared(rows, profile)).to_frame()
    assert list(frame.columns) == ["Client ID", "Field", "Before", "After"]
    assert len(frame) == 1


def test_frame_is_empty_but_well_formed_without_changes(rows, profile):
    data = _prepared(rows, profile)
    frame = diff_records(data, data).to_frame()
    assert frame.empty
    assert list(frame.columns) == ["Client ID", "Field", "Before", "After"]


def test_summary_states_added_removed_and_changed(rows, profile):
    diff = diff_records(_prepared(rows[:-1], profile), _prepared(rows, profile))
    text = " ".join(diff.summary_lines())
    assert "removed" in text
    assert "identical" in text


def test_duplicate_client_rows_use_the_first(profile):
    """Which row is authoritative is the audit's question (DQ-010), not this one."""
    rows = [
        make_row(VALID_ACTIVE, client_id="C-1", household_id="H-1"),
        make_row(VALID_ACTIVE, client_id="C-1", household_id="H-9"),
    ]
    data = prepare_dataset(make_source_df(rows), profile)
    diff = diff_records(data, data)
    assert diff.unchanged_count == 1


def test_blank_client_ids_are_skipped(profile):
    rows = [
        make_row(VALID_ACTIVE, client_id="", household_id="H-1"),
        make_row(VALID_ACTIVE, client_id="C-2", household_id="H-2"),
    ]
    data = prepare_dataset(make_source_df(rows), profile)
    diff = diff_records(data, data)
    # A row with no client id cannot be matched to anything, so it is skipped
    # rather than becoming a client named "nan".
    assert diff.unchanged_count == 1
