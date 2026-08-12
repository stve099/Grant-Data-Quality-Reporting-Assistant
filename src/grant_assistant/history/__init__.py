"""Run history: track data quality and outcomes across reporting periods."""

from grant_assistant.history.aging import (
    RuleAge,
    resolved_since_last_run,
    rule_ages,
)
from grant_assistant.history.store import (
    DB_PATH_ENV_VAR,
    DEFAULT_DB_NAME,
    HistoryEntry,
    default_db_path,
    history_frame,
    load_history,
    metric_series,
    record_run,
    score_trend,
)
from grant_assistant.history.summary import (
    AgedFinding,
    HistorySummary,
    TrendPoint,
    build_history_summary,
    load_history_summary,
)

__all__ = [
    "DB_PATH_ENV_VAR",
    "DEFAULT_DB_NAME",
    "AgedFinding",
    "HistoryEntry",
    "HistorySummary",
    "RuleAge",
    "TrendPoint",
    "build_history_summary",
    "default_db_path",
    "history_frame",
    "load_history",
    "load_history_summary",
    "metric_series",
    "record_run",
    "resolved_since_last_run",
    "rule_ages",
    "score_trend",
]
