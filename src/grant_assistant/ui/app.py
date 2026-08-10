"""Grant Data Quality & Reporting Assistant — Streamlit application.

Run with:
    uv run streamlit run src/grant_assistant/ui/app.py

Page functions hold only presentation logic; every calculation comes from the
audit, analytics, agent, and reporting packages.
"""

from __future__ import annotations

import io
import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from grant_assistant import schema
from grant_assistant.agents import DataAnalystAgent, get_provider
from grant_assistant.agents.provider import ai_available
from grant_assistant.agents.workflows import should_stream
from grant_assistant.analytics import compute_analytics
from grant_assistant.analytics.charts import (
    demographic_chart,
    dq_category_chart,
    dq_severity_chart,
    enrollment_trend_chart,
    exit_destination_chart,
    followup_chart,
    goal_vs_actual_chart,
    income_change_chart,
    outcome_rate_chart,
    program_comparison_chart,
)
from grant_assistant.analytics.metrics import available_measure_metrics
from grant_assistant.audit import list_rules, run_audit
from grant_assistant.configuration import ProfileValidationError, list_profiles, load_profile_file
from grant_assistant.corrections import write_worksheet
from grant_assistant.env import load_environment
from grant_assistant.ingestion import IngestionError, load_dataset, prepare_dataset
from grant_assistant.models import SEVERITY_ORDER
from grant_assistant.reporting import (
    build_report_data,
    render_html_report,
    write_analytics_workbook,
    write_audit_workbook,
    write_docx_report,
)
from grant_assistant.ui import theme
from grant_assistant.ui.theme import Kpi

load_environment()

