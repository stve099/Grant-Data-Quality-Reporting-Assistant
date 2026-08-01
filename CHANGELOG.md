# Changelog

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
