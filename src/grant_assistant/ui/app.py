"""Grant Data Quality & Reporting Assistant — Streamlit application.

Run with:
    uv run streamlit run src/grant_assistant/ui/app.py
"""

from __future__ import annotations

import io
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from grant_assistant import schema
from grant_assistant.agents import DataAnalystAgent, get_provider
from grant_assistant.agents.provider import ai_available
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
from grant_assistant.ingestion import IngestionError, load_dataset, prepare_dataset
from grant_assistant.models import SEVERITY_ORDER
from grant_assistant.reporting import (
    build_report_data,
    render_html_report,
    write_analytics_workbook,
    write_audit_workbook,
    write_docx_report,
)

load_dotenv()

st.set_page_config(
    page_title="Grant Data Quality & Reporting Assistant",
    page_icon="📊",
    layout="wide",
)

# Design-system chrome (tokens documented in docs/design_system.md).
st.markdown(
    """
<style>
:root {
  --ga-surface: #fcfcfb; --ga-surface-2: #f0efec; --ga-ink: #0b0b0b;
  --ga-ink-2: #52514e; --ga-muted: #898781; --ga-grid: #e1e0d9;
  --ga-baseline: #c3c2b7; --ga-blue: #2a78d6; --ga-blue-deep: #1c5cab;
  --ga-good: #0ca30c; --ga-critical: #d03b3b;
}
/* KPI tiles */
div[data-testid="stMetric"] {
  background: var(--ga-surface);
  border: 1px solid var(--ga-grid);
  border-radius: 12px;
  padding: 14px 16px 12px;
  box-shadow: 0 1px 2px rgba(11,11,11,0.04);
}
div[data-testid="stMetric"] label { color: var(--ga-ink-2); }
div[data-testid="stMetricValue"] {
  color: var(--ga-blue-deep);
  font-variant-numeric: tabular-nums;
}
/* Headings */
h1, h2, h3 { color: var(--ga-ink); letter-spacing: -0.01em; }
h1 { font-weight: 700; }
/* Sidebar */
section[data-testid="stSidebar"] {
  background: var(--ga-surface-2);
  border-right: 1px solid var(--ga-grid);
}
section[data-testid="stSidebar"] .stRadio label { color: var(--ga-ink); }
/* Buttons */
button[kind="primary"] { border-radius: 8px; }
/* Dataframes: hairline border to sit on the surface */
div[data-testid="stDataFrame"] {
  border: 1px solid var(--ga-grid);
  border-radius: 10px;
  overflow: hidden;
}
/* Tabs underline in brand blue */
button[data-baseweb="tab"][aria-selected="true"] { color: var(--ga-blue-deep); }
</style>
""",
    unsafe_allow_html=True,
)

PAGES = [
    "🏠 Upload & Profile",
    "🔎 Data Preview",
    "🧪 Audit Dashboard",
    "🗂️ Issue Explorer",
    "📈 Analytics Dashboard",
    "🔁 Period Comparison",
    "💬 AI Analyst Chat",
    "🧠 Proactive Insights",
    "📄 Report Builder",
    "⬇️ Export Center",
    "⚙️ Configuration Help",
]


def _state() -> st.session_state:  # type: ignore[valid-type]
    return st.session_state


def _loaded() -> bool:
    return "pipeline" in st.session_state


def _agent() -> DataAnalystAgent:
    if "agent" not in st.session_state:
        p = st.session_state["pipeline"]
        st.session_state["agent"] = DataAnalystAgent(
            p["analytics"], p["audit"], p["profile"], provider=get_provider()
        )
    return st.session_state["agent"]


def _require_data() -> bool:
    if not _loaded():
        st.info("Upload a data file and run the pipeline on the **Upload & Profile** page first.")
        return False
    return True


def _output_dir() -> Path:
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = Path(tempfile.mkdtemp(prefix="grant_assistant_"))
    return st.session_state["output_dir"]


# ---------------------------------------------------------------------------
# Page: Upload & Profile
# ---------------------------------------------------------------------------


