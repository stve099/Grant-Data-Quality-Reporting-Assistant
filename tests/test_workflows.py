"""Workflow pattern tests: routing, chaining, and parallelization."""

from __future__ import annotations

import threading

import pytest

from grant_assistant.agents.workflows import Intent, classify_question, run_chain, run_parallel


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Which program had the highest successful exit rate?", Intent.PROGRAM_OUTCOMES),
        ("Which program had the most exits?", Intent.PROGRAM_OUTCOMES),
        ("Which clients are overdue for follow-up?", Intent.FOLLOWUPS),
        ("How did household income change?", Intent.INCOME),
        ("Which outcomes are below target?", Intent.MEASURES),
        ("Which data quality issues affect this report?", Intent.DATA_QUALITY),
        ("What are the enrollment trends by month?", Intent.TRENDS),
        ("Summarize grant outcomes for leadership.", Intent.SUMMARY),
        ("Are any metrics distorted by small sample sizes?", Intent.CAVEATS),
        ("Did the program cause better outcomes?", Intent.CAUSAL),
    ],
)
def test_routing_table(question: str, expected: Intent):
    assert classify_question(question) is expected


def test_causal_framing_outranks_its_subject():
    """A causal question about income still needs the causation caveat."""
    assert classify_question("Did the program cause income to rise?") is Intent.CAUSAL


def test_unknown_field_is_not_force_fitted_to_a_route():
    """'housing' appears in unanswerable questions; it must not trigger a route."""
    question = "What is the average credit score, and how does it relate to housing retention?"
    assert classify_question(question) is Intent.UNKNOWN


def test_unrelated_question_is_unknown():
    assert classify_question("What is the weather tomorrow?") is Intent.UNKNOWN


def test_routing_is_case_insensitive():
    assert classify_question("WHICH PROGRAM HAD THE MOST EXITS?") is Intent.PROGRAM_OUTCOMES


# -- Chaining ----------------------------------------------------------------


def test_run_chain_applies_steps_in_order():
    steps = [lambda s: s + "a", lambda s: s + "b", lambda s: s + "c"]
    assert run_chain("", steps) == "abc"


def test_run_chain_with_no_steps_is_identity():
    assert run_chain("value", []) == "value"


# -- Parallelization ---------------------------------------------------------


def test_run_parallel_preserves_input_order():
    items = list(range(12))
    assert run_parallel(items, lambda n: n * 2, max_workers=4) == [n * 2 for n in items]


def test_run_parallel_handles_empty_and_single():
    assert run_parallel([], lambda n: n) == []
    assert run_parallel([5], lambda n: n + 1) == [6]


def test_run_parallel_actually_uses_threads():
    seen: set[int] = set()
    lock = threading.Lock()

    def work(n: int) -> int:
        with lock:
            seen.add(threading.get_ident())
        return n

    run_parallel(list(range(16)), work, max_workers=4)
    assert len(seen) > 1, "expected work to run on multiple threads"


def test_run_parallel_propagates_errors():
    def work(n: int) -> int:
        if n == 3:
            raise ValueError("boom")
        return n

    with pytest.raises(ValueError, match="boom"):
        run_parallel([1, 2, 3], work)
