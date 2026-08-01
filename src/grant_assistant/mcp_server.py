"""MCP server exposing audit, analytics, and reporting tools.

Lets any MCP client (Claude Desktop, Claude Code, etc.) audit datasets and
generate reports through the same deterministic pipeline as the CLI and UI.

Setup:
    uv sync --extra mcp
    uv run grant-assistant-mcp          # stdio transport

Claude Desktop config example:
    {"mcpServers": {"grant-assistant": {
        "command": "uv",
        "args": ["run", "--directory", "<repo path>", "grant-assistant-mcp"]}}}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as _ServerClass  # mcp >= 2.0
except ImportError:  # pragma: no cover - depends on installed SDK generation
    try:
        from mcp.server.fastmcp import FastMCP as _ServerClass  # type: ignore[no-redef]  # mcp 1.x
    except ImportError as exc:
        raise ImportError(
            "The MCP server requires the optional 'mcp' extra: uv sync --extra mcp"
        ) from exc

from grant_assistant.workflow import run_pipeline

mcp = _ServerClass(
    name="grant-assistant",
    instructions=(
        "Audit and report on grant program datasets. All metrics are calculated "
        "deterministically by the application; results are aggregated and contain "
        "no client-level records."
    ),
)


@mcp.tool()
def audit_dataset(data_file: str, profile: str = "housing_stability") -> dict[str, Any]:
    """Run the data quality audit on a CSV/Excel file; returns the aggregated summary."""
    result = run_pipeline(data_file, profile)
    audit = result.audit
    return {
        "overall_score": audit.overall_score,
        "grade": audit.grade,
        "total_rows": audit.total_rows,
        "total_findings": audit.total_findings,
        "findings_by_severity": audit.issue_count_by_severity,
        "score_by_category": audit.score_by_category,
        "score_by_program": audit.score_by_program,
        "blocking_issues": [
            {"rule_id": i.rule_id, "name": i.rule_name, "records": i.record_count}
            for i in audit.blocking_issues
        ],
        "issues": [
            {
                "rule_id": i.rule_id,
                "name": i.rule_name,
                "severity": i.severity.value,
                "records": i.record_count,
                "recommendation": i.recommendation,
            }
            for i in audit.issues_sorted()
        ],
        "executive_summary": audit.executive_summary(),
    }


@mcp.tool()
def analyze_dataset(data_file: str, profile: str = "housing_stability") -> dict[str, Any]:
    """Compute program analytics and performance measures for a CSV/Excel file."""
    result = run_pipeline(data_file, profile)
    analytics = result.analytics
    return {
        "headline_metrics": analytics.metric_lookup(),
        "programs": [p.model_dump() for p in analytics.programs],
        "measures": [m.model_dump() for m in analytics.measures],
        "monthly_enrollments": analytics.monthly_enrollments,
        "monthly_exits": analytics.monthly_exits,
        "notes": analytics.notes,
    }


@mcp.tool()
def generate_report(
    data_file: str,
    profile: str = "housing_stability",
    output_dir: str = "output",
) -> list[str]:
    """Generate the HTML/Word reports and Excel workbooks; returns written file paths."""
    from grant_assistant.reporting import (
        build_report_data,
        write_analytics_workbook,
        write_audit_workbook,
        write_docx_report,
        write_html_report,
    )

    result = run_pipeline(data_file, profile)
    agent = result.make_agent(use_ai=False)
    data = build_report_data(result.analytics, result.audit, result.profile, agent)
    out = Path(output_dir)
    written = [
        write_html_report(data, out / "grant_report.html"),
        write_docx_report(data, out / "grant_report.docx"),
        write_audit_workbook(result.audit, result.prepared, out / "audit_workbook.xlsx"),
        write_analytics_workbook(result.analytics, out / "analytics_summary.xlsx"),
    ]
    return [str(p) for p in written]


@mcp.tool()
def ask_analyst(data_file: str, question: str, profile: str = "housing_stability") -> str:
    """Ask the (deterministic) data analyst a question about a dataset."""
    result = run_pipeline(data_file, profile)
    agent = result.make_agent(use_ai=False)
    return agent.ask(question)


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
