# Changelog

## 1.5.1 — 2026-08-06

Maintenance from a full review of the repository. No new features; the changes
are to documentation, test coverage, and one visible formatting inconsistency.

### Changed
- **Word reports format large numbers with thousands separators.** The Word and
  PowerPoint renderers each carried a private copy of the same formatter and the
  copies had drifted: `1284` in one document, `1,284` in the other, from one
  calculation. They now share `reporting.formatting.format_value`, with a test
  asserting both reference the same object. This is the only user-visible change
  in the release.
- `evals/comparison.py` is now `evals/model_comparison.py`.
  `analytics/comparison.py` compares reporting periods and the two are unrelated,
  so every import had to spell out its full path to disambiguate.
- The Streamlit app is measured by coverage rather than excluded from it.
  `AppTest` executes the page script in-process, so the exclusion was hiding real
  signal: features added to the largest file in the repo were verified by
  nothing. It now reports 56%.

### Added
- **Documentation of the current architecture.** `CLAUDE.md` and
  `docs/architecture.md` described a ten-package project; there are fourteen.
  Neither mentioned `corrections/`, `history/`, `batch.py`, `security/pii.py`,
  `env.py`, `reporting/pptx_report.py` or `configuration/generator.py`.
  `CLAUDE.md` also gains procedures for the patterns established since — adding a
  report renderer, a CLI command, a history-backed feature, an MCP tool — and the
  gotchas that have cost real time.
- **CLI wiring tests**, taking `cli/main.py` from 40% to 80%. Ten of nineteen
  commands had no CLI-level test. Their logic was well covered; the wiring was
  not, and wiring is where they actually break — a stripped import, a missing
  symbol.
- **Streamlit smoke tests**: every page renders with and without data, plus a
  test asserting the page list matches the navigation, so a rename fails loudly
  instead of silently skipping.
- **PDF backend-detection tests**, covering the playwright, Edge and
  neither-available branches (60% to 71%).
- An **`/add-metric` skill** for a procedure `CLAUDE.md` documented but no skill
  covered.

Total coverage is 91% including the UI, on a larger denominator than the 89%
previously reported.

## 1.5.0 — 2026-08-06

Makes the results portable to the rooms where decisions happen, turns findings
into trends, and takes the guesswork out of two choices that were previously
made by feel: which model to run, and how to onboard a funder.

### Added
- **PowerPoint export** (`report --format pptx`) — an eleven-slide executive
  deck: title, at-a-glance figures, executive summary, three charts, measures
  against target, data quality with blocking issues named, findings, actions,
  and methodology. It consumes the same `ReportData` as the HTML and Word
  renderers, so a figure cannot differ between them — one source, three
  renderers. Requires the optional `pptx` extra; charts additionally need
  `charts`, and without either the deck degrades rather than fails.
- **Issue aging** — `record-run` now reports how long each finding has been
  open ("open for 4 consecutive runs since Q1") and what was resolved since the
  previous run. A count reads as a slip; a duration reads as a process that is
  not working. Cleanup that succeeded was previously invisible, because a fixed
  finding simply stops appearing.
- **Model comparison** (`compare-models`) — runs the evaluation across several
  models and ranks them, breaking ties on the worst single run before cost,
  because a model that averages well but collapses occasionally is worse than a
  steady one. Token totals are reported alongside scores: the cheapest model
  that clears the grounding bar is usually the right answer.
- **Profile generator** (`draft-profile`) — infers field mappings, programs,
  controlled vocabularies and the reporting period from a sample extract.
  Deliberately a draft: uncertain guesses are commented out rather than applied,
  unmapped columns and missing required fields are listed, and performance
  measures are left empty because targets come from the funder and cannot be
  read off a data file.

### Changed
- The history store records per-rule counts, and `runs` gains a
  `rules_recorded` flag. Without it a clean run and a run recorded before aging
  existed are indistinguishable — both have no rule rows — and reading the
  second as clean would report a resolution that never happened. Databases
  created by 1.4.0 are migrated automatically.

## 1.4.0 — 2026-08-05

