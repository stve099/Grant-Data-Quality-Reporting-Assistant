"""Report generation and export tests (HTML, Word, Excel)."""

from __future__ import annotations

import openpyxl
import pytest
from docx import Document

from grant_assistant.reporting import (
    build_report_data,
    render_html_report,
    write_analytics_workbook,
    write_audit_workbook,
    write_docx_report,
    write_html_report,
)


@pytest.fixture(scope="module")
def report_data(analytics_flawed, audit_flawed, profile):
    return build_report_data(analytics_flawed, audit_flawed, profile)


def test_report_data_assembled(report_data, analytics_flawed):
    assert report_data.executive_summary
    assert str(analytics_flawed.total_enrollments) in report_data.executive_summary
    assert report_data.insights.key_findings
    assert report_data.ai_generated_narrative is False
    assert report_data.measure_definitions()
    assert report_data.data_limitations()


def test_html_report_contains_all_sections(report_data):
    html = render_html_report(report_data)
    for heading in (
        "Program Overview",
        "Executive Summary",
        "Data Quality Statement",
        "Population Served",
        "Demographic Summary",
        "Enrollment &amp; Exit Metrics",
        "Housing Outcomes",
        "Income Outcomes",
        "Follow-Up Outcomes",
        "Performance Measures",
        "Program Comparison",
        "Key Findings",
        "Recommended Actions",
        "Methodology",
        "Data Limitations",
        "Appendix: Measure Definitions",
    ):
        assert heading in html, f"missing section: {heading}"
    assert "plotly" in html.lower()  # interactive charts embedded
    assert report_data.profile.grant_name in html


def test_html_report_written_to_disk(report_data, tmp_path):
    path = write_html_report(report_data, tmp_path / "report.html")
    assert path.exists()
    assert path.stat().st_size > 10_000


def test_docx_report_written_and_valid(report_data, tmp_path):
    path = write_docx_report(report_data, tmp_path / "report.docx")
    doc = Document(str(path))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    for expected in (
        "Program Overview",
        "Executive Summary",
        "Data Quality Statement",
        "Population Served",
        "Performance Measures",
        "Recommended Actions",
        "Methodology",
        "Data Limitations",
    ):
        assert any(expected in h for h in headings), f"missing heading: {expected}"
    assert doc.tables, "report should contain tables"


def test_audit_workbook_sheets_and_content(audit_flawed, prepared_flawed, tmp_path):
    path = write_audit_workbook(audit_flawed, prepared_flawed, tmp_path / "audit.xlsx")
    wb = openpyxl.load_workbook(path)
    assert set(wb.sheetnames) >= {
        "Audit Summary",
        "Issues by Rule",
        "Row-Level Issues",
        "Flagged Records",
    }
    issues_sheet = wb["Row-Level Issues"]
    assert issues_sheet.max_row == audit_flawed.total_findings + 1  # header + findings
    flagged = wb["Flagged Records"]
    header = [c.value for c in flagged[1]]
    assert "Issues Found" in header
    assert "Corrected Value(s)" in header


def test_analytics_workbook_sheets(analytics_flawed, tmp_path):
    path = write_analytics_workbook(analytics_flawed, tmp_path / "analytics.xlsx")
    wb = openpyxl.load_workbook(path)
    assert set(wb.sheetnames) >= {
        "Overview",
        "Programs",
        "Performance Measures",
        "Follow-Ups",
        "Demographics",
        "Exit Destinations",
        "Monthly Trends",
    }
    overview = wb["Overview"]
    metrics = {row[0].value: row[1].value for row in overview.iter_rows(min_row=2)}
    assert metrics["Total enrollments"] == analytics_flawed.total_enrollments


def test_concise_template_is_shorter_but_keeps_the_headline_numbers(report_data, analytics_flawed):
    full = render_html_report(report_data)
    concise = render_html_report(report_data, template="concise")
    assert len(concise) < len(full) / 2
    assert "Executive Brief" in concise
    assert "Recommended Actions" in concise
    assert "Performance Measures" in concise
    # Same source of truth: headline figures must match the full report exactly.
    assert str(analytics_flawed.total_enrollments) in concise
    assert str(analytics_flawed.total_exits) in concise
    # Detail sections belong to the full report only.
    assert "Appendix: Measure Definitions" not in concise
    assert "Demographic Summary" not in concise


def test_concise_template_written_to_disk(report_data, tmp_path):
    path = write_html_report(report_data, tmp_path / "brief.html", template="concise")
    assert path.exists()
    assert "Executive Brief" in path.read_text(encoding="utf-8")


def test_unknown_template_rejected(report_data):
    with pytest.raises(ValueError, match="Unknown report template"):
        render_html_report(report_data, template="fancy")


def test_clean_dataset_report_renders_without_audit_section(analytics_clean, profile):
    data = build_report_data(analytics_clean, None, profile)
    html = render_html_report(data)
    assert "Data Quality Statement" not in html
    assert "Executive Summary" in html
