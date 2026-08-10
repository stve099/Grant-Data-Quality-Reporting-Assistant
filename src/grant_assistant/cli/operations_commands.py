"""Data generation, history, configuration, and correction CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from grant_assistant.cli.main import (
    ConfigDirOpt,
    ProfileOpt,
    _echo_header,
    _run,
    app,
)


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
    fail_under: Annotated[
        float | None,
        typer.Option(
            "--fail-under",
            min=0.0,
            max=100.0,
            help="Exit non-zero if the row-weighted score falls below this.",
        ),
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

    score = result.weighted_score
    below_threshold = fail_under is not None and score is not None and score < fail_under
    if below_threshold:
        typer.secho(
            f"\nWeighted score {score:.1f} is below the required {fail_under:.1f}.",
            fg=typer.colors.RED,
            err=True,
        )
    if result.failed or below_threshold:
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
    chart: Annotated[
        Path | None,
        typer.Option("--chart", help="Write the trend as an HTML chart to this path."),
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

    if chart is not None:
        from grant_assistant.analytics.charts import history_trend_chart

        chart.parent.mkdir(parents=True, exist_ok=True)
        history_trend_chart(entries, metric).write_html(str(chart), include_plotlyjs="cdn")
        typer.secho(f"\nChart: {chart}", fg=typer.colors.GREEN)


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
    typer.echo(f"  grant-assistant validate-config {output}")


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
    from grant_assistant.evals.model_comparison import compare_models

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