st.set_page_config(
    page_title="Grant Assistant — Data Quality & Reporting",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject()

# Navigation: (group, page label). Labels carry no emoji — the rail styles them.
NAV: list[tuple[str, list[str]]] = [
    ("Data", ["Upload & Profile", "Data Preview"]),
    ("Quality", ["Audit Dashboard", "Issue Explorer"]),
    ("Analysis", ["Analytics Dashboard", "Period Comparison"]),
    ("AI Analyst", ["Analyst Chat", "Proactive Insights"]),
    ("Deliverables", ["Report Builder", "Export Center"]),
    ("Reference", ["Configuration Help"]),
]
PAGES = [page for _, pages in NAV for page in pages]


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _loaded() -> bool:
    return "pipeline" in st.session_state


@st.cache_data(show_spinner=False)
def _profile_label(profiles: dict[str, Path], profile_id: str) -> str:
    """Human label for a profile id, for the selector.

    Falls back to the id when the YAML will not load — the selector still has to
    render so the user can pick a different profile and read the error, rather
    than the page dying on the invalid one.
    """
    try:
        return load_profile_file(profiles[profile_id]).grant_name
    except (ProfileValidationError, KeyError, OSError):
        return profile_id


def _agent() -> DataAnalystAgent:
    if "agent" not in st.session_state:
        p = st.session_state["pipeline"]
        st.session_state["agent"] = DataAnalystAgent(
            p["analytics"], p["audit"], p["profile"], provider=get_provider()
        )
    return st.session_state["agent"]


def _require_data(page: str) -> bool:
    if not _loaded():
        theme.page_header(
            page,
            eyebrow="No dataset loaded",
            subtitle="Load a CSV or Excel extract on the Upload & Profile page to activate "
            "this view.",
        )
        st.info(
            "Go to **Upload & Profile** in the left rail, choose a grant profile, and run "
            "the pipeline."
        )
        return False
    return True


def _output_dir() -> Path:
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = Path(tempfile.mkdtemp(prefix="grant_assistant_"))
    return st.session_state["output_dir"]


def _score_tone(score: float) -> str:
    if score >= 90:
        return "good"
    if score >= 75:
        return "warning"
    return "critical"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


# ---------------------------------------------------------------------------
# Page: Upload & Profile
# ---------------------------------------------------------------------------


def page_upload() -> None:
    pills = [theme.pill("Synthetic demo data only", "warning")]
    if _loaded():
        p = st.session_state["pipeline"]
        pills.insert(0, theme.pill(f"Loaded · {p['filename']}", "good"))
    theme.page_header(
        "Upload & Profile",
        eyebrow="Workspace",
        subtitle="Select the grant reporting profile that matches your funder, then load a "
        "client-level enrollment extract. Never upload real client data to a demo "
        "environment.",
        pills=pills,
    )

    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        theme.panel_title("1 · Grant profile")
        profiles = list_profiles()
        if not profiles:
            st.error("No profiles found in configs/. Add a YAML profile to continue.")
            return
        # Show the grant name, not the profile id. The id is an internal key —
        # a user picking their funder should see "Stable Homes Grant", not
        # "housing_stability" — but the id stays the selected value because it
        # is what every other layer keys on.
        profile_id = st.selectbox(
            "Grant profile",
            sorted(profiles),
            key="profile_choice",
            label_visibility="collapsed",
            format_func=lambda pid: _profile_label(profiles, pid),
        )
        try:
            profile = load_profile_file(profiles[profile_id])
        except ProfileValidationError as exc:
            st.error(str(exc))
            return
        theme.kpis(
            [
                Kpi("Programs", str(len(profile.programs))),
                Kpi("Measures", str(len(profile.performance_measures))),
                Kpi("Follow-ups", str(len(profile.followup_schedule))),
            ],
            min_width=120,
        )
        st.markdown(
            f"**{profile.grant_name}**  \n"
            f"{profile.grantor or 'No grantor specified'}  \n"
            f"Reporting period: {profile.reporting_period.label}"
        )
        with st.expander("Profile detail"):
            st.markdown(f"**Programs:** {', '.join(profile.program_names)}")
            st.markdown(
                "**Performance measures:**\n"
                + "\n".join(
                    f"- {m.name} — target {m.target}" + (f" ({m.program})" if m.program else "")
                    for m in profile.performance_measures
                )
            )

    with col2:
        theme.panel_title("2 · Data extract")
        uploaded = st.file_uploader(
            "CSV or Excel enrollment extract",
            type=["csv", "xlsx", "xls", "xlsm"],
            label_visibility="collapsed",
        )
        st.caption(
            "Samples in `sample_data/`: `housing_program_clean.csv` audits at 100/100, "
            "`housing_program_flawed.csv` contains 23 documented injected error types."
        )

        theme.panel_title("3 · Run pipeline")
        if uploaded is None:
            st.info("Upload a file to enable the audit and analytics pipeline.")
        elif st.button("Run audit + analytics", type="primary", use_container_width=True):
            try:
                raw = load_dataset(io.BytesIO(uploaded.getvalue()), filename=uploaded.name)
                prepared = prepare_dataset(raw, profile)
                audit = run_audit(prepared, profile)
                analytics = compute_analytics(prepared, profile)
            except (IngestionError, ProfileValidationError) as exc:
                st.error(str(exc))
                return
            st.session_state["pipeline"] = {
                "prepared": prepared,
                "profile": profile,
                "audit": audit,
                "analytics": analytics,
                "filename": uploaded.name,
            }
            for key in ("agent", "chat_history", "report_html", "report_docx", "report_pdf"):
                st.session_state.pop(key, None)
            st.success(
                f"Processed **{uploaded.name}** — {len(prepared.df)} rows, data quality score "
                f"{audit.overall_score:.1f}/100 (grade {audit.grade})."
            )
            if audit.pii_warnings:
                st.error(
                    "**Possible personal information in this upload.** This tool is built "
                    "for pseudonymous extracts — remove or hash these columns and re-upload.\n\n- "
                    + "\n- ".join(audit.pii_warnings[:5])
                )
            if audit.injection_warnings:
                st.warning(
                    "Security note — possible prompt-injection text found in uploaded cells. "
                    "It is neutralized before any AI processing.\n\n- "
                    + "\n- ".join(audit.injection_warnings[:5])
                )


# ---------------------------------------------------------------------------
# Page: Data Preview
# ---------------------------------------------------------------------------


def page_preview() -> None:
    if not _require_data("Data Preview"):
        return
    p = st.session_state["pipeline"]
    prepared = p["prepared"]
    theme.page_header(
        "Data Preview",
        eyebrow="Workspace",
        subtitle="Source columns mapped onto the canonical schema, with dates and numerics "
        "coerced. Invalid values are preserved in the audit trail rather than silently "
        "dropped.",
        pills=[theme.pill(p["filename"], "info")],
    )
    theme.kpis(
        [
            Kpi("Rows", f"{len(prepared.df):,}"),
            Kpi("Mapped columns", str(len(prepared.mapped_columns)), tone="good"),
            Kpi(
                "Unmapped source columns",
                str(len(prepared.unmapped_source_columns)),
                tone="warning" if prepared.unmapped_source_columns else "neutral",
            ),
            Kpi(
                "Missing canonical columns",
                str(len(prepared.missing_canonical_columns)),
                tone="warning" if prepared.missing_canonical_columns else "neutral",
            ),
        ]
    )

    theme.panel_title("Prepared data", "canonical schema")
    st.dataframe(
        prepared.df.drop(columns=[schema.PROGRAM_RAW], errors="ignore"),
        use_container_width=True,
        height=430,
    )

    with st.expander("Field mapping applied"):
        st.dataframe(
            pd.DataFrame(
                [
                    {"Source column": s, "Canonical column": c}
                    for s, c in prepared.mapped_columns.items()
                ]
            ),
            use_container_width=True,
        )
        if prepared.unmapped_source_columns:
            st.warning("Ignored columns: " + ", ".join(prepared.unmapped_source_columns))
        if prepared.missing_canonical_columns:
            st.info(
                "Canonical columns absent from the upload: "
                + ", ".join(prepared.missing_canonical_columns)
            )


# ---------------------------------------------------------------------------
# Page: Audit Dashboard
# ---------------------------------------------------------------------------


def page_audit() -> None:
    if not _require_data("Audit Dashboard"):
        return
    audit = st.session_state["pipeline"]["audit"]

    pills = [theme.pill(f"Grade {audit.grade}", _score_tone(audit.overall_score))]  # type: ignore[arg-type]
    if audit.blocking_issues:
        pills.append(theme.pill(f"{len(audit.blocking_issues)} blocking", "critical"))
    else:
        pills.append(theme.pill("No blocking issues", "good"))
    theme.page_header(
        "Audit Dashboard",
        eyebrow="Data Quality",
        subtitle=f"{len(list_rules())} configurable rules across completeness, uniqueness, "
        "validity, consistency, case management, timeliness, and statistical anomalies.",
        pills=pills,
    )

    counts = audit.issue_count_by_severity
    theme.kpis(
        [
            Kpi(
                "Overall score",
                f"{audit.overall_score:.1f}",
                unit="/100",
                note=f"Grade {audit.grade}",
                tone=_score_tone(audit.overall_score),  # type: ignore[arg-type]
                note_tone=_score_tone(audit.overall_score),  # type: ignore[arg-type]
            ),
            Kpi("Records audited", f"{audit.total_rows:,}", tone="neutral"),
            Kpi("Total findings", f"{audit.total_findings:,}", tone="info"),
            Kpi(
                "Critical + high",
                f"{counts['critical'] + counts['high']:,}",
                tone="critical" if counts["critical"] + counts["high"] else "good",
            ),
            Kpi(
                "Blocking rule types",
                str(len(audit.blocking_issues)),
                note="Must clear before submission" if audit.blocking_issues else "Clear",
                tone="critical" if audit.blocking_issues else "good",
                note_tone="critical" if audit.blocking_issues else "good",
            ),
        ]
    )

    if audit.blocking_issues:
        st.error(
            "**Blocking issues must be resolved before funder submission**\n\n"
            + "\n".join(
                f"- `{i.rule_id}` {i.rule_name} — {i.record_count} record(s)"
                for i in audit.blocking_issues
            )
        )
    if audit.pii_warnings:
        st.error(
            f"{len(audit.pii_warnings)} column(s) look like they contain personal information. "
            "See the Upload page for detail — this tool expects pseudonymous extracts."
        )
    if audit.injection_warnings:
        st.warning(
            f"{len(audit.injection_warnings)} cell(s) contain text resembling prompt-injection "
            "attempts. They are neutralized before any AI processing."
        )

    col1, col2 = st.columns(2, gap="large")
    with col1:
        theme.panel_title("Findings by severity")
        st.plotly_chart(dq_severity_chart(audit), use_container_width=True)
    with col2:
        theme.panel_title("Score by category")
        if audit.score_by_category:
            st.plotly_chart(dq_category_chart(audit), use_container_width=True)
        else:
            st.success("No category scored below 100 — no findings in any category.")

    if audit.score_by_program:
        theme.panel_title("Score by program")
        st.dataframe(
            pd.DataFrame(
                [{"Program": k, "Data quality score": v} for k, v in audit.score_by_program.items()]
            ),
            use_container_width=True,
            hide_index=True,
        )

    theme.panel_title("Findings by rule", "sorted by severity, then volume")
    rows = [
        {
            "Rule": i.rule_id,
            "Finding": i.rule_name,
            "Category": i.category.replace("_", " ").title(),
            "Severity": i.severity.label,
            "Blocking": "Yes" if i.blocking else "—",
            "Records": i.record_count,
            "Recommended correction": i.recommendation,
        }
        for i in audit.issues_sorted()
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=420, hide_index=True)
    else:
        st.success("No data quality issues detected — this dataset is clean.")

    theme.panel_title("Executive audit summary")
    st.write(audit.executive_summary())


# ---------------------------------------------------------------------------
# Page: Issue Explorer
# ---------------------------------------------------------------------------


def page_issues() -> None:
    if not _require_data("Issue Explorer"):
        return
    audit = st.session_state["pipeline"]["audit"]
    frame = audit.row_level_frame()

    theme.page_header(
        "Issue Explorer",
        eyebrow="Data Quality",
        subtitle="Row-level findings for correction work. Client-level detail appears here "
        "because you opened this view explicitly — AI answers and reports stay aggregated.",
        pills=[theme.pill(f"{len(frame):,} findings", "info")],
    )
    if frame.empty:
        st.success("No row-level issues to explore — the dataset is clean.")
        return

    c1, c2, c3 = st.columns(3)
    severities = c1.multiselect(
        "Severity", [s.label for s in SEVERITY_ORDER], default=[], placeholder="All severities"
    )
    rules = c2.multiselect(
        "Rule", sorted(frame["rule_id"].unique()), default=[], placeholder="All rules"
    )
    programs = c3.multiselect(
        "Program",
        sorted(x for x in frame["program"].dropna().unique() if x),
        default=[],
        placeholder="All programs",
    )

    filtered = frame
    if severities:
        filtered = filtered[filtered["severity"].isin(severities)]
    if rules:
        filtered = filtered[filtered["rule_id"].isin(rules)]
    if programs:
        filtered = filtered[filtered["program"].isin(programs)]

    theme.panel_title("Findings", f"{len(filtered):,} of {len(frame):,} shown")
    st.dataframe(filtered, use_container_width=True, height=460, hide_index=True)
    st.download_button(
        "Download filtered findings (CSV)",
        data=filtered.to_csv(index=False).encode("utf-8"),
        file_name="row_level_issues.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Page: Analytics Dashboard
# ---------------------------------------------------------------------------


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


def page_chat() -> None:
    if not _require_data("Analyst Chat"):
        return
    agent = _agent()
    mode_pill = (
        theme.pill("AI mode · Claude with tool use", "good")
        if agent.ai_enabled
        else theme.pill("Deterministic mode · no API key", "warning")
    )
    theme.page_header(
        "Analyst Chat",
        eyebrow="AI Analyst",
        subtitle="A senior-analyst agent grounded in the calculated metrics. It retrieves "
        "values through typed tools, never invents numbers, and keeps answers aggregated.",
        pills=[mode_pill],
    )

    examples = [
        "Which program had the highest successful exit rate?",
        "Which clients are overdue for follow-up?",
        "Summarize grant outcomes for the reporting period.",
        "Which data quality issues could affect this report?",
        "Are any metrics distorted by small sample sizes?",
        "Which outcomes are below target?",
    ]
    with st.expander("Example questions"):
        for example in examples:
            st.markdown(f"- {example}")

    history: list[dict[str, str]] = st.session_state.setdefault("chat_history", [])
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    response_mode = st.radio(
        "Response mode",
        ["Automatic", "Always stream", "Always use tools"],
        horizontal=True,
        help="Automatic streams narrative questions and uses the lookup tools for "
        "anything that needs a specific figure. Streaming cannot run the tool loop, "
        "so a streamed number comes from the fact sheet rather than a traced "
        "retrieval — which is why picking per question was never the user's job.",
        disabled=not agent.ai_enabled,
    )

    question: str | None = st.chat_input("Ask the senior data analyst…")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        if response_mode == "Always stream":
            stream_this = True
        elif response_mode == "Always use tools":
            stream_this = False
        else:
            stream_this = should_stream(question)

        with st.chat_message("assistant"):
            if stream_this and agent.ai_enabled:
                answer = st.write_stream(agent.ask_stream(question, history=history[-8:]))
            else:
                with st.spinner("Retrieving values…" if agent.ai_enabled else "Analyzing…"):
                    answer = agent.ask(question, history=history[-8:])
                    st.markdown(answer)
                if agent.ai_enabled and response_mode == "Automatic":
                    st.caption("Answered with lookup tools, so every figure is retrieved.")
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": str(answer)})

    usage = getattr(agent.provider, "usage", None)
    if usage is not None and usage.calls:
        st.caption(f"Session usage — {usage.session_summary()}")


# ---------------------------------------------------------------------------
# Page: Proactive Insights
# ---------------------------------------------------------------------------


def page_insights() -> None:
    if not _require_data("Proactive Insights"):
        return
    agent = _agent()
    report = agent.proactive_insights()
    theme.page_header(
        "Proactive Insights",
        eyebrow="AI Analyst",
        subtitle="A senior-analyst review generated automatically from the calculated "
        "results — anomalies, trends, risks, and recommended actions. Works with or "
        "without an API key.",
        pills=[
            theme.pill(f"{sum(len(v) for v in report.sections().values())} observations", "info")
        ],
    )

    tone_by_section: dict[str, str] = {
        "Anomalies Detected": "warning",
        "Data Quality Risks": "critical",
        "Program Concerns": "warning",
        "Program Strengths": "good",
        "Recommended Actions": "info",
    }
    left, right = st.columns(2, gap="large")
    sections = [(title, items) for title, items in report.sections().items() if items]
    for index, (title, items) in enumerate(sections):
        target = left if index % 2 == 0 else right
        with target:
            theme.panel_title(title)
            tone = tone_by_section.get(title, "neutral")
            body = "\n".join(f"- {item}" for item in items)
            if tone == "critical":
                st.error(body)
            elif tone == "warning":
                st.warning(body)
            elif tone == "good":
                st.success(body)
            else:
                st.markdown(body)

    if agent.ai_enabled:
        theme.panel_title("AI narrative")
        if st.button("Generate AI-polished narrative"):
            with st.spinner("Narrating insights…"):
                st.markdown(agent.narrated_insights())


# ---------------------------------------------------------------------------
# Page: Report Builder
# ---------------------------------------------------------------------------


def page_report() -> None:
    if not _require_data("Report Builder"):
        return
    from grant_assistant.reporting import PdfBackendError, pdf_backend, write_pdf_report

    p = st.session_state["pipeline"]
    agent = _agent()
    narrative_pill = (
        theme.pill("AI-assisted narrative", "good")
        if agent.ai_enabled
        else theme.pill("Deterministic narrative", "neutral")
    )
    theme.page_header(
        "Report Builder",
        eyebrow="Deliverables",
        subtitle=f"{p['profile'].report.title} · {p['profile'].reporting_period.label}. "
        "Includes cover, executive summary, data quality statement, population, "
        "demographics, outcomes, income, follow-ups, measures, program comparison, "
        "charts, findings, recommendations, methodology, limitations, and appendix.",
        pills=[narrative_pill],
    )

    template_label = st.radio(
        "Template",
        ["Full report", "Executive brief"],
        horizontal=True,
        help="The full report is the complete funder submission. The executive brief is a "
        "2–3 page summary built from the same calculated results.",
    )
    template = "full" if template_label == "Full report" else "concise"

    if st.button("Build report", type="primary"):
        with st.spinner("Generating report…"):
            data = build_report_data(p["analytics"], p["audit"], p["profile"], agent)
            st.session_state["report_template"] = template
            st.session_state["report_html"] = render_html_report(data, template=template)
            st.session_state["report_docx"] = write_docx_report(
                data, _output_dir() / "grant_report.docx"
            ).read_bytes()
            st.session_state["report_summary"] = data.executive_summary
            st.session_state.pop("report_pdf", None)
        st.success("Report generated.")

    if "report_html" not in st.session_state:
        return

    theme.panel_title("Executive summary preview")
    st.write(st.session_state["report_summary"])

    theme.panel_title("Download")
    col1, col2, col3 = st.columns(3)
    col1.download_button(
        "HTML report",
        data=st.session_state["report_html"].encode("utf-8"),
        file_name="grant_report.html",
        mime="text/html",
        use_container_width=True,
    )
    col2.download_button(
        "Word report",
        data=st.session_state["report_docx"],
        file_name="grant_report.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
    )
    with col3:
        if "report_pdf" in st.session_state:
            st.download_button(
                "PDF report",
                data=st.session_state["report_pdf"],
                file_name="grant_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        elif pdf_backend() is None:
            st.caption(
                "PDF needs a headless browser: `uv sync --extra pdf` then "
                "`uv run playwright install chromium`."
            )
        elif st.button("Render PDF", use_container_width=True):
            with st.spinner("Rendering PDF…"):
                try:
                    data = build_report_data(p["analytics"], p["audit"], p["profile"], agent)
                    st.session_state["report_pdf"] = write_pdf_report(
                        data,
                        _output_dir() / "grant_report.pdf",
                        template=st.session_state.get("report_template", "full"),
                    ).read_bytes()
                    st.rerun()
                except PdfBackendError as exc:
                    st.error(str(exc))

    with st.expander("Inline preview"):
        st.components.v1.html(st.session_state["report_html"], height=650, scrolling=True)


# ---------------------------------------------------------------------------
# Page: Export Center
# ---------------------------------------------------------------------------


def page_exports() -> None:
    if not _require_data("Export Center"):
        return
    p = st.session_state["pipeline"]
    out = _output_dir()
    theme.page_header(
        "Export Center",
        eyebrow="Deliverables",
        subtitle="Every artifact from this session: audit workbooks with a correction "
        "template, analytics summaries, row-level findings, and generated reports.",
    )

    col1, col2 = st.columns(2, gap="large")

    with col1:
        theme.panel_title("Audit exports")
        if st.button("Prepare audit workbook", use_container_width=True):
            st.session_state["export_audit"] = write_audit_workbook(
                p["audit"], p["prepared"], out / "audit_workbook.xlsx"
            ).read_bytes()
        if "export_audit" in st.session_state:
            st.download_button(
                "audit_workbook.xlsx",
                data=st.session_state["export_audit"],
                file_name="audit_workbook.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        st.download_button(
            "row_level_issues.csv",
            data=p["audit"].row_level_frame().to_csv(index=False).encode("utf-8"),
            file_name="row_level_issues.csv",
            mime="text/csv",
            use_container_width=True,
        )
        if st.button("Prepare correction worksheet", use_container_width=True):
            st.session_state["export_corrections"] = write_worksheet(
                p["audit"], out / "corrections.xlsx"
            ).read_bytes()
        if "export_corrections" in st.session_state:
            st.download_button(
                "corrections.xlsx",
                data=st.session_state["export_corrections"],
                file_name="corrections.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            st.caption(
                "Fill in 'Corrected Value', then apply it with: "
                "`grant-assistant apply-corrections <data file> corrections.xlsx`"
            )

    with col2:
        theme.panel_title("Analytics exports")
        if st.button("Prepare analytics workbook", use_container_width=True):
            st.session_state["export_analytics"] = write_analytics_workbook(
                p["analytics"], out / "analytics_summary.xlsx"
            ).read_bytes()
        if "export_analytics" in st.session_state:
            st.download_button(
                "analytics_summary.xlsx",
                data=st.session_state["export_analytics"],
                file_name="analytics_summary.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        st.download_button(
            "analytics.json",
            data=p["analytics"].model_dump_json(indent=2).encode("utf-8"),
            file_name="analytics.json",
            mime="application/json",
            use_container_width=True,
        )

    theme.panel_title("Reports", "built on the Report Builder page")
    if "report_html" in st.session_state or "report_docx" in st.session_state:
        rcol1, rcol2 = st.columns(2)
        if "report_html" in st.session_state:
            rcol1.download_button(
                "grant_report.html",
                data=st.session_state["report_html"].encode("utf-8"),
                file_name="grant_report.html",
                mime="text/html",
                key="export_html",
                use_container_width=True,
            )
        if "report_docx" in st.session_state:
            rcol2.download_button(
                "grant_report.docx",
                data=st.session_state["report_docx"],
                file_name="grant_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="export_docx",
                use_container_width=True,
            )
    else:
        st.info("No report built yet — visit **Report Builder** to generate one.")


# ---------------------------------------------------------------------------
# Page: Configuration Help
# ---------------------------------------------------------------------------


def page_config_help() -> None:
    theme.page_header(
        "Configuration Help",
        eyebrow="Reference",
        subtitle="Grant profiles are YAML files in configs/. They drive field mappings, "
        "controlled vocabularies, follow-up schedules, performance targets, outcome "
        "definitions, severity overrides, and blocking rules.",
        pills=[theme.pill(f"{len(list_rules())} audit rules", "info")],
    )

    st.markdown(
        """
**To add a grant profile**

1. Copy an existing profile in `configs/` (for example `housing_stability.yaml`).
2. Set a unique `profile_id`, then update `grant_name` and `reporting_period`.
3. Map each spreadsheet header to a canonical column in `field_mappings`.
4. Define programs with any alias labels that appear in your data.
5. Adjust `controlled_values`, `followup_schedule`, and `performance_measures`.
6. Validate: `uv run grant-assistant validate-config`

Full guide: `docs/creating_profiles.md`. Design tokens: `docs/design_system.md`.
        """
    )

    tab1, tab2, tab3 = st.tabs(["Canonical schema", "Measure metrics", "Audit rules"])
    with tab1:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Canonical column": c, "Report label": schema.label_for(c)}
                    for c in schema.CANONICAL_COLUMNS
                ]
            ),
            use_container_width=True,
            height=380,
            hide_index=True,
        )
    with tab2:
        st.caption("Values a profile's `performance_measures.metric` may reference.")
        st.code("\n".join(available_measure_metrics()))
        st.caption(
            "Add `program: <name>` to a measure to scope it to a single program "
            "(enrollments, exits, exit_rate, successful_exit_rate, permanent_housing_rate, "
            "avg_income_change, median_income_change)."
        )
    with tab3:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Rule": m.rule_id,
                        "Name": m.name,
                        "Category": m.category.replace("_", " ").title(),
                        "Default severity": m.severity.label,
                        "Blocking": "Yes" if m.blocking else "—",
                        "Description": m.description,
                    }
                    for m in list_rules()
                ]
            ),
            use_container_width=True,
            height=420,
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# Demo autoload + router
# ---------------------------------------------------------------------------


