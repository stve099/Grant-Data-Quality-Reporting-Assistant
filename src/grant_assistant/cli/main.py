"""grant-assistant CLI.

Examples:
    grant-assistant audit sample_data/housing_program_flawed.csv --profile housing_stability
    grant-assistant analyze sample_data/housing_program_clean.xlsx --profile housing_stability
    grant-assistant report sample_data/housing_program_flawed.csv --profile rapid_rehousing
    grant-assistant ask sample_data/housing_program_flawed.csv "Which program had the best outcomes?"
    grant-assistant full-run sample_data/housing_program_flawed.csv --profile housing_stability
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from grant_assistant import __version__

app = typer.Typer(
    name="grant-assistant",
    help="Grant Data Quality & Reporting Assistant — audit program data, compute grant "
    "performance measures, generate reports, and ask a grounded AI data analyst.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

ProfileOpt = Annotated[
    str,
    typer.Option("--profile", "-p", help="Profile id from configs/, or a path to a YAML file."),
]
ConfigDirOpt = Annotated[
    Path | None,
    typer.Option("--config-dir", help="Directory containing profile YAML files."),
]
OutputOpt = Annotated[Path, typer.Option("--output", "-o", help="Directory for generated files.")]


def _echo_header(title: str) -> None:
    typer.secho(f"\n=== {title} ===", fg=typer.colors.CYAN, bold=True)


def _run(data_file: Path, profile: str, config_dir: Path | None):
    from grant_assistant.workflow import run_pipeline, setup_logging

    setup_logging()
    load_dotenv()
    try:
        return run_pipeline(data_file, profile, config_dir)
    except Exception as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc


@app.callback(invoke_without_command=True)
def _version_callback(
    version: Annotated[
        bool, typer.Option("--version", help="Show the version and exit.", is_eager=True)
    ] = False,
) -> None:
    if version:
        typer.echo(f"grant-assistant {__version__}")
        raise typer.Exit()


@app.command()
def audit(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: OutputOpt = Path("output"),
    export: Annotated[bool, typer.Option(help="Write the Excel audit workbook.")] = True,
) -> None:
    """Run the data quality audit and print a summary."""
    result = _run(data_file, profile, config_dir)
    a = result.audit

    _echo_header(f"Data Quality Audit — {a.grant_name}")
    typer.echo(f"Records audited:     {a.total_rows}")
    color = (
        typer.colors.GREEN
        if a.overall_score >= 90
        else (typer.colors.YELLOW if a.overall_score >= 70 else typer.colors.RED)
    )
    typer.secho(f"Overall score:       {a.overall_score:.1f}/100 (grade {a.grade})", fg=color)
    typer.echo(f"Total findings:      {a.total_findings}")
    for sev, count in a.issue_count_by_severity.items():
        if count:
            typer.echo(f"  {sev:<9} {count}")
    if a.score_by_program:
        typer.echo("Score by program:")
        for prog, score in a.score_by_program.items():
            typer.echo(f"  {prog:<32} {score:.1f}")

    if a.issues_sorted():
        _echo_header("Findings")
        for issue in a.issues_sorted():
            flag = " [BLOCKING]" if issue.blocking else ""
            typer.echo(
                f"{issue.rule_id}  {issue.severity.label:<13} {issue.record_count:>4}  "
                f"{issue.rule_name}{flag}"
            )
    if a.injection_warnings:
        _echo_header("Security warnings")
        for warning in a.injection_warnings:
            typer.secho(f"  ! {warning}", fg=typer.colors.YELLOW)

    _echo_header("Executive summary")
    typer.echo(a.executive_summary())

    if export:
        from grant_assistant.reporting import write_audit_workbook

        path = write_audit_workbook(a, result.prepared, output / "audit_workbook.xlsx")
        typer.secho(f"\nAudit workbook: {path}", fg=typer.colors.GREEN)
    if a.blocking_issues:
        raise typer.Exit(code=1)


@app.command()
def analyze(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: OutputOpt = Path("output"),
    export: Annotated[bool, typer.Option(help="Write the Excel analytics workbook.")] = True,
) -> None:
    """Compute program analytics and performance measures."""
    result = _run(data_file, profile, config_dir)
    an = result.analytics

    _echo_header(f"Analytics — {an.grant_name} ({an.period_start} to {an.period_end})")
    typer.echo(f"Enrollments:            {an.total_enrollments}")
    typer.echo(f"Households served:      {an.households_served}")
    typer.echo(
        f"Individuals:            {an.total_individuals} "
        f"({an.total_adults} adults, {an.total_children} children)"
    )
    typer.echo(f"Active enrollments:     {an.active_enrollments}")
    typer.echo(f"Exits:                  {an.total_exits} ({an.exit_rate}%)")
    typer.echo(f"Successful exits:       {an.successful_exits} ({an.successful_exit_rate}%)")
    typer.echo(
        f"Permanent housing:      {an.permanent_housing_exits} ({an.permanent_housing_rate}%)"
    )
    typer.echo(
        f"Median income change:   ${an.median_income_change or 0:,.0f} "
        f"({an.pct_income_increased}% of households increased)"
    )
    typer.echo(f"Overdue follow-ups:     {an.total_overdue_followups}")

    _echo_header("Programs")
    for p in an.programs:
        small = "  (small sample)" if p.small_sample else ""
        typer.echo(
            f"{p.program:<32} enroll {p.enrollments:>4}  exits {p.exits:>4}  "
            f"success {p.successful_exit_rate if p.successful_exit_rate is not None else 'n/a'}%"
            f"{small}"
        )

    _echo_header("Performance measures")
    for m in an.measures:
        status = "MET" if m.met else ("NOT MET" if m.met is False else "NO DATA")
        color = (
            typer.colors.GREEN
            if m.met
            else (typer.colors.RED if m.met is False else typer.colors.YELLOW)
        )
        typer.secho(
            f"{m.id:<8} {m.name:<48} target {m.target:>8}  actual "
            f"{m.actual if m.actual is not None else 'n/a':>8}  {status}",
            fg=color,
        )

    if export:
        from grant_assistant.reporting import write_analytics_workbook

        path = write_analytics_workbook(an, output / "analytics_summary.xlsx")
        typer.secho(f"\nAnalytics workbook: {path}", fg=typer.colors.GREEN)


@app.command()
def report(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: OutputOpt = Path("output"),
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Report formats: html, docx, pdf, or all.")
    ] = "all",
    offline_charts: Annotated[
        bool, typer.Option(help="Embed plotly.js in the HTML report so charts work offline.")
    ] = False,
    ai: Annotated[
        bool, typer.Option(help="Use the AI provider for narrative if configured.")
    ] = True,
) -> None:
    """Generate the grant outcome report (HTML/Word/PDF) plus Excel workbooks."""
    if fmt not in {"html", "docx", "pdf", "all"}:
        typer.secho("--format must be html, docx, pdf, or all", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    result = _run(data_file, profile, config_dir)
    agent = result.make_agent(use_ai=ai)
    typer.echo(
        "Narrative mode: "
        + ("AI-assisted (grounded)" if agent.ai_enabled else "deterministic (non-AI mode)")
    )

    from grant_assistant.reporting import (
        PdfBackendError,
        build_report_data,
        write_analytics_workbook,
        write_audit_workbook,
        write_docx_report,
        write_html_report,
        write_pdf_report,
    )

    data = build_report_data(result.analytics, result.audit, result.profile, agent)
    written: list[Path] = []
    if fmt in {"html", "all"}:
        written.append(
            write_html_report(data, output / "grant_report.html", offline_charts=offline_charts)
        )
    if fmt in {"docx", "all"}:
        written.append(write_docx_report(data, output / "grant_report.docx"))
    if fmt == "pdf" or fmt == "all":
        try:
            written.append(write_pdf_report(data, output / "grant_report.pdf"))
        except PdfBackendError as exc:
            if fmt == "pdf":
                typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
            typer.secho(f"Skipping PDF: {exc}", fg=typer.colors.YELLOW)
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


@app.command()
def compare(
    current_file: Annotated[Path, typer.Argument(help="Current-period CSV or Excel file.")],
    prior_file: Annotated[Path, typer.Argument(help="Prior-period CSV or Excel file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
) -> None:
    """Compare two reporting-period extracts (same profile) and show deltas."""
    from grant_assistant.analytics.comparison import compare_analytics

    current = _run(current_file, profile, config_dir)
    prior = _run(prior_file, profile, config_dir)
    comparison = compare_analytics(
        current.analytics,
        prior.analytics,
        current_label=current_file.name,
        prior_label=prior_file.name,
    )

    _echo_header(f"Period comparison — {current_file.name} vs {prior_file.name}")
    for d in comparison.headline:
        arrow = "→"
        color = typer.colors.WHITE
        if d.improved is True:
            arrow, color = "↑", typer.colors.GREEN
        elif d.improved is False:
            arrow, color = "↓", typer.colors.RED
        typer.secho(
            f"{d.label:<34} {d.format_value(d.prior):>12}  {arrow}  "
            f"{d.format_value(d.current):>12}"
            + (f"   ({d.pct_change:+.1f}%)" if d.pct_change is not None else ""),
            fg=color,
        )
    _echo_header("Narrative")
    for line in comparison.narrative:
        typer.echo(f"- {line}")


@app.command("generate-sample-data")
def generate_sample_data(
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Directory for sample files.")
    ] = Path("sample_data"),
    seed: Annotated[int, typer.Option(help="Random seed for reproducibility.")] = 42,
) -> None:
    """Generate synthetic clean + flawed sample datasets with an issue manifest."""
    from grant_assistant.datagen import write_sample_files

    paths = write_sample_files(output, seed=seed)
    _echo_header("Sample data written")
    for name, path in paths.items():
        typer.secho(f"  {name:<32} {path}", fg=typer.colors.GREEN)


@app.command("validate-config")
def validate_config(
    profile: Annotated[
        str | None,
        typer.Argument(help="Profile id or YAML path. Omit to validate every profile."),
    ] = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Validate grant profile configuration files."""
    from grant_assistant.configuration import (
        ProfileValidationError,
        list_profiles,
        load_profile_file,
    )
    from grant_assistant.workflow import resolve_profile

    targets: list[tuple[str, Path | None]] = []
    if profile:
        targets.append((profile, None))
    else:
        found = list_profiles(config_dir)
        if not found:
            typer.secho("No profiles found.", fg=typer.colors.YELLOW)
            raise typer.Exit(code=1)
        targets.extend((pid, path) for pid, path in found.items())

    failures = 0
    for name, path in targets:
        try:
            loaded = load_profile_file(path) if path else resolve_profile(name, config_dir)
            typer.secho(
                f"  OK  {loaded.profile_id:<24} {loaded.grant_name} "
                f"({len(loaded.programs)} programs, "
                f"{len(loaded.performance_measures)} measures)",
                fg=typer.colors.GREEN,
            )
        except ProfileValidationError as exc:
            failures += 1
            typer.secho(f"  FAIL {name}\n{exc}", fg=typer.colors.RED)
    if failures:
        raise typer.Exit(code=1)


@app.command()
def rules() -> None:
    """List every audit rule the engine applies."""
    from grant_assistant.audit import list_rules

    _echo_header("Audit rules")
    for meta in list_rules():
        blocking = " [blocking]" if meta.blocking else ""
        typer.echo(
            f"{meta.rule_id}  {meta.severity.label:<13} {meta.category:<16} {meta.name}{blocking}"
        )


if __name__ == "__main__":
    app()
