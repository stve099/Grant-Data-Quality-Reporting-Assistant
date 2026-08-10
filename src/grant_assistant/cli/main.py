"""Typer application bootstrap for ``grant-assistant``.

Core commands are registered from :mod:`grant_assistant.cli.commands`; specialized
relational-ingestion and scheduled-run commands live in focused modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from grant_assistant import __version__
from grant_assistant.cli.automation_commands import register_automation_commands
from grant_assistant.cli.ingestion_commands import register_ingestion_commands
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


def _register_commands() -> None:
    # Importing the module applies its @app.command decorators after this bootstrap
    # has initialized the shared app and option aliases.
    from grant_assistant.cli import commands

    _ = commands
    register_automation_commands(app)
    register_ingestion_commands(app)


_register_commands()
