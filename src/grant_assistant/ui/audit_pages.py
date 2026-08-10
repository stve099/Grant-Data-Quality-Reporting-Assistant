"""Streamlit audit and issue-detail pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from grant_assistant.analytics.charts import (
    dq_category_chart,
    dq_severity_chart,
)
from grant_assistant.audit import list_rules
from grant_assistant.models import SEVERITY_ORDER
from grant_assistant.ui import theme
from grant_assistant.ui.state import (
    require_data as _require_data,
)
from grant_assistant.ui.state import (
    score_tone as _score_tone,
)
from grant_assistant.ui.theme import Kpi


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
