"""Run the eval across several models and put the results side by side.

Choosing a model was guesswork: run the suite, read a number, run it again and
get a different one. The pieces to do this properly already exist — backend
provenance, repeated runs, usage accounting — so this is the loop that uses them.

The table reports a mean across runs rather than a single score, because a
hosted model is not reproducible even at temperature 0 and one run measures luck
as much as quality. It also reports tokens, since the cheapest model that clears
the grounding bar is usually the right answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from grant_assistant.agents import DataAnalystAgent
from grant_assistant.evals.dataset import EvalCase
from grant_assistant.evals.runner import EvalReport, run_evals, summarize_runs

logger = logging.getLogger(__name__)


@dataclass
class ModelResult:
    """One model's outcome across repeated runs."""

    model: str
    provider: str = ""
    pass_rates: list[float] = field(default_factory=list)
    flaky_cases: list[str] = field(default_factory=list)
    failed_cases: list[str] = field(default_factory=list)
    total_tokens: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def mean_pass_rate(self) -> float:
        return round(sum(self.pass_rates) / len(self.pass_rates), 1) if self.pass_rates else 0.0

    @property
    def min_pass_rate(self) -> float:
        return min(self.pass_rates) if self.pass_rates else 0.0


@dataclass
class ComparisonResult:
    """Every model's outcome, best mean first."""

    results: list[ModelResult] = field(default_factory=list)
    runs_per_model: int = 1

    @property
    def ranked(self) -> list[ModelResult]:
        """Best first, breaking ties on the worst single run then on tokens.

        A model that averages well but collapses occasionally is worse than a
        steady one, so the floor breaks the tie before cost does.
        """
        return sorted(
            [r for r in self.results if r.ok],
            key=lambda r: (-r.mean_pass_rate, -r.min_pass_rate, r.total_tokens),
        )

    @property
    def winner(self) -> ModelResult | None:
        return self.ranked[0] if self.ranked else None

    def as_markdown(self) -> str:
        lines = [
            "# Model comparison",
            "",
            f"Each model ran the evaluation {self.runs_per_model} time(s).",
            "",
            "| Model | Mean | Worst run | Tokens | Intermittent | Always failing |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.ranked:
            lines.append(
                f"| {r.model} | {r.mean_pass_rate}% | {r.min_pass_rate}% | "
                f"{r.total_tokens:,} | {', '.join(r.flaky_cases) or '—'} | "
                f"{', '.join(r.failed_cases) or '—'} |"
            )
        for r in self.results:
            if not r.ok:
                lines.append(f"| {r.model} | failed | — | — | — | {r.error} |")
        return "\n".join(lines) + "\n"


def compare_models(
    models: list[str],
    agent_factory,
    cases: list[EvalCase] | None = None,
    client_ids: set[str] | None = None,
    runs: int = 1,
) -> ComparisonResult:
    """Evaluate each model and collect the results.

    ``agent_factory(model)`` returns a :class:`DataAnalystAgent` configured for
    that model. A model that cannot be reached is recorded and the sweep
    continues, because the others are still worth comparing.
    """
    comparison = ComparisonResult(runs_per_model=runs)

    for model in models:
        try:
            agent: DataAnalystAgent = agent_factory(model)
        except Exception as exc:
            logger.warning("Could not build an agent for %s: %s", model, exc)
            comparison.results.append(ModelResult(model=model, error=str(exc)[:150]))
            continue

        reports: list[EvalReport] = []
        try:
            for index in range(runs):
                logger.info("Evaluating %s (run %d/%d)", model, index + 1, runs)
                reports.append(run_evals(agent, cases=cases, client_ids=client_ids))
        except Exception as exc:
            comparison.results.append(ModelResult(model=model, error=str(exc)[:150]))
            continue

        stability = summarize_runs(reports)
        usage = getattr(agent.provider, "usage", None)
        comparison.results.append(
            ModelResult(
                model=model,
                provider=getattr(agent.provider, "name", ""),
                pass_rates=stability.pass_rates,
                flaky_cases=stability.flaky,
                failed_cases=stability.never_passed,
                total_tokens=(usage.total_input_tokens + usage.total_output_tokens if usage else 0),
            )
        )
    return comparison
