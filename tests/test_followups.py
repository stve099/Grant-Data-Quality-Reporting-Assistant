"""Follow-up due/overdue calculation tests."""

from __future__ import annotations

from datetime import date

import pandas as pd

from grant_assistant import schema
from grant_assistant.configuration import FollowUpDef
from grant_assistant.followups import followup_status

FU_3M = FollowUpDef(
    key="3_month",
    label="3-Month Follow-Up",
    months_after_exit=3,
    completion_field=schema.FOLLOWUP_3M_DATE,
    grace_days=14,
)


def _frame(exit_date: str | None, completion: str | None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            schema.EXIT_DATE: [pd.Timestamp(exit_date) if exit_date else pd.NaT],
            schema.FOLLOWUP_3M_DATE: [pd.Timestamp(completion) if completion else pd.NaT],
        }
    )


def test_not_due_before_three_months():
    status = followup_status(_frame("2025-06-01", None), FU_3M, today=date(2025, 8, 15))
    assert not status.loc[0, "due"]
    assert not status.loc[0, "overdue"]


def test_due_exactly_at_three_months():
    status = followup_status(_frame("2025-06-01", None), FU_3M, today=date(2025, 9, 1))
    assert status.loc[0, "due"]
    assert not status.loc[0, "overdue"]  # inside the 14-day grace window


def test_overdue_after_grace_period():
    status = followup_status(_frame("2025-06-01", None), FU_3M, today=date(2025, 9, 16))
    assert status.loc[0, "due"]
    assert status.loc[0, "overdue"]


def test_completed_never_overdue():
    status = followup_status(_frame("2025-06-01", "2025-09-05"), FU_3M, today=date(2026, 1, 1))
    assert status.loc[0, "due"]
    assert status.loc[0, "completed"]
    assert not status.loc[0, "overdue"]


def test_active_client_never_due():
    status = followup_status(_frame(None, None), FU_3M, today=date(2026, 1, 1))
    assert not status.loc[0, "due"]
    assert not status.loc[0, "overdue"]


def test_due_date_calculation():
    status = followup_status(_frame("2025-01-31", None), FU_3M, today=date(2026, 1, 1))
    # pandas DateOffset clamps to the end of shorter months
    assert status.loc[0, "due_date"] == pd.Timestamp("2025-04-30")


def test_grace_days_zero_is_strict():
    fu = FollowUpDef(
        key="3_month",
        label="3-Month Follow-Up",
        months_after_exit=3,
        completion_field=schema.FOLLOWUP_3M_DATE,
        grace_days=0,
    )
    status = followup_status(_frame("2025-06-01", None), fu, today=date(2025, 9, 2))
    assert status.loc[0, "overdue"]
