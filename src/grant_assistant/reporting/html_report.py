"""Render the grant report as a standalone HTML document with interactive charts."""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from grant_assistant.analytics.charts import standard_chart_set
from grant_assistant.reporting.context import ReportData

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_html_report(report: ReportData, include_charts: bool = True) -> str:
    """Render the full report to an HTML string."""
    charts_html: dict[str, Markup] = {}
    if include_charts:
        figures = standard_chart_set(report.analytics, report.audit)
        for name, fig in figures.items():
            charts_html[name] = Markup(
                fig.to_html(full_html=False, include_plotlyjs=False, default_height="420px")
            )
    template = _environment().get_template("report.html.j2")
    return template.render(r=report, a=report.analytics, charts=charts_html)


def write_html_report(report: ReportData, path: str | Path, include_charts: bool = True) -> Path:
    """Render and write the HTML report; returns the output path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html_report(report, include_charts=include_charts), encoding="utf-8")
    logger.info("Wrote HTML report to %s", path)
    return path
