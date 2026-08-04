"""Grant report generation and export (HTML, Word, Excel)."""

from grant_assistant.reporting.context import ReportData, build_report_data
from grant_assistant.reporting.data_dictionary import (
    build_data_dictionary,
    write_data_dictionary,
)
from grant_assistant.reporting.docx_report import write_docx_report
from grant_assistant.reporting.excel_export import (
    write_analytics_workbook,
    write_audit_workbook,
)
from grant_assistant.reporting.html_report import render_html_report, write_html_report
from grant_assistant.reporting.pdf_report import PdfBackendError, pdf_backend, write_pdf_report

__all__ = [
    "PdfBackendError",
    "ReportData",
    "build_data_dictionary",
    "build_report_data",
    "pdf_backend",
    "render_html_report",
    "write_analytics_workbook",
    "write_audit_workbook",
    "write_data_dictionary",
    "write_docx_report",
    "write_html_report",
    "write_pdf_report",
]