def _demo_autoload() -> None:
    """Preload a dataset when GRANT_ASSISTANT_DEMO or ?demo= is supplied.

    Used for demos and screenshots, e.g.
        ?demo=housing_program_flawed.csv&profile=housing_stability
    """
    demo_file = os.environ.get("GRANT_ASSISTANT_DEMO", "").strip()
    demo_profile = os.environ.get("GRANT_ASSISTANT_DEMO_PROFILE", "").strip()
    query_demo = st.query_params.get("demo", "")
    if query_demo:
        candidate = (Path("sample_data") / Path(query_demo).name).resolve()
        if candidate.is_file():
            demo_file = str(candidate)
            demo_profile = st.query_params.get("profile", demo_profile)
    if not demo_file or _loaded():
        return
    demo_path = Path(demo_file)
    profiles = list_profiles()
    if not demo_path.exists() or not profiles:
        return
    profile_id = demo_profile or sorted(profiles)[0]
    if profile_id not in profiles:
        return
    profile = load_profile_file(profiles[profile_id])
    prepared = prepare_dataset(load_dataset(demo_path), profile)
    st.session_state["pipeline"] = {
        "prepared": prepared,
        "profile": profile,
        "audit": run_audit(prepared, profile),
        "analytics": compute_analytics(prepared, profile),
        "filename": demo_path.name,
    }


