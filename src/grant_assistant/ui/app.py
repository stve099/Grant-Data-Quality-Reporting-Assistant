"""Grant Data Quality & Reporting Assistant — Streamlit bootstrap and router.

Run with:
    uv run streamlit run src/grant_assistant/ui/app.py

Page renderers live in :mod:`grant_assistant.ui.pages`; this module owns only
application setup, demo loading, navigation, and routing.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import streamlit as st

from grant_assistant.agents.provider import ai_available
from grant_assistant.analytics import compute_analytics
from grant_assistant.audit import run_audit
from grant_assistant.configuration import list_profiles, load_profile_file
from grant_assistant.env import load_environment
from grant_assistant.ingestion import load_dataset, prepare_dataset
from grant_assistant.ui import theme
from grant_assistant.ui.pages import (
    page_analytics,
    page_audit,
    page_chat,
    page_comparison,
    page_config_help,
    page_exports,
    page_insights,
    page_issues,
    page_preview,
    page_report,
    page_upload,
)
from grant_assistant.ui.state import loaded

load_environment()

st.set_page_config(
    page_title="Grant Assistant — Data Quality & Reporting",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject()

NAV: list[tuple[str, list[str]]] = [
    ("Data", ["Upload & Profile", "Data Preview"]),
    ("Quality", ["Audit Dashboard", "Issue Explorer"]),
    ("Analysis", ["Analytics Dashboard", "Period Comparison"]),
    ("AI Analyst", ["Analyst Chat", "Proactive Insights"]),
    ("Deliverables", ["Report Builder", "Export Center"]),
    ("Reference", ["Configuration Help"]),
]
PAGES = [page for _, pages in NAV for page in pages]


def _demo_autoload() -> None:
    """Preload a dataset when GRANT_ASSISTANT_DEMO or ``?demo=`` is supplied."""
    demo_file = os.environ.get("GRANT_ASSISTANT_DEMO", "").strip()
    demo_profile = os.environ.get("GRANT_ASSISTANT_DEMO_PROFILE", "").strip()
    query_demo = st.query_params.get("demo", "")
    if query_demo:
        candidate = (Path("sample_data") / Path(query_demo).name).resolve()
        if candidate.is_file():
            demo_file = str(candidate)
            demo_profile = st.query_params.get("profile", demo_profile)
    if not demo_file or loaded():
        return
    demo_path = Path(demo_file)
    profiles = list_profiles()
    if not demo_path.exists() or not profiles:
        return
    profile_id = demo_profile or sorted(profiles)[0]
    if profile_id not in profiles:
        return
    profile = load_profile_file(profiles[profile_id])
    prepared = prepare_dataset(load_dataset(demo_path), profile)
    st.session_state["pipeline"] = {
        "prepared": prepared,
        "profile": profile,
        "audit": run_audit(prepared, profile),
        "analytics": compute_analytics(prepared, profile),
        "filename": demo_path.name,
    }
    # Point the Upload page's profile selector at what was actually loaded. Without
    # this it falls back to the first profile alphabetically, so a demo visitor sees
    # the picker naming one grant while the sidebar names another. Set before the
    # widget is created, which this is: autoload runs ahead of routing.
    st.session_state.setdefault("profile_choice", profile_id)


def _select_page(group: str) -> None:
    """Adopt one navigation group's choice and clear the other groups."""
    choice = st.session_state.get(f"nav_{group}")
    if choice is None:
        return
    st.session_state["nav_page"] = choice
    for other, _pages in NAV:
        if other != group:
            st.session_state[f"nav_{other}"] = None


def _rail() -> str:
    """Render the navigation rail and return the selected page."""
    with st.sidebar:
        theme.brand()
        current = st.session_state.get("nav_page", PAGES[0])
        for group, pages in NAV:
            theme.nav_group(group)
            st.radio(
                group,
                pages,
                index=pages.index(current) if current in pages else None,
                key=f"nav_{group}",
                on_change=_select_page,
                args=(group,),
                label_visibility="collapsed",
            )
        selected = st.session_state.get("nav_page", PAGES[0])
        if loaded():
            pipeline = st.session_state["pipeline"]
            audit = pipeline["audit"]
            theme.rail_card(
                [
                    ("Dataset", pipeline["filename"]),
                    ("Profile", pipeline["profile"].profile_id),
                    ("Records", f"{audit.total_rows:,}"),
                    ("DQ score", f"{audit.overall_score:.1f} ({audit.grade})"),
                ]
            )
        else:
            theme.rail_card([("Dataset", "None loaded"), ("Profile", "—")])
        theme.rail_note(
            ("AI mode enabled" if ai_available() else "AI mode off — deterministic answers")
            + f" · {date.today():%b %d, %Y}"
        )
    return selected


def main() -> None:
    _demo_autoload()
    selected = _rail()
    router = {
        "Upload & Profile": page_upload,
        "Data Preview": page_preview,
        "Audit Dashboard": page_audit,
        "Issue Explorer": page_issues,
        "Analytics Dashboard": page_analytics,
        "Period Comparison": page_comparison,
        "Analyst Chat": page_chat,
        "Proactive Insights": page_insights,
        "Report Builder": page_report,
        "Export Center": page_exports,
        "Configuration Help": page_config_help,
    }
    router[selected]()


main()
