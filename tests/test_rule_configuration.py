"""Per-profile rule configuration: disabling rules and tuning thresholds.

Onboarding a funder is meant to be config-only. Two things blocked that: a grant
that does not collect a field still got findings for it, and the statistical
rules' sensitivity was fixed in code.
"""

from __future__ import annotations

import pytest

from grant_assistant.audit import run_audit
from grant_assistant.audit.engine import RuleContext


def _rule_ids(audit) -> set[str]:
    return {issue.rule_id for issue in audit.issues}


# -- Disabling ---------------------------------------------------------------


def test_a_disabled_rule_produces_no_findings(prepared_flawed, profile):
    baseline = run_audit(prepared_flawed, profile)
    target = next(iter(_rule_ids(baseline)))

    tuned = profile.model_copy(update={"disabled_rules": [target]})
    audit = run_audit(prepared_flawed, tuned)
    assert target not in _rule_ids(audit)


def test_disabling_does_not_penalize_the_score(prepared_flawed, profile):
    """A rule that does not apply must not quietly cost points either."""
    baseline = run_audit(prepared_flawed, profile)
    worst = max(baseline.issues, key=lambda i: i.record_count)

    tuned = profile.model_copy(update={"disabled_rules": [worst.rule_id]})
    audit = run_audit(prepared_flawed, tuned)
    assert audit.overall_score >= baseline.overall_score
    assert audit.total_findings < baseline.total_findings


def test_a_follow_up_sub_rule_can_be_disabled_on_its_own(prepared_flawed, profile):
    """One registered rule emits several IDs; each must be separately disableable."""
    baseline = _rule_ids(run_audit(prepared_flawed, profile))
    followup_ids = sorted(r for r in baseline if r.startswith("DQ-05"))
    if len(followup_ids) < 2:
        pytest.skip("sample does not exercise multiple follow-up sub-rules")

    tuned = profile.model_copy(update={"disabled_rules": [followup_ids[0]]})
    remaining = _rule_ids(run_audit(prepared_flawed, tuned))
    assert followup_ids[0] not in remaining
    assert followup_ids[1] in remaining


def test_an_unknown_disabled_rule_id_is_harmless(prepared_flawed, profile):
    tuned = profile.model_copy(update={"disabled_rules": ["DQ-999"]})
    audit = run_audit(prepared_flawed, tuned)
    assert audit.total_findings == run_audit(prepared_flawed, profile).total_findings


def test_nothing_disabled_by_default(profile):
    assert profile.disabled_rules == []


# -- Thresholds --------------------------------------------------------------


def test_threshold_falls_back_to_the_rule_default(prepared_flawed, profile):
    ctx = RuleContext(data=prepared_flawed, profile=profile)
    assert ctx.threshold("anomaly_min_months", 6) == 6
    assert ctx.threshold("not_a_real_knob", 1.5) == 1.5


def test_a_profile_threshold_wins(prepared_flawed, profile):
    tuned = profile.model_copy(update={"rule_thresholds": {"anomaly_min_months": 99}})
    ctx = RuleContext(data=prepared_flawed, profile=tuned)
    assert ctx.threshold("anomaly_min_months", 6) == 99


def test_raising_the_anomaly_window_silences_the_trend_rules(prepared_flawed, profile):
    """Demanding more months than the data has must switch the rules off."""
    tuned = profile.model_copy(update={"rule_thresholds": {"anomaly_min_months": 999}})
    audit = run_audit(prepared_flawed, tuned)
    assert "DQ-061" not in _rule_ids(audit)
    assert "DQ-062" not in _rule_ids(audit)


def test_lowering_the_z_score_finds_more_anomalies(prepared_flawed, profile):
    strict = profile.model_copy(update={"rule_thresholds": {"enrollment_anomaly_zscore": 0.5}})
    lax = profile.model_copy(update={"rule_thresholds": {"enrollment_anomaly_zscore": 99.0}})

    strict_records = sum(
        i.record_count for i in run_audit(prepared_flawed, strict).issues if i.rule_id == "DQ-061"
    )
    lax_records = sum(
        i.record_count for i in run_audit(prepared_flawed, lax).issues if i.rule_id == "DQ-061"
    )
    assert strict_records > lax_records
    assert lax_records == 0


def test_default_behaviour_is_unchanged_when_nothing_is_configured(prepared_flawed, profile):
    """A profile naming no thresholds must behave exactly as before."""
    explicit_defaults = profile.model_copy(
        update={
            "rule_thresholds": {
                "income_outlier_min_sample": 20,
                "income_outlier_iqr_multiplier": 3.0,
                "anomaly_min_months": 6,
                "enrollment_anomaly_zscore": 2.0,
                "program_anomaly_zscore": 2.5,
            }
        }
    )
    baseline = run_audit(prepared_flawed, profile)
    same = run_audit(prepared_flawed, explicit_defaults)
    assert same.overall_score == baseline.overall_score
    assert same.total_findings == baseline.total_findings
