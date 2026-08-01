# CLAUDE.md

Working notes for Claude Code in this repository. Read this before changing code.

## What this project is

A configurable data quality audit + grant reporting application for housing and human
services programs. Three interfaces (Streamlit app, Typer CLI, MCP server) sit on one
deterministic core. **All sample data is synthetic.**

## The one rule that governs everything

**Calculate in Python, narrate with AI.** Every number that reaches a dashboard, report,
or AI answer is computed in `analytics/` or `audit/` and covered by a test. The model is
given a sanitized, aggregated fact sheet and typed read-only tools; it never does
arithmetic and never sees client-level rows.

If you are tempted to let the model compute something, add a deterministic function and a
tool instead.

## Commands

```bash
uv sync --extra dev --extra pdf --extra mcp   # install everything
uv run pytest                                  # tests
uv run ruff check . && uv run ruff format .    # lint + format
uv run mypy                                    # types
uv run grant-assistant --help                  # CLI
uv run streamlit run src/grant_assistant/ui/app.py
uv run grant-assistant eval                    # prompt-eval harness
uv run python scripts/capture_screenshots.py   # README screenshots
```

Windows note: this repo often lives in OneDrive, which breaks uv's hardlinks. Prefix uv
commands with `UV_LINK_MODE=copy` (PowerShell: `$env:UV_LINK_MODE='copy'`) if you hit
`os error 396` or an access-denied `.dist-info` failure.

## Architecture

```
configuration/  pydantic profile models + YAML loader (the funder's rules)
ingestion/      file loading, header mapping, type coercion; keeps a raw copy
audit/          rule registry (@rule decorator), 27 rules, scoring model
analytics/      deterministic metrics, comparison, plotly charts
agents/         provider abstraction, fact sheet, tools, workflows, insights, analyst
evals/          prompt-eval dataset, graders, runner
security/       prompt-injection scrubbing for untrusted uploads
reporting/      HTML (Jinja2), Word, PDF, Excel exports
datagen/        synthetic clean + flawed sample generator with issue manifest
cli/ ui/        Typer CLI and Streamlit app (presentation only)
```

`ingestion.prepare_dataset` returns both `df` (coerced) and `raw` (original strings) with
the same index. Audit rules compare the two to tell *missing* from *present but invalid* —
do not drop `raw`.

## Conventions

- Python 3.12+, full type hints, `from __future__ import annotations`.
- Docstrings explain *why*; skip narrating what the code plainly does.
- Comments only for constraints the code cannot express.
- Line length 100, Ruff formatted. No `# type: ignore` without a reason on the same line.
- Pydantic models for anything crossing a module boundary or serialized.
- UI code holds no business logic. If a page function computes something, move it.
- Never commit secrets. API keys come from environment variables only.
- Never add real client data. Sample data comes from `datagen` only.

## Adding things

**An audit rule** — use the `/add-audit-rule` skill. Register with `@rule` in
`audit/rules.py`, add a targeted test in `tests/test_audit_rules.py`, and if the flawed
sample should demonstrate it, inject it in `datagen/generator.py` and log it to the
manifest (the manifest test then enforces detection permanently).

**A grant profile** — use the `/new-grant-profile` skill. Validate with
`uv run grant-assistant validate-config`.

**A metric** — compute it in `analytics/metrics.py`, add it to `metric_lookup()`, expose
it through `agents/tools.py` if the analyst should reach it, and test the expected value.

## Verification before you call something done

Run all four gates; CI enforces the same set:

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
```

For UI or report changes, also regenerate artifacts and look at them:
`uv run grant-assistant report sample_data/housing_program_flawed.csv --output examples`.

Do not claim a feature works without running it.

## Gotchas

- pandas 3 uses the `str` dtype for text columns; use `pd.api.types.is_string_dtype`,
  never `dtype == object`.
- The Streamlit nav is several radio groups; a callback clears the others so exactly one
  row stays active. Changing that will produce two highlighted rows.
- PDF export lays the page out at 720px (Letter minus margins) because Plotly sizes its
  SVGs once at load; changing the viewport width will cut charts off the page.
- Follow-up math lives in `followups.py` and is shared by audit rules and analytics so the
  two can never disagree. Change it in one place.
