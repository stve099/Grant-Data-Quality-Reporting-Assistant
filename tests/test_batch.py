"""Batch audit tests.

The property that matters is resilience: one unreadable file must not cost the
other eleven, and the rollup must never quietly report totals that cover fewer
files than the user handed over.
"""

from __future__ import annotations

import pandas as pd
import pytest

from grant_assistant.batch import (
    batch_summary_lines,
    discover_datasets,
    run_batch,
    write_batch_summary,
)


@pytest.fixture()
def extracts(tmp_path, clean_df, flawed):
    """A folder holding one clean and one flawed extract."""
    clean_df.to_csv(tmp_path / "site_a.csv", index=False)
    flawed[0].to_csv(tmp_path / "site_b.csv", index=False)
    return tmp_path


# -- Discovery ---------------------------------------------------------------


def test_data_files_are_found_and_ordered(extracts):
    found = discover_datasets(extracts)
    assert [p.name for p in found] == ["site_a.csv", "site_b.csv"]


def test_non_data_files_are_ignored(extracts):
    (extracts / "notes.md").write_text("not data", encoding="utf-8")
    (extracts / "report.pdf").write_bytes(b"%PDF-")
    assert len(discover_datasets(extracts)) == 2


def test_excel_lock_files_are_skipped(extracts):
    """A user with a workbook open must not get a spurious failure."""
    (extracts / "~$site_a.xlsx").write_bytes(b"lock")
    assert all(not p.name.startswith("~$") for p in discover_datasets(extracts))


def test_a_pattern_narrows_the_set(extracts):
    assert [p.name for p in discover_datasets(extracts, "site_a*")] == ["site_a.csv"]


def test_a_missing_directory_is_a_clear_error(tmp_path):
    with pytest.raises(NotADirectoryError):
        discover_datasets(tmp_path / "nope")


# -- Running -----------------------------------------------------------------


def test_every_file_is_audited(extracts, profile):
    result = run_batch(discover_datasets(extracts), profile.profile_id)
    assert len(result.succeeded) == 2
    assert not result.failed
    assert all(e.rows > 0 for e in result.succeeded)


def test_one_bad_file_does_not_stop_the_batch(extracts, profile):
    """The eleven that parsed are still worth seeing."""
    (extracts / "broken.csv").write_text("this,is\nnot,a,valid\nextract\n", encoding="utf-8")
    result = run_batch(discover_datasets(extracts), profile.profile_id)

    assert len(result.succeeded) == 2
    assert len(result.failed) == 1
    assert result.failed[0].path.name == "broken.csv"
    assert result.failed[0].error


def test_failures_are_visible_in_the_rollup(extracts, profile):
    """A summary covering fewer files than given would be worse than none."""
    (extracts / "broken.csv").write_text("a\n1,2,3\n", encoding="utf-8")
    result = run_batch(discover_datasets(extracts), profile.profile_id)
    text = " ".join(batch_summary_lines(result))
    assert "could not be processed" in text


# -- Rollup ------------------------------------------------------------------


def test_score_is_weighted_by_rows():
    """A 5-row file must not swing the figure like a 5,000-row one."""
    from pathlib import Path

    from grant_assistant.batch import BatchEntry, BatchResult

    result = BatchResult(
        entries=[
            BatchEntry(path=Path("big.csv"), rows=5000, score=90.0),
            BatchEntry(path=Path("tiny.csv"), rows=5, score=10.0),
        ]
    )
    # A plain mean would say 50.0; weighting keeps the tiny file from dominating.
    assert result.weighted_score == 89.9


def test_totals_only_count_successful_files(extracts, profile):
    (extracts / "broken.csv").write_text("x\n", encoding="utf-8")
    result = run_batch(discover_datasets(extracts), profile.profile_id)
    assert result.total_rows == sum(e.rows for e in result.succeeded)


def test_worst_file_is_identified(extracts, profile):
    result = run_batch(discover_datasets(extracts), profile.profile_id)
    worst = result.worst
    assert worst is not None
    assert worst.score == min(e.score for e in result.succeeded)


def test_weighted_score_is_none_with_nothing_to_average():
    from grant_assistant.batch import BatchResult

    assert BatchResult().weighted_score is None
    assert BatchResult().worst is None


# -- Output ------------------------------------------------------------------


def test_summary_csv_lists_every_file(extracts, profile, tmp_path):
    result = run_batch(discover_datasets(extracts), profile.profile_id)
    path = write_batch_summary(result, tmp_path / "out" / "summary.csv")
    frame = pd.read_csv(path)
    assert len(frame) == 2
    assert set(frame["File"]) == {"site_a.csv", "site_b.csv"}
    assert (frame["Status"] == "OK").all()


def test_summary_excel_is_written(extracts, profile, tmp_path):
    result = run_batch(discover_datasets(extracts), profile.profile_id)
    path = write_batch_summary(result, tmp_path / "summary.xlsx")
    assert len(pd.read_excel(path)) == 2
