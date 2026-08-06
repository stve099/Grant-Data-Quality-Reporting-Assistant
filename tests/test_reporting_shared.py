"""The shared formatter, and the PDF backend detection that had no tests.

Both exist because a renderer must behave the same way in every format and must
degrade cleanly when an optional backend is missing.
"""

from __future__ import annotations

import pytest

from grant_assistant.reporting.formatting import format_value

# -- Formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (64.1, "percent", "64.1%"),
        (0, "percent", "0%"),
        (1037.25, "currency", "$1,037"),
        (0, "currency", "$0"),
        (260, "", "260"),
        (1284, "", "1,284"),
        (1284.5, "", "1,284.5"),
    ],
)
def test_values_render_as_expected(value, unit, expected):
    assert format_value(value, unit) == expected


def test_none_is_explicit_not_blank():
    """A blank cell in a funder report reads as zero, which is a lie."""
    assert format_value(None) == "n/a"
    assert format_value(None, "percent") == "n/a"
    assert format_value(None, "currency") == "n/a"


def test_both_renderers_use_the_same_formatter():
    """The reason this module exists: two copies drift apart."""
    from grant_assistant.reporting import docx_report, pptx_report

    assert docx_report._fmt is format_value
    assert pptx_report._fmt is format_value


# -- PDF backend detection ---------------------------------------------------


def test_pdf_backend_reports_a_known_value():
    from grant_assistant.reporting import pdf_backend

    assert pdf_backend() in {None, "playwright", "edge"}


def test_playwright_is_preferred_when_present(monkeypatch):
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: True)
    monkeypatch.setattr(pdf_report, "_find_edge", lambda: r"C:\edge.exe")
    assert pdf_report.pdf_backend() == "playwright"


def test_edge_is_the_fallback(monkeypatch):
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: False)
    monkeypatch.setattr(pdf_report, "_find_edge", lambda: r"C:\edge.exe")
    assert pdf_report.pdf_backend() == "edge"


def test_no_backend_is_reported_as_none(monkeypatch):
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: False)
    monkeypatch.setattr(pdf_report, "_find_edge", lambda: None)
    assert pdf_report.pdf_backend() is None


def test_writing_without_a_backend_names_the_fix(
    monkeypatch, analytics_flawed, audit_flawed, profile, tmp_path
):
    """The error has to tell the user what to install, not just fail."""
    from grant_assistant.reporting import PdfBackendError, build_report_data, pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: False)
    monkeypatch.setattr(pdf_report, "_find_edge", lambda: None)

    data = build_report_data(analytics_flawed, audit_flawed, profile)
    with pytest.raises(PdfBackendError) as exc:
        pdf_report.write_pdf_report(data, tmp_path / "out.pdf")
    assert "--extra pdf" in str(exc.value)


def test_edge_detection_checks_real_paths(monkeypatch):
    """_find_edge must not claim a browser that is not installed."""
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_report.Path, "exists", lambda self: False)
    assert pdf_report._find_edge() is None