def _select_page(group: str) -> None:
    """Nav callback: adopt this group's choice and clear the other groups.

    The rail is several radio groups, so exactly one selection must survive —
    otherwise two rows render as active.
    """
    choice = st.session_state.get(f"nav_{group}")
    if choice is None:
        return
    st.session_state["nav_page"] = choice
    for other, _pages in NAV:
        if other != group:
            st.session_state[f"nav_{other}"] = None


def _rail() -> str:
    """Render the navigation rail and return the selected page."""
    with st.sidebar:
        theme.brand()
        current = st.session_state.get("nav_page", PAGES[0])
        for group, pages in NAV:
            theme.nav_group(group)
            st.radio(
                group,
                pages,
                index=pages.index(current) if current in pages else None,
                key=f"nav_{group}",
                on_change=_select_page,
                args=(group,),
                label_visibility="collapsed",
            )
        selected = st.session_state.get("nav_page", PAGES[0])
        if _loaded():
            p = st.session_state["pipeline"]
            audit = p["audit"]
            theme.rail_card(
                [
                    ("Dataset", p["filename"]),
                    ("Profile", p["profile"].profile_id),
                    ("Records", f"{audit.total_rows:,}"),
                    ("DQ score", f"{audit.overall_score:.1f} ({audit.grade})"),
                ]
            )
        else:
            theme.rail_card([("Dataset", "None loaded"), ("Profile", "—")])
        theme.rail_note(
            ("AI mode enabled" if ai_available() else "AI mode off — deterministic answers")
            + f" · {date.today():%b %d, %Y}"
        )
    return selected


def main() -> None:
    _demo_autoload()
    selected = _rail()
    router = {
        "Upload & Profile": page_upload,
        "Data Preview": page_preview,
        "Audit Dashboard": page_audit,
        "Issue Explorer": page_issues,
        "Analytics Dashboard": page_analytics,
        "Period Comparison": page_comparison,
        "Analyst Chat": page_chat,
        "Proactive Insights": page_insights,
        "Report Builder": page_report,
        "Export Center": page_exports,
        "Configuration Help": page_config_help,
    }
    router[selected]()


main()
