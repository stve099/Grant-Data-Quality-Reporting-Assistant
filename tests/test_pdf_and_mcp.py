"""Optional-extra features: PDF export and the MCP server."""

from __future__ import annotations

import importlib.util
from pathlib import Path

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


def test_report_includes_print_rules(analytics_flawed, audit_flawed, profile):
    """Pagination rules must ship, or PDFs break blocks across pages."""
    from grant_assistant.reporting import render_html_report

    html = render_html_report(build_report_data(analytics_flawed, audit_flawed, profile))
    assert "@page" in html
    assert "@media print" in html
    assert "break-inside: avoid" in html
    assert "display: table-header-group" in html  # repeat table headers per page


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
    # Everything the CLI can do should be reachable by an MCP client too.
    assert {
        "check_for_personal_information",
        "export_correction_worksheet",
        "apply_corrections",
        "batch_audit",
        "data_quality_history",
        "get_data_dictionary",
    } <= names


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_mcp_tools_describe_themselves():
    """A tool with no description is unusable by a model choosing between them."""
    import anyio

    from grant_assistant.mcp_server import mcp

    for tool in anyio.run(mcp.list_tools):
        assert tool.description and tool.description.strip(), tool.name


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_pii_check_tool_reports_cleanly(tmp_path, clean_df):
    from grant_assistant import mcp_server

    path = tmp_path / "clean.csv"
    clean_df.to_csv(path, index=False)
    result = mcp_server.check_for_personal_information(str(path))
    assert result["looks_clean"] is True
    assert result["warnings"] == []


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_pii_check_tool_flags_identifiers(tmp_path, clean_df):
    from grant_assistant import mcp_server

    frame = clean_df.copy()
    frame["Client Name"] = "Jane Doe"
    path = tmp_path / "identified.csv"
    frame.to_csv(path, index=False)

    result = mcp_server.check_for_personal_information(str(path))
    assert result["looks_clean"] is False
    assert any("Client Name" in w for w in result["warnings"])


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_correction_worksheet_tool_round_trips(tmp_path, flawed):
    from grant_assistant import mcp_server

    source = tmp_path / "flawed.csv"
    flawed[0].to_csv(source, index=False)
    exported = mcp_server.export_correction_worksheet(
        str(source), output_path=str(tmp_path / "corrections.xlsx")
    )
    assert exported["records"] > 0
    assert Path(exported["path"]).exists()

    # Nothing filled in, so applying is a no-op rather than an error.
    applied = mcp_server.apply_corrections(
        str(source), exported["path"], output_path=str(tmp_path / "out.csv")
    )
    assert applied["applied"] == 0


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_batch_tool_reports_failures(tmp_path, clean_df):
    from grant_assistant import mcp_server

    clean_df.to_csv(tmp_path / "good.csv", index=False)
    (tmp_path / "bad.csv").write_text("nonsense\n1\n", encoding="utf-8")

    result = mcp_server.batch_audit(str(tmp_path))
    assert result["files_audited"] == 1
    assert result["files_failed"] == 1


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_history_tool_is_honest_when_empty(tmp_path):
    from grant_assistant import mcp_server

    result = mcp_server.data_quality_history(str(tmp_path / "none.db"))
    assert result["runs"] == 0


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_data_dictionary_tool_returns_markdown():
    from grant_assistant import mcp_server

    text = mcp_server.get_data_dictionary()
    assert text.startswith("# ")
    assert "Validation rules" in text


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_mcp_resources_registered(monkeypatch):
    import anyio

    monkeypatch.chdir(REPO_ROOT)
    from grant_assistant.mcp_server import mcp

    uris = {str(r.uri) for r in anyio.run(mcp.list_resources)}
    assert {"grant://profiles", "grant://audit-rules", "grant://measure-definitions"} <= uris


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_mcp_prompts_registered():
    import anyio

    from grant_assistant.mcp_server import mcp

    names = {p.name for p in anyio.run(mcp.list_prompts)}
    assert {"review_grant_report", "explain_data_quality_issue"} <= names


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_mcp_resource_content(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    from grant_assistant import mcp_server

    profiles = mcp_server.list_profiles_resource()
    assert "housing_stability" in profiles
    assert "rapid_rehousing" in profiles

    rules = mcp_server.audit_rules_resource()
    assert "DQ-001" in rules

    yaml_source = mcp_server.profile_resource("housing_stability")
    assert "profile_id: housing_stability" in yaml_source
    assert "No profile" in mcp_server.profile_resource("nope")


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_mcp_prompt_templates_are_grounded():
    from grant_assistant import mcp_server

    prompt = mcp_server.review_grant_report("data.csv", "housing_stability")
    assert "audit_dataset" in prompt
    assert "Do not compute your own figures" in prompt
    assert "client-level identifiers" in prompt


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