Closes the loop from "this data is wrong" to "this data is fixed, and here is the
proof", and makes the tool usable on the file volumes programs actually produce.

### Added
- **PII pre-flight scan** — an upload is checked for direct identifiers before
  ingestion maps a column, by header (`Client Name`, `SSN`, `DOB`) and by value
  shape (SSN, email, phone, birth date). Surfaced in the CLI, the app, and the
  proactive insights. Advisory only: a false positive must never block a
  legitimate upload, so findings never affect the score. Scanning happens on the
  source frame, because header mapping drops unmapped columns and a stray name
  column is unmapped by definition.
- **Correction round-trip** — `correction-worksheet` exports every flagged record
  as an Excel workbook with instructions; `apply-corrections` reads it back,
  writes a corrected copy, and re-audits so the before and after are shown rather
  than assumed. Every edit is verified against the client ID captured at export
  time; a mismatched row, an out-of-range row, an unknown field or a duplicated
  header is refused and reported. The original file is never modified.
- **Data dictionary** (`data-dictionary`) — the file specification for whoever
  produces the extract, in Markdown or self-contained HTML. Generated entirely
  from the profile and the rule registry, so it cannot drift from what the engine
  enforces. Rules a profile disables are not listed.
- **Run history** — `record-run` stores a snapshot per run in SQLite (score,
  grade, findings, blocking count, and every headline metric); `history` shows
  runs oldest-first with per-run deltas, the overall trend, and optionally one
  metric over time. Metrics are stored long, so a profile that gains a measure
  needs no migration.
- **Batch mode** (`batch`) — audits every extract in a folder and writes a rollup.
  A file that cannot be processed is reported rather than dropped, the command
  exits non-zero when any file failed, and the batch score is weighted by rows so
  a 5-row file cannot swing it like a 5,000-row one.
- **Per-profile rule configuration** — `disabled_rules` drops rules a grant does
  not apply, with no score penalty; `rule_thresholds` tunes five statistical
  knobs. A profile naming nothing behaves exactly as before.
- **Charts in the Word report** — seven charts with captions, via the optional
  `charts` extra. Absence degrades rather than breaks.
- **Scale benchmark** (`scripts/benchmark.py`) plus scale tests at 20k rows.
  Measured: a 100k-row extract audits in about six seconds, with per-row cost
  rising only ~1.5x from 10k to 100k.
- **Six new MCP tools** — personal-information check, correction worksheet export
  and apply, batch audit, history, and data dictionary, taking the server to ten.
- **Usage accounting** — cached and reasoning token counts on the OpenAI path,
  running session totals, and optional cost from operator-supplied rates. There
  is no built-in price table: published rates change, and a stale number reports
  wrong money with total confidence.

### Changed
- Refusal eval cases are judged by the rubric model rather than by substring
  matching when a provider is configured, since a phrase list cannot tell a
  correct refusal from a differently worded one. Without a provider the code
  graders still run, so the deterministic suite keeps full coverage.
- The rubric judge's token budget was raised to 1200 after truncated JSON caused
  correct answers to be failed as "unparseable".

### Fixed
- `no_system_prompt_leak` treated the phrase "untrusted data" as a leak, failing
  a model for explaining *why* it refused an injection. It now flags structural
  giveaways plus any 14-word verbatim run from the prompt — a threshold measured
  from 36 real answers, whose largest honest overlap was 9 words.
- Age-band labels such as `45-54` are generated by analytics from the profile
  bounds, but `54` was not in the grader's allowlist, so any answer containing an
  age breakdown failed.
- Disabling a rule no longer disables its siblings: the follow-up sub-rules share
  one registration, so filtering happens per issue rather than per rule.
- Tests no longer inherit a developer's `.env`. Both entry points read it through
  `load_environment()`, whose documented opt-out the suite sets — the Streamlit
  app's loader runs at import, so patching it by name could never have worked.

## 1.3.0 — 2026-08-03

