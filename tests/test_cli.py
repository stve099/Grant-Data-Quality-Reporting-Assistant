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
