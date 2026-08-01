"""Excel exports: audit issue workbook and analytics summary workbook."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from grant_assistant.analytics import AnalyticsResult
from grant_assistant.analytics.metrics import analytics_to_flat_frames
from grant_assistant.ingestion import PreparedData
from grant_assistant.models import AuditResult

logger = logging.getLogger(__name__)

_HEADER_FMT = {"bold": True, "bg_color": "#1e3a8a", "font_color": "white", "border": 1}
_SEVERITY_BG = {
    "Critical": "#fecaca",
    "High": "#fed7aa",
    "Medium": "#fef08a",
    "Low": "#e2e8f0",
    "Informational": "#f1f5f9",
}


def _write_frame(
    writer: pd.ExcelWriter, df: pd.DataFrame, sheet: str, autofit_max: int = 60
) -> None:
    df.to_excel(writer, sheet_name=sheet, index=False, startrow=1, header=False)
    workbook = writer.book
    worksheet = writer.sheets[sheet]
    header_format = workbook.add_format(_HEADER_FMT)
    for col_num, name in enumerate(df.columns):
        worksheet.write(0, col_num, str(name), header_format)
        try:
            width = min(
                max(len(str(name)), int(df[name].astype(str).str.len().max() or 0)) + 2,
                autofit_max,
            )
        except (TypeError, ValueError):
            width = len(str(name)) + 2
        worksheet.set_column(col_num, col_num, width)
    worksheet.freeze_panes(1, 0)


def write_audit_workbook(
    audit: AuditResult,
    data: PreparedData,
    path: str | Path,
) -> Path:
    """Write the audit findings workbook.

    Sheets:
        Audit Summary — scores, severity counts, executive summary
        Issues by Rule — one row per rule with counts and guidance
        Row-Level Issues — every finding with row/client/field detail
        Flagged Records — original data rows that have at least one finding,
            with issue annotations and a blank "Corrected Value" template column
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row_frame = audit.row_level_frame()

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        # -- Summary ---------------------------------------------------------
        summary_rows: list[dict[str, Any]] = [
            {"Item": "Grant", "Value": audit.grant_name},
            {"Item": "Profile", "Value": audit.profile_id},
            {"Item": "Records audited", "Value": audit.total_rows},
            {"Item": "Overall data quality score", "Value": audit.overall_score},
            {"Item": "Grade", "Value": audit.grade},
            {"Item": "Total findings", "Value": audit.total_findings},
        ]
        for sev, count in audit.issue_count_by_severity.items():
            label = "Informational" if sev == "info" else sev.title()
            summary_rows.append({"Item": f"{label} findings", "Value": count})
        for cat, score in audit.score_by_category.items():
            summary_rows.append({"Item": f"Score — {cat.replace('_', ' ')}", "Value": score})
        for prog, score in audit.score_by_program.items():
            summary_rows.append({"Item": f"Score — {prog}", "Value": score})
        summary_rows.append({"Item": "Executive summary", "Value": audit.executive_summary()})
        _write_frame(writer, pd.DataFrame(summary_rows), "Audit Summary", autofit_max=110)

        # -- Issues by rule ---------------------------------------------------
        rule_rows = [
            {
                "Rule ID": i.rule_id,
                "Rule Name": i.rule_name,
                "Category": i.category,
                "Severity": i.severity.label,
                "Blocking": "Yes" if i.blocking else "No",
                "Records Affected": i.record_count,
                "Explanation": i.explanation,
                "Recommended Correction": i.recommendation,
            }
            for i in audit.issues_sorted()
        ]
        _write_frame(
            writer,
            pd.DataFrame(
                rule_rows
                or [
                    {
                        "Rule ID": "—",
                        "Rule Name": "No issues detected",
                        "Category": "",
                        "Severity": "",
                        "Blocking": "",
                        "Records Affected": 0,
                        "Explanation": "",
                        "Recommended Correction": "",
                    }
                ]
            ),
            "Issues by Rule",
            autofit_max=70,
        )

        # -- Row-level issues -------------------------------------------------
        _write_frame(writer, row_frame, "Row-Level Issues", autofit_max=70)
        if not row_frame.empty:
            worksheet = writer.sheets["Row-Level Issues"]
            severity_col = list(row_frame.columns).index("severity")
            for fmt_severity, bg in _SEVERITY_BG.items():
                cell_format = writer.book.add_format({"bg_color": bg})
                worksheet.conditional_format(
                    1,
                    0,
                    len(row_frame),
                    len(row_frame.columns) - 1,
                    {
                        "type": "formula",
                        "criteria": (f'=${chr(65 + severity_col)}2="{fmt_severity}"'),
                        "format": cell_format,
                    },
                )

        # -- Flagged records (correction template) ----------------------------
        if not row_frame.empty:
            flagged_rows = sorted(row_frame["row"].unique())
            source = data.raw.copy()
            source.insert(0, "Data Row", range(1, len(source) + 1))
            flagged = source[source["Data Row"].isin(flagged_rows)].copy()
            issue_labels: dict[int, list[str]] = {}
            for rec in row_frame.to_dict(orient="records"):
                label = f"{rec['rule_id']} {rec['rule_name']}" + (
                    f" [{rec['field']}]" if rec["field"] else ""
                )
                issue_labels.setdefault(int(str(rec["row"])), []).append(label)
            issues_per_row = {row: "; ".join(v) for row, v in issue_labels.items()}
            flagged["Issues Found"] = flagged["Data Row"].map(issues_per_row)
            flagged["Corrected Value(s)"] = ""
            flagged["Correction Notes"] = ""
            _write_frame(writer, flagged, "Flagged Records", autofit_max=50)

    logger.info("Wrote audit workbook to %s (%d findings)", path, audit.total_findings)
    return path


def write_analytics_workbook(analytics: AnalyticsResult, path: str | Path) -> Path:
    """Write the analytics summary workbook (one sheet per topic)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = analytics_to_flat_frames(analytics)
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        for sheet, df in frames.items():
            _write_frame(writer, df, sheet[:31])
    logger.info("Wrote analytics workbook to %s (%d sheets)", path, len(frames))
    return path
