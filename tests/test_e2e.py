"""End-to-end workflow test: file -> pipeline -> agent -> reports."""

from __future__ import annotations

from grant_assistant.reporting import (
    build_report_data,
    write_analytics_workbook,
    write_audit_workbook,
    write_docx_report,
    write_html_report,
)
from grant_assistant.workflow import run_pipeline
from tests.conftest import CONFIG_DIR, REPO_ROOT, TODAY


def test_full_workflow_from_excel(tmp_path):
    data_file = REPO_ROOT / "sample_data" / "housing_program_flawed.xlsx"
    result = run_pipeline(data_file, "housing_stability", CONFIG_DIR, today=TODAY)

    # Audit found the injected problems.
    assert result.audit.total_findings > 50
    assert result.audit.overall_score < 100
    assert result.audit.blocking_issues

    # Analytics computed sensible values.
    an = result.analytics
    assert an.total_enrollments > 200
    assert an.total_exits > 100
    assert an.successful_exit_rate is not None
    assert an.programs

    # Agent (non-AI mode) answers from calculated results.
    agent = result.make_agent(use_ai=False)
    answer = agent.ask("Summarize grant outcomes for the reporting period.")
    assert str(an.total_enrollments) in answer
    insights = agent.proactive_insights()
    assert insights.recommended_actions

    # Every artifact generates.
    data = build_report_data(an, result.audit, result.profile, agent)
    html = write_html_report(data, tmp_path / "report.html")
    docx = write_docx_report(data, tmp_path / "report.docx")
    audit_wb = write_audit_workbook(result.audit, result.prepared, tmp_path / "audit.xlsx")
    analytics_wb = write_analytics_workbook(an, tmp_path / "analytics.xlsx")
    for path in (html, docx, audit_wb, analytics_wb):
        assert path.exists()
        assert path.stat().st_size > 5_000


def test_full_workflow_profile_by_path(tmp_path):
    data_file = REPO_ROOT / "sample_data" / "housing_program_clean.csv"
    profile_path = CONFIG_DIR / "rapid_rehousing.yaml"
    result = run_pipeline(data_file, str(profile_path), today=TODAY)
    assert result.profile.profile_id == "rapid_rehousing"
    assert result.audit.overall_score == 100.0
