# Publishing checklist

Steps to take this repository live (these need your accounts, so they're manual).

## 1. Push to GitHub

```bash
git remote add origin https://github.com/<your-username>/grant-data-assistant.git
git push -u origin main
```

Then on the repository page:

- **About → Description:** "Audits grant program data, calculates performance measures,
  and generates reports with a grounded AI data analyst (Python · Streamlit · Claude)."
- **Topics:** `data-quality`, `grant-reporting`, `nonprofit`, `streamlit`, `plotly`,
  `ai-agents`, `claude`, `anthropic`, `pandas`, `data-analytics`
- Confirm the **Actions** run is green (it runs lint, format, mypy, tests on 3.12/3.13,
  and a CLI smoke pipeline).

## 2. Add the CI badge

Put this at the top of `README.md` (replace `<your-username>`):

```markdown
[![CI](https://github.com/<your-username>/grant-data-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-username>/grant-data-assistant/actions/workflows/ci.yml)
```

## 3. Cut a release

```bash
git tag -a v1.1.0 -m "Grant Data Quality & Reporting Assistant 1.1.0"
git push origin v1.1.0
```

Create a GitHub Release from the tag and paste the 1.1.0 section of `CHANGELOG.md`.

## 4. Deploy the free live demo (Streamlit Community Cloud)

1. Go to https://share.streamlit.io → **New app** → pick your repo/branch.
2. Main file path: `src/grant_assistant/ui/app.py`.
3. (Optional) Secrets → add `ANTHROPIC_API_KEY` to enable AI chat in the demo.
4. After it deploys, share the demo link with data preloaded:
   `https://<your-app>.streamlit.app/?demo=housing_program_flawed.csv&profile=housing_stability`
5. Put that link at the top of the README.

Streamlit Cloud installs from `pyproject.toml` automatically. The demo uses only the
synthetic sample data — remind viewers not to upload real client data to a public demo.

## 5. LinkedIn blurb

> Built a Python-based Grant Data Quality & Reporting Assistant: a configurable audit
> engine (27 rules), deterministic grant analytics, interactive dashboards, professional
> HTML/PDF/Word/Excel reports, and a grounded AI data analyst with typed tool use —
> plus a 170+ test suite, CI, Docker, and an MCP server. Live demo + code: <links>
