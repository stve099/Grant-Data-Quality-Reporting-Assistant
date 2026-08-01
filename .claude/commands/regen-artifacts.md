---
description: Regenerate sample data, example reports, and README screenshots
---

Regenerate every committed artifact so the repository matches the current code:

```bash
uv run grant-assistant generate-sample-data
uv run grant-assistant report sample_data/housing_program_flawed.csv --profile housing_stability --output examples --format all
uv run python scripts/capture_screenshots.py
```

Then run `uv run pytest` — the manifest test verifies the regenerated flawed dataset still
trips every documented rule.

Report which files changed and confirm the audit still detects all injected issues.
