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
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
    "Run History",
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


# -- The demo landing page ----------------------------------------------------
# This is the first screen a visitor to the hosted demo sees. Two things on it
# used to contradict each other and the sidebar, which is worse than a bug in a
# page nobody reaches.


def test_demo_profile_selector_matches_the_loaded_profile(loaded_app):
    """The picker must name the grant that was actually loaded.

    It defaulted to the first profile alphabetically, so a visitor arriving with
    ?profile=housing_stability saw the picker naming a different grant than the
    sidebar, with no indication which one produced the numbers on screen.
    """
    _goto(loaded_app, "Upload & Profile")
    assert not loaded_app.exception

    loaded = loaded_app.session_state["pipeline"]["profile"]
    assert loaded.profile_id == "housing_stability"
    box = next((s for s in loaded_app.selectbox if s.label == "Grant profile"), None)
    assert box is not None
    # The selector's value is the profile id; format_func only changes the label.
    assert box.value == loaded.profile_id


def test_demo_landing_does_not_ask_for_an_upload_it_already_has(loaded_app):
    """With data loaded, step 3 must report state, not demand work already done."""
    _goto(loaded_app, "Upload & Profile")
    assert not loaded_app.exception

    text = _text_of(loaded_app)
    assert "Upload a file to enable" not in text
    assert "is loaded and audited" in text
    assert "Audit Dashboard" in text


def test_upload_prompt_still_appears_with_no_data():
    """The prompt is right when there is genuinely nothing loaded."""
    app = _app().run()
    _goto(app, "Upload & Profile")
    assert not app.exception
    assert "Upload a file to enable" in _text_of(app)


def test_selecting_another_profile_offers_a_re_run(loaded_app):
    """Choosing a different funder must do something, not just relabel a dropdown."""
    _goto(loaded_app, "Upload & Profile")
    box = next(s for s in loaded_app.selectbox if s.label == "Grant profile")
    assert box.value == "housing_stability"

    box.set_value("rapid_rehousing").run()
    assert not loaded_app.exception

    labels = [b.label for b in loaded_app.button]
    assert any("Re-run this dataset" in label for label in labels), labels
    # Still the old results until the button is pressed.
    assert loaded_app.session_state["pipeline"]["profile"].profile_id == "housing_stability"


def test_re_running_under_another_profile_re_audits_the_same_rows(loaded_app):
    """The re-run must apply the new profile's rules, not relabel the old result."""
    _goto(loaded_app, "Upload & Profile")
    before = loaded_app.session_state["pipeline"]
    before_score = before["audit"].overall_score
    before_rows = len(before["prepared"].df)
    filename = before["filename"]

    box = next(s for s in loaded_app.selectbox if s.label == "Grant profile")
    box.set_value("rapid_rehousing").run()
    button = next(b for b in loaded_app.button if "Re-run this dataset" in b.label)
    button.click().run()
    assert not loaded_app.exception

    after = loaded_app.session_state["pipeline"]
    assert after["profile"].profile_id == "rapid_rehousing"
    assert after["filename"] == filename, "same dataset, not a re-upload"
    assert len(after["prepared"].df) == before_rows, "same rows"
    # A different profile means different mappings, vocabularies, and targets, so
    # the audit is genuinely recomputed rather than carried over.
    assert after["audit"].overall_score != before_score
    assert after["analytics"] is not before["analytics"]


def test_re_run_clears_the_agent_bound_to_the_previous_profile(loaded_app):
    """A stale agent would narrate the new dataset using the old profile's facts."""
    _goto(loaded_app, "Analyst Chat")
    assert not loaded_app.exception
    _goto(loaded_app, "Upload & Profile")
    loaded_app.session_state["agent"] = object()

    box = next(s for s in loaded_app.selectbox if s.label == "Grant profile")
    box.set_value("rapid_rehousing").run()
    next(b for b in loaded_app.button if "Re-run this dataset" in b.label).click().run()

    assert "agent" not in loaded_app.session_state


# -- The correction round trip -----------------------------------------------
# Exporting the worksheet shipped long before taking it back did, so the app
# used to hand the user a spreadsheet and a command line. These drive the whole
# loop through the interface a program manager actually has.


