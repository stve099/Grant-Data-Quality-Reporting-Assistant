"""Verify every intentionally injected sample-data issue is detected."""

from __future__ import annotations

from tests.conftest import fired_rules


def test_clean_sample_has_zero_findings(audit_clean):
    assert audit_clean.total_findings == 0
    assert audit_clean.overall_score == 100.0
    assert audit_clean.grade == "A"


def test_every_injected_issue_is_detected(audit_flawed, flawed):
    """Each manifest entry's expected rules must fire on the expected rows."""
    _, manifest = flawed
    assert manifest, "manifest must not be empty"
    findings_by_rule: dict[str, set[int]] = {}
    for issue in audit_flawed.issues:
        findings_by_rule.setdefault(issue.rule_id, set()).update(r.row for r in issue.records)
    for entry in manifest:
        expected_rows = set(entry["rows"])
        for rule_id in entry["expected_rules"]:
            assert rule_id in findings_by_rule, (
                f"rule {rule_id} never fired (injected: {entry['description']})"
            )
            covered = findings_by_rule[rule_id] & expected_rows
            assert covered, (
                f"rule {rule_id} fired but missed injected rows {sorted(expected_rows)} "
                f"({entry['description']}); it flagged {sorted(findings_by_rule[rule_id])[:10]}"
            )


def test_flawed_sample_score_reduced_but_reasonable(audit_flawed):
    assert audit_flawed.overall_score < 95
    assert audit_flawed.overall_score > 40
    assert audit_flawed.grade in {"B", "C", "D"}


def test_flawed_sample_has_blocking_issues(audit_flawed):
    assert audit_flawed.blocking_issues
    blocking_ids = {i.rule_id for i in audit_flawed.blocking_issues}
    assert "DQ-010" in blocking_ids  # duplicates are always blocking


def test_injection_attempt_is_reported(audit_flawed):
    assert audit_flawed.injection_warnings
    joined = " ".join(audit_flawed.injection_warnings)
    # The warning names the column but never echoes the payload.
    assert "Exit Destination".casefold() in joined.casefold() or "exit" in joined.casefold()
    assert "Ignore previous instructions" not in joined


def test_row_level_frame_matches_findings(audit_flawed):
    frame = audit_flawed.row_level_frame()
    assert len(frame) == audit_flawed.total_findings
    assert set(frame.columns) >= {
        "rule_id",
        "rule_name",
        "severity",
        "row",
        "client_id",
        "explanation",
        "recommendation",
    }
    fired = fired_rules(audit_flawed)
    assert set(frame["rule_id"].unique()) == set(fired)
