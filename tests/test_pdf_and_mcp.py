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


@pytest.mark.skipif(pdf_backend() is None, reason="no headless-browser PDF backend installed")
def test_pdf_report_renders_concise_template(analytics_flawed, audit_flawed, profile, tmp_path):
    from grant_assistant.reporting import write_pdf_report

    data = build_report_data(analytics_flawed, audit_flawed, profile)
    path = write_pdf_report(data, tmp_path / "report.pdf", template="concise")
    assert path.exists()
    assert path.read_bytes()[:5] == b"%PDF-"


def test_pdf_report_raises_when_no_backend(
    monkeypatch, analytics_flawed, audit_flawed, profile, tmp_path
):
    """The degrade-or-error contract: without any backend, the caller gets a clear error."""
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: False)
    monkeypatch.setattr(pdf_report, "_find_edge", lambda: None)

    with pytest.raises(Exception) as exc_info:  # PdfBackendError
        pdf_report.write_pdf_report(
            build_report_data(analytics_flawed, audit_flawed, profile), tmp_path / "report.pdf"
        )
    assert "headless browser" in str(exc_info.value).lower()


def test_installed_playwright_without_its_browser_is_not_a_backend(monkeypatch, tmp_path):
    """The import alone used to count, so a missing download crashed instead of degrading."""
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: True)
    monkeypatch.setattr(pdf_report, "_find_edge", lambda: None)
    monkeypatch.setattr(pdf_report, "_expected_chromium_revision", lambda: "9999")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    assert pdf_report.pdf_backend() is None
    hint = pdf_report.missing_backend_hint()
    assert "playwright install chromium" in hint
    assert "9999" in hint, "the hint should name the build that is missing"


@pytest.mark.parametrize("layout", ["chromium", "chromium_headless_shell"])
def test_the_expected_chromium_build_counts_as_a_backend(monkeypatch, tmp_path, layout):
    """Either download satisfies a headless launch, so either one must count."""
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: True)
    monkeypatch.setattr(pdf_report, "_expected_chromium_revision", lambda: "9999")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    (tmp_path / f"{layout}-9999").mkdir()

    assert pdf_report.pdf_backend() == "playwright"


def test_a_browser_from_a_different_playwright_does_not_count(monkeypatch, tmp_path):
    """The pairing is the point: an older build is not one this playwright can launch."""
    from grant_assistant.reporting import pdf_report

    monkeypatch.setattr(pdf_report, "_playwright_available", lambda: True)
    monkeypatch.setattr(pdf_report, "_find_edge", lambda: None)
    monkeypatch.setattr(pdf_report, "_expected_chromium_revision", lambda: "9999")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    (tmp_path / "chromium-1234").mkdir()

    assert pdf_report.pdf_backend() is None


def test_the_real_playwright_manifest_names_a_chromium_build():
    """The probe reads playwright's own manifest; a shape change must not pass silently."""
    if importlib.util.find_spec("playwright") is None:
        pytest.skip("playwright not installed")
    from grant_assistant.reporting.pdf_report import _expected_chromium_revision

    assert (_expected_chromium_revision() or "").isdigit()


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


# -- MCP tool bodies ---------------------------------------------------------
#
# Registration was asserted, but the tool functions themselves never ran. A tool
# that is registered and raises when called is worse than one that is absent.


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_audit_dataset_returns_an_aggregated_summary(tmp_path, flawed):
    from grant_assistant import mcp_server

    path = tmp_path / "flawed.csv"
    flawed[0].to_csv(path, index=False)
    result = mcp_server.audit_dataset(str(path))

    assert 0 <= result["overall_score"] <= 100
    assert result["total_rows"] > 0
    assert result["issues"]
    # Aggregates only: no client-level records may cross this boundary.
    assert "records" not in result
    assert all("row" not in issue for issue in result["issues"])


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_analyze_dataset_returns_metrics(tmp_path, clean_df):
    from grant_assistant import mcp_server

    path = tmp_path / "clean.csv"
    clean_df.to_csv(path, index=False)
    result = mcp_server.analyze_dataset(str(path))

    assert result["headline_metrics"]["total_enrollments"] > 0
    assert result["programs"]


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_generate_report_writes_the_files_it_names(tmp_path, clean_df):
    from grant_assistant import mcp_server

    path = tmp_path / "clean.csv"
    clean_df.to_csv(path, index=False)
    written = mcp_server.generate_report(str(path), output_dir=str(tmp_path / "out"))

    assert written
    for entry in written:
        assert Path(entry).exists(), entry


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_ask_analyst_answers_deterministically(tmp_path, clean_df, monkeypatch):
    from grant_assistant import mcp_server

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path = tmp_path / "clean.csv"
    clean_df.to_csv(path, index=False)
    answer = mcp_server.ask_analyst(str(path), "How many enrollments were there?")
    assert isinstance(answer, str)
    assert answer.strip()


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_batch_tool_rolls_up_a_folder(tmp_path, clean_df, flawed):
    from grant_assistant import mcp_server

    clean_df.to_csv(tmp_path / "a.csv", index=False)
    flawed[0].to_csv(tmp_path / "b.csv", index=False)
    result = mcp_server.batch_audit(str(tmp_path))

    assert result["files_audited"] == 2
    assert result["weighted_score"] is not None
    assert len(result["per_file"]) == 2


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_history_tool_reads_recorded_runs(tmp_path, profile, audit_flawed, analytics_flawed):
    from grant_assistant import mcp_server
    from grant_assistant.history import record_run

    db = tmp_path / "history.db"
    record_run(profile, audit_flawed, analytics_flawed, db, label="Q1")
    result = mcp_server.data_quality_history(str(db))

    assert result["runs"] == 1
    assert result["history"][0]["label"] == "Q1"


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_resources_return_content():
    from grant_assistant import mcp_server

    assert "housing_stability" in mcp_server.list_profiles_resource()
    assert "DQ-" in mcp_server.audit_rules_resource()
    assert mcp_server.measure_definitions_resource().strip()


@pytest.mark.skipif(not _HAS_MCP, reason="mcp extra not installed")
def test_prompts_render():
    from grant_assistant import mcp_server

    review = mcp_server.review_grant_report("data.csv")
    assert "data.csv" in review
    assert "DQ-010" in mcp_server.explain_data_quality_issue("DQ-010")
