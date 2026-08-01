"""Shared follow-up schedule calculations.

Used by both the audit rules (overdue detection) and analytics
(completion rates) so the two can never disagree.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from grant_assistant import schema
from grant_assistant.configuration import FollowUpDef


def followup_status(df: pd.DataFrame, fu: FollowUpDef, today: date) -> pd.DataFrame:
    """Compute per-row follow-up status for one milestone.

    Returns a frame aligned to ``df`` with columns:
        due_date: exit_date + months_after_exit (NaT when never due)
        due: the milestone has come due on/before ``today``
        completed: a completion date is recorded
        overdue: due, not completed, and past the grace window
    """
    exit_dates = pd.to_datetime(df[schema.EXIT_DATE])
    due_date = exit_dates + pd.DateOffset(months=fu.months_after_exit)
    today_ts = pd.Timestamp(today)
    due = due_date.notna() & (due_date <= today_ts)
    completed = pd.to_datetime(df[fu.completion_field]).notna()
    overdue = due & ~completed & ((due_date + pd.Timedelta(days=fu.grace_days)) < today_ts)
    return pd.DataFrame(
        {"due_date": due_date, "due": due, "completed": completed, "overdue": overdue},
        index=df.index,
    )
