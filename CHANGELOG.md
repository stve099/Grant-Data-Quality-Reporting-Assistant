# Changelog

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