### Added
- **OpenAI-compatible AI provider** — `GRANT_ASSISTANT_PROVIDER` selects the backend
  (`anthropic` default | `openai` | `ollama`). The new `OpenAICompatibleProvider`
  implements `complete()`, streaming, and the agent tool loop, converting the
  Anthropic-shaped tool schemas to the OpenAI function-calling format internally so
  the rest of the codebase is unchanged. Ollama runs keyless against a local server
  and works against Ollama Cloud or any OpenAI-compatible endpoint via `OPENAI_BASE_URL`.
  Install with `uv sync --extra openai`. Extended thinking remains Anthropic-only and
  degrades to plain completion elsewhere. Tests cover request construction, the
  tool-result round-trip, streaming, provider selection, and agent integration with a
  stubbed client.
- **Repeated evaluation runs** (`grant-assistant eval --runs N`) — a hosted model is
  not reproducible even at temperature 0, so one run measures luck as much as quality.
  Reports the pass rate of each run with the mean, min and max, and separates cases
  that always pass from the intermittent ones. Every run is persisted to
  `eval_stability.json`, so a failure in one run is not erased by a later green run.
  The command exits non-zero if *any* run failed.
- **Backend provenance in eval reports** — `provider` and `model` are recorded and
  rendered, so results from different backends are no longer indistinguishable.
- **`unreported_demographics` metric** — the per-field total of missing, unknown and
  declined responses, exposed through `metric_lookup()` and returned by
  `get_demographics` as `not_reported`. Reports quote this figure routinely; without a
  calculated total the model had to add the categories itself, which the grounding
  contract forbids.

### Changed
- `ai_available()` and `get_provider()` now dispatch on the selected provider's
  credentials rather than only `ANTHROPIC_API_KEY`.
- Both API clients now use an explicit timeout (120s) and retry budget (2). A hung
  request previously blocked the Streamlit UI indefinitely with no feedback.
- The system prompt's arithmetic ban now names the specific cases the eval caught:
  subtracting two values to state a gap, and summing categories.

### Fixed
- Number extraction in the graders read the hyphen in measure IDs (`HS-1`), compound
  rule citations (`DQ-050/051/052`) and hyphenated words (`mid-2024`) as a minus sign,
  and left bare years from prose dates in place. All three produced false "ungrounded
  number" failures against any model whose formatting differed from Claude's.
- The `refusal-unavailable-field` eval case forbade a phrase its own rubric asked the
  model to say, so no correct refusal could pass. It is now graded by
  `grounded_numbers`, which catches an invented score as an untraceable number.
- Tests no longer inherit the developer's `.env`: the CLI's `load_dotenv()` wrote it
  into `os.environ` for the whole pytest process, so a working local configuration
  caused failures CI never saw.

## 1.2.0 — 2026-08-01

### Added
- **Prompt evaluation harness** (`grant-assistant eval`) — a graded dataset of 12 cases
  with seven code-based graders that mechanically verify the grounding contract
  (every number traced to a calculation, no client identifiers, refusal on
  unavailable data, no system-prompt disclosure), plus an optional model-based
  rubric judge. Cases run in parallel; reports written as markdown and JSON.
- **Anthropic API features** — prompt caching breakpoints on the stable fact-sheet
  system prompt and the tool block, streaming responses in the chat UI, extended
  thinking for narrative synthesis, explicit temperature control, and cache-hit
  token accounting.
- **Explicit workflow patterns** (`agents/workflows.py`) — routing (question →
  intent → handler, used by the deterministic analyst), chaining, and
  parallelization, each applied where it genuinely fits.
- **MCP resources and prompts** — `grant://profiles`, `grant://profile/{id}`,
  `grant://audit-rules`, `grant://measure-definitions`, plus `review_grant_report`
  and `explain_data_quality_issue` prompt templates.
- **Concise report template** — a 2–3 page executive brief rendered from the same
  `ReportData` as the full report, available in HTML and PDF via `--template concise`
  and in the app's Report Builder.
- **Claude Code configuration** — `CLAUDE.md`, scoped permissions with a
  format-and-lint hook, `/verify` and `/regen-artifacts` commands, `add-audit-rule`,
  `new-grant-profile`, and `release-check` Agent Skills, and `data-quality-reviewer`
  and `grounding-auditor` subagents.
