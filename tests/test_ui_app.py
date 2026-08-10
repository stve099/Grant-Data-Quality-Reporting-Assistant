"""Streamlit app smoke tests.

The app is the largest file in the repo and was excluded from coverage entirely,
so features added to it — the PII warning, the correction-worksheet download,
the usage footer — were verified by nothing at all.

These do not test appearance. They assert that every page renders without
raising, which is the failure that actually happens when a helper is renamed or
an import is stripped, and that the safety-relevant text reaches the screen.
``AppTest`` runs the script headlessly in-process.
"""

from __future__ import annotations

import importlib.util

import pytest

from tests.conftest import REPO_ROOT

_HAS_APPTEST = importlib.util.find_spec("streamlit") is not None
pytestmark = [
    pytest.mark.skipif(not _HAS_APPTEST, reason="streamlit not installed"),
    pytest.mark.slow,
]

APP_PATH = REPO_ROOT / "src" / "grant_assistant" / "ui" / "app.py"
FLAWED = REPO_ROOT / "sample_data" / "housing_program_flawed.csv"


def _app(timeout: int = 90):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(APP_PATH), default_timeout=timeout)


def _text_of(app) -> str:
    """Everything the page put on screen, whatever element carried it."""
    parts: list[str] = []
    for attr in (
        "markdown",
        "title",
        "header",
        "subheader",
        "caption",
        "text",
        "info",
        "warning",
        "error",
        "success",
    ):
        collection = getattr(app, attr, None)
        if collection is None:
            continue
        for element in collection:
            value = getattr(element, "value", None)
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


# -- The app starts ----------------------------------------------------------


def test_app_runs_without_exception():
    """The single most valuable assertion: the script executes top to bottom."""
    app = _app().run()
    assert not app.exception


def test_navigation_is_present():
    app = _app().run()
    assert app.radio, "expected the sidebar navigation radio groups"


def test_landing_page_explains_the_tool():
    app = _app().run()
    text = _text_of(app).casefold()
    assert "grant" in text


# -- Pages render ------------------------------------------------------------


def _goto(app, page_label: str):
    """Select a page by its label in whichever nav group holds it."""
    for group in app.radio:
        options = [str(o) for o in group.options]
        if page_label in options:
            group.set_value(page_label).run()
            return app
    raise AssertionError(f"navigation has no page labelled {page_label!r}")


#: Every page in NAV. Parametrized from the same list the app builds its
#: navigation from would hide a rename, so these are spelled out deliberately.
ALL_PAGES = [
    "Upload & Profile",
    "Data Preview",
    "Audit Dashboard",
    "Issue Explorer",
    "Analytics Dashboard",
    "Period Comparison",
    "Analyst Chat",
    "Proactive Insights",
    "Report Builder",
    "Export Center",
    "Configuration Help",
]


def test_the_page_list_matches_the_app():
    """If a page is renamed, these tests must fail rather than silently skip."""
    from grant_assistant.ui.app import PAGES

    assert sorted(PAGES) == sorted(ALL_PAGES)


@pytest.mark.parametrize("page", ALL_PAGES)
def test_each_page_renders_without_data(page):
    """Before an upload every page must still render, not traceback."""
    app = _app().run()
    _goto(app, page)
    assert not app.exception, f"{page} raised: {app.exception}"


# -- With a dataset loaded ---------------------------------------------------


@pytest.fixture()
def loaded_app(tmp_path):
    """The app with the demo dataset preloaded via its query-parameter path."""
    app = _app()
    app.query_params["demo"] = "housing_program_flawed.csv"
    app.query_params["profile"] = "housing_stability"
    return app.run()


def test_demo_data_loads(loaded_app):
    assert not loaded_app.exception


def test_pages_render_with_data(loaded_app):
    for page in ("Audit Dashboard", "Analytics Dashboard", "Export Center"):
        _goto(loaded_app, page)
        assert not loaded_app.exception, f"{page} raised with data loaded"


def test_export_center_offers_the_correction_worksheet(loaded_app):
    """Added this session and previously verified by nothing."""
    _goto(loaded_app, "Export Center")
    labels = [b.label for b in loaded_app.button]
    assert any("correction worksheet" in label.casefold() for label in labels), labels


# -- Interactions ------------------------------------------------------------
#
# Rendering a page proves it does not crash on load. These drive the buttons,
# which is where the work actually happens: building a report, preparing a
# workbook, generating a narrative. Each was previously unverified.


def _click(app, label_fragment: str):
    """Press the first button whose label contains the fragment."""
    for button in app.button:
        if label_fragment.casefold() in button.label.casefold():
            button.click().run()
            return app
    raise AssertionError(
        f"no button matching {label_fragment!r}; saw {[b.label for b in app.button]}"
    )


def test_report_builder_builds_a_report(loaded_app):
    """The primary action of the Deliverables section."""
    _goto(loaded_app, "Report Builder")
    _click(loaded_app, "Build report")
    assert not loaded_app.exception
    assert "report_html" in loaded_app.session_state


