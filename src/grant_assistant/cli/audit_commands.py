"""Audit and analytics CLI commands."""

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
def audit(
    data_file: Annotated[Path, typer.Argument(help="CSV or Excel data file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    output: OutputOpt = Path("output"),
    export: Annotated[bool, typer.Option(help="Write the Excel audit workbook.")] = True,
    fail_under: Annotated[
        float | None,
        typer.Option(
            "--fail-under",
            min=0.0,
            max=100.0,
            help="Exit non-zero if the data quality score falls below this. "
            "Lets a pipeline gate on quality, not just on blocking issues.",
        ),
    ] = None,
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

    below_threshold = fail_under is not None and a.overall_score < fail_under
    if below_threshold:
        typer.secho(
            f"\nScore {a.overall_score:.1f} is below the required {fail_under:.1f}.",
            fg=typer.colors.RED,
            err=True,
        )
    if a.blocking_issues or below_threshold:
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
    if an.median_length_of_stay_days is not None:
        typer.echo(
            f"Median length of stay:  {an.median_length_of_stay_days:.0f} days "
            f"(across {an.n_length_of_stay} completed stays)"
        )
    if an.period_elapsed_pct is not None:
        closed = " — period closed" if an.period_elapsed_pct >= 100 else ""
        typer.echo(f"Period elapsed:         {an.period_elapsed_pct:.0f}%{closed}")

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
        pace = ""
        if m.on_pace is not None:
            pace = "  ON PACE" if m.on_pace else "  BEHIND PACE"
        typer.secho(
            f"{m.id:<8} {m.name:<48} target {m.target:>8}  actual "
            f"{m.actual if m.actual is not None else 'n/a':>8}  {status}{pace}",
            fg=color,
        )

    if export:
        from grant_assistant.reporting import write_analytics_workbook

        path = write_analytics_workbook(an, output / "analytics_summary.xlsx")
        typer.secho(f"\nAnalytics workbook: {path}", fg=typer.colors.GREEN)
