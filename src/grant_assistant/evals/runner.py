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

from pydantic import BaseModel, Field

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
    dataset: str = "built-in"
    results: list[CaseResult] = Field(default_factory=list)

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

    report = EvalReport(
        mode="ai" if agent.ai_enabled else "deterministic",
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
