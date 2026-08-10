"""Compatibility facade for deterministic analytics APIs.

Implementations are split across models, calculations, and exports so callers keep
the established ``grant_assistant.analytics.metrics`` import path.
"""

from grant_assistant.analytics.calculations import (
    NOT_REPORTED_VALUES,
    SMALL_SAMPLE_N,
    compute_analytics,
)
from grant_assistant.analytics.calculations import (
    _age_group_labels as _age_group_labels,
)
from grant_assistant.analytics.calculations import (
    _evaluate_measures as _evaluate_measures,
)
from grant_assistant.analytics.calculations import (
    _rate as _rate,
)
from grant_assistant.analytics.calculations import (
    _stay_days as _stay_days,
)
from grant_assistant.analytics.exports import analytics_to_flat_frames, available_measure_metrics
from grant_assistant.analytics.models import (
    AnalyticsResult,
    FollowUpMetrics,
    MeasureResult,
    ProgramMetrics,
)

__all__ = [
    "NOT_REPORTED_VALUES",
    "SMALL_SAMPLE_N",
    "AnalyticsResult",
    "FollowUpMetrics",
    "MeasureResult",
    "ProgramMetrics",
    "analytics_to_flat_frames",
    "available_measure_metrics",
    "compute_analytics",
]
