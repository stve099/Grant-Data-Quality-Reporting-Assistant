# Contributing

Thanks for your interest in improving the Grant Data Quality & Reporting Assistant!

## Development setup

```bash
uv sync --extra dev
uv run pre-commit install
```

## Workflow

1. Create a branch from `main`.
2. Make your change with tests. Everything in `src/grant_assistant` (except `ui/`) should
   be covered; new audit rules need a rule-level test and, if the sample generator injects
   the error, a manifest expectation.
3. Run the full quality gate locally — CI enforces all of it:

   ```bash
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy
   ```

4. Open a pull request describing the behavior change and how you verified it.

## Adding an audit rule

1. Implement the rule in `src/grant_assistant/audit/rules.py` using the `@rule` decorator
   (pick the next free `DQ-###` id and a sensible category/severity).
2. Add a targeted test in `tests/test_audit_rules.py` using the row-builder helpers.
3. If the flawed sample should demonstrate it, inject the error in
   `src/grant_assistant/datagen/generator.py` and log it to the manifest — the manifest
   test will then enforce detection forever.
4. Document nothing else: the CLI `rules` command, the Configuration Help page, and the
   audit workbook all pick the rule up automatically from the registry.

## Adding a metric or performance-measure key

1. Compute it in `analytics/metrics.py` and add it to `metric_lookup()` and/or the measure
   lookup in `_evaluate_measures`.
2. Add expected-value tests in `tests/test_analytics.py` or `tests/test_measures.py`.
3. List the new key in `available_measure_metrics()` and `docs/creating_profiles.md`.

## Ground rules

- No real client data, ever — sample data must come from the generator.
- No secrets in the repository; configuration via environment variables.
- The AI must never be the source of a number: calculate in Python, narrate with AI.
