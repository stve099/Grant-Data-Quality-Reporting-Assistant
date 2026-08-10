"""Report and AI workflow CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from grant_assistant.cli.main import (
    ConfigDirOpt,
    OutputOpt,
    ProfileOpt,
    _echo_header,
    _run,
    app,
)


@app.command()
def report(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: OutputOpt = Path("output"),
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Report formats: html, docx, pdf, pptx, or all.")
    ] = "all",
    template: Annotated[
        str,
        typer.Option(
            "--template",
            "-t",
            help="Report template: 'full' (complete submission) or 'concise' "
            "(2-3 page executive brief). Applies to HTML and PDF.",
        ),
    ] = "full",
    offline_charts: Annotated[
        bool, typer.Option(help="Embed plotly.js in the HTML report so charts work offline.")
    ] = False,
    ai: Annotated[
        bool, typer.Option(help="Use the AI provider for narrative if configured.")
    ] = True,
) -> None:
    """Generate the grant outcome report (HTML/Word/PDF) plus Excel workbooks."""
    from grant_assistant.reporting.html_report import TEMPLATES

    if template not in TEMPLATES:
        typer.secho(
            f"--template must be one of: {', '.join(sorted(TEMPLATES))}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if fmt not in {"html", "docx", "pdf", "pptx", "all"}:
        typer.secho("--format must be html, docx, pdf, pptx, or all", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    result = _run(data_file, profile, config_dir)
    agent = result.make_agent(use_ai=ai)
    typer.echo(
        "Narrative mode: "
        + ("AI-assisted (grounded)" if agent.ai_enabled else "deterministic (non-AI mode)")
    )

    from grant_assistant.reporting import (
        PdfBackendError,
        PptxBackendError,
        build_report_data,
        write_analytics_workbook,
        write_audit_workbook,
        write_docx_report,
        write_html_report,
        write_pdf_report,
        write_pptx_report,
    )

    data = build_report_data(result.analytics, result.audit, result.profile, agent)
    suffix = "" if template == "full" else f"_{template}"
    written: list[Path] = []
    if fmt in {"html", "all"}:
        written.append(
            write_html_report(
                data,
                output / f"grant_report{suffix}.html",
                offline_charts=offline_charts,
                template=template,
            )
        )
    if fmt in {"docx", "all"}:
        written.append(write_docx_report(data, output / "grant_report.docx"))
    if fmt == "pdf" or fmt == "all":
        try:
            written.append(
                write_pdf_report(data, output / f"grant_report{suffix}.pdf", template=template)
            )
        except PdfBackendError as exc:
            if fmt == "pdf":
                typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
            typer.secho(f"Skipping PDF: {exc}", fg=typer.colors.YELLOW)
    if fmt in {"pptx", "all"}:
        try:
            written.append(write_pptx_report(data, output / "grant_report.pptx"))
        except PptxBackendError as exc:
            if fmt == "pptx":
                typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
            typer.secho(f"Skipping PowerPoint: {exc}", fg=typer.colors.YELLOW)
    written.append(
        write_audit_workbook(result.audit, result.prepared, output / "audit_workbook.xlsx")
    )
    written.append(write_analytics_workbook(result.analytics, output / "analytics_summary.xlsx"))
    _echo_header("Generated files")
    for path in written:
        typer.secho(f"  {path}", fg=typer.colors.GREEN)


@app.command()
def ask(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    question: Annotated[str, typer.Argument(help="Natural-language question about the data.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    ai: Annotated[bool, typer.Option(help="Use the AI provider if configured.")] = True,
) -> None:
    """Ask the Senior Data Analyst agent a question about the dataset."""
    result = _run(data_file, profile, config_dir)
    agent = result.make_agent(use_ai=ai)
    _echo_header("Senior Data Analyst")
    typer.echo(agent.ask(question))


@app.command()
def insights(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    ai: Annotated[
        bool, typer.Option(help="Use the AI provider for narration if configured.")
    ] = True,
) -> None:
    """Generate the proactive senior-analyst review of the dataset."""
    result = _run(data_file, profile, config_dir)
    agent = result.make_agent(use_ai=ai)
    _echo_header("Proactive Insights")
    typer.echo(agent.narrated_insights())


@app.command("full-run")
def full_run(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: OutputOpt = Path("output"),
    ai: Annotated[bool, typer.Option(help="Use the AI provider if configured.")] = True,
) -> None:
    """Audit + analytics + insights + full report generation in one command."""
    result = _run(data_file, profile, config_dir)
    agent = result.make_agent(use_ai=ai)

    a = result.audit
    _echo_header(f"Audit — score {a.overall_score:.1f}/100 (grade {a.grade})")
    typer.echo(a.executive_summary())

    an = result.analytics
    _echo_header("Analytics")
    typer.echo(
        f"{an.total_enrollments} enrollments, {an.total_exits} exits, "
        f"{an.successful_exit_rate}% successful, "
        f"{an.permanent_housing_rate}% to permanent housing."
    )

    _echo_header("Proactive Insights")
    typer.echo(agent.narrated_insights())

    from grant_assistant.reporting import (
        build_report_data,
        write_analytics_workbook,
        write_audit_workbook,
        write_docx_report,
        write_html_report,
    )

    data = build_report_data(an, a, result.profile, agent)
    files = [
        write_html_report(data, output / "grant_report.html"),
        write_docx_report(data, output / "grant_report.docx"),
        write_audit_workbook(a, result.prepared, output / "audit_workbook.xlsx"),
        write_analytics_workbook(an, output / "analytics_summary.xlsx"),
    ]
    _echo_header("Generated files")
    for path in files:
        typer.secho(f"  {path}", fg=typer.colors.GREEN)
