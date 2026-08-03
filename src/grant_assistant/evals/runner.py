"""Run the evaluation dataset and report pass rates.

Cases are independent, so the runner executes them with a thread pool — the
parallelization workflow pattern applied to a real workload rather than a toy.
Results are deterministic in ordering regardless of completion order.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.evals.dataset import EvalCase, default_cases
from grant_assistant.evals.graders import (
    GraderResult,
    GradingContext,
    grade_answer,
    grade_with_model,
)

logger = logging.getLogger(__name__)


class CaseResult(BaseModel):
    """Grading outcome for one case."""

    case_id: str
    category: str
    question: str
    answer: str
    graders: list[GraderResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.graders)

    @property
    def failures(self) -> list[GraderResult]:
        return [g for g in self.graders if not g.passed]


class EvalReport(BaseModel):
    """Complete evaluation run."""

    generated_at: datetime = Field(default_factory=datetime.now)
    mode: str = Field(description="'ai' or 'deterministic'")
    #: Which backend answered. Without these a 12/12 and a later 9/12 report are
    #: indistinguishable once the provider or model changes, which would make the
    #: harness useless as a regression detector.
    provider: str | None = Field(default=None, description="Provider name in AI mode.")
    model: str | None = Field(default=None, description="Model id in AI mode.")
    dataset: str = "built-in"
    results: list[CaseResult] = Field(default_factory=list)

    @property
    def backend(self) -> str:
        """Human-readable backend label: 'ollama / llama3.1', or the mode alone."""
        if self.provider is None:
            return self.mode
        return f"{self.provider} / {self.model}" if self.model else self.provider

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return round(100.0 * self.passed / self.total, 1) if self.total else 0.0

    def by_grader(self) -> dict[str, tuple[int, int]]:
        """grader name -> (passed, total)."""
        tally: dict[str, list[int]] = {}
        for result in self.results:
            for grader in result.graders:
                entry = tally.setdefault(grader.grader, [0, 0])
                entry[0] += int(grader.passed)
                entry[1] += 1
        return {name: (p, t) for name, (p, t) in sorted(tally.items())}

    def by_category(self) -> dict[str, tuple[int, int]]:
        tally: dict[str, list[int]] = {}
        for result in self.results:
            entry = tally.setdefault(result.category, [0, 0])
            entry[0] += int(result.passed)
            entry[1] += 1
        return {name: (p, t) for name, (p, t) in sorted(tally.items())}

    def as_markdown(self) -> str:
        lines = [
            "# Prompt Evaluation Report",
            "",
            f"- Generated: {self.generated_at:%Y-%m-%d %H:%M}",
            f"- Mode: **{self.mode}**",
            f"- Backend: {self.backend}",
            f"- Dataset: {self.dataset}",
            f"- Result: **{self.passed}/{self.total} cases passed ({self.pass_rate}%)**",
            "",
            "## By grader",
            "",
            "| Grader | Passed | Total |",
            "|---|---:|---:|",
        ]
        lines += [f"| {name} | {p} | {t} |" for name, (p, t) in self.by_grader().items()]
        lines += ["", "## By category", "", "| Category | Passed | Total |", "|---|---:|---:|"]
        lines += [f"| {name} | {p} | {t} |" for name, (p, t) in self.by_category().items()]
        lines += ["", "## Cases", ""]
        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            lines.append(f"### [{status}] {result.case_id}")
            lines.append(f"*{result.question}*")
            for grader in result.graders:
                mark = "ok" if grader.passed else "**failed**"
                detail = f" — {grader.detail}" if grader.detail else ""
                lines.append(f"- {grader.grader}: {mark}{detail}")
            lines.append("")
        return "\n".join(lines)


class RunStability(BaseModel):
    """Spread of results across repeated runs of the same dataset.

    A hosted model is not reproducible even at temperature 0, so a single run
    reports luck as much as quality. Repeating the suite separates cases that
    always pass from the ones that only usually do — and it is the intermittent
    ones that matter, because a grounding rule obeyed 4 times in 5 is not obeyed.
    """

    pass_rates: list[float] = Field(description="Pass rate of each run, in order.")
    case_pass_counts: dict[str, int] = Field(description="case id -> runs passed.")

    # Computed fields, not plain properties, so the written artifact carries the
    # summary rather than only the raw counts a reader would have to redo.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def runs(self) -> int:
        return len(self.pass_rates)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mean_pass_rate(self) -> float:
        return round(sum(self.pass_rates) / len(self.pass_rates), 1) if self.pass_rates else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def min_pass_rate(self) -> float:
        return min(self.pass_rates) if self.pass_rates else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_pass_rate(self) -> float:
        return max(self.pass_rates) if self.pass_rates else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def always_passed(self) -> list[str]:
        return sorted(c for c, n in self.case_pass_counts.items() if n == self.runs)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def never_passed(self) -> list[str]:
        return sorted(c for c, n in self.case_pass_counts.items() if n == 0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def flaky(self) -> list[str]:
        """Cases that passed some runs but not all — the interesting ones."""
        return sorted(c for c, n in self.case_pass_counts.items() if 0 < n < self.runs)


def summarize_runs(reports: list[EvalReport]) -> RunStability:
    """Aggregate repeated runs of the same dataset into a stability summary."""
    counts: dict[str, int] = {}
    for report in reports:
        for result in report.results:
            counts[result.case_id] = counts.get(result.case_id, 0) + int(result.passed)
    return RunStability(
        pass_rates=[r.pass_rate for r in reports],
        case_pass_counts=counts,
    )


def run_evals(
    agent: DataAnalystAgent,
    cases: list[EvalCase] | None = None,
    client_ids: set[str] | None = None,
    use_model_grader: bool = False,
    max_workers: int = 4,
) -> EvalReport:
    """Run every case against the agent and grade the answers.

    Args:
        agent: the analyst under test (AI mode or deterministic fallback).
        cases: dataset; defaults to the built-in set.
        client_ids: real identifiers from the dataset, so leak detection can
            check for them literally as well as by pattern.
        use_model_grader: additionally judge each answer against its rubric with
            the agent's provider. Ignored when no provider is configured.
        max_workers: thread pool size for the parallel run.
    """
    cases = cases or default_cases()
    ctx = GradingContext(
        analytics=agent.analytics,
        audit=agent.audit,
        profile=agent.profile,
        client_ids=client_ids,
    )
    judge = agent.provider if (use_model_grader and agent.provider is not None) else None

    def run_case(case: EvalCase) -> CaseResult:
        try:
            answer = agent.ask(case.question)
        except Exception as exc:
            logger.warning("Case %s raised: %s", case.id, exc)
            return CaseResult(
                case_id=case.id,
                category=case.category,
                question=case.question,
                answer="",
                graders=[GraderResult(grader="execution", passed=False, detail=f"raised: {exc}")],
            )
        graders = grade_answer(answer, case, ctx)
        if judge is not None:
            graders.append(grade_with_model(answer, case, judge))
        return CaseResult(
            case_id=case.id,
            category=case.category,
            question=case.question,
            answer=answer,
            graders=graders,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(run_case, cases))

    provider = agent.provider if agent.ai_enabled else None
    report = EvalReport(
        mode="ai" if agent.ai_enabled else "deterministic",
        # `model` is not part of the AIProvider protocol, only of the concrete
        # implementations, so read it defensively.
        provider=getattr(provider, "name", None),
        model=getattr(provider, "model", None),
        results=results,
    )
    logger.info(
        "Eval complete: %d/%d cases passed (%.1f%%)",
        report.passed,
        report.total,
        report.pass_rate,
    )
    return report


def write_report(report: EvalReport, directory: str | Path) -> dict[str, Path]:
    """Write the markdown and JSON forms of an evaluation report."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    md_path = directory / "eval_report.md"
    json_path = directory / "eval_report.json"
    md_path.write_text(report.as_markdown(), encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return {"markdown": md_path, "json": json_path}


class StabilityReport(BaseModel):
    """Every run of a repeated evaluation, plus the summary across them.

    Written whenever the suite runs more than once. Without it the final run
    overwrites ``eval_report.json`` and a failure in an earlier run leaves no
    evidence — which would defeat the point of repeating the suite.
    """

    generated_at: datetime = Field(default_factory=datetime.now)
    summary: RunStability
    reports: list[EvalReport]


def write_stability(reports: list[EvalReport], directory: str | Path) -> Path:
    """Persist all runs of a repeated evaluation to one JSON artifact."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "eval_stability.json"
    payload = StabilityReport(summary=summarize_runs(reports), reports=reports)
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return path
