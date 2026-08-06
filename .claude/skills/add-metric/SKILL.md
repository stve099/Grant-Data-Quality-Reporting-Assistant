---
name: add-metric
description: Add a deterministic metric to the analytics layer and wire it everywhere it belongs — metric_lookup, the agent tools, the fact sheet, and the run history. Use when the user wants a new calculated figure, measure input, or headline number.
---

# Adding a metric

Every number this project shows is computed in Python and covered by a test. A
metric added in the wrong place either never reaches the analyst, or — worse —
gets derived by the model instead, which the grounding contract forbids.

## Where it goes

1. **Compute it** in `analytics/metrics.py`, inside `compute_analytics`. Add the
   field to `AnalyticsResult` with a type and a comment saying what it means
   when it is `None`. A rate with a zero denominator is `None`, never `0.0`.

2. **Register it** in `AnalyticsResult.metric_lookup()`. This one call feeds
   three consumers at once — the AI fact sheet, `get_metric`/`list_metrics`, and
   the run history — so registering is what makes a metric real. A metric that
   exists on the model but not in the lookup is invisible to the analyst and to
   trending.

3. **Expose the breakdown** through `agents/tools.py` only if the analyst needs
   detail the lookup cannot carry (a per-category mapping, say). Tool results
   must stay aggregated: no client-level rows, ever.

4. **Test the expected value** in `tests/test_analytics.py` against the
   controlled fixture, not the generated sample. Assert the number, not that it
   is non-null.

## Guardrails

- **Small denominators.** If the metric is a rate, respect `SMALL_SAMPLE_N`; a
  rate over 4 exits is noise and must be flagged as such downstream.
- **Suppression before publication.** Anything disaggregated by demographic
  needs a suppression rule before it reaches a report.
- **Do not let the model derive it.** If you find yourself writing a prompt
  instruction like "add these two categories together", stop and add the metric
  instead. `unreported_demographics` exists precisely because the model was
  summing category counts and calling the result data.

## Verify

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run grant-assistant analyze sample_data/housing_program_flawed.csv
```

Then confirm the analyst can actually reach it:

```bash
uv run grant-assistant ask sample_data/housing_program_flawed.csv "What is <metric>?"
```

If the answer says the figure is unavailable, the metric is computed but not
registered — go back to step 2.