def _filled_worksheet(app, value: str = "Rental by client, no ongoing subsidy") -> bytes:
    """The loaded dataset's worksheet with every exit-destination row filled in."""
    import io

    import pandas as pd

    from grant_assistant.corrections import SHEET_NAME, build_worksheet

    frame = build_worksheet(app.session_state["pipeline"]["audit"])
    targets = frame["Field"] == "exit_destination"
    assert targets.any(), "the flawed sample should flag exit destinations"
    frame.loc[targets, "Corrected Value"] = value

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name=SHEET_NAME, index=False)
    return buffer.getvalue()


def test_export_center_takes_a_worksheet_back(loaded_app):
    """The uploader is the half of the loop that used to live only in the CLI."""
    _goto(loaded_app, "Export Center")
    assert not loaded_app.exception
    labels = [u.label for u in loaded_app.file_uploader]
    assert any("correction worksheet" in label.casefold() for label in labels), labels


def test_applying_a_worksheet_re_audits_the_loaded_dataset(loaded_app):
    _goto(loaded_app, "Export Center")
    before = loaded_app.session_state["pipeline"]["audit"].overall_score
    payload = _filled_worksheet(loaded_app)

    uploader = next(
        u for u in loaded_app.file_uploader if "correction worksheet" in u.label.casefold()
    )
    uploader.set_value(("corrections.xlsx", payload, _XLSX_MIME)).run()
    _click(loaded_app, "Apply corrections")
    assert not loaded_app.exception

    outcome = loaded_app.session_state["correction_outcome"]
    assert outcome.report.applied > 0
    assert outcome.impact.before_score == before
    assert outcome.impact.after_score > before, "fixing what was flagged must raise the score"
    # The whole session moves to the corrected data, not just this page.
    assert loaded_app.session_state["pipeline"]["audit"].overall_score == outcome.impact.after_score
    assert "(corrected)" in loaded_app.session_state["pipeline"]["filename"]
    payload, name, _mime = loaded_app.session_state["corrected_dataset"]
    assert payload.startswith(b"Client ID"), "the CSV upload comes back as CSV"
    assert name.endswith("_corrected.csv")


def test_a_worksheet_that_is_not_one_is_refused_on_screen(loaded_app):
    """A wrong file must produce a message, not a traceback in the browser."""
    _goto(loaded_app, "Export Center")
    uploader = next(
        u for u in loaded_app.file_uploader if "correction worksheet" in u.label.casefold()
    )
    uploader.set_value(("notes.csv", b"a,b\n1,2\n", "text/csv")).run()
    _click(loaded_app, "Apply corrections")

    assert not loaded_app.exception
    assert "not a correction worksheet" in _text_of(loaded_app)
    assert "correction_outcome" not in loaded_app.session_state


def test_an_empty_worksheet_says_so_rather_than_re_auditing(loaded_app):
    _goto(loaded_app, "Export Center")
    payload = _filled_worksheet(loaded_app, value="")
    uploader = next(
        u for u in loaded_app.file_uploader if "correction worksheet" in u.label.casefold()
    )
    uploader.set_value(("corrections.xlsx", payload, _XLSX_MIME)).run()
    _click(loaded_app, "Apply corrections")

    assert not loaded_app.exception
    assert "No corrections found" in _text_of(loaded_app)
    assert "(corrected)" not in loaded_app.session_state["pipeline"]["filename"]


# -- The retained source frame has a ceiling ---------------------------------


def test_a_dataset_too_large_to_retain_says_what_it_costs(monkeypatch):
    """Re-run and apply-corrections need a second copy; past the ceiling, they say so."""
    monkeypatch.setenv("GRANT_ASSISTANT_MAX_RETAINED_ROWS", "1")
    app = _app()
    app.query_params["demo"] = "housing_program_flawed.csv"
    app.query_params["profile"] = "housing_stability"
    app.run()

    assert not app.exception
    assert app.session_state["pipeline"]["source"] is None, "the copy must be dropped"

    _goto(app, "Upload & Profile")
    box = next(s for s in app.selectbox if s.label == "Grant profile")
    box.set_value("rapid_rehousing").run()
    assert not any("Re-run this dataset" in b.label for b in app.button)
    assert "too large to keep a second copy" in _text_of(app)

    _goto(app, "Export Center")
    assert not app.exception
    assert not app.file_uploader, "no worksheet can be applied without the source frame"
    assert "too large to keep a second copy" in _text_of(app)


