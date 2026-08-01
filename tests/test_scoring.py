"""Data quality scoring model tests."""

from __future__ import annotations

from grant_assistant.audit.scoring import grade_for, score_from_issues
from grant_assistant.models import AuditIssue, IssueRecord, Severity


def _issue(severity: Severity, rows: list[int]) -> AuditIssue:
    return AuditIssue(
        rule_id="DQ-TST",
        rule_name="Test issue",
        category="validity",
        severity=severity,
        blocking=False,
        explanation="x",
        recommendation="y",
        records=[IssueRecord(row=r) for r in rows],
    )


def test_no_issues_scores_100():
    assert score_from_issues([], 100) == 100.0


def test_all_rows_critical_scores_0():
    issue = _issue(Severity.CRITICAL, list(range(1, 101)))
    assert score_from_issues([issue], 100) == 0.0


def test_half_rows_high_severity():
    # 50 high-severity rows of 100: penalty = 5*50 / (8*100) = 0.3125 -> 68.8
    issue = _issue(Severity.HIGH, list(range(1, 51)))
    assert score_from_issues([issue], 100) == 68.8


def test_info_findings_do_not_reduce_score():
    issue = _issue(Severity.INFO, list(range(1, 101)))
    assert score_from_issues([issue], 100) == 100.0


def test_duplicate_rows_within_issue_counted_once():
    issue = _issue(Severity.HIGH, [1, 1, 1])
    same_as_single = _issue(Severity.HIGH, [1])
    assert score_from_issues([issue], 100) == score_from_issues([same_as_single], 100)


def test_score_floors_at_zero():
    issues = [_issue(Severity.CRITICAL, list(range(1, 101))) for _ in range(3)]
    assert score_from_issues(issues, 100) == 0.0


def test_empty_dataset_scores_100():
    assert score_from_issues([], 0) == 100.0


def test_grades():
    assert grade_for(95) == "A"
    assert grade_for(90) == "A"
    assert grade_for(85) == "B"
    assert grade_for(72.4) == "C"
    assert grade_for(60) == "D"
    assert grade_for(59.9) == "F"


def test_flawed_audit_scores_by_category_and_program(audit_flawed):
    assert audit_flawed.score_by_category
    for score in audit_flawed.score_by_category.values():
        assert 0 <= score <= 100
    assert set(audit_flawed.score_by_program) <= {
        "Rapid Re-Housing",
        "Emergency Shelter",
        "Permanent Supportive Housing",
    }
    for score in audit_flawed.score_by_program.values():
        assert 0 <= score <= 100
