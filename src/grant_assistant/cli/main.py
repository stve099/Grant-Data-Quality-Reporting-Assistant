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

from grant_assistant import __version__
from grant_assistant.env import load_environment

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
    load_environment()
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
    if a.injection_warnings or a.pii_warnings:
        _echo_header("Security warnings")
        for warning in a.injection_warnings:
            typer.secho(f"  ! {warning}", fg=typer.colors.YELLOW)
        for warning in a.pii_warnings:
            typer.secho(f"  ! {warning}", fg=typer.colors.RED)

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


@app.command("eval")
def run_eval(
    data_file: Annotated[
        Path, typer.Argument(help="Dataset the analyst is evaluated against.")
    ] = Path("sample_data/housing_program_flawed.csv"),
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    cases: Annotated[
        Path | None, typer.Option("--cases", help="YAML case file (default: built-in set).")
    ] = None,
    output: OutputOpt = Path("output"),
    ai: Annotated[bool, typer.Option(help="Evaluate the AI path if a key is configured.")] = True,
    model_grader: Annotated[
        bool, typer.Option(help="Also judge answers against their rubric with the model.")
    ] = False,
    runs: Annotated[
        int,
        typer.Option(
            "--runs",
            min=1,
            help="Repeat the suite N times and report the spread. A hosted model "
            "is not reproducible, so one run measures luck as much as quality.",
        ),
    ] = 1,
) -> None:
    """Grade the AI analyst against the prompt-evaluation dataset."""
    from grant_assistant import schema
    from grant_assistant.evals import load_cases, run_evals
    from grant_assistant.evals.runner import summarize_runs, write_report, write_stability

    result = _run(data_file, profile, config_dir)
    agent = result.make_agent(use_ai=ai)
    client_ids = {str(v) for v in result.prepared.raw[schema.CLIENT_ID].dropna().unique() if str(v)}

    _echo_header(
        "Prompt Evaluation — "
        + ("AI mode" if agent.ai_enabled else "deterministic mode (no API key)")
    )
    loaded_cases = load_cases(cases)
    reports = []
    for run_index in range(runs):
        if runs > 1:
            typer.secho(f"  run {run_index + 1}/{runs}...", fg=typer.colors.BRIGHT_BLACK)
        reports.append(
            run_evals(
                agent,
                cases=loaded_cases,
                client_ids=client_ids,
                use_model_grader=model_grader,
            )
        )
    # The written report is the final run; the spread is reported to the console.
    report = reports[-1]

    for case in report.results:
        color = typer.colors.GREEN if case.passed else typer.colors.RED
        typer.secho(
            f"  {'PASS' if case.passed else 'FAIL'}  {case.case_id:<28} {case.category}",
            fg=color,
        )
        for failure in case.failures:
            typer.secho(f"        {failure.grader}: {failure.detail}", fg=typer.colors.RED)

    _echo_header("Summary")
    for name, (passed, total) in report.by_grader().items():
        color = typer.colors.GREEN if passed == total else typer.colors.RED
        typer.secho(f"  {name:<26} {passed}/{total}", fg=color)
    overall = typer.colors.GREEN if report.passed == report.total else typer.colors.RED
    typer.secho(
        f"\n  {report.passed}/{report.total} cases passed ({report.pass_rate}%)",
        fg=overall,
        bold=True,
    )

    if runs > 1:
        stability = summarize_runs(reports)
        _echo_header(f"Stability across {stability.runs} runs")
        typer.echo("  per run:  " + ", ".join(f"{r}%" for r in stability.pass_rates))
        typer.secho(
            f"  mean {stability.mean_pass_rate}%  "
            f"(min {stability.min_pass_rate}%, max {stability.max_pass_rate}%)",
            bold=True,
        )
        if stability.never_passed:
            typer.secho(
                f"  always failed: {', '.join(stability.never_passed)}", fg=typer.colors.RED
            )
        if stability.flaky:
            # Intermittent failures are the finding: a rule obeyed most of the
            # time is not obeyed, and a single green run would have hidden it.
            typer.secho(f"  intermittent:  {', '.join(stability.flaky)}", fg=typer.colors.YELLOW)
        if not stability.never_passed and not stability.flaky:
            typer.secho("  every case passed every run.", fg=typer.colors.GREEN)

    paths = write_report(report, output)
    label = " (final run)" if runs > 1 else ""
    typer.secho(f"\nReport{label}: {paths['markdown']}", fg=typer.colors.GREEN)
    if runs > 1:
        # Every run, not just the last: otherwise a failure in run 2 is erased by
        # a green run 3, which is exactly the case --runs exists to surface.
        typer.secho(f"All runs:   {write_stability(reports, output)}", fg=typer.colors.GREEN)
    if any(r.passed != r.total for r in reports):
        raise typer.Exit(code=1)


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