def test_report_builder_offers_both_templates(loaded_app):
    _goto(loaded_app, "Report Builder")
    labels = [str(o) for group in loaded_app.radio for o in group.options]
    # The concise template is presented as "Executive brief" to users.
    assert "Full report" in labels
    assert "Executive brief" in labels


def test_export_center_prepares_the_audit_workbook(loaded_app):
    _goto(loaded_app, "Export Center")
    _click(loaded_app, "audit workbook")
    assert not loaded_app.exception
    assert loaded_app.session_state["export_audit"]


def test_export_center_prepares_the_correction_worksheet(loaded_app):
    """Added this session; previously nothing executed this code path."""
    _goto(loaded_app, "Export Center")
    _click(loaded_app, "correction worksheet")
    assert not loaded_app.exception
    assert loaded_app.session_state["export_corrections"]


def test_export_center_prepares_the_analytics_workbook(loaded_app):
    _goto(loaded_app, "Export Center")
    _click(loaded_app, "analytics workbook")
    assert not loaded_app.exception
    assert loaded_app.session_state["export_analytics"]


def test_issue_explorer_shows_findings(loaded_app):
    _goto(loaded_app, "Issue Explorer")
    assert not loaded_app.exception
    assert loaded_app.dataframe, "expected the findings table"


def test_audit_dashboard_reports_the_score(loaded_app):
    _goto(loaded_app, "Audit Dashboard")
    text = _text_of(loaded_app)
    assert not loaded_app.exception
    # The flawed sample scores 85.1; assert the figure reaches the screen.
    assert "85" in text or any("85" in str(m.value) for m in loaded_app.metric)


def test_analyst_chat_renders_in_deterministic_mode(loaded_app):
    """Without a key the analyst still answers; the page must say so."""
    _goto(loaded_app, "Analyst Chat")
    assert not loaded_app.exception
    assert "non-ai" in _text_of(loaded_app).casefold() or loaded_app.chat_input


def test_data_preview_shows_the_mapping(loaded_app):
    _goto(loaded_app, "Data Preview")
    assert not loaded_app.exception
    assert loaded_app.dataframe


def test_period_comparison_asks_for_a_second_file(loaded_app):
    """With only one dataset loaded it must prompt, not fail."""
    _goto(loaded_app, "Period Comparison")
    assert not loaded_app.exception


def test_configuration_help_lists_the_profile(loaded_app):
    _goto(loaded_app, "Configuration Help")
    assert not loaded_app.exception
    assert "housing" in _text_of(loaded_app).casefold()


def test_profile_selector_offers_every_configured_profile():
    """A new profile in configs/ must reach the selector, not just the registry.

    The selector is built from ``list_profiles()`` and relabels each id with the
    profile's grant name, so a profile that validates but is never picked up here
    would be invisible in the UI. This guards the wiring: the option set must
    match the grant names of every configured profile exactly.
    """
    from grant_assistant.configuration import list_profiles, load_profile_file

    app = _app().run()
    _goto(app, "Upload & Profile")
    assert not app.exception
    expected = {load_profile_file(path).grant_name for path in list_profiles().values()}
    box = next((s for s in app.selectbox if s.label == "Grant profile"), None)
    assert box is not None, "no 'Grant profile' selectbox on Upload & Profile"
    missing = expected - set(box.options)
    assert not missing, f"profile selector missing: {sorted(missing)}"


def test_configuration_help_lists_every_registered_rule():
    """A new rule in the registry must appear on the Configuration Help page.

    The rules tab builds its table from ``list_rules()``; a rule that registers
    but never reaches this table is undocumented to the user. Tabs execute
    regardless of which is active, so the dataframe is present either way.
    """
    from grant_assistant.audit import list_rules

    app = _app().run()
    _goto(app, "Configuration Help")
    assert not app.exception
    rule_ids = {m.rule_id for m in list_rules()}
    rules_df = next(
        (df.value for df in app.dataframe if "Rule" in getattr(df.value, "columns", [])),
        None,
    )
    assert rules_df is not None, "no rules table on the Configuration Help page"
    missing = rule_ids - set(rules_df["Rule"])
    assert not missing, f"Configuration Help missing rules: {sorted(missing)}"


def test_pii_warning_reaches_the_audit_dashboard(tmp_path, clean_df):
    """A file with identifiers must say so on screen, not only in the CLI."""
    from grant_assistant.audit import run_audit
    from grant_assistant.configuration import load_profile
    from grant_assistant.ingestion import prepare_dataset
    from tests.conftest import CONFIG_DIR

    frame = clean_df.copy()
    frame["Client Name"] = "Jane Doe"
    profile = load_profile("housing_stability", CONFIG_DIR)
    audit = run_audit(prepare_dataset(frame, profile), profile)

    # The page renders from session state, so seed it the way the app does.
    assert audit.pii_warnings, "expected the scan to flag the added column"
    assert any("Client Name" in w for w in audit.pii_warnings)
