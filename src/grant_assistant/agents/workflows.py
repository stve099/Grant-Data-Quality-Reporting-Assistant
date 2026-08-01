"""Explicit agent workflow patterns.

Three patterns are used in this application, each where it genuinely fits:

**Routing** — an incoming question is classified into an intent, then dispatched
to the handler that can answer it. Classification is deterministic keyword
matching, so routing behaves identically with or without an API key, and the
route is inspectable and testable.

**Chaining** — report narrative is produced by a fixed sequence where each step
consumes the previous step's output: audit summary → deterministic insights →
executive summary. No step is allowed to invent inputs for the next.

**Parallelization** — independent units of work run concurrently. The evaluation
runner uses this for grading cases (see ``evals/runner.py``); ``run_parallel``
here is the shared helper.

Choosing between a workflow and an agent: workflows are used wherever the steps
are known in advance (they are cheaper, reproducible, and testable). The tool
loop in ``provider.complete_with_tools`` is the one genuinely agentic path,
used only for open-ended questions where the model must decide what to look up.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum

logger = logging.getLogger(__name__)


class Intent(StrEnum):
    """What a user's question is asking for."""

    PROGRAM_OUTCOMES = "program_outcomes"
    FOLLOWUPS = "followups"
    INCOME = "income"
    MEASURES = "measures"
    DATA_QUALITY = "data_quality"
    TRENDS = "trends"
    CAUSAL = "causal"
    CAVEATS = "caveats"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


#: Ordered rules: the first intent whose predicate matches wins. Order matters —
#: causal framing outranks the topic it asks about, because the answer needs the
#: correlation caveat regardless of subject.
_ROUTES: list[tuple[Intent, Callable[[str], bool]]] = [
    (
        Intent.CAUSAL,
        lambda q: any(
            k in q for k in ("cause", "caused", "because of", "due to", "effect of", "impact of")
        ),
    ),
    (
        Intent.CAVEATS,
        lambda q: any(
            k in q
            for k in ("small sample", "sample size", "distort", "unstable", "reliab", "misleading")
        ),
    ),
    (Intent.FOLLOWUPS, lambda q: "follow" in q or "overdue" in q),
    (
        # "housing" is deliberately not a trigger on its own: every program in
        # this domain is a housing program, so it appears in questions about
        # data the dataset does not hold. Those must fall through to UNKNOWN
        # and be answered with "not available" rather than a program comparison.
        Intent.PROGRAM_OUTCOMES,
        lambda q: (
            any(k in q for k in ("program", "exit", "successful", "permanent"))
            and not any(k in q for k in ("income", "target", "measure"))
        ),
    ),
    (Intent.INCOME, lambda q: "income" in q or "earn" in q or "wage" in q),
    (
        Intent.MEASURES,
        lambda q: any(k in q for k in ("target", "measure", "below", "goal", "benchmark")),
    ),
    (
        Intent.DATA_QUALITY,
        lambda q: any(k in q for k in ("data quality", "issue", "audit", "error", "missing")),
    ),
    (Intent.TRENDS, lambda q: any(k in q for k in ("trend", "month", "over time", "quarter"))),
    (
        Intent.SUMMARY,
        lambda q: any(k in q for k in ("summar", "executive", "leadership", "outcome", "overall")),
    ),
]


def classify_question(question: str) -> Intent:
    """Route a question to an intent (deterministic, no model call)."""
    q = question.casefold()
    for intent, matches in _ROUTES:
        if matches(q):
            logger.debug("Routed %r to %s", question[:60], intent)
            return intent
    return Intent.UNKNOWN


def run_parallel[T, R](
    items: Sequence[T],
    work: Callable[[T], R],
    max_workers: int = 4,
) -> list[R]:
    """Run independent work concurrently, preserving input order.

    Used where units of work do not depend on each other — grading evaluation
    cases, or analyzing several datasets with the same profile.
    """
    if not items:
        return []
    if len(items) == 1:
        return [work(items[0])]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(work, items))


def run_chain[T](initial: T, steps: Sequence[Callable[[T], T]]) -> T:
    """Feed a value through a fixed sequence of transformations.

    Each step receives the previous step's output. Steps are pure functions of
    their input so the chain is reproducible and each link is unit-testable.
    """
    value = initial
    for index, step in enumerate(steps, start=1):
        value = step(value)
        logger.debug("Chain step %d/%d complete", index, len(steps))
    return value