@app.command()
def batch(
    directory: Annotated[Path, typer.Argument(help="Folder of extracts to audit.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    pattern: Annotated[str, typer.Option("--pattern", help="Glob, e.g. '2025-*.csv'.")] = "*",
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Rollup path (.csv or .xlsx).")
    ] = Path("output/batch_summary.csv"),
    record: Annotated[
        Path | None, typer.Option("--record", help="Also add each file to this history db.")
    ] = None,
) -> None:
    """Audit every extract in a folder and roll the results up."""
    from grant_assistant.batch import (
        batch_summary_lines,
        discover_datasets,
        run_batch,
        write_batch_summary,
    )

    try:
        files = discover_datasets(directory, pattern)
    except NotADirectoryError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    if not files:
        typer.secho(f"No data files matching '{pattern}' in {directory}.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    _echo_header(f"Batch audit — {len(files)} file(s)")
    result = run_batch(files, profile, config_dir)

    for entry in result.entries:
        if entry.ok:
            color = typer.colors.GREEN if entry.blocking == 0 else typer.colors.YELLOW
            typer.secho(
                f"  {entry.path.name:<44} {entry.rows:>6} rows  {entry.score:>5.1f} "
                f"({entry.grade})  {entry.blocking} blocking",
                fg=color,
            )
        else:
            typer.secho(f"  {entry.path.name:<44} FAILED — {entry.error}", fg=typer.colors.RED)

    _echo_header("Rollup")
    for line in batch_summary_lines(result):
        typer.echo(f"  {line}")

    path = write_batch_summary(result, output)
    typer.secho(f"\nSummary: {path}", fg=typer.colors.GREEN)

    if record is not None:
        from grant_assistant.history import record_run

        recorded = 0
        for entry in result.succeeded:
            try:
                run = _run(entry.path, profile, config_dir)
                record_run(
                    run.profile,
                    run.audit,
                    run.analytics,
                    record,
                    label=entry.path.stem[:40],
                    source=str(entry.path),
                )
                recorded += 1
            except Exception as exc:  # pragma: no cover - defensive
                typer.secho(
                    f"  ! could not record {entry.path.name}: {exc}", fg=typer.colors.YELLOW
                )
        typer.secho(f"Recorded {recorded} run(s) to {record}", fg=typer.colors.GREEN)

    if result.failed:
        raise typer.Exit(code=1)


@app.command("record-run")
def record_run_command(
    data_file: Annotated[Path, typer.Argument(help="Dataset to audit and record.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    db: Annotated[Path, typer.Option("--db", help="History database.")] = Path("output/history.db"),
    label: Annotated[str, typer.Option("--label", help="Name this run, e.g. 'Q3 FY25'.")] = "",
) -> None:
    """Audit a dataset and add the result to the history database."""
    from grant_assistant.history import load_history, record_run

    result = _run(data_file, profile, config_dir)
    previous = load_history(db, result.profile.profile_id)
    run_id = record_run(
        result.profile,
        result.audit,
        result.analytics,
        db,
        label=label,
        source=str(data_file),
    )

    _echo_header("Run recorded")
    typer.echo(f"  Run #{run_id}  {label or '(unlabelled)'}")
    typer.echo(f"  Score {result.audit.overall_score:.1f} ({result.audit.grade})")
    if previous:
        delta = result.audit.overall_score - previous[-1].score
        color = typer.colors.GREEN if delta >= 0 else typer.colors.YELLOW
        typer.secho(f"  {delta:+.1f} versus the previous run", fg=color)

        from grant_assistant.history import resolved_since_last_run, rule_ages

        resolved = resolved_since_last_run(previous, result.audit)
        if resolved:
            typer.secho(f"  Resolved since last run: {', '.join(resolved)}", fg=typer.colors.GREEN)
        persistent = [a for a in rule_ages(previous, result.audit) if a.is_persistent]
        if persistent:
            _echo_header("Long-standing issues")
            for age in persistent:
                typer.secho(f"  {age.describe()}", fg=typer.colors.YELLOW)
    typer.secho(f"\nHistory: {db}", fg=typer.colors.GREEN)


@app.command()
def history(
    profile: Annotated[
        str | None, typer.Option("--profile", "-p", help="Limit to one profile.")
    ] = None,
    db: Annotated[Path, typer.Option("--db", help="History database.")] = Path("output/history.db"),
    metric: Annotated[
        str | None, typer.Option("--metric", help="Also chart one metric over time.")
    ] = None,
) -> None:
    """Show recorded runs and how data quality has moved."""
    from grant_assistant.history import load_history, metric_series, score_trend

    entries = load_history(db, profile)
    if not entries:
        typer.secho(
            f"No history recorded yet in {db}. Add one with: grant-assistant record-run",
            fg=typer.colors.YELLOW,
        )
        return

    _echo_header("Run history")
    typer.echo(f"  {'When':<17} {'Label':<14} {'Rows':>6} {'Score':>7} {'Find':>6} {'Block':>6}")
    previous: float | None = None
    for entry in entries:
        arrow = ""
        if previous is not None:
            change = entry.score - previous
            arrow = f"  {change:+.1f}"
        typer.echo(
            f"  {entry.recorded_at:%Y-%m-%d %H:%M}  {entry.label[:14]:<14} "
            f"{entry.total_rows:>6} {entry.score:>6.1f}{entry.grade:>1} "
            f"{entry.findings:>6} {entry.blocking:>6}{arrow}"
        )
        previous = entry.score

    trend = score_trend(entries)
    if trend is not None:
        color = typer.colors.GREEN if trend >= 0 else typer.colors.YELLOW
        typer.secho(f"\n  Overall change across {len(entries)} runs: {trend:+.1f}", fg=color)

    if metric:
        series = metric_series(entries, metric)
        if not series:
            typer.secho(f"\n  No recorded values for '{metric}'.", fg=typer.colors.YELLOW)
        else:
            _echo_header(metric)
            for when, value in series:
                typer.echo(f"  {when:%Y-%m-%d}  {value:>12,.1f}")


@app.command("draft-profile")
def draft_profile_command(
    data_file: Annotated[Path, typer.Argument(help="Sample extract from the new funder.")],
    profile_id: Annotated[
        str, typer.Option("--id", help="Profile id, e.g. 'county_esg'.")
    ] = "new_grant",
    grant_name: Annotated[str, typer.Option("--name", help="Grant name.")] = "New Grant",
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Where to write the draft YAML.")
    ] = Path("configs/draft_profile.yaml"),
) -> None:
    """Draft a grant profile from a sample extract, for a human to finish."""
    from grant_assistant.configuration.generator import draft_profile, draft_to_yaml
    from grant_assistant.ingestion import load_dataset

    frame = load_dataset(data_file)
    draft = draft_profile(frame, profile_id=profile_id, grant_name=grant_name)

    _echo_header("Profile draft")
    typer.secho(f"  {len(draft.confident)} column(s) mapped confidently", fg=typer.colors.GREEN)
    for guess in draft.uncertain:
        typer.secho(
            f"  ? {guess.source_header} -> {guess.canonical} ({guess.reason})",
            fg=typer.colors.YELLOW,
        )
    for canonical in draft.missing_required:
        typer.secho(f"  ! no column found for required field '{canonical}'", fg=typer.colors.RED)
    if draft.unmapped_headers:
        typer.echo(f"  {len(draft.unmapped_headers)} column(s) unmapped and ignored")
    if draft.programs:
        typer.echo(f"  {len(draft.programs)} program(s) found: {', '.join(draft.programs[:4])}")
    if draft.period_start:
        typer.echo(f"  Dates span {draft.period_start} to {draft.period_end}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(draft_to_yaml(draft), encoding="utf-8")
    typer.secho(f"\nDraft: {output}", fg=typer.colors.GREEN)
    typer.echo("Review every mapping, add the performance measures, then run:")
    typer.echo(f"  grant-assistant validate-config --path {output}")


@app.command("compare-models")
def compare_models_command(
    models: Annotated[str, typer.Argument(help="Comma-separated model ids to compare.")],
    data_file: Annotated[
        Path, typer.Argument(help="Dataset the models are evaluated against.")
    ] = Path("sample_data/housing_program_flawed.csv"),
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    runs: Annotated[
        int, typer.Option("--runs", min=1, help="Runs per model; a mean beats one sample.")
    ] = 1,
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Where to write the comparison table.")
    ] = Path("output/model_comparison.md"),
) -> None:
    """Evaluate several models on the same dataset and rank them."""
    from grant_assistant import schema
    from grant_assistant.agents import DataAnalystAgent
    from grant_assistant.agents.provider import get_provider
    from grant_assistant.evals.comparison import compare_models

    names = [m.strip() for m in models.split(",") if m.strip()]
    if not names:
        typer.secho("Give at least one model id.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    result = _run(data_file, profile, config_dir)
    client_ids = {str(v) for v in result.prepared.raw[schema.CLIENT_ID].dropna().unique() if str(v)}

    def agent_factory(model: str) -> DataAnalystAgent:
        provider = get_provider(model=model)
        if provider is None:
            raise RuntimeError("No AI provider configured — set a key first.")
        return DataAnalystAgent(result.analytics, result.audit, result.profile, provider=provider)

    _echo_header(f"Comparing {len(names)} model(s), {runs} run(s) each")
    comparison = compare_models(names, agent_factory, client_ids=client_ids, runs=runs)

    for entry in comparison.ranked:
        color = typer.colors.GREEN if entry.mean_pass_rate >= 100 else typer.colors.YELLOW
        typer.secho(
            f"  {entry.model:<38} {entry.mean_pass_rate:>6.1f}%  "
            f"(worst {entry.min_pass_rate:.1f}%)  {entry.total_tokens:>9,} tokens",
            fg=color,
        )
    for entry in comparison.results:
        if not entry.ok:
            typer.secho(f"  {entry.model:<38} failed — {entry.error}", fg=typer.colors.RED)

    winner = comparison.winner
    if winner is not None:
        typer.secho(f"\n  Best: {winner.model} ({winner.mean_pass_rate}%)", bold=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(comparison.as_markdown(), encoding="utf-8")
    typer.secho(f"\nComparison: {output}", fg=typer.colors.GREEN)


@app.command("data-dictionary")
def data_dictionary(
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Output path (.md or .html).")
    ] = Path("output/data_dictionary.md"),
) -> None:
    """Generate the file specification for whoever produces the extract."""
    from grant_assistant.configuration import ProfileValidationError
    from grant_assistant.reporting import write_data_dictionary
    from grant_assistant.workflow import resolve_profile

    try:
        loaded = resolve_profile(profile, config_dir)
    except ProfileValidationError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    path = write_data_dictionary(loaded, output)
    _echo_header("Data dictionary")
    typer.echo(f"  {loaded.grant_name} ({loaded.profile_id})")
    typer.echo(
        f"  {len(loaded.field_mappings)} column(s), {len(loaded.programs)} program(s), "
        f"{len(loaded.performance_measures)} measure(s)"
    )
    typer.secho(f"\nWritten: {path}", fg=typer.colors.GREEN)


@app.command("correction-worksheet")
def correction_worksheet(
    data_file: Annotated[Path, typer.Argument(help="Dataset to build corrections for.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="Worksheet path (.xlsx).")] = Path(
        "output/corrections.xlsx"
    ),
) -> None:
    """Export every flagged record to a worksheet staff can fill in and return."""
    from grant_assistant.corrections import build_worksheet, write_worksheet

    result = _run(data_file, profile, config_dir)
    frame = build_worksheet(result.audit)
    if frame.empty:
        typer.secho(
            "No correctable records — every finding is dataset-level.", fg=typer.colors.GREEN
        )
        return
    path = write_worksheet(result.audit, output)

    _echo_header("Correction worksheet")
    typer.echo(f"  {len(frame)} record(s) across {frame['Rule'].nunique()} rule(s)")
    blocking = int((frame["Blocking"] == "Yes").sum())
    if blocking:
        typer.secho(f"  {blocking} of them block submission", fg=typer.colors.YELLOW)
    typer.secho(f"\nWorksheet: {path}", fg=typer.colors.GREEN)
    typer.echo("Fill in 'Corrected Value', then run: grant-assistant apply-corrections")


@app.command("apply-corrections")
def apply_corrections_command(
    data_file: Annotated[Path, typer.Argument(help="The dataset the worksheet came from.")],
    worksheet: Annotated[Path, typer.Argument(help="Filled-in correction worksheet.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Where to write the corrected dataset.")
    ] = Path("output/corrected.csv"),
) -> None:
    """Apply a filled-in worksheet and re-audit to show what actually cleared."""
    from grant_assistant.audit import run_audit
    from grant_assistant.corrections import apply_corrections, read_worksheet
    from grant_assistant.ingestion import load_dataset, prepare_dataset

    before = _run(data_file, profile, config_dir)
    try:
        corrections = read_worksheet(worksheet)
    except (ValueError, FileNotFoundError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    if not corrections:
        typer.secho(
            "No corrections found — the 'Corrected Value' column is empty.",
            fg=typer.colors.YELLOW,
        )
        return

    source = load_dataset(data_file)
    corrected, report = apply_corrections(source, corrections, before.prepared)

    _echo_header("Applying corrections")
    typer.echo(f"  {report.summary()}")
    for reason in report.skipped:
        typer.secho(f"  ! {reason}", fg=typer.colors.YELLOW)

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".xlsx", ".xls"}:
        corrected.to_excel(output, index=False)
    else:
        corrected.to_csv(output, index=False)

    after = run_audit(prepare_dataset(corrected, before.profile), before.profile)

    _echo_header("Before and after")
    delta = after.overall_score - before.audit.overall_score
    typer.echo(
        f"  Data quality score  {before.audit.overall_score:.1f} -> {after.overall_score:.1f} "
        f"({delta:+.1f})"
    )
    typer.echo(
        f"  Findings            {before.audit.total_findings} -> {after.total_findings} "
        f"({after.total_findings - before.audit.total_findings:+d})"
    )
    typer.echo(
        f"  Blocking issues     {len(before.audit.blocking_issues)} -> {len(after.blocking_issues)}"
    )
    color = typer.colors.GREEN if delta >= 0 else typer.colors.RED
    typer.secho(f"\nCorrected dataset: {output}", fg=color)


if __name__ == "__main__":
    app()
