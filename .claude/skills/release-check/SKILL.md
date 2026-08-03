---
name: release-check
description: Run the full pre-release verification for the grant assistant — quality gates, artifact regeneration, eval harness, interface smoke tests, and secret scan — then report actual results. Use before tagging a release, opening a PR, or claiming the project is done.
---

# Release check

Every claim in this project's README is meant to be reproducible. This procedure verifies
them. Report the **actual** output of each step; never mark a step green without running it.

## 1. Quality gates

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

All four must pass. A failure here stops the release — diagnose, fix, re-run.

## 2. Prompt evals

```bash
uv run grant-assistant eval
```

The deterministic (non-AI) suite must be 100%. With a provider configured (`ANTHROPIC_API_KEY`,
or `GRANT_ASSISTANT_PROVIDER=openai` with `OPENAI_API_KEY`), also run the AI suite and record
the pass rate — a regression here means the grounding contract slipped.

## 3. Regenerate artifacts

```bash
uv run grant-assistant generate-sample-data
uv run grant-assistant report sample_data/housing_program_flawed.csv --profile housing_stability --output examples --format all
uv run python scripts/capture_screenshots.py
uv run pytest tests/test_audit_manifest.py
```

Confirm the flawed sample still trips every documented rule and the example PDF/HTML/Word
files regenerate cleanly.

## 4. Interface smoke tests

```bash
uv run grant-assistant --help
uv run grant-assistant validate-config
uv run grant-assistant audit sample_data/housing_program_clean.csv --no-export   # expect 100.0/100
uv run grant-assistant audit sample_data/housing_program_flawed.csv --no-export  # expect blocking issues, exit 1
uv run grant-assistant full-run sample_data/housing_program_flawed.csv --output output
```

Then launch the Streamlit app and confirm it starts with no exception and the pages render:

```bash
uv run streamlit run src/grant_assistant/ui/app.py
```

## 5. Safety scan

- No `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, token, or credential anywhere outside
  `.env.example`.
- `.env` is git-ignored and not staged.
- Sample data contains no name, SSN, birth date, phone, email, or address fields
  (`tests/test_datagen.py::test_no_real_pii_fields` enforces this).
- Generated data stays inside the profile vocabularies
  (`test_clean_data_uses_only_controlled_values`).

## 6. Documentation truth check

Read the README's feature claims and confirm each one is real. Any feature that does not
work must be removed from the docs or moved to the Limitations section — an inaccurate
README is worse than a missing feature.

## Report

Finish with a table of every command run and its actual result, then state any remaining
limitations honestly.
