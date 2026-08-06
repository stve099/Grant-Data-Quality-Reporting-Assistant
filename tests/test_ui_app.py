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
