"""Time the deterministic pipeline as the dataset grows.

Everything in this project is tested on a few hundred rows. A real HMIS extract
is tens of thousands, and nobody knew whether the audit's per-rule passes stayed
linear or quietly went quadratic. This measures it.

    uv run python scripts/benchmark.py
    uv run python scripts/benchmark.py --sizes 1000,10000,50000

Reports wall time per stage and, more usefully, time per 1,000 rows: a figure
that stays flat means linear scaling, and one that climbs means the stage will
eventually dominate.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterator
from contextlib import contextmanager

from grant_assistant.analytics import compute_analytics
from grant_assistant.audit import run_audit
from grant_assistant.configuration import load_profile
from grant_assistant.datagen import generate_clean_dataset, inject_issues
from grant_assistant.ingestion import prepare_dataset

DEFAULT_SIZES = (500, 2_000, 10_000, 50_000)


@contextmanager
def timed(store: dict[str, float], key: str) -> Iterator[None]:
    start = time.perf_counter()
    yield
    store[key] = time.perf_counter() - start


def benchmark(n_clients: int, profile_id: str = "housing_stability") -> dict[str, float]:
    """Time each stage for a dataset of ``n_clients`` rows."""
    profile = load_profile(profile_id)
    timings: dict[str, float] = {}

    with timed(timings, "generate"):
        frame, _ = inject_issues(generate_clean_dataset(n_clients=n_clients, seed=7), seed=8)
    with timed(timings, "prepare"):
        prepared = prepare_dataset(frame, profile)
    with timed(timings, "audit"):
        audit = run_audit(prepared, profile)
    with timed(timings, "analytics"):
        compute_analytics(prepared, profile)

    timings["rows"] = float(len(prepared.df))
    timings["findings"] = float(audit.total_findings)
    timings["pipeline"] = timings["prepare"] + timings["audit"] + timings["analytics"]
    return timings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help="Comma-separated client counts to benchmark.",
    )
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]

    header = f"{'rows':>8} {'prepare':>9} {'audit':>9} {'analytics':>10} {'total':>9} {'ms/1k':>8}"
    print(header)
    print("-" * len(header))
    for size in sizes:
        t = benchmark(size)
        rows = t["rows"]
        per_1k = (t["pipeline"] / rows) * 1000 * 1000  # milliseconds per 1,000 rows
        print(
            f"{int(rows):>8} {t['prepare']:>8.2f}s {t['audit']:>8.2f}s "
            f"{t['analytics']:>9.2f}s {t['pipeline']:>8.2f}s {per_1k:>7.0f}ms"
        )


if __name__ == "__main__":
    main()
