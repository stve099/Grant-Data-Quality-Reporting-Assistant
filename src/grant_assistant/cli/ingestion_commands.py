"""CLI commands for flattening related grant-data extracts."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def register_ingestion_commands(app: typer.Typer) -> None:
    """Register relational-ingestion commands without expanding the main CLI module."""

    @app.command("merge-datasets")
    def merge_datasets(
        primary_file: Annotated[Path, typer.Argument(help="Primary CSV or Excel extract.")],
        related_files: Annotated[
            list[Path],
            typer.Argument(help="One or more related extracts with unique join keys."),
        ],
        output: Annotated[Path, typer.Option("--output", "-o", help="Merged CSV path.")],
        profile: Annotated[
            str,
            typer.Option(
                "--profile", "-p", help="Profile id from configs/, or a path to a YAML file."
            ),
        ] = "housing_stability",
        join_on: Annotated[
            str, typer.Option("--join-on", help="Canonical schema field used as the join key.")
        ] = "client_id",
        config_dir: Annotated[
            Path | None,
            typer.Option("--config-dir", help="Directory containing profile YAML files."),
        ] = None,
    ) -> None:
        """Flatten related extracts into one audit-ready CSV."""
        from grant_assistant.ingestion import merge_related_datasets
        from grant_assistant.workflow import resolve_profile

        try:
            grant_profile = resolve_profile(profile, config_dir)
            merged = merge_related_datasets(primary_file, related_files, grant_profile, join_on)
            output.parent.mkdir(parents=True, exist_ok=True)
            merged.to_csv(output, index=False)
        except Exception as exc:
            typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.secho(f"Merged {len(related_files)} related file(s): {output}", fg=typer.colors.GREEN)