def page_upload() -> None:
    st.title("Grant Data Quality & Reporting Assistant")
    st.markdown(
        "Audit client-level program data, explore analytics, ask a grounded AI data "
        "analyst, and generate professional grant reports. **Synthetic demo data only — "
        "never upload real client information to a demo environment.**"
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1 · Choose a grant profile")
        profiles = list_profiles()
        if not profiles:
            st.error("No profiles found in configs/. Add a YAML profile to continue.")
            return
        profile_id = st.selectbox("Grant profile", sorted(profiles), key="profile_choice")
        try:
            profile = load_profile_file(profiles[profile_id])
            st.success(
                f"**{profile.grant_name}** · {profile.reporting_period.label} · "
                f"{len(profile.programs)} programs · "
                f"{len(profile.performance_measures)} performance measures"
            )
            with st.expander("Profile details"):
                st.markdown(f"**Grantor:** {profile.grantor or '—'}")
                st.markdown(f"**Programs:** {', '.join(profile.program_names)}")
                st.markdown(
                    "**Measures:** "
                    + "; ".join(
                        f"{m.name} (target {m.target})" for m in profile.performance_measures
                    )
                )
        except ProfileValidationError as exc:
            st.error(str(exc))
            return

    with col2:
        st.subheader("2 · Upload your data")
        uploaded = st.file_uploader(
            "CSV or Excel enrollment extract",
            type=["csv", "xlsx", "xls", "xlsm"],
            help="Try sample_data/housing_program_flawed.csv from the repository.",
        )
        st.caption(
            "Sample files live in the repository's `sample_data/` folder: a clean file "
            "and a flawed file with documented, intentionally injected errors."
        )

    st.subheader("3 · Run the pipeline")
    if uploaded is None:
        st.info("Upload a file to enable the pipeline.")
        return
    if st.button("Run audit + analytics", type="primary"):
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
        st.session_state.pop("agent", None)
        st.session_state.pop("chat_history", None)
        st.success(
            f"Processed **{uploaded.name}**: {len(prepared.df)} rows · data quality score "
            f"{audit.overall_score:.1f}/100 (grade {audit.grade}). Use the sidebar to explore."
        )
        if audit.injection_warnings:
            st.warning(
                "Security note — possible prompt-injection text found in the file:\n\n- "
                + "\n- ".join(audit.injection_warnings)
            )

    if _loaded():
        p = st.session_state["pipeline"]
        st.caption(f"Currently loaded: {p['filename']} with profile '{p['profile'].profile_id}'.")


# ---------------------------------------------------------------------------
# Page: Data Preview
# ---------------------------------------------------------------------------


def page_preview() -> None:
    st.header("Data Preview")
    if not _require_data():
        return
    p = st.session_state["pipeline"]
    prepared = p["prepared"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", len(prepared.df))
    c2.metric("Mapped columns", len(prepared.mapped_columns))
    c3.metric("Unmapped source columns", len(prepared.unmapped_source_columns))

    st.subheader("Prepared data (canonical schema)")
    display = prepared.df.drop(columns=[schema.PROGRAM_RAW], errors="ignore")
    st.dataframe(display, use_container_width=True, height=420)

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
            st.warning("Unmapped columns ignored: " + ", ".join(prepared.unmapped_source_columns))
        if prepared.missing_canonical_columns:
            st.info(
                "Canonical columns not present in the upload: "
                + ", ".join(prepared.missing_canonical_columns)
            )


# ---------------------------------------------------------------------------
# Page: Audit Dashboard
# ---------------------------------------------------------------------------


def page_audit() -> None:
    st.header("Data Quality Audit")
    if not _require_data():
        return
    p = st.session_state["pipeline"]
    audit = p["audit"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overall score", f"{audit.overall_score:.1f}/100")
    c2.metric("Grade", audit.grade)
    c3.metric("Total findings", audit.total_findings)
    c4.metric("Blocking issue types", len(audit.blocking_issues))

    if audit.blocking_issues:
        st.error(
            "**Blocking issues must be resolved before funder submission:**\n\n- "
            + "\n- ".join(
                f"{i.rule_id} {i.rule_name} ({i.record_count} records)"
                for i in audit.blocking_issues
            )
        )
    if audit.injection_warnings:
        st.warning(
            "Possible prompt-injection content detected in uploaded cells. It is "
            "neutralized before any AI processing."
        )

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(dq_severity_chart(audit), use_container_width=True)
    with col2:
        if audit.score_by_category:
            st.plotly_chart(dq_category_chart(audit), use_container_width=True)

    if audit.score_by_program:
        st.subheader("Score by program")
        st.dataframe(
            pd.DataFrame([{"Program": k, "Score": v} for k, v in audit.score_by_program.items()]),
            use_container_width=True,
        )

    st.subheader("Findings by rule")
    rows = [
        {
            "Rule": i.rule_id,
            "Name": i.rule_name,
            "Category": i.category,
            "Severity": i.severity.label,
            "Blocking": "Yes" if i.blocking else "No",
            "Records": i.record_count,
            "Recommendation": i.recommendation,
        }
        for i in audit.issues_sorted()
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=420)
    else:
        st.success("No data quality issues detected — this dataset is clean. 🎉")

    st.subheader("Executive audit summary")
    st.write(audit.executive_summary())


# ---------------------------------------------------------------------------
# Page: Issue Explorer
# ---------------------------------------------------------------------------


def page_issues() -> None:
    st.header("Issue Explorer")
    if not _require_data():
        return
    p = st.session_state["pipeline"]
    audit = p["audit"]
    frame = audit.row_level_frame()
    if frame.empty:
        st.success("No row-level issues to explore — the dataset is clean.")
        return

    st.caption(
        "Row-level findings are shown here because you explicitly opened the Issue "
        "Explorer; AI chat and reports only use aggregated results."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        severities = c1.multiselect(
            "Severity", [s.label for s in SEVERITY_ORDER], default=[], placeholder="All"
        )
    with c2:
        rules = c2.multiselect(
            "Rule", sorted(frame["rule_id"].unique()), default=[], placeholder="All"
        )
    with c3:
        programs = c3.multiselect(
            "Program", sorted(frame["program"].dropna().unique()), default=[], placeholder="All"
        )

    filtered = frame
    if severities:
        filtered = filtered[filtered["severity"].isin(severities)]
    if rules:
        filtered = filtered[filtered["rule_id"].isin(rules)]
    if programs:
        filtered = filtered[filtered["program"].isin(programs)]

    st.write(f"{len(filtered)} finding(s) shown of {len(frame)} total.")
    st.dataframe(filtered, use_container_width=True, height=460)
    st.download_button(
        "Download row-level issues (CSV)",
        data=filtered.to_csv(index=False).encode("utf-8"),
        file_name="row_level_issues.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Page: Analytics Dashboard
# ---------------------------------------------------------------------------


def page_analytics() -> None:
    st.header("Analytics Dashboard")
    if not _require_data():
        return
    p = st.session_state["pipeline"]
    a = p["analytics"]

    c = st.columns(6)
    c[0].metric("Enrollments", a.total_enrollments)
    c[1].metric("Households", a.households_served)
    c[2].metric("Individuals", a.total_individuals)
    c[3].metric("Active", a.active_enrollments)
    c[4].metric("Exits", a.total_exits)
    c[5].metric(
        "Successful exits",
        a.successful_exits,
        f"{a.successful_exit_rate}%" if a.successful_exit_rate is not None else None,
    )

    if a.notes:
        st.caption(" · ".join(a.notes))

    tab_prog, tab_trend, tab_outcome, tab_demo, tab_income, tab_follow, tab_measures = st.tabs(
        ["Programs", "Trends", "Outcomes", "Demographics", "Income", "Follow-Ups", "Measures"]
    )

    with tab_prog:
        if a.programs:
            st.plotly_chart(program_comparison_chart(a), use_container_width=True)
            st.plotly_chart(outcome_rate_chart(a), use_container_width=True)
            st.dataframe(
                pd.DataFrame([m.model_dump() for m in a.programs]),
                use_container_width=True,
            )
    with tab_trend:
        if a.monthly_enrollments:
            st.plotly_chart(enrollment_trend_chart(a), use_container_width=True)
            if a.month_over_month_enrollment_change is not None:
                st.metric(
                    "Month-over-month enrollment change",
                    f"{a.month_over_month_enrollment_change}%",
                )
    with tab_outcome:
        if a.exit_destination_breakdown:
            st.plotly_chart(exit_destination_chart(a), use_container_width=True)
            st.dataframe(
                pd.DataFrame(
                    [{"Category": k, "Exits": v} for k, v in a.exit_category_breakdown.items()]
                ),
                use_container_width=True,
            )
        else:
            st.info("No exits with destinations recorded.")
    with tab_demo:
        col1, col2 = st.columns(2)
        with col1:
            st.plotly_chart(demographic_chart(a, "age_groups"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "gender"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "household_size"), use_container_width=True)
        with col2:
            st.plotly_chart(demographic_chart(a, "race"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "veteran_status"), use_container_width=True)
            st.plotly_chart(demographic_chart(a, "disability_status"), use_container_width=True)
    with tab_income:
        cols = st.columns(4)
        cols[0].metric(
            "Avg entry income",
            f"${a.avg_entry_income:,.0f}" if a.avg_entry_income is not None else "n/a",
        )
        cols[1].metric(
            "Avg exit income",
            f"${a.avg_exit_income:,.0f}" if a.avg_exit_income is not None else "n/a",
        )
        cols[2].metric(
            "Median income change",
            f"${a.median_income_change:,.0f}" if a.median_income_change is not None else "n/a",
        )
        cols[3].metric(
            "Households increasing income",
            f"{a.pct_income_increased}%" if a.pct_income_increased is not None else "n/a",
        )
        if a.income_changes:
            st.plotly_chart(income_change_chart(a), use_container_width=True)
    with tab_follow:
        if a.followups:
            st.plotly_chart(followup_chart(a), use_container_width=True)
            st.dataframe(
                pd.DataFrame([f.model_dump() for f in a.followups]),
                use_container_width=True,
            )
    with tab_measures:
        if a.measures:
            st.plotly_chart(goal_vs_actual_chart(a), use_container_width=True)
            rows = [
                {
                    "Measure": m.name,
                    "Target": m.target,
                    "Actual": m.actual,
                    "Status": "✅ Met" if m.met else ("❌ Not met" if m.met is False else "—"),
                    "Small sample": "⚠️" if m.small_sample else "",
                }
                for m in a.measures
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)


# ---------------------------------------------------------------------------
# Page: Period Comparison
# ---------------------------------------------------------------------------


def page_comparison() -> None:
    st.header("Period Comparison")
    if not _require_data():
        return
    p = st.session_state["pipeline"]
    st.markdown(
        f"The currently loaded file (**{p['filename']}**) is treated as the *current* "
        "period. Upload a **prior-period extract** (same layout, same profile) to compare."
    )
    prior_upload = st.file_uploader(
        "Prior-period CSV or Excel extract",
        type=["csv", "xlsx", "xls", "xlsm"],
        key="prior_upload",
    )
    if prior_upload is None:
        st.info("Upload a prior-period file to compute deltas.")
        return
    from grant_assistant.analytics.charts import comparison_chart
    from grant_assistant.analytics.comparison import compare_analytics

    try:
        prior_raw = load_dataset(io.BytesIO(prior_upload.getvalue()), filename=prior_upload.name)
        prior_prepared = prepare_dataset(prior_raw, p["profile"])
        prior_analytics = compute_analytics(prior_prepared, p["profile"])
    except (IngestionError, ProfileValidationError) as exc:
        st.error(str(exc))
        return
    comparison = compare_analytics(
        p["analytics"],
        prior_analytics,
        current_label=p["filename"],
        prior_label=prior_upload.name,
    )

    st.subheader("Headline metrics")
    rows = []
    for d in comparison.headline:
        trend = "—"
        if d.improved is True:
            trend = "▲ improved"
        elif d.improved is False:
            trend = "▼ declined"
        rows.append(
            {
                "Metric": d.label,
                "Prior": d.format_value(d.prior),
                "Current": d.format_value(d.current),
                "Change": d.format_value(d.delta) if d.delta is not None else "n/a",
                "Trend": trend,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    st.plotly_chart(comparison_chart(comparison), use_container_width=True)

    st.subheader("Program movement (successful-exit rate)")
    prog_rows = [
        {
            "Program": pr.program,
            "Prior rate": f"{pr.prior_rate}%" if pr.prior_rate is not None else "n/a",
            "Current rate": f"{pr.current_rate}%" if pr.current_rate is not None else "n/a",
            "Delta (pts)": pr.delta if pr.delta is not None else "n/a",
            "Small sample": "⚠️" if pr.small_sample else "",
        }
        for pr in comparison.programs
    ]
    st.dataframe(pd.DataFrame(prog_rows), use_container_width=True)

    st.subheader("Narrative")
    for line in comparison.narrative:
        st.markdown(f"- {line}")


# ---------------------------------------------------------------------------
# Page: AI Analyst Chat
# ---------------------------------------------------------------------------


def page_chat() -> None:
    st.header("AI Analyst Chat")
    if not _require_data():
        return
    agent = _agent()
    if agent.ai_enabled:
        st.caption(
            "AI mode: answers are generated by Claude, grounded in a sanitized fact sheet "
            "of deterministically calculated metrics. No client-level data is sent."
        )
    else:
        st.caption(
            "Non-AI mode (no API key configured): deterministic answers computed from "
            "calculated metrics. Set ANTHROPIC_API_KEY in .env for conversational answers."
        )

    examples = [
        "Which program had the highest successful exit rate?",
        "Which clients are overdue for follow-up?",
        "Summarize grant outcomes for the reporting period.",
        "Which data quality issues could affect this report?",
        "Are any metrics distorted by small sample sizes?",
        "Which outcomes are below target?",
    ]
    st.markdown("**Example questions:** " + " · ".join(f"_{q}_" for q in examples))

    history: list[dict[str, str]] = st.session_state.setdefault("chat_history", [])
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Ask the senior data analyst…")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"), st.spinner("Analyzing…"):
            answer = agent.ask(question, history=history[-8:])
            st.markdown(answer)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})


# ---------------------------------------------------------------------------
# Page: Proactive Insights
# ---------------------------------------------------------------------------


def page_insights() -> None:
    st.header("Proactive Insights")
    if not _require_data():
        return
    agent = _agent()
    st.caption(
        "A senior-analyst review generated automatically from the calculated results — "
        "anomalies, trends, risks, and recommended actions. Works with or without AI."
    )
    report = agent.proactive_insights()
    icons = {
        "Key Findings": "🔑",
        "Notable Trends": "📈",
        "Anomalies Detected": "🚨",
        "Data Quality Risks": "🧪",
        "Program Strengths": "💪",
        "Program Concerns": "⚠️",
        "Recommended Actions": "✅",
        "Questions Requiring Further Investigation": "❓",
        "Executive Takeaways": "🏛️",
    }
    for title, items in report.sections().items():
        if not items:
            continue
        st.subheader(f"{icons.get(title, '•')} {title}")
        for item in items:
            st.markdown(f"- {item}")

    if agent.ai_enabled and st.button("Generate AI-polished narrative"):
        with st.spinner("Narrating insights…"):
            st.markdown(agent.narrated_insights())


# ---------------------------------------------------------------------------
# Page: Report Builder
# ---------------------------------------------------------------------------


def page_report() -> None:
    st.header("Grant Report Builder")
    if not _require_data():
        return
    p = st.session_state["pipeline"]
    agent = _agent()

    st.markdown(
        f"Build the **{p['profile'].report.title}** for period "
        f"**{p['profile'].reporting_period.label}**. The report includes a cover page, "
        "executive summary, data quality statement, population and demographics, "
        "outcomes, income, follow-ups, performance measures, program comparisons, "
        "charts, findings, recommendations, methodology, limitations, and an appendix "
        "of measure definitions."
    )
    st.info(
        "Narrative mode: "
        + (
            "**AI-assisted** — executive summary written by Claude from calculated metrics."
            if agent.ai_enabled
            else "**Deterministic** — template-based narrative (set ANTHROPIC_API_KEY for AI)."
        )
    )

    if st.button("Build report", type="primary"):
        with st.spinner("Generating report…"):
            data = build_report_data(p["analytics"], p["audit"], p["profile"], agent)
            html = render_html_report(data)
            out = _output_dir()
            docx_path = write_docx_report(data, out / "grant_report.docx")
            st.session_state["report_html"] = html
            st.session_state["report_docx"] = docx_path.read_bytes()
            st.session_state["report_summary"] = data.executive_summary
        st.success("Report generated.")

    if "report_html" in st.session_state:
        st.subheader("Executive summary preview")
        st.write(st.session_state["report_summary"])
        col1, col2, col3 = st.columns(3)
        col1.download_button(
            "Download HTML report",
            data=st.session_state["report_html"].encode("utf-8"),
            file_name="grant_report.html",
            mime="text/html",
        )
        col2.download_button(
            "Download Word report",
            data=st.session_state["report_docx"],
            file_name="grant_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        with col3:
            from grant_assistant.reporting import PdfBackendError, pdf_backend, write_pdf_report

            if "report_pdf" in st.session_state:
                st.download_button(
                    "Download PDF report",
                    data=st.session_state["report_pdf"],
                    file_name="grant_report.pdf",
                    mime="application/pdf",
                )
            elif pdf_backend() is None:
                st.caption(
                    "PDF export needs a headless browser: `uv sync --extra pdf` then "
                    "`uv run playwright install chromium` (or Microsoft Edge on Windows)."
                )
            elif st.button("Render PDF report"):
                with st.spinner("Rendering PDF…"):
                    try:
                        data = build_report_data(p["analytics"], p["audit"], p["profile"], agent)
                        pdf_path = write_pdf_report(data, _output_dir() / "grant_report.pdf")
                        st.session_state["report_pdf"] = pdf_path.read_bytes()
                        st.rerun()
                    except PdfBackendError as exc:
                        st.error(str(exc))
        with st.expander("Inline HTML preview"):
            st.components.v1.html(st.session_state["report_html"], height=650, scrolling=True)


# ---------------------------------------------------------------------------
# Page: Export Center
# ---------------------------------------------------------------------------


def page_exports() -> None:
    st.header("Export Center")
    if not _require_data():
        return
    p = st.session_state["pipeline"]
    out = _output_dir()

    st.markdown("Generate and download every artifact from this session.")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Audit exports")
        if st.button("Prepare audit workbook (Excel)"):
            path = write_audit_workbook(p["audit"], p["prepared"], out / "audit_workbook.xlsx")
            st.session_state["export_audit"] = path.read_bytes()
        if "export_audit" in st.session_state:
            st.download_button(
                "Download audit_workbook.xlsx",
                data=st.session_state["export_audit"],
                file_name="audit_workbook.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.download_button(
            "Download row-level issues (CSV)",
            data=p["audit"].row_level_frame().to_csv(index=False).encode("utf-8"),
            file_name="row_level_issues.csv",
            mime="text/csv",
        )

    with col2:
        st.subheader("Analytics exports")
        if st.button("Prepare analytics workbook (Excel)"):
            path = write_analytics_workbook(p["analytics"], out / "analytics_summary.xlsx")
            st.session_state["export_analytics"] = path.read_bytes()
        if "export_analytics" in st.session_state:
            st.download_button(
                "Download analytics_summary.xlsx",
                data=st.session_state["export_analytics"],
                file_name="analytics_summary.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.download_button(
            "Download analytics (JSON)",
            data=p["analytics"].model_dump_json(indent=2).encode("utf-8"),
            file_name="analytics.json",
            mime="application/json",
        )

    st.subheader("Reports")
    st.caption("Build reports on the Report Builder page — download buttons appear there too.")
    if "report_html" in st.session_state:
        st.download_button(
            "Download grant_report.html",
            data=st.session_state["report_html"].encode("utf-8"),
            file_name="grant_report.html",
            mime="text/html",
            key="export_html",
        )
    if "report_docx" in st.session_state:
        st.download_button(
            "Download grant_report.docx",
            data=st.session_state["report_docx"],
            file_name="grant_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="export_docx",
        )


# ---------------------------------------------------------------------------
# Page: Configuration Help
# ---------------------------------------------------------------------------


def page_config_help() -> None:
    st.header("Configuration Help")
    st.markdown(
        """
Grant profiles are YAML files in `configs/`. Each profile defines everything the
pipeline needs for one grant: reporting period, programs and aliases, field
mappings from your spreadsheet headers to the canonical schema, controlled
vocabularies, follow-up schedules, performance measures with targets, exit
destination categories, and report settings.

**To add a new grant profile:**
1. Copy an existing profile in `configs/` (e.g. `housing_stability.yaml`).
2. Set a unique `profile_id` and update `grant_name` and `reporting_period`.
3. Update `field_mappings` so each of your spreadsheet headers maps to a canonical column.
4. Define your programs with any alias labels that appear in the data.
5. Adjust `controlled_values`, `followup_schedule`, and `performance_measures`.
6. Validate with: `uv run grant-assistant validate-config`

See `docs/creating_profiles.md` in the repository for the full field-by-field guide.
        """
    )

    st.subheader("Canonical schema")
    st.dataframe(
        pd.DataFrame(
            [
                {"Canonical column": c, "Label": schema.label_for(c)}
                for c in schema.CANONICAL_COLUMNS
            ]
        ),
        use_container_width=True,
        height=350,
    )

    st.subheader("Performance measure metrics available")
    st.code("\n".join(available_measure_metrics()))

    st.subheader("Audit rules")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Rule": m.rule_id,
                    "Name": m.name,
                    "Category": m.category,
                    "Default severity": m.severity.label,
                    "Blocking by default": "Yes" if m.blocking else "No",
                    "Description": m.description,
                }
                for m in list_rules()
            ]
        ),
        use_container_width=True,
        height=420,
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _demo_autoload() -> None:
    """Load a dataset automatically when GRANT_ASSISTANT_DEMO points to a file.

    Lets demos and screenshots start with data preloaded, e.g.:
        GRANT_ASSISTANT_DEMO=sample_data/housing_program_flawed.csv
    """
    import os

    demo_file = os.environ.get("GRANT_ASSISTANT_DEMO", "").strip()
    demo_profile = os.environ.get("GRANT_ASSISTANT_DEMO_PROFILE", "").strip()
    # ?demo=<name>&profile=<id> also works, restricted to the sample_data folder.
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
    raw = load_dataset(demo_path)
    prepared = prepare_dataset(raw, profile)
    st.session_state["pipeline"] = {
        "prepared": prepared,
        "profile": profile,
        "audit": run_audit(prepared, profile),
        "analytics": compute_analytics(prepared, profile),
        "filename": demo_path.name,
    }


def main() -> None:
    _demo_autoload()
    with st.sidebar:
        st.markdown("## 📊 Grant Assistant")
        page = st.radio("Navigate", PAGES, label_visibility="collapsed")
        st.divider()
        if _loaded():
            p = st.session_state["pipeline"]
            st.caption(
                f"**Loaded:** {p['filename']}\n\n"
                f"**Profile:** {p['profile'].profile_id}\n\n"
                f"**DQ score:** {p['audit'].overall_score:.1f} ({p['audit'].grade})"
            )
        else:
            st.caption("No dataset loaded yet.")
        st.caption(
            ("🤖 AI mode: **enabled**" if ai_available() else "🔌 AI mode: **off** (no API key)")
            + f"\n\n_{date.today():%B %d, %Y}_"
        )

    router = {
        PAGES[0]: page_upload,
        PAGES[1]: page_preview,
        PAGES[2]: page_audit,
        PAGES[3]: page_issues,
        PAGES[4]: page_analytics,
        PAGES[5]: page_comparison,
        PAGES[6]: page_chat,
        PAGES[7]: page_insights,
        PAGES[8]: page_report,
        PAGES[9]: page_exports,
        PAGES[10]: page_config_help,
    }
    router[page]()


main()
