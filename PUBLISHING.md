# Publishing checklist

Steps to take this repository live. These need your accounts and your decision, so they are
deliberately manual. Every figure below was verified against the working tree — if you change
the project, re-check them before pasting anything into a public profile.

Repository: <https://github.com/stve099/Grant-Data-Quality-Reporting-Assistant>

## 1. Make the repository public

The code is already pushed. What remains is the visibility switch, on the repository page:
**Settings → General → Danger Zone → Change repository visibility → Public.**

Before flipping it, the safety checks that matter have already passed:

- No API keys, tokens, or credentials anywhere outside `.env.example` (scanned).
- `.env` is git-ignored and untracked.
- All sample data is synthetic and enforced so by `tests/test_datagen.py::test_no_real_pii_fields`;
  no name, SSN, birth date, phone, email, or address field exists in it.

Nothing technical blocks publishing. It is still a one-way door in practice, so it stays your call.

## 2. Fill in the About panel

- **Description:**

  > Audits grant program data against 28 configurable rules, calculates funder performance
  > measures, and generates branded HTML/PDF/Word/PowerPoint reports — with a grounded AI
  > analyst that narrates but never calculates.

- **Website:** the Streamlit demo URL from step 4.
- **Topics:** `data-quality`, `grant-reporting`, `nonprofit`, `streamlit`, `plotly`,
  `ai-agents`, `claude`, `anthropic`, `pandas`, `data-analytics`, `hmis`

## 3. Add the CI badge

At the top of `README.md`:

```markdown
[![CI](https://github.com/stve099/Grant-Data-Quality-Reporting-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/stve099/Grant-Data-Quality-Reporting-Assistant/actions/workflows/ci.yml)
```

CI runs six jobs: lint/format/mypy, tests on Python 3.12 and 3.13, a full run with every
optional extra installed (the one that measures coverage), a CLI smoke pipeline, and a Windows
job that forces a cp1252 console to guard a real encoding regression.

## 4. Deploy the free live demo (Streamlit Community Cloud)

1. Go to <https://share.streamlit.io> → **New app** → pick the repo and `main`.
2. Main file path: `src/grant_assistant/ui/app.py`.
3. (Optional) Secrets → add `ANTHROPIC_API_KEY` to enable the AI analyst in the demo. To use
   OpenAI instead, add `GRANT_ASSISTANT_PROVIDER=openai` and `OPENAI_API_KEY`.
4. Share the link with data preloaded, so a first-time visitor lands on a populated dashboard
   instead of an upload prompt:

   ```
   https://<your-app>.streamlit.app/?demo=housing_program_flawed.csv&profile=housing_stability
   ```

5. Put that link at the top of the README and in the About panel.

Streamlit Cloud installs from `pyproject.toml`, base dependencies only — the `openai`, `pdf`,
`pptx`, and `charts` extras are not installed. The app degrades rather than erroring: without a
provider it runs in deterministic mode, and exports that need a missing backend warn and skip.
The demo carries only synthetic sample data; remind viewers not to upload real client data to a
public demo.

## 5. Cut a release

```bash
git tag -a v1.11.0 -m "v1.11.0"
git push origin v1.11.0
```

Create a GitHub Release from the tag and paste that version's section of `CHANGELOG.md`.

## 6. LinkedIn blurb

> Built a Python Grant Data Quality & Reporting Assistant: a configurable audit engine
> (28 rules), deterministic grant analytics, interactive dashboards, and branded
> HTML/PDF/Word/PowerPoint reports generated from one source so no two can disagree — plus a
> grounded AI data analyst with typed tool use that narrates the numbers but never computes
> them, and a graded eval harness that mechanically verifies that contract. 720 tests, six CI
> jobs, Docker, and an MCP server. Live demo + code: <links>

The eval harness is the part worth leading with in conversation: it is the difference between
claiming an AI feature is grounded and proving it on every run.
