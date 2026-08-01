"""Optional-extra features: PDF export and the MCP server."""

from __future__ import annotations

import importlib.util

import pytest

from grant_assistant.reporting import build_report_data, pdf_backend
from tests.conftest import CONFIG_DIR, REPO_ROOT


def test_pdf_backend_detection_returns_known_value():
    assert pdf_backend() in {None, "playwright", "edge"}


@pytest.mark.skipif(pdf_backend() is None, reason="no headless-browser PDF backend installed")
def test_pdf_report_renders(analytics_flawed, audit_flawed, profile, tmp_path):
    from grant_assistant.reporting import write_pdf_report

    data = build_report_data(analytics_flawed, audit_flawed, profile)
    path = write_pdf_report(data, tmp_path / "report.pdf")
    assert path.exists()
    content = path.read_bytes()
    assert content[:5] == b"%PDF-"
    assert len(content) > 20_000


def test_offline_html_embeds_plotly(analytics_flawed, audit_flawed, profile):
    from grant_assistant.reporting import render_html_report

    online = render_html_report(build_report_data(analytics_flawed, audit_flawed, profile))
    offline = render_html_report(
        build_report_data(analytics_flawed, audit_flawed, profile), offline_charts=True
    )
    assert 'src="https://cdn.plot.ly' in online
    # plotly.js source itself mentions cdn.plot.ly internally, so check the
    # script *tag* is gone rather than the substring.
    assert 'src="https://cdn.plot.ly' not in offline
    assert len(offline) > len(online) + 1_000_000  # plotly.js inlined


_HAS_MCP = importlib.util.find_spec("mcp") is not None


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_mcp_server_tools_registered():
    import anyio

    from grant_assistant.mcp_server import mcp

    tools = anyio.run(mcp.list_tools)
    names = {t.name for t in tools}
    assert {"audit_dataset", "analyze_dataset", "generate_report", "ask_analyst"} <= names


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_mcp_audit_tool_runs_pipeline(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)  # profile lookup uses the repo's configs/
    from grant_assistant import mcp_server

    summary = mcp_server.audit_dataset(
        str(REPO_ROOT / "sample_data" / "housing_program_flawed.csv"), "housing_stability"
    )
    assert summary["total_findings"] > 50
    assert summary["grade"] in {"A", "B", "C", "D", "F"}
    assert CONFIG_DIR.exists()
