"""Streamlit analytics and period-comparison pages."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from grant_assistant.analytics import compute_analytics
from grant_assistant.analytics.charts import (
    demographic_chart,
    enrollment_trend_chart,
    exit_destination_chart,
    followup_chart,
    goal_vs_actual_chart,
    income_change_chart,
    outcome_rate_chart,
    program_comparison_chart,
)
from grant_assistant.configuration import (
    ProfileValidationError,
)
from grant_assistant.ingestion import IngestionError, load_dataset, prepare_dataset
from grant_assistant.ui import theme
from grant_assistant.ui.state import (
    pct as _pct,
)
from grant_assistant.ui.state import (
    require_data as _require_data,
)
from grant_assistant.ui.state import (
    usd as _usd,
)
from grant_assistant.ui.theme import Kpi


def page_analytics() -> None:
    if not _require_data("Analytics Dashboard"):
        return
    a = st.session_state["pipeline"]["analytics"]

    theme.page_header(
        "Analytics Dashboard",
        eyebrow="Analysis",
        subtitle="Deterministic program metrics calculated in tested Python — the same "
        "numbers used by the report generator and the AI analyst.",
        pills=[theme.pill(f"{a.period_start:%b %Y} – {a.period_end:%b %Y}", "info")],
    )

    theme.kpis(
        [
            Kpi("Enrollments", f"{a.total_enrollments:,}"),
            Kpi("Households", f"{a.households_served:,}"),
            Kpi(
                "Individuals",
                f"{a.total_individuals:,}",
                note=f"{a.total_adults:,} adults · {a.total_children:,} children",
            ),
            Kpi("Active", f"{a.active_enrollments:,}", tone="neutral"),
            Kpi("Exits", f"{a.total_exits:,}", note=f"{_pct(a.exit_rate)} of enrollments"),
            Kpi(
                "Successful exits",
                f"{a.successful_exits:,}",
                note=_pct(a.successful_exit_rate),
                tone="good",
                note_tone="good",
            ),
            Kpi(
                "Overdue follow-ups",
                f"{a.total_overdue_followups:,}",
                tone="critical" if a.total_overdue_followups else "good",
            ),
        ],
        min_width=146,
    )
    if a.notes:
        st.caption("Methodology notes: " + " · ".join(a.notes))

    tabs = st.tabs(
        ["Programs", "Trends", "Outcomes", "Demographics", "Income", "Follow-Ups", "Measures"]
    )

    with tabs[0]:
        if a.programs:
            st.plotly_chart(program_comparison_chart(a), use_container_width=True)
            st.plotly_chart(outcome_rate_chart(a), use_container_width=True)
            st.dataframe(
                pd.DataFrame([m.model_dump() for m in a.programs]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No program-level data available.")

    with tabs[1]:
        if a.monthly_enrollments:
            st.plotly_chart(enrollment_trend_chart(a), use_container_width=True)
            if a.month_over_month_enrollment_change is not None:
                change = a.month_over_month_enrollment_change
                theme.kpis(
                    [
                        Kpi(
                            "Month-over-month enrollment change",
                            f"{change:+.1f}%",
                            tone="good" if change >= 0 else "warning",
                        )
                    ],
                    min_width=260,
                )
        else:
            st.info("No dated enrollments to trend.")

    with tabs[2]:
        if a.exit_destination_breakdown:
            st.plotly_chart(exit_destination_chart(a), use_container_width=True)
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Outcome category": k.replace("_", " ").title(), "Exits": v}
                        for k, v in a.exit_category_breakdown.items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No exits with destinations recorded.")

    with tabs[3]:
        col1, col2 = st.columns(2, gap="large")
        with col1:
            st.plotly_chart(demographic_chart(a, "age_groups"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "gender"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "household_size"), use_container_width=True)
        with col2:
            st.plotly_chart(demographic_chart(a, "race"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "veteran_status"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "disability_status"), use_container_width=True)

    with tabs[4]:
        theme.kpis(
            [
                Kpi("Avg entry income", _usd(a.avg_entry_income)),
                Kpi("Avg exit income", _usd(a.avg_exit_income)),
                Kpi(
                    "Median income change",
                    _usd(a.median_income_change),
                    tone="good" if (a.median_income_change or 0) > 0 else "neutral",
                ),
                Kpi("Households increasing income", _pct(a.pct_income_increased), tone="good"),
                Kpi("Exits with income data", f"{a.n_income_pairs:,}", tone="neutral"),
            ]
        )
        if a.income_changes:
            st.plotly_chart(income_change_chart(a), use_container_width=True)
        else:
            st.info("No exits have both entry and exit income recorded.")

    with tabs[5]:
        if a.followups:
            st.plotly_chart(followup_chart(a), use_container_width=True)
            st.dataframe(
                pd.DataFrame([f.model_dump() for f in a.followups]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("This profile defines no follow-up schedule.")

    with tabs[6]:
        if a.measures:
            st.plotly_chart(goal_vs_actual_chart(a), use_container_width=True)
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "ID": m.id,
                            "Measure": m.name,
                            "Scope": m.program or "All programs",
                            "Target": m.target,
                            "Actual": m.actual,
                            "Status": "Met" if m.met else ("Not met" if m.met is False else "—"),
                            "Small sample": "Yes" if m.small_sample else "",
                        }
                        for m in a.measures
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("This profile defines no performance measures.")


# ---------------------------------------------------------------------------
# Page: Period Comparison
# ---------------------------------------------------------------------------


def page_comparison() -> None:
    if not _require_data("Period Comparison"):
        return
    from grant_assistant.analytics.charts import comparison_chart
    from grant_assistant.analytics.comparison import compare_analytics

    p = st.session_state["pipeline"]
    theme.page_header(
        "Period Comparison",
        eyebrow="Analysis",
        subtitle=f"The loaded extract ({p['filename']}) is the current period. Upload a "
        "prior-period extract with the same layout to compute deltas.",
        pills=[theme.pill(f"Current · {p['filename']}", "info")],
    )

    prior_upload = st.file_uploader(
        "Prior-period CSV or Excel extract",
        type=["csv", "xlsx", "xls", "xlsm"],
        key="prior_upload",
    )
    if prior_upload is None:
        st.info("Upload a prior-period file to compute period-over-period movement.")
        return

    try:
        prior_raw = load_dataset(io.BytesIO(prior_upload.getvalue()), filename=prior_upload.name)
        prior_prepared = prepare_dataset(prior_raw, p["profile"])
        prior_analytics = compute_analytics(prior_prepared, p["profile"])
    except (IngestionError, ProfileValidationError) as exc:
        st.error(str(exc))
        return

    comparison = compare_analytics(
        p["analytics"], prior_analytics, p["filename"], prior_upload.name
    )

    improved = sum(1 for d in comparison.headline if d.improved is True)
    declined = sum(1 for d in comparison.headline if d.improved is False)
    theme.kpis(
        [
            Kpi("Metrics improved", str(improved), tone="good"),
            Kpi("Metrics declined", str(declined), tone="critical" if declined else "good"),
            Kpi(
                "Metrics unchanged",
                str(len(comparison.headline) - improved - declined),
                tone="neutral",
            ),
        ],
        min_width=180,
    )

    theme.panel_title("Headline metrics")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Metric": d.label,
                    "Prior": d.format_value(d.prior),
                    "Current": d.format_value(d.current),
                    "Change": d.format_value(d.delta) if d.delta is not None else "n/a",
                    "% change": f"{d.pct_change:+.1f}%" if d.pct_change is not None else "—",
                    "Direction": (
                        "Improved"
                        if d.improved is True
                        else ("Declined" if d.improved is False else "No change")
                    ),
                }
                for d in comparison.headline
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.plotly_chart(comparison_chart(comparison), use_container_width=True)

    theme.panel_title("Program movement", "successful-exit rate")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Program": pr.program,
                    "Prior rate": _pct(pr.prior_rate),
                    "Current rate": _pct(pr.current_rate),
                    "Delta (pts)": pr.delta if pr.delta is not None else "n/a",
                    "Small sample": "Yes" if pr.small_sample else "",
                }
                for pr in comparison.programs
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    theme.panel_title("Narrative")
    for line in comparison.narrative:
        st.markdown(f"- {line}")


# ---------------------------------------------------------------------------
# Page: Analyst Chat
# ---------------------------------------------------------------------------