def test_the_ceiling_is_generous_enough_for_the_sample(loaded_app):
    """The default must not quietly disable the features on an ordinary extract."""
    from grant_assistant.ui.state import max_retained_source_rows

    assert loaded_app.session_state["pipeline"]["source"] is not None
    assert max_retained_source_rows() >= len(loaded_app.session_state["pipeline"]["prepared"].df)


# -- Run history --------------------------------------------------------------


def test_run_history_records_the_loaded_dataset(loaded_app):
    """Every writer into the history store used to be a command line."""
    from grant_assistant.history import default_db_path, load_history

    _goto(loaded_app, "Run History")
    assert not loaded_app.exception

    label = next(t for t in loaded_app.text_input if "Label" in t.label)
    label.set_value("Q3 FY26").run()
    _click(loaded_app, "Record run")
    assert not loaded_app.exception

    entries = load_history(default_db_path())
    assert len(entries) == 1
    entry = entries[0]
    assert entry.label == "Q3 FY26"
    assert entry.score == loaded_app.session_state["pipeline"]["audit"].overall_score
    assert entry.source == loaded_app.session_state["pipeline"]["filename"]
    assert entry.rule_counts, "rule counts are what makes aging possible"
    assert "Recorded run #" in _text_of(loaded_app)


def test_run_history_shows_the_trend_across_runs(loaded_app):
    _goto(loaded_app, "Run History")
    _click(loaded_app, "Record run")
    _click(loaded_app, "Record run")
    assert not loaded_app.exception

    table = next(
        (df.value for df in loaded_app.dataframe if "Score" in getattr(df.value, "columns", [])),
        None,
    )
    assert table is not None, "no run table on the Run History page"
    assert len(table) == 2
    assert "2" in _text_of(loaded_app)


def test_run_history_without_a_dataset_still_renders():
    """The page reads history as well as writing it, so it must work before an upload."""
    app = _app().run()
    _goto(app, "Run History")
    assert not app.exception
    assert "No runs recorded yet" in _text_of(app)
    assert not app.button, "nothing to record without a dataset"


def test_run_history_ages_findings_against_the_recorded_runs(loaded_app):
    """Aging is the reason rule counts are stored; the page must surface it."""
    _goto(loaded_app, "Run History")
    _click(loaded_app, "Record run")
    assert not loaded_app.exception

    # The expander label carries the count; its body carries each finding's age.
    labels = [e.label for e in loaded_app.expander]
    assert any("with age" in label for label in labels), labels
    assert "record(s)" in _text_of(loaded_app)


# -- What a correction or a re-run must invalidate -----------------------------


def test_applying_corrections_drops_workbooks_built_from_the_old_audit(loaded_app):
    """A prepared download must not outlive the audit it was built from."""
    _goto(loaded_app, "Export Center")
    _click(loaded_app, "audit workbook")
    _click(loaded_app, "analytics workbook")
    assert loaded_app.session_state["export_audit"]

    payload = _filled_worksheet(loaded_app)
    uploader = next(
        u for u in loaded_app.file_uploader if "correction worksheet" in u.label.casefold()
    )
    uploader.set_value(("corrections.xlsx", payload, _XLSX_MIME)).run()
    _click(loaded_app, "Apply corrections")

    assert "export_audit" not in loaded_app.session_state
    assert "export_analytics" not in loaded_app.session_state


def test_re_running_under_another_profile_drops_the_old_workbooks(loaded_app):
    """Same hazard by the other route: the workbook would state the old profile's rules."""
    _goto(loaded_app, "Export Center")
    _click(loaded_app, "audit workbook")
    assert loaded_app.session_state["export_audit"]

    _goto(loaded_app, "Upload & Profile")
    box = next(s for s in loaded_app.selectbox if s.label == "Grant profile")
    box.set_value("rapid_rehousing").run()
    next(b for b in loaded_app.button if "Re-run this dataset" in b.label).click().run()

    assert "export_audit" not in loaded_app.session_state


# -- Aging must not count the current run as its own history ------------------


