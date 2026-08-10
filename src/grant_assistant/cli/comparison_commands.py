"""Comparison and evaluation CLI commands."""

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
def compare(
    current_file: Annotated[Path, typer.Argument(help="Current-period CSV or Excel file.")],
    prior_file: Annotated[Path, typer.Argument(help="Prior-period CSV or Excel file.")],
    profile: ProfileOpt = "housing_stability",
    config_dir: ConfigDirOpt = None,
    records: Annotated[
        bool,
        typer.Option(
            "--records/--no-records",
            help="Also show which client records changed, not just which totals.",
        ),
    ] = False,
    records_output: Annotated[
        Path | None,
        typer.Option("--records-output", help="Write the record-level changes to CSV."),
    ] = None,
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
        # ASCII arrows: the Unicode arrows (U+2192/2191/2193) crash on a Windows
        # cp1252 console (UnicodeEncodeError), and the CliRunner used in tests
        # never hits that codec so the bug was invisible. Color still signals
        # improved/declined and the pct-change is printed alongside.
        arrow = "~"
        color = typer.colors.WHITE
        if d.improved is True:
            arrow, color = "^", typer.colors.GREEN
        elif d.improved is False:
            arrow, color = "v", typer.colors.RED
        typer.secho(
            f"{d.label:<34} {d.format_value(d.prior):>12}  {arrow}  "
            f"{d.format_value(d.current):>12}"
            + (f"   ({d.pct_change:+.1f}%)" if d.pct_change is not None else ""),
            fg=color,
        )
    _echo_header("Narrative")
    for line in comparison.narrative:
        typer.echo(f"- {line}")

    if records or records_output is not None:
        from grant_assistant.analytics import diff_records

        diff = diff_records(current.prepared, prior.prepared)
        _echo_header("Record-level changes")
        for line in diff.summary_lines():
            typer.echo(f"  {line}")
        for change in diff.changed[:15]:
            typer.echo(
                f"  {change.client_id:<12} {change.field_name:<24} "
                f"{change.before or '(blank)'} -> {change.after or '(blank)'}"
            )
        if len(diff.changed) > 15:
            typer.echo(f"  ... and {len(diff.changed) - 15} more")

        if records_output is not None:
            records_output.parent.mkdir(parents=True, exist_ok=True)
            diff.to_frame().to_csv(records_output, index=False)
            typer.secho(f"\nRecord changes: {records_output}", fg=typer.colors.GREEN)


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
