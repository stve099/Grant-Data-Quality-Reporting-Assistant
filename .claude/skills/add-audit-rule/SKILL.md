---
name: add-audit-rule
description: Add a new data quality audit rule to the grant assistant, with its test, optional sample-data injection, and manifest entry. Use when the user wants to detect a new kind of data problem, add a DQ- rule, or extend the audit engine.
---

# Add an audit rule

A rule is not finished until it is registered, tested, and — if the demo data should show
it off — injected into the flawed sample and recorded in the manifest. Follow all four
steps; skipping the manifest is how a rule silently stops being demonstrated.

## 1. Pick the identity

Run `uv run grant-assistant rules` to see what exists and choose the next free ID in the
right band:

| Band | Category | Meaning |
|---|---|---|
| DQ-00x | completeness | required or expected fields are empty |
| DQ-01x | uniqueness | duplicate clients, households, or rows |
| DQ-02x | validity | value is present but impossible or out of vocabulary |
| DQ-03x | consistency | two fields contradict each other |
| DQ-04x | case_management | assessments, exit plans |
| DQ-05x | timeliness | follow-up milestones (one per schedule entry) |
| DQ-06x | statistical | outliers and distribution anomalies |

Severity guide: **critical** corrupts every downstream rate; **high** distorts a reported
measure or blocks submission; **medium** affects a breakdown; **low** is completeness-only;
**info** never reduces the score. Set `blocking=True` only when a funder would reject the
submission.

## 2. Implement it in `src/grant_assistant/audit/rules/<category>.py`

Rules live in one module per category — `completeness`, `uniqueness`, `validity`,
`consistency`, `case_management`, `timeliness`, `statistical`. Shared helpers
(`_records`, `_issue`, `_exited`, `_s`) come from `audit.rules._helpers`. A new
category needs a module *and* an import in `audit/rules/__init__.py`; without it
the decorators never run and the rule silently does not exist.

```python
@rule(
    "DQ-0XX",
    "Short rule name",
    "category",
    Severity.MEDIUM,
    blocking=False,
    description="One line for the rules listing and Configuration Help page.",
)
def my_rule(ctx: RuleContext) -> list[AuditIssue]:
    df, raw = ctx.data.df, ctx.data.raw
    mask = ...  # boolean Series aligned to df
    records = _records(ctx, mask, field=schema.SOME_COLUMN, value_col=schema.SOME_COLUMN)
    if not records:
        return []
    return [
        _issue(
            "DQ-0XX",
            "Short rule name",
            "category",
            Severity.MEDIUM,
            False,
            "What is wrong and why it matters for the report.",
            "What the user should do about it.",
            records,
        )
    ]
```

Requirements:
- Read `raw` when you need the original string (to tell *missing* from *invalid*); read
  `df` for coerced dates and numbers.
- Take thresholds from `ctx.profile`, never hardcode them.
- `mask` must be a boolean Series; `_records` calls `.fillna(False)` for you.
- Return `[]` when nothing is found — never an issue with zero records.

## 3. Add a targeted test in `tests/test_audit_rules.py`

Use the row builders from `tests/conftest.py`. Assert *which* client is flagged, and add a
negative case if the rule could over-fire:

```python
def test_my_rule_detected(profile):
    rows = [make_row(some_field="bad"), make_row(client_id="C-9")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-0XX"] == {"C-1"}
```

`VALID_ACTIVE` and `VALID_EXITED` are clean templates — a rule that fires on an unmodified
template is over-firing and will break `test_fully_valid_rows_produce_no_findings`.

## 4. Demonstrate it in the sample data (optional but preferred)

In `src/grant_assistant/datagen/generator.py`, inside `inject_issues`, add a numbered block
and log it:

```python
idx = take(any_pool, 3)  # or exited_pool for exit-dependent rules
df.loc[idx, H["some_field"]] = "bad value"
log("Human-readable description of the injected error", ["DQ-0XX"], idx)
```

Then regenerate and verify:

```bash
uv run grant-assistant generate-sample-data
uv run pytest tests/test_audit_manifest.py
```

`test_every_injected_issue_is_detected` now enforces this rule forever.

## 5. Verify

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run grant-assistant audit sample_data/housing_program_flawed.csv --no-export
```

Confirm the new rule appears in the findings list with a sensible count. Nothing else needs
updating: the CLI `rules` command, the Configuration Help page, and the audit workbook all
read from the registry automatically.