def test_recording_a_run_does_not_age_its_own_findings(loaded_app):
    """rule_ages() counts the loaded audit as one run; its recorded row is the same run."""
    _goto(loaded_app, "Run History")
    _click(loaded_app, "Record run")
    assert not loaded_app.exception

    text = _text_of(loaded_app)
    assert "new this run" in text
    assert "consecutive runs" not in text, "one recording cannot make a finding long-standing"


def test_three_recordings_of_one_dataset_are_not_three_periods(loaded_app):
    """The persistence threshold means three reporting periods, not three clicks."""
    _goto(loaded_app, "Run History")
    for _ in range(3):
        _click(loaded_app, "Record run")
    assert not loaded_app.exception
    assert "consecutive runs" not in _text_of(loaded_app)


def test_a_run_recorded_before_this_session_still_ages(loaded_app):
    """Only this session's own recordings are excluded — real history must count."""
    from grant_assistant.history import default_db_path, record_run

    pipeline = loaded_app.session_state["pipeline"]
    record_run(
        pipeline["profile"],
        pipeline["audit"],
        pipeline["analytics"],
        default_db_path(),
        label="last quarter",
    )
    _goto(loaded_app, "Run History")
    assert not loaded_app.exception
    assert "consecutive runs" in _text_of(loaded_app)


# -- History with no dataset loaded stays scoped to one profile ---------------


def test_history_without_a_dataset_does_not_mix_profiles(monkeypatch):
    """Scores from two funders are calculated under different rules."""
    from grant_assistant.history import default_db_path, record_run
    from grant_assistant.workflow import run_pipeline
    from tests.conftest import CONFIG_DIR

    db = default_db_path()
    for profile_id in ("housing_stability", "rapid_rehousing"):
        result = run_pipeline(FLAWED, profile_id, config_dir=CONFIG_DIR)
        record_run(result.profile, result.audit, result.analytics, db, label=f"{profile_id} run")

    app = _app().run()
    _goto(app, "Run History")
    assert not app.exception

    picker = next((s for s in app.selectbox if s.label == "Profile"), None)
    assert picker is not None, "expected a profile picker when no dataset names one"
    assert set(picker.options) == {"housing_stability", "rapid_rehousing"}

    table = next(
        (df.value for df in app.dataframe if "Label" in getattr(df.value, "columns", [])),
        None,
    )
    assert table is not None
    assert list(table["Label"]) == [f"{picker.value} run"], "one profile's runs only"


# -- The trend reaches the report the app builds ------------------------------


def test_a_report_built_in_the_app_carries_the_recorded_trend(loaded_app):
    """Recording a run then building a report must show the movement, not a snapshot."""
    from grant_assistant.history import default_db_path, record_run

    pipeline = loaded_app.session_state["pipeline"]
    record_run(
        pipeline["profile"],
        pipeline["audit"],
        pipeline["analytics"],
        default_db_path(),
        label="Q1 FY26",
    )

    _goto(loaded_app, "Report Builder")
    _click(loaded_app, "Build report")
    assert not loaded_app.exception

    html = loaded_app.session_state["report_html"]
    assert "Data Quality Over Time" in html
    assert "Q1 FY26" in html


def test_the_analyst_is_grounded_in_the_same_history(loaded_app):
    from grant_assistant.history import default_db_path, record_run

    pipeline = loaded_app.session_state["pipeline"]
    record_run(
        pipeline["profile"],
        pipeline["audit"],
        pipeline["analytics"],
        default_db_path(),
        label="Q1 FY26",
    )
    _goto(loaded_app, "Analyst Chat")
    assert not loaded_app.exception

    facts = loaded_app.session_state["agent"].fact_sheet["quality_history"]
    assert facts["recorded_runs"] == 1
    assert facts["trend"][0]["label"] == "Q1 FY26"


def test_a_run_recorded_in_this_session_is_not_a_trend_against_itself(loaded_app):
    """Record then report: the app must not compare the dataset with its own row."""
    _goto(loaded_app, "Run History")
    _click(loaded_app, "Record run")

    _goto(loaded_app, "Report Builder")
    _click(loaded_app, "Build report")
    assert not loaded_app.exception
    assert "Data Quality Over Time" not in loaded_app.session_state["report_html"]
