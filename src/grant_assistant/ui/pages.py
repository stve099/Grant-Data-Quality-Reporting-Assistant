"""Compatibility exports for focused Streamlit page modules."""

from grant_assistant.ui.ai_pages import page_chat, page_insights
from grant_assistant.ui.analytics_pages import page_analytics, page_comparison
from grant_assistant.ui.audit_pages import page_audit, page_issues
from grant_assistant.ui.data_pages import page_preview, page_upload
from grant_assistant.ui.report_pages import page_config_help, page_exports, page_report

__all__ = [
    "page_analytics",
    "page_audit",
    "page_chat",
    "page_comparison",
    "page_config_help",
    "page_exports",
    "page_insights",
    "page_issues",
    "page_preview",
    "page_report",
    "page_upload",
]
