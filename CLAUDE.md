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
configuration/  pydantic profile models + YAML loader (the funder's rules), plus a
                generator that drafts a profile from a sample extract
ingestion/      file loading, header mapping, type coercion; keeps a raw copy
audit/          rule registry (@rule decorator), 28 rules, scoring model
analytics/      deterministic metrics, period comparison, plotly charts
agents/         provider abstraction, fact sheet, tools, workflows, insights, analyst
evals/          prompt-eval dataset, graders, runner, model_comparison
security/       prompt-injection scrubbing and PII pre-flight for untrusted uploads
corrections/    export flagged records, take fixes back, apply them to a copy, and
                report the before/after both entry points show
history/        SQLite run history + issue aging across reporting periods
reporting/      HTML (Jinja2), Word, PDF, PowerPoint, Excel, data dictionary
datagen/        synthetic clean + flawed sample generator with issue manifest
batch.py        audit a folder of extracts and roll the results up
env.py          .env loading shared by both entry points, with a test opt-out
cli/ ui/        Typer CLI and Streamlit app (presentation only)
```

`ingestion.prepare_dataset` returns both `df` (coerced) and `raw` (original strings) with
the same index. Audit rules compare the two to tell *missing* from *present but invalid* —
do not drop `raw`. It also carries `pii_warnings`, scanned against the *source* frame
before header mapping drops unmapped columns — a stray name column is unmapped by
definition, so scanning later would never see it.

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
the `audit/rules/` module for its category (a new category needs an import in
`audit/rules/__init__.py`, or its rules never register), add a targeted test in
`tests/test_audit_rules.py`, and if the flawed
sample should demonstrate it, inject it in `datagen/generator.py` and log it to the
manifest (the manifest test then enforces detection permanently).

**A grant profile** — use the `/new-grant-profile` skill. Validate with
`uv run grant-assistant validate-config`.

**A metric** — use the `/add-metric` skill. Compute it in `analytics/metrics.py`, add it to
`metric_lookup()`, expose it through `agents/tools.py` if the analyst should reach it, and
test the expected value. `metric_lookup()` feeds the fact sheet, the agent tools, and the
history store at once, so one addition reaches all three.

**A report renderer** — take `ReportData` and nothing else. HTML, Word, PDF and PowerPoint
are four renderers over one source, which is the only reason a figure cannot differ
between them; do not recompute anything in a renderer. Charts go through
`reporting/chart_images.figure_png`, which returns `None` when the optional backend is
absent — an export missing its charts is still a correct export, so degrade rather than
raise. Export it from `reporting/__init__.py` and wire it into `report --format`.

**A CLI command** — add it to `cli/main.py`, then add a smoke test to `tests/test_cli.py`.
The logic belongs in a module and is tested there; the CLI test exists to catch wiring,
which is where these actually break (a stripped import, a missing symbol).

**Something backed by history** — write through `history/store.record_run` and read with
`load_history`. Both metrics and rule counts are stored long, one row per key per run, so
a profile that gains a measure needs no migration. If you add a column to `runs`, extend
`_migrate()`: databases created by earlier versions are expected to keep working, and
there is a test that builds an old schema by hand to prove it.

**A Streamlit page** — put the renderer in the `ui/*_pages.py` module for its section, export
it from `ui/pages.py`, and register it in `app.py` in both `NAV` and the router. Then add its
label to `ALL_PAGES` in `tests/test_ui_app.py`: that list is spelled out rather than imported
so a rename fails loudly instead of skipping. Every page must render with no dataset loaded.

**An MCP tool** — mirror an existing one in `mcp_server.py`, return aggregated shapes only,
and give it a real description; a tool without one is unusable by a model choosing between
ten. Add its name to the registration test.

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
- The session keeps the pre-mapping source frame so a dataset can be re-run under another
  profile or corrected in place, but only up to `ui.state.max_retained_source_rows()`. Above
  it `pipeline["source"]` is `None` on purpose — read it through `state.source_frame()` and
  offer `SOURCE_DROPPED_NOTE` rather than assuming a frame is there.
- `store_pipeline` clears every derived session key, so anything you want to survive a
  re-audit must be written *after* it, not before. `apply_correction_upload` is the example.
- `pdf_backend()` requires the chromium build the installed playwright names in its own
  `browsers.json`, not merely the import. Installing the `pdf` extra without running
  `playwright install chromium` is a no-backend environment, and the tests skip accordingly.
- Follow-up math lives in `followups.py` and is shared by audit rules and analytics so the
  two can never disagree. Change it in one place.
- Tests must not read a developer's `.env`. Both entry points load it through
  `env.load_environment()`, and the autouse fixture in `conftest.py` sets its opt-out. The
  Streamlit app's loader runs at import, so patching it by name could never work.
- One registered audit rule can emit several rule IDs (the follow-up sub-rules), so
  anything that filters by rule — `disabled_rules`, aging — must filter per *issue*, not
  per registration, or it will silently take siblings with it.
- Empty Excel cells read back as `NaN`, whose `str()` is the non-empty `"nan"`. Read
  worksheets with `keep_default_na=False` or an untouched sheet looks full of edits.
- Optional extras (`pdf`, `charts`, `pptx`, `mcp`, `openai`) must degrade, not crash. The
  test suite runs with and without them.
- This repo lives in OneDrive: a version bump can leave a locked `*.dist-info` behind and
  break the editable install. Delete the stale directory and re-sync if uv reports an
  access denial.
