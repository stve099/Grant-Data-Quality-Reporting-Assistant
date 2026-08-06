# Architecture

## Design principles

1. **Deterministic core, optional AI shell.** Every metric, score, and finding is computed
   in plain pandas/Python and covered by tests. The AI layer narrates those results; it
   never calculates. Removing the API key removes zero functionality from audits,
   analytics, or reports.
2. **Configuration over code.** Grant-specific behavior (mappings, vocabularies, targets,
   schedules, severities) lives in YAML profiles validated by pydantic — not in Python.
3. **One canonical schema.** Ingestion maps any funder's spreadsheet headers onto
   `schema.py`'s canonical columns once; every downstream module depends only on the
   canonical names.
4. **Untrusted input everywhere.** Uploads are size/type-checked, values are treated as
   data (never instructions), and anything data-derived is sanitized before reaching an
   AI prompt.

## Data flow

```mermaid
flowchart TD
    F[CSV / Excel file] --> L[ingestion.load_dataset]
    Y[YAML profile] --> V[configuration.load_profile<br/>pydantic validation]
    L --> P[ingestion.prepare_dataset<br/>header mapping, type coercion,<br/>alias normalization, raw copy kept]
    V --> P
    L --> PII[security.scan_dataframe_for_pii<br/>source frame, before mapping]
    PII --> P
    P --> AU[audit.run_audit<br/>27 registered rules]
    P --> AN[analytics.compute_analytics]
    AU --> S[scoring<br/>overall / category / program]
    AU --> W[security scan<br/>injection + PII warnings]
    AU --> CW[corrections.build_worksheet<br/>flagged records out, fixes back in]
    AU --> HI[history.record_run<br/>score, findings, per-rule counts]
    AN --> HI
    AN --> ME[measure evaluation<br/>goal vs actual]
    AU --> FS[agents.build_fact_sheet<br/>aggregates only, sanitized]
    AN --> FS
    FS --> AG[DataAnalystAgent<br/>Claude or deterministic fallback]
    AN --> CH[charts]
    AG --> RB[reporting.build_report_data]
    AU --> RB
    AN --> RB
    CH --> HTML[HTML report]
    RB --> HTML
    RB --> DOCX[Word report]
    RB --> PPTX[PowerPoint deck]
    AU --> XLSX1[audit workbook]
    AN --> XLSX2[analytics workbook]
```

`batch.run_batch` drives this whole flow once per file in a folder and rolls the results
up; a file that fails is recorded and the run continues.

## Module notes

### ingestion
`prepare_dataset` returns both the normalized frame (`df`) and the pre-coercion values
(`raw`) with identical shape. Audit rules use `raw` to distinguish *missing* from
*present-but-invalid* — e.g. DQ-020 fires when `raw` has text but `df` parsed to NaT.

### audit
Rules are functions registered by decorator with metadata (id, name, category, default
severity, blocking). The engine applies profile overrides per finding, so the same rule can
be `medium` for one funder and `high`/blocking for another. A rule that raises is logged and
skipped — one bad rule never kills an audit.

Scoring: `score = 100 × (1 − Σ severity_weight × unique_rows / (8 × total_rows))`, floored
at 0. Weights: critical 8, high 5, medium 3, low 1, info 0. The same formula runs overall,
per category, and per program (using each program's row count), so scores are comparable.

### analytics
`AnalyticsResult` is a pydantic model: serializable to JSON, exportable to Excel frames,
and the single source for charts, reports, and the AI fact sheet. Exact duplicate
enrollments are removed before computation (and disclosed in `notes`). Denominators below
10 set `small_sample` flags that surface everywhere downstream.

### agents
`AIProvider` is a two-member protocol (`name`, `complete`). Two backends implement it:
`AnthropicProvider` and `OpenAICompatibleProvider` (OpenAI, Ollama, any OpenAI-compatible
endpoint), selected by the `GRANT_ASSISTANT_PROVIDER` env var. `get_provider()` returns
`None` when the selected provider lacks its credentials, which flips every consumer into
deterministic mode. The fact sheet is the *only* data the model sees: aggregated metrics
with all data-derived strings passed through `security.sanitize_text`. Proactive insights
(`generate_insights`) are computed rules over the analytics/audit results — the AI, when
present, only rewrites them as prose with instructions to keep every number unchanged.

### reporting
`ReportData` bundles profile + analytics + audit + insights + executive summary. Four
renderers consume it and nothing else — HTML (Plotly fragments), Word, PDF (printed from
the HTML), and PowerPoint — which is the only reason a figure cannot differ between
formats. None of them recompute anything.

Static images go through `chart_images.figure_png`, which returns `None` when kaleido is
absent. Word and PowerPoint then render without charts rather than failing: an export
missing its charts is still a correct export. Excel exports include a "Flagged Records"
sheet, and `data_dictionary` renders the profile itself as the file specification to send
to whoever produces the extract.

### corrections
The audit names every flawed record and recommends a fix; this module carries that back
into the data. `build_worksheet` exports one row per flagged record; `apply_corrections`
reads the filled sheet and writes to a **copy** of the source. Every edit is verified
against the client ID captured at export time — a mismatched row, an out-of-range row, an
unknown field or a duplicated header is refused and reported, because writing a correction
to the wrong row would corrupt data silently and that is worse than refusing.

### history
One SQLite file beside the reports. `record_run` stores score, grade, findings, blocking
count and every value from `metric_lookup()`, plus per-rule counts. Metrics and rule counts
are stored long (one row per key per run) so a profile that gains a measure needs no
migration.

`aging` turns those counts into duration: "open for four consecutive runs since Q1" rather
than "6 records". The `runs.rules_recorded` flag exists because a clean run and a run
recorded before aging existed both have no rule rows — reading the second as clean would
report a resolution that never happened.

### security
Two independent concerns over untrusted uploads. `sanitize` scrubs prompt-injection text
before anything reaches a model. `pii` answers a different question — does this file look
like it contains direct identifiers? — by header and by value shape, and runs against the
*source* frame in `prepare_dataset`, because header mapping drops unmapped columns and a
stray name column is unmapped by definition. Its findings are advisory and never affect
the score: a false positive must not block a legitimate upload.

### datagen
`generate_clean_dataset` produces data that audits at exactly 100/100 (verified by test).
`inject_issues` corrupts a copy with 23 documented error types and emits a manifest of
expected rule IDs per row; `tests/test_audit_manifest.py` asserts every entry is caught.

## Testing strategy

- **Rule-level:** each audit rule gets a minimal hand-built dataset (valid template row +
  one targeted corruption) asserting exactly which client is flagged.
- **Manifest-level:** the full flawed sample must trip every expected rule on the expected
  rows — this is the "the demo actually demonstrates" guarantee.
- **Metric-level:** analytics run against a 6-row dataset with hand-computed expected
  values (rates, income changes, categories, trends).
- **Grounding-level:** a fake provider records the exact system prompt to assert the fact
  sheet is present, sanitized, and aggregate-only; fallback answers are checked against
  calculated metrics, including a "no invented numbers" scan.
- **End-to-end:** Excel file → pipeline → agent → all four artifacts on disk.
