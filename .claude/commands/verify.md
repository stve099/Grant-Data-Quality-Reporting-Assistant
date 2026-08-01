---
description: Run the full verification gate (tests, lint, format, types) and report results
---

Run all four quality gates in order and report the actual output of each:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

If any gate fails, diagnose the root cause, fix it, and re-run that gate before moving on.
Do not summarize a gate as passing unless you ran it and saw it pass.

Finish with a short table: gate, command, result.
