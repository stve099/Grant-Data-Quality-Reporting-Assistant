---
name: new-grant-profile
description: Create a new YAML grant reporting profile for a funder — field mappings, controlled vocabularies, follow-up schedule, performance measures, outcome definitions, and blocking rules. Use when onboarding a new grant, funder, or reporting period.
---

# Create a grant profile

A profile is the complete configuration for one funder's reporting: how to read their
extract, which values are legal, what counts as success, and what they measure. Nothing
about a funder should be hardcoded in Python.

## 1. Start from an existing profile

```bash
cp configs/housing_stability.yaml configs/<new_id>.yaml
```

`housing_stability.yaml` is the fuller example (annual period, three follow-up milestones).
`rapid_rehousing.yaml` shows the advanced options: a broader successful-exit definition,
severity overrides, blocking rules, and a program-scoped measure.

## 2. Fill in the sections

**Identity** — `profile_id` must be unique (it is the `--profile` argument);
`reporting_period.end` must not precede `start`.

**Programs** — canonical `name` plus every `alias` that appears in the real data.
Unmatched labels fire DQ-026 (blocking); aliases are normalized and reported as
informational DQ-027.

**field_mappings** — source spreadsheet header → canonical column. Matching ignores case,
spaces, hyphens, and underscores. A mapping to `client_id` is required. Canonical columns
are listed in `src/grant_assistant/schema.py` and on the app's Configuration Help page.

**controlled_values** — the legal vocabulary per field. Quote anything YAML would parse as
a boolean: `"Yes"`, `"No"`, `"On"`. Values outside the list fire DQ-028.

**followup_schedule** — each entry generates an overdue rule and completion-rate metrics.
`completion_field` must be a canonical date column; `grace_days` is the window before
"due" becomes "overdue".

**exit_destination_categories** and **successful_exit_categories** — these define what the
grant counts as a good outcome. The `permanent_housing` category additionally drives the
permanent-housing rate metric.

**performance_measures** — `metric` must be a key from `available_measure_metrics()`. Add
`program: <canonical name>` to scope a measure to one program.

**Audit tuning** — `income_cap`, `max_household_size`, `max_age`, plus
`severity_overrides` (per rule ID) and `blocking_rules` to match how strict the funder is.

## 3. Validate and smoke-test

```bash
uv run grant-assistant validate-config
uv run grant-assistant audit sample_data/housing_program_flawed.csv --profile <new_id> --no-export
uv run grant-assistant analyze sample_data/housing_program_flawed.csv --profile <new_id> --no-export
```

Validation errors name the exact field and problem. Check that programs resolve (no
unexpected DQ-026), that controlled-value findings are real problems rather than a
vocabulary you forgot to list, and that every measure produces an actual value rather than
"n/a" (an "n/a" usually means a misspelled `metric` key).

## 4. Add a test if the profile encodes new behavior

Profiles that exercise new logic — a new metric key, a new severity override pattern —
deserve a test in `tests/test_measures.py` or `tests/test_configuration.py` asserting the
computed result. Pure configuration clones do not need one.
