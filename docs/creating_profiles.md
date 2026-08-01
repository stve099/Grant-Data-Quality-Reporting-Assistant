# Creating Grant Profiles

A grant profile is one YAML file in `configs/` that tells the assistant everything about a
grant: how to read your spreadsheet, which values are valid, what outcomes count as success,
what the funder measures, and how strictly to audit. Start by copying
`configs/housing_stability.yaml` and validate as you edit:

```bash
uv run grant-assistant validate-config
```

Validation errors name the exact field and problem.

## Field-by-field guide

### Identity

```yaml
profile_id: my_grant          # unique id used with --profile
grant_name: My Housing Grant
grantor: Example Foundation   # optional
description: >                # appears in the report's Program Overview
  One-paragraph description of the grant.
```

### Reporting period

```yaml
reporting_period:
  start: 2025-01-01
  end: 2025-12-31             # must not precede start
```

Dates after the period end are flagged by rule DQ-034.

### Programs and aliases

```yaml
programs:
  - name: Rapid Re-Housing            # canonical label used everywhere
    aliases: ["RRH", "Rapid Rehousing"]
    description: Optional sentence for the report.
```

Alias matching is case-insensitive. Labels matching an alias are normalized automatically
(and reported informationally by DQ-027); labels matching nothing are flagged by DQ-026.

### Field mappings

Map your spreadsheet headers (left) to canonical columns (right). Matching ignores case,
extra spaces, hyphens, and underscores.

```yaml
field_mappings:
  "Client ID": client_id
  "Entry Date": enrollment_date
  # ...
```

Canonical columns (the complete list lives in `src/grant_assistant/schema.py` and on the
app's Configuration Help page):

`client_id, household_id, program, enrollment_date, enrollment_status, exit_date,
exit_destination, household_size, adults, children, age, gender, race, ethnicity,
veteran_status, disability_status, entry_income, exit_income, assessment_status,
exit_plan_status, followup_3m_date, followup_6m_date, followup_12m_date`

A column mapping to `client_id` is required; other canonical columns missing from an upload
are created empty (and reported).

### Required fields and controlled vocabularies

```yaml
required_fields: [client_id, household_id, program, enrollment_date]

controlled_values:
  enrollment_status: [Active, Exited]
  veteran_status: ["Yes", "No", "Unknown"]   # quote Yes/No — bare YAML parses them as booleans!
```

Blank required fields fire DQ-001 (blocking by default). Values outside a controlled list
fire DQ-028.

### Follow-up schedule

```yaml
followup_schedule:
  - key: 3_month                    # used in metric names: followup_3_month_completion_rate
    label: 3-Month Follow-Up
    months_after_exit: 3
    completion_field: followup_3m_date   # must be a canonical date column
    grace_days: 14                  # days past due before flagged overdue
```

Each milestone generates an overdue rule (DQ-050, DQ-051, …) and completion-rate metrics.

### Exit destination categories and success definitions

```yaml
exit_destination_categories:
  permanent_housing: ["Rental by client, no subsidy", Homeownership]
  temporary_housing: ["Transitional housing"]
  # any category names you like

successful_exit_categories: [permanent_housing]   # categories that count as success
```

`permanent_housing` is special: it also feeds the permanent-housing-rate metric.

### Performance measures

```yaml
performance_measures:
  - id: M-1
    name: Permanent housing exit rate
    metric: permanent_housing_rate   # see list below
    target: 60
    unit: percent                    # percent | count | currency
    direction: at_least              # at_least | at_most
  - id: M-2
    name: RRH permanent housing rate
    metric: permanent_housing_rate
    target: 65
    unit: percent
    program: Rapid Re-Housing        # optional: scope the measure to one program
```

Program-scoped measures (with `program:`) support these metrics: `enrollments`,
`exits`, `exit_rate`, `successful_exit_rate`, `permanent_housing_rate`,
`avg_income_change`, `median_income_change`.

Available metric keys:
`total_enrollments, households_served, total_exits, exit_rate, successful_exit_rate,
permanent_housing_rate, pct_income_increased, avg_income_change, median_income_change,
assessment_completion_rate, exit_plan_completion_rate, overall_followup_completion_rate,
followup_<key>_completion_rate`

### Audit tuning

```yaml
income_cap: 300000        # incomes above this are implausible (DQ-025)
max_household_size: 12    # DQ-023
max_age: 110              # DQ-022

severity_overrides:       # per-rule severity: critical|high|medium|low|info
  DQ-003: high

blocking_rules: [DQ-004, DQ-010]   # additional rules that block submission
```

Rule IDs: run `uv run grant-assistant rules` for the full list with default severities.

### Demographics and report settings

```yaml
demographic_fields: [gender, race, ethnicity, veteran_status, disability_status]
age_group_bounds: [18, 25, 35, 45, 55, 62]   # upper bounds; a final 62+ band is added

report:
  title: My Grant — Annual Outcome Report
  prepared_by: Data Team
```

## Tips

- Keep one profile per funder/reporting cycle; profiles are cheap and explicit.
- Quote any YAML scalars that could parse as booleans or numbers (`"Yes"`, `"No"`, `"On"`).
- If a legitimate destination or status keeps firing DQ-028, add it to `controlled_values`
  rather than ignoring the finding.
- Use `severity_overrides` and `blocking_rules` to mirror how strict your funder actually is.
