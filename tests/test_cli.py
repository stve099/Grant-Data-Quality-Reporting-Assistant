"""CLI command tests using Typer's test runner."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from grant_assistant.cli.main import app
from tests.conftest import CONFIG_DIR, REPO_ROOT

runner = CliRunner()

FLAWED = REPO_ROOT / "sample_data" / "housing_program_flawed.csv"
CLEAN = REPO_ROOT / "sample_data" / "housing_program_clean.csv"


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "audit",
        "analyze",
        "report",
        "ask",
        "insights",
        "full-run",
        "generate-sample-data",
        "validate-config",
    ):
        assert command in result.output


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "grant-assistant" in result.output


def test_rules_command_lists_rule_ids():
    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0
    assert "DQ-001" in result.output
    assert "DQ-050" in result.output


def test_validate_config_all_profiles():
    result = runner.invoke(app, ["validate-config", "--config-dir", str(CONFIG_DIR)])
    assert result.exit_code == 0
    assert "housing_stability" in result.output
    assert "rapid_rehousing" in result.output


def test_validate_config_reports_failure(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("profile_id: broken\ngrant_name: X\n", encoding="utf-8")
    result = runner.invoke(app, ["validate-config", str(bad)])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_audit_clean_exits_zero(tmp_path):
    result = runner.invoke(
        app,
        [
            "audit",
            str(CLEAN),
            "--profile",
            "housing_stability",
            "--config-dir",
            str(CONFIG_DIR),
            "--no-export",
        ],
    )
    assert result.exit_code == 0
    assert "100.0/100" in result.output


def test_audit_flawed_exits_nonzero_for_blocking(tmp_path):
    result = runner.invoke(
        app,
        [
            "audit",
            str(FLAWED),
            "--profile",
            "housing_stability",
            "--config-dir",
            str(CONFIG_DIR),
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1  # blocking issues present
    assert "DQ-010" in result.output
    assert (tmp_path / "audit_workbook.xlsx").exists()


def test_audit_missing_file_friendly_error():
    result = runner.invoke(app, ["audit", "nope.csv", "--config-dir", str(CONFIG_DIR)])
    assert result.exit_code == 2
    assert "Error" in result.output


def test_analyze_outputs_metrics(tmp_path):
    result = runner.invoke(
        app,
        [
            "analyze",
            str(FLAWED),
            "--profile",
            "housing_stability",
            "--config-dir",
            str(CONFIG_DIR),
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "Enrollments:" in result.output
    assert "Performance measures" in result.output
    assert (tmp_path / "analytics_summary.xlsx").exists()


def test_ask_works_without_api_key():
    result = runner.invoke(
        app,
        [
            "ask",
            str(FLAWED),
            "Which program had the highest successful exit rate?",
            "--config-dir",
            str(CONFIG_DIR),
        ],
    )
    assert result.exit_code == 0
    assert "Non-AI mode" in result.output


def test_insights_without_api_key():
    result = runner.invoke(
        app,
        ["insights", str(FLAWED), "--config-dir", str(CONFIG_DIR)],
    )
    assert result.exit_code == 0
    assert "Key Findings" in result.output


def test_report_generates_files(tmp_path):
    result = runner.invoke(
        app,
        [
            "report",
            str(FLAWED),
            "--profile",
            "rapid_rehousing",
            "--config-dir",
            str(CONFIG_DIR),
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "grant_report.html").exists()
    assert (tmp_path / "grant_report.docx").exists()
    assert (tmp_path / "audit_workbook.xlsx").exists()
    assert (tmp_path / "analytics_summary.xlsx").exists()


def test_generate_sample_data(tmp_path):
    result = runner.invoke(app, ["generate-sample-data", "--output", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "housing_program_clean.csv").exists()
    assert (tmp_path / "ISSUES_MANIFEST.md").exists()


# ---------------------------------------------------------------------------
# Wiring smoke tests
#
# The logic behind each command is tested in its own module. These exist to
# catch wiring: a stripped import, a symbol that does not exist, an option that
# never reaches the function. That is where these commands actually break, and
# no amount of module-level coverage sees it.
# ---------------------------------------------------------------------------


def _run(*args) -> object:
    result = runner.invoke(app, list(args))
    if result.exit_code not in (0, 1):  # 1 is a legitimate "findings present"
        raise AssertionError(
            f"{' '.join(str(a) for a in args)} exited {result.exit_code}\n"
            f"{result.output}\n{result.exception!r}"
        )
    return result


def test_every_command_is_listed_in_help():
    """A command nobody can discover may as well not exist."""
    output = runner.invoke(app, ["--help"]).output
    for command in (
        "batch",
        "history",
        "record-run",
        "draft-profile",
        "compare-models",
        "data-dictionary",
        "correction-worksheet",
        "apply-corrections",
        "compare",
        "eval",
    ):
        assert command in output, command


def test_data_dictionary_writes_markdown(tmp_path):
    out = tmp_path / "spec.md"
    result = _run("data-dictionary", "--output", str(out), "--config-dir", str(CONFIG_DIR))
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("# ")
    assert "Data dictionary" in result.output


def test_data_dictionary_writes_html(tmp_path):
    out = tmp_path / "spec.html"
    _run("data-dictionary", "--output", str(out), "--config-dir", str(CONFIG_DIR))
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_data_dictionary_rejects_an_unknown_profile(tmp_path):
    result = runner.invoke(
        app, ["data-dictionary", "--profile", "no_such_grant", "--output", str(tmp_path / "x.md")]
    )
    assert result.exit_code == 2


def test_correction_worksheet_and_apply_round_trip(tmp_path):
    sheet = tmp_path / "corrections.xlsx"
    result = _run(
        "correction-worksheet",
        str(FLAWED),
        "--output",
        str(sheet),
        "--config-dir",
        str(CONFIG_DIR),
    )
    assert sheet.exists()
    assert "record(s)" in result.output

    # Nothing filled in: applying is a reported no-op, not an error.
    applied = _run(
        "apply-corrections",
        str(FLAWED),
        str(sheet),
        "--output",
        str(tmp_path / "corrected.csv"),
        "--config-dir",
        str(CONFIG_DIR),
    )
    assert "Corrected Value" in applied.output


def test_apply_corrections_rejects_a_file_that_is_not_a_worksheet(tmp_path):
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("a,b\n1,2\n", encoding="utf-8")
    result = runner.invoke(app, ["apply-corrections", str(FLAWED), str(wrong)])
    assert result.exit_code == 2
    assert "not a correction worksheet" in result.output


def test_batch_audits_a_folder(tmp_path):
    import shutil

    folder = tmp_path / "extracts"
    folder.mkdir()
    shutil.copy(FLAWED, folder / "site_a.csv")
    shutil.copy(CLEAN, folder / "site_b.csv")
    out = tmp_path / "summary.csv"

    result = _run("batch", str(folder), "--output", str(out), "--config-dir", str(CONFIG_DIR))
    assert out.exists()
    assert "Weighted data quality score" in result.output
    assert "site_a.csv" in result.output


def test_batch_reports_a_file_it_could_not_read(tmp_path):
    import shutil

    folder = tmp_path / "extracts"
    folder.mkdir()
    shutil.copy(CLEAN, folder / "good.csv")
    (folder / "bad.csv").write_text("nonsense\n1\n", encoding="utf-8")

    result = runner.invoke(app, ["batch", str(folder), "--output", str(tmp_path / "s.csv")])
    assert result.exit_code == 1  # a failed file must not pass silently
    assert "could not be processed" in result.output


def test_batch_on_an_empty_folder_says_so(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["batch", str(empty)])
    assert result.exit_code == 1
    assert "No data files" in result.output


def test_record_run_then_history(tmp_path):
    db = tmp_path / "history.db"
    _run(
        "record-run", str(FLAWED), "--db", str(db), "--label", "Q1", "--config-dir", str(CONFIG_DIR)
    )
    _run(
        "record-run", str(CLEAN), "--db", str(db), "--label", "Q2", "--config-dir", str(CONFIG_DIR)
    )

    result = _run("history", "--db", str(db))
    assert "Q1" in result.output
    assert "Q2" in result.output
    assert "Overall change" in result.output


def test_history_reports_resolutions_and_aging(tmp_path):
    db = tmp_path / "history.db"
    _run(
        "record-run",
        str(FLAWED),
        "--db",
        str(db),
        "--label",
        "before",
        "--config-dir",
        str(CONFIG_DIR),
    )
    result = _run(
        "record-run",
        str(CLEAN),
        "--db",
        str(db),
        "--label",
        "after",
        "--config-dir",
        str(CONFIG_DIR),
    )
    assert "Resolved since last run" in result.output


def test_history_with_no_database_is_not_an_error(tmp_path):
    result = _run("history", "--db", str(tmp_path / "missing.db"))
    assert "No history recorded" in result.output


def test_history_metric_series(tmp_path):
    db = tmp_path / "history.db"
    _run("record-run", str(FLAWED), "--db", str(db), "--config-dir", str(CONFIG_DIR))
    result = _run("history", "--db", str(db), "--metric", "total_enrollments")
    assert "total_enrollments" in result.output


def test_draft_profile_writes_reviewable_yaml(tmp_path):
    out = tmp_path / "draft.yaml"
    result = _run(
        "draft-profile", str(FLAWED), "--id", "demo", "--name", "Demo", "--output", str(out)
    )
    text = out.read_text(encoding="utf-8")
    assert "profile_id: demo" in text
    assert "not a finished profile" in text
    assert "mapped confidently" in result.output


def test_compare_command_reports_deltas(tmp_path):
    result = _run("compare", str(FLAWED), str(CLEAN), "--config-dir", str(CONFIG_DIR))
    assert result.exit_code == 0


def test_compare_output_is_windows_console_safe(tmp_path):
    # CliRunner captures stdout in memory as UTF-8, so it hides the
    # UnicodeEncodeError a real Windows cp1252 console raises on non-Latin-1
    # glyphs (the → used to live in the headline and narrative). Asserting the
    # captured output encodes to cp1252 is the only way to catch that class of
    # bug from a test runner that never touches the real codec.
    out = tmp_path / "record_diff.csv"
    result = runner.invoke(
        app,
        [
            "compare",
            str(FLAWED),
            str(CLEAN),
            "--records",
            "--records-output",
            str(out),
            "--config-dir",
            str(CONFIG_DIR),
        ],
    )
    assert result.exit_code == 0, result.output
    result.output.encode("cp1252")  # raises UnicodeEncodeError if a glyph slipped in
    assert out.exists()


def test_eval_runs_deterministically(tmp_path):
    result = _run(
        "eval", str(FLAWED), "--no-ai", "--output", str(tmp_path), "--config-dir", str(CONFIG_DIR)
    )
    assert "cases passed" in result.output
    assert (tmp_path / "eval_report.md").exists()


def test_eval_repeated_runs_write_a_stability_artifact(tmp_path):
    _run(
        "eval",
        str(FLAWED),
        "--no-ai",
        "--runs",
        "2",
        "--output",
        str(tmp_path),
        "--config-dir",
        str(CONFIG_DIR),
    )
    assert (tmp_path / "eval_stability.json").exists()


def test_compare_models_needs_at_least_one_model():
    result = runner.invoke(app, ["compare-models", ""])
    assert result.exit_code == 2
    assert "at least one model" in result.output


def test_report_rejects_an_unknown_format(tmp_path):
    result = runner.invoke(app, ["report", str(FLAWED), "--format", "wingdings"])
    assert result.exit_code == 2
    assert "--format must be" in result.output


# -- Commands whose bodies shipped but were never executed --------------------
#
# `full-run`, the apply path of `apply-corrections`, the `batch --record` branch,
# and the ranking body of `compare-models` all showed 0 coverage: existing tests
# touched only an early-return or an error guard. A command that is registered
# and raises when its body runs is worse than one that is absent.


def test_full_run_generates_every_artifact(tmp_path):
    """full-run is the one-shot pipeline; its whole body was unexercised."""
    out = tmp_path / "out"
    result = _run("full-run", str(FLAWED), "--output", str(out), "--config-dir", str(CONFIG_DIR))
    assert result.exit_code == 0, result.output
    assert "Generated files" in result.output
    # No API key (autouse fixture), so the agent runs deterministically and the
    # audit/analytics/insights sections all print before the files are written.
    assert "Audit" in result.output and "Analytics" in result.output
    for name in (
        "grant_report.html",
        "grant_report.docx",
        "audit_workbook.xlsx",
        "analytics_summary.xlsx",
    ):
        assert (out / name).exists(), name


def test_apply_corrections_runs_the_apply_path(tmp_path):
    """A filled-in worksheet must reach the before/after re-audit, not just the no-op."""
    import pandas as pd

    sheet = tmp_path / "corrections.xlsx"
    _run(
        "correction-worksheet", str(FLAWED), "--output", str(sheet), "--config-dir", str(CONFIG_DIR)
    )

    # Fill one Corrected Value so the command passes the empty-worksheet early
    # return and runs the apply + re-audit path. The value need not actually
    # clear the issue -- this is a wiring test; audit correctness is covered
    # in test_corrections.py.
    frame = pd.read_excel(sheet, sheet_name="Corrections", dtype=str, keep_default_na=False)
    assert not frame.empty, "the flawed sample should produce correctable rows"
    frame.loc[frame.index[0], "Corrected Value"] = "Permanent housing"
    with pd.ExcelWriter(sheet, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Corrections", index=False)

    corrected = tmp_path / "corrected.csv"
    result = _run(
        "apply-corrections",
        str(FLAWED),
        str(sheet),
        "--output",
        str(corrected),
        "--config-dir",
        str(CONFIG_DIR),
    )
    assert result.exit_code == 0, result.output
    assert "correction(s) applied" in result.output
    assert "Before and after" in result.output
    assert corrected.exists()


def test_batch_records_each_file_to_history(tmp_path):
    """--record writes every succeeded file to a history db; the branch was unexercised."""
    import shutil

    folder = tmp_path / "extracts"
    folder.mkdir()
    shutil.copy(CLEAN, folder / "good.csv")
    db = tmp_path / "history.db"

    result = _run("batch", str(folder), "--record", str(db), "--config-dir", str(CONFIG_DIR))
    assert result.exit_code == 0, result.output
    assert "Recorded 1 run(s)" in result.output
    assert db.exists()


def test_compare_models_ranks_and_writes_markdown(tmp_path, monkeypatch):
    """The ranking body needs a provider; fake compare_models so it runs without a key."""
    from grant_assistant.evals.model_comparison import ComparisonResult, ModelResult

    def fake_compare(models, agent_factory, cases=None, client_ids=None, runs=1):
        return ComparisonResult(
            results=[
                ModelResult(model="alpha", pass_rates=[100.0, 100.0], total_tokens=500),
                ModelResult(model="beta", pass_rates=[80.0], total_tokens=300),
                ModelResult(model="gamma", error="No AI provider configured — set a key first."),
            ],
            runs_per_model=runs,
        )

    monkeypatch.setattr("grant_assistant.evals.model_comparison.compare_models", fake_compare)

    out = tmp_path / "cmp.md"
    result = _run(
        "compare-models",
        "alpha,beta,gamma",
        str(FLAWED),
        "--output",
        str(out),
        "--config-dir",
        str(CONFIG_DIR),
    )
    assert result.exit_code == 0, result.output
    assert "Best: alpha" in result.output
    # The failed model is reported, not silently dropped.
    assert "gamma" in result.output and "failed" in result.output
    assert out.exists()
    assert "# Model comparison" in out.read_text(encoding="utf-8")
