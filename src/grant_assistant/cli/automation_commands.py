"""CLI commands for unattended and scheduler-driven runs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def register_automation_commands(app: typer.Typer) -> None:
    """Register automation commands without expanding the main CLI module."""

    @app.command("scheduled-audit")
    def scheduled_audit(
        data_file: Annotated[Path, typer.Argument(help="Dataset to audit, record, and report.")],
        profile: Annotated[
            str,
            typer.Option(
                "--profile", "-p", help="Profile id from configs/, or a path to a YAML file."
            ),
        ] = "housing_stability",
        config_dir: Annotated[
            Path | None,
            typer.Option("--config-dir", help="Directory containing profile YAML files."),
        ] = None,
        output: Annotated[
            Path, typer.Option("--output", "-o", help="Directory for generated reports.")
        ] = Path("output/scheduled"),
        db: Annotated[Path, typer.Option("--db", help="History database.")] = Path(
            "output/history.db"
        ),
        label: Annotated[str, typer.Option("--label", help="History label for this run.")] = (
            "scheduled"
        ),
        email_to: Annotated[
            list[str] | None,
            typer.Option("--email-to", help="Email recipient; repeat for multiple recipients."),
        ] = None,
    ) -> None:
        """Run one scheduler-safe audit, record history, report, and optionally email."""
        from grant_assistant.automation import run_scheduled_audit
        from grant_assistant.env import load_environment
        from grant_assistant.workflow import setup_logging

        setup_logging()
        load_environment()
        try:
            result = run_scheduled_audit(
                data_file,
                profile,
                output_dir=output,
                db_path=db,
                label=label,
                recipients=email_to,
                config_dir=config_dir,
            )
        except Exception as exc:
            typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc

        typer.secho(
            f"Run #{result.run_id} recorded; report: {result.report_path}", fg=typer.colors.GREEN
        )
        if result.email_sent:
            typer.secho("Email summary sent.", fg=typer.colors.GREEN)
