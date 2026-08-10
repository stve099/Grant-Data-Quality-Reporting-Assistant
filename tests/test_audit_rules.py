"""Targeted tests for individual audit rules using hand-built rows."""

from __future__ import annotations

from grant_assistant.models import Severity
from tests.conftest import (
    VALID_ACTIVE,
    VALID_EXITED,
    audit_source_rows,
    fired_rules,
    make_row,
)


def test_fully_valid_rows_produce_no_findings(profile):
    audit = audit_source_rows([dict(VALID_ACTIVE), dict(VALID_EXITED)], profile)
    assert audit.total_findings == 0
    assert audit.overall_score == 100.0


def test_missing_required_fields_detected(profile):
    rows = [make_row(client_id=""), make_row(VALID_ACTIVE, household_id="", client_id="C-3")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert "DQ-001" in fired


def test_duplicate_client_enrollment_detected(profile):
    rows = [dict(VALID_ACTIVE), dict(VALID_ACTIVE)]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-010"] == {"C-1"}


def test_same_client_different_program_not_duplicate(profile):
    rows = [dict(VALID_ACTIVE), make_row(program="Emergency Shelter")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert "DQ-010" not in fired


def test_invalid_date_detected(profile):
    rows = [make_row(VALID_EXITED, exit_date="not a date")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-020"] == {"C-2"}


def test_invalid_numeric_detected(profile):
    rows = [make_row(entry_income="five hundred")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-021"] == {"C-1"}


def test_invalid_age_detected(profile):
    rows = [make_row(age=-3), make_row(age=250, client_id="C-9")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-022"] == {"C-1", "C-9"}


def test_invalid_household_size_detected(profile):
    rows = [make_row(household_size=0), make_row(household_size=25, client_id="C-9")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-023"] == {"C-1", "C-9"}


def test_negative_income_detected(profile):
    rows = [make_row(entry_income=-100)]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-024"] == {"C-1"}


def test_unrealistic_income_detected(profile):
    rows = [make_row(entry_income=1_500_000)]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-025"] == {"C-1"}


def test_unknown_program_detected(profile):
    rows = [make_row(program="Mystery Program")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-026"] == {"C-1"}


def test_program_alias_reported_as_info(profile):
    rows = [make_row(program="RRH")]
    audit = audit_source_rows(rows, profile)
    fired = fired_rules(audit)
    assert fired["DQ-027"] == {"C-1"}
    issue = next(i for i in audit.issues if i.rule_id == "DQ-027")
    assert issue.severity == Severity.INFO


def test_controlled_value_violation_detected(profile):
    rows = [make_row(race="Caucasian"), make_row(veteran_status="Maybe", client_id="C-9")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-028"] == {"C-1", "C-9"}


def test_exit_before_enrollment_detected(profile):
    rows = [make_row(VALID_EXITED, exit_date="2024-01-01")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-030"] == {"C-2"}


def test_followup_before_exit_detected(profile):
    rows = [make_row(VALID_EXITED, followup_3m="2024-12-01")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-031"] == {"C-2"}


def test_household_composition_mismatch_detected(profile):
    rows = [make_row(household_size=4, adults=1, children=1)]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-032"] == {"C-1"}


def test_status_contradicts_exit_date_both_directions(profile):
    rows = [
        make_row(VALID_EXITED, enrollment_status="Active"),
        make_row(enrollment_status="Exited", client_id="C-9"),
    ]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-033"] == {"C-2", "C-9"}


def test_date_outside_reporting_period_flagged_info(profile):
    rows = [make_row(enrollment_date="2025-09-15")]  # after 2025-06-30 period end
    audit = audit_source_rows(rows, profile)
    fired = fired_rules(audit)
    assert fired["DQ-034"] == {"C-1"}


def test_missing_assessment_detected(profile):
    rows = [make_row(assessment_status="Not Started")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-040"] == {"C-1"}


def test_missing_exit_plan_only_for_exited(profile):
    rows = [
        make_row(VALID_EXITED, exit_plan_status="Not Started"),
        make_row(exit_plan_status="Not Started"),  # active client: not flagged
    ]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-041"] == {"C-2"}


def test_overdue_followups_detected_per_milestone(profile):
    rows = [make_row(VALID_EXITED, followup_3m="", followup_6m="", followup_12m="")]
    fired = fired_rules(audit_source_rows(rows, profile))
    assert fired["DQ-050"] == {"C-2"}  # 3-month
    assert fired["DQ-051"] == {"C-2"}  # 6-month
    assert fired["DQ-052"] == {"C-2"}  # annual


def test_completed_followups_not_flagged(profile):
    audit = audit_source_rows([dict(VALID_EXITED)], profile)
    fired = fired_rules(audit)
    assert "DQ-050" not in fired
    assert "DQ-051" not in fired
    assert "DQ-052" not in fired


def test_severity_override_applied(rrh_profile):
    # rapid_rehousing raises DQ-003 (missing exit income) to high severity
    rows = [make_row(VALID_EXITED, exit_income="")]
    audit = audit_source_rows(rows, rrh_profile)
    issue = next(i for i in audit.issues if i.rule_id == "DQ-003")
    assert issue.severity == Severity.HIGH


def test_blocking_rules_from_profile(rrh_profile):
    # rapid_rehousing marks DQ-004 (missing exit destination) as blocking
    rows = [make_row(VALID_EXITED, exit_destination="")]
    audit = audit_source_rows(rows, rrh_profile)
    issue = next(i for i in audit.issues if i.rule_id == "DQ-004")
    assert issue.blocking is True
    assert issue in audit.blocking_issues


def test_blocking_rules_can_elevate_a_non_default_rule(hp_profile, profile):
    # DQ-033 (status contradicts exit date) is registered blocking=False, so a
    # profile must list it to make it block. homeless_prevention does; the
    # default profile does not. This is the case where blocking_rules actually
    # changes behaviour, unlike listing an already-blocking rule.
    rows = [make_row(VALID_EXITED, enrollment_status="Active")]
    blocking_audit = audit_source_rows(rows, hp_profile)
    issue = next(i for i in blocking_audit.issues if i.rule_id == "DQ-033")
    assert issue.blocking is True
    assert issue in blocking_audit.blocking_issues

    default_audit = audit_source_rows(rows, profile)
    default_issue = next(i for i in default_audit.issues if i.rule_id == "DQ-033")
    assert default_issue.blocking is False
    assert default_issue not in default_audit.blocking_issues


def test_single_followup_schedule_emits_one_overdue_rule(hp_profile):
    # The rule IDs are positional (DQ-05{i}), so a one-entry schedule must mean
    # only DQ-050 can fire — DQ-051/DQ-052 do not exist under this profile.
    rows = [make_row(VALID_EXITED, followup_3m="")]
    fired = fired_rules(audit_source_rows(rows, hp_profile))
    assert fired["DQ-050"] == {"C-2"}
    assert "DQ-051" not in fired
    assert "DQ-052" not in fired


def test_severity_overrides_to_medium(hp_profile):
    # homeless_prevention raises missing demographic fields (DQ-005) and missing
    # entry income (DQ-002) from low to medium — both default low.
    rows = [make_row(VALID_EXITED, gender="", entry_income="")]
    audit = audit_source_rows(rows, hp_profile)
    by_rule = {i.rule_id: i for i in audit.issues}
    assert by_rule["DQ-005"].severity == Severity.MEDIUM
    assert by_rule["DQ-002"].severity == Severity.MEDIUM


def test_issue_metadata_completeness(profile):
    """Every finding must carry the full metadata contract from the spec."""
    rows = [make_row(client_id=""), dict(VALID_ACTIVE)]
    audit = audit_source_rows(rows, profile)
    for issue in audit.issues:
        assert issue.rule_id.startswith("DQ-")
        assert issue.rule_name
        assert issue.category
        assert issue.severity in Severity
        assert isinstance(issue.blocking, bool)
        assert issue.explanation
        assert issue.recommendation
        assert issue.record_count == len(issue.records)
        for record in issue.records:
            assert record.row >= 1
