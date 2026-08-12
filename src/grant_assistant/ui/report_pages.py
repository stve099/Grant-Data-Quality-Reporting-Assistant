"""Streamlit report, export, and configuration-help pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from grant_assistant import schema
from grant_assistant.analytics.metrics import available_measure_metrics
from grant_assistant.audit import list_rules
from grant_assistant.corrections import write_worksheet
from grant_assistant.reporting import (
    build_report_data,
    render_html_report,
    write_analytics_workbook,
    write_audit_workbook,
    write_docx_report,
)
from grant_assistant.ui import theme
from grant_assistant.ui.state import (
    SOURCE_DROPPED_NOTE as _SOURCE_DROPPED_NOTE,
)
from grant_assistant.ui.state import (
    agent as _agent,
)
from grant_assistant.ui.state import (
    apply_correction_upload as _apply_correction_upload,
)
from grant_assistant.ui.state import (
    output_dir as _output_dir,
)
from grant_assistant.ui.state import (
    require_data as _require_data,
)
from grant_assistant.ui.state import (
    session_history as _session_history,
)
from grant_assistant.ui.state import (
    source_frame as _source_frame,
)
from grant_assistant.ui.theme import Kpi


def page_report() -> None:
    if not _require_data("Report Builder"):
        return
    from grant_assistant.reporting import (
        PdfBackendError,
        missing_backend_hint,
        pdf_backend,
        write_pdf_report,
    )

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
            data = build_report_data(
                p["analytics"], p["audit"], p["profile"], agent, _session_history()
            )
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
            st.caption(missing_backend_hint())
        elif st.button("Render PDF", use_container_width=True):
            with st.spinner("Rendering PDF…"):
                try:
                    data = build_report_data(
                        p["analytics"], p["audit"], p["profile"], agent, _session_history()
                    )
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


def _correction_round_trip() -> None:
    """Take a filled-in worksheet back, apply it, and show what actually cleared.

    The export half of the loop shipped long before this half, so the app told
    users to finish the job in a terminal — which the people this tool is for do
    not have open.
    """
    theme.panel_title("Apply corrections", "return a filled-in worksheet")
    if _source_frame() is None:
        st.caption(_SOURCE_DROPPED_NOTE)
        return

    filled = st.file_uploader(
        "Filled-in correction worksheet",
        type=["xlsx", "xlsm", "xls", "csv"],
        key="corrections_return",
        help="The worksheet exported above, with the 'Corrected Value' column filled in. "
        "Corrections are applied to a copy — the file you uploaded is never modified.",
    )
    if filled is not None and st.button(
        "Apply corrections and re-audit", type="primary", use_container_width=True
    ):
        try:
            _apply_correction_upload(filled.getvalue(), filled.name)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.rerun()

    outcome = st.session_state.get("correction_outcome")
    if outcome is None:
        return

    impact = outcome.impact
    st.success(f"{outcome.report.summary()} from **{outcome.filename}**, then re-audited.")
    theme.kpis(
        [
            Kpi(
                "Data quality score",
                f"{impact.after_score:.1f}",
                note=f"was {impact.before_score:.1f} ({impact.score_delta:+.1f})",
                tone="good" if impact.improved else "warning",
            ),
            Kpi(
                "Findings",
                str(impact.after_findings),
                note=f"was {impact.before_findings} ({impact.findings_delta:+d})",
            ),
            Kpi(
                "Blocking issues",
                str(impact.after_blocking),
                note=f"was {impact.before_blocking} ({impact.blocking_delta:+d})",
                tone="good" if impact.after_blocking == 0 else "critical",
            ),
        ]
    )
    if impact.cleared_rules:
        st.markdown("**Cleared entirely:** " + ", ".join(impact.cleared_rules))
    if outcome.report.skipped:
        with st.expander(f"{len(outcome.report.skipped)} correction(s) skipped"):
            # Every refusal is shown. A silently dropped edit is the one outcome
            # a user would never think to check for.
            for reason in outcome.report.skipped:
                st.write(f"- {reason}")
    payload, download_name, mime = st.session_state["corrected_dataset"]
    st.download_button(
        download_name,
        data=payload,
        file_name=download_name,
        mime=mime,
        use_container_width=True,
    )
    st.caption(
        "Every page now reflects the corrected dataset. Download it to take the fixes "
        "back to your case management system."
    )


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
                "Fill in 'Corrected Value', then return the file under **Apply corrections** "
                "below to re-audit this dataset with the fixes in place."
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

    _correction_round_trip()

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

    with st.expander("Run this audit on a schedule"):
        # The app deliberately runs no background scheduler, so the honest thing
        # to offer here is the command an operator hands to their own scheduler.
        st.markdown(
            "This application does not run a background scheduler — Windows Task Scheduler, "
            "cron, or your existing orchestrator controls timing. Each invocation audits, "
            "records history, and writes an offline HTML report."
        )
        st.code(
            "grant-assistant scheduled-audit extract.csv --profile housing_stability \\\n"
            "  --output output/scheduled --db output/history.db --label nightly",
            language="bash",
        )
        st.markdown(
            "To email a summary, set the `GRANT_ASSISTANT_SMTP_*` variables from "
            "`.env.example` and add `--email-to`. Verify the relay without mailing anyone:"
        )
        st.code(
            "grant-assistant scheduled-audit extract.csv --email-to team@example.org --dry-run",
            language="bash",
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
