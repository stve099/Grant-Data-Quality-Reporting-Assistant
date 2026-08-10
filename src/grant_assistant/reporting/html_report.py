"""Render the grant report as a standalone HTML document with interactive charts."""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from grant_assistant.analytics.charts import standard_chart_set
from grant_assistant.reporting.branding import logo_data_uri
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


#: Available report templates. "full" is the complete funder submission;
#: "concise" is a 2–3 page executive brief drawn from the same context.
TEMPLATES: dict[str, str] = {
    "full": "report.html.j2",
    "concise": "report_concise.html.j2",
}

#: Charts included in the concise brief — enough to carry the story, no more.
_CONCISE_CHARTS = {"goal_vs_actual", "outcome_rates"}


def render_html_report(
    report: ReportData,
    include_charts: bool = True,
    offline_charts: bool = False,
    template: str = "full",
) -> str:
    """Render the report to an HTML string.

    Args:
        include_charts: embed interactive Plotly figures.
        offline_charts: inline the plotly.js library (~3.5 MB) so charts work
            with no internet connection — required for PDF rendering.
        template: "full" for the complete report, "concise" for the executive
            brief. Both are rendered from the same :class:`ReportData`, so the
            numbers cannot diverge between them.
    """
    if template not in TEMPLATES:
        raise ValueError(f"Unknown report template '{template}'. Available: {sorted(TEMPLATES)}")
    charts_html: dict[str, Markup] = {}
    plotly_js = ""
    if include_charts:
        figures = standard_chart_set(report.analytics, report.audit)
        if template == "concise":
            figures = {k: v for k, v in figures.items() if k in _CONCISE_CHARTS}
        for name, fig in figures.items():
            charts_html[name] = Markup(
                fig.to_html(full_html=False, include_plotlyjs=False, default_height="420px")
            )
        if offline_charts and charts_html:
            from plotly.offline import get_plotlyjs

            plotly_js = Markup(get_plotlyjs())
    rendered = _environment().get_template(TEMPLATES[template])
    return rendered.render(
        r=report,
        a=report.analytics,
        charts=charts_html,
        plotly_js=plotly_js,
        logo_data_uri=logo_data_uri(report),
    )


def write_html_report(
    report: ReportData,
    path: str | Path,
    include_charts: bool = True,
    offline_charts: bool = False,
    template: str = "full",
) -> Path:
    """Render and write the HTML report; returns the output path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_html_report(
            report,
            include_charts=include_charts,
            offline_charts=offline_charts,
            template=template,
        ),
        encoding="utf-8",
    )
    logger.info("Wrote %s HTML report to %s", template, path)
    return path
