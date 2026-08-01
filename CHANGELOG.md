# Changelog

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