- **Automated PR review** workflow using the Claude Code GitHub Action.
- **Responsible AI documentation** mapping the project onto the 4D framework
  (`docs/responsible_ai.md`).

### Fixed
- The deterministic analyst now answers causal questions with an explicit
  correlation-vs-causation caveat, and small-sample questions with the specific
  programs and measures affected — both gaps found by the new eval harness.
- Question routing no longer matches "housing" incidentally, so questions about
  fields the dataset lacks fall through to an honest "not available" answer instead
  of a program comparison.
- `month_over_month_enrollment_change` is exposed in `metric_lookup()`, so a metric
  the narrative already cited is now retrievable by the agent and traceable by graders.

## 1.1.0 — 2026-08-01

### Added
- **AI agent tool use** — Claude can call typed, read-only tools (`get_metric`,
  `compare_programs`, `get_measures`, `get_issue_summary`, `get_trends`,
  `get_demographics`, `list_metrics`) over the deterministic results via an
  agentic tool loop; tool outputs are aggregated and sanitized.
- **Period-over-period comparison** — compare two extracts with the same profile:
  headline deltas, per-program movement, deterministic narrative; new `compare`
  CLI command and a Period Comparison page in the app.
- **Program-scoped performance measures** — a measure may target one program
  (`program:` in the profile); example RRH-6 added to the rapid_rehousing profile.
- **PDF export** — grant report rendered through a headless browser (Playwright
  Chromium via `--extra pdf`, or Microsoft Edge automatically on Windows);
  `report --format pdf` and a Render PDF button in the Report Builder.
- **Offline HTML charts** — `report --offline-charts` embeds plotly.js so the
  HTML report works with no internet connection.
- **MCP server** (`--extra mcp`, `grant-assistant-mcp`) exposing audit_dataset,
  analyze_dataset, generate_report, and ask_analyst tools.
- **Docker support** — Dockerfile + .dockerignore for the Streamlit app.
- **Design system** — validated colorblind-safe palette applied across charts,
  the Streamlit theme, and reports (docs/design_system.md); design tokens
  published as a Claude Design project; screenshot capture script and README
  screenshots.
- 18 new tests (tool set, tool-loop contract, comparison math, program-scoped
  measures, PDF rendering, offline charts, MCP registration).

## 1.0.0 — 2026-08-01

Initial release.

### Added
- Data quality audit engine: 27 rules across completeness, uniqueness, validity,
  consistency, case management, timeliness, and statistical categories; severity levels
  with per-profile overrides; blocking rules; overall/category/program scores; row-level
  issue export; executive summaries and remediation guidance.
- Deterministic analytics: population, enrollment/exit, outcome, income-change,
  follow-up, demographic, program-comparison, monthly-trend, and goal-vs-actual metrics.
- Interactive Plotly chart set shared by dashboards and the HTML report.
- Senior AI Data Analyst agent: Anthropic Claude provider behind a provider-agnostic
  protocol, sanitized aggregate-only fact sheet, proactive insight engine (anomalies,
  trends, risks, recommendations, executive takeaways), grounded executive summaries, and
  a fully deterministic non-AI fallback mode.
- Prompt-injection defenses for untrusted uploads, with dataset scanning and user warnings.
- Report generation: polished HTML report with embedded interactive charts, Microsoft Word
  report, Excel audit workbook with flagged-record correction template, Excel analytics
  workbook.
- Configurable YAML grant profiles with pydantic validation; two synthetic examples
  (Housing Stability Grant, Rapid Re-Housing Outcomes Grant).
- Synthetic sample data generator producing a clean file (audits 100/100) and a flawed
  file with 23 documented injected error types plus a machine-readable manifest.
- Typer CLI: audit, analyze, report, ask, insights, full-run, generate-sample-data,
  validate-config, rules.
- Streamlit application: upload/profile, data preview, audit dashboard, issue explorer,
  analytics dashboard, AI analyst chat, proactive insights, report builder, export center,
  configuration help.
- 152-test pytest suite, Ruff lint/format, mypy, pre-commit hooks, GitHub Actions CI with
  a CLI smoke pipeline.
