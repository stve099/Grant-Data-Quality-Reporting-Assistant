"""Audit rule registry and orchestration.

Rules are plain functions registered with the :func:`rule` decorator. Each
receives a :class:`RuleContext` and returns zero or more
:class:`~grant_assistant.models.AuditIssue` objects. The engine applies
profile-level severity/blocking overrides, computes data quality scores, and
returns a complete :class:`~grant_assistant.models.AuditResult`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from grant_assistant.audit.scoring import compute_scores, grade_for
from grant_assistant.configuration import GrantProfile
from grant_assistant.ingestion import PreparedData
from grant_assistant.models import AuditIssue, AuditResult, Severity
from grant_assistant.security import scan_dataframe_for_injection

logger = logging.getLogger(__name__)


@dataclass
class RuleContext:
    """Everything a rule needs to evaluate the dataset."""

    data: PreparedData
    profile: GrantProfile
    today: date = field(default_factory=date.today)


@dataclass(frozen=True)
class RuleMeta:
    """Static metadata describing an audit rule."""

    rule_id: str
    name: str
    category: str
    severity: Severity
    blocking: bool
    description: str


RuleFunc = Callable[[RuleContext], list[AuditIssue]]

_REGISTRY: list[tuple[RuleMeta, RuleFunc]] = []


def rule(
    rule_id: str,
    name: str,
    category: str,
    severity: Severity,
    blocking: bool = False,
    description: str = "",
) -> Callable[[RuleFunc], RuleFunc]:
    """Register an audit rule function with its metadata."""

    def decorator(func: RuleFunc) -> RuleFunc:
        _REGISTRY.append((RuleMeta(rule_id, name, category, severity, blocking, description), func))
        return func

    return decorator


def list_rules() -> list[RuleMeta]:
    """All registered rules (dynamic follow-up sub-rules appear under one entry)."""
    _ensure_rules_loaded()
    return [meta for meta, _ in _REGISTRY]


def _ensure_rules_loaded() -> None:
    # Importing the module executes the decorators exactly once.
    from grant_assistant.audit import rules  # noqa: F401


def run_audit(
    data: PreparedData,
    profile: GrantProfile,
    today: date | None = None,
) -> AuditResult:
    """Run every registered audit rule and score the results."""
    _ensure_rules_loaded()
    ctx = RuleContext(data=data, profile=profile, today=today or date.today())
    issues: list[AuditIssue] = []
    for meta, func in _REGISTRY:
        try:
            produced = func(ctx)
        except Exception:
            logger.exception("Audit rule %s (%s) failed; skipping", meta.rule_id, meta.name)
            continue
        for issue in produced:
            issue.severity = profile.severity_for(issue.rule_id, issue.severity)
            issue.blocking = profile.is_blocking(issue.rule_id, issue.blocking)
            issues.append(issue)

    n_rows = len(data.df)
    overall, by_category, by_program = compute_scores(issues, n_rows, data, profile)
    result = AuditResult(
        profile_id=profile.profile_id,
        grant_name=profile.grant_name,
        total_rows=n_rows,
        issues=issues,
        overall_score=overall,
        grade=grade_for(overall),
        score_by_category=by_category,
        score_by_program=by_program,
        injection_warnings=scan_dataframe_for_injection(data.raw),
    )
    logger.info(
        "Audit complete: %d findings across %d rules, score %.1f (%s)",
        result.total_findings,
        len([i for i in issues if i.record_count]),
        overall,
        result.grade,
    )
    return result
