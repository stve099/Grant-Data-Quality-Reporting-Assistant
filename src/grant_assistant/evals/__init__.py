"""Prompt evaluation harness for the AI Data Analyst.

Answer quality is measured, not assumed. The harness runs a fixed dataset of
questions through the agent and grades each answer with deterministic
(code-based) graders plus an optional model-based grader, then reports pass
rates per case and per grader.

The code-based graders are the important ones: they mechanically verify the
project's central claim — that the analyst never states a number the
deterministic layer did not calculate, and never leaks client-level data.
"""

from grant_assistant.evals.dataset import EvalCase, default_cases, load_cases
from grant_assistant.evals.graders import (
    GraderResult,
    all_graders,
    grade_answer,
)
from grant_assistant.evals.runner import CaseResult, EvalReport, run_evals

__all__ = [
    "CaseResult",
    "EvalCase",
    "EvalReport",
    "GraderResult",
    "all_graders",
    "default_cases",
    "grade_answer",
    "load_cases",
    "run_evals",
]
