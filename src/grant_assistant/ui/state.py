"""Shared Streamlit session-state and formatting helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from grant_assistant.agents import DataAnalystAgent, get_provider
from grant_assistant.configuration import (
    GrantProfile,
    ProfileValidationError,
    load_profile_file,
)
from grant_assistant.models import AuditResult
from grant_assistant.ui import theme
from grant_assistant.workflow import run_pipeline_on_frame

#: Session keys derived from the pipeline. They must be dropped whenever it is
#: replaced, or a new dataset is narrated by an agent still holding the old one.
_DERIVED_KEYS = ("agent", "chat_history", "report_html", "report_docx", "report_pdf")


def loaded() -> bool:
    return "pipeline" in st.session_state


def store_pipeline(source: pd.DataFrame, profile: GrantProfile, filename: str) -> AuditResult:
    """Run the pipeline over a source frame and make it the session's dataset.

    The source frame is kept alongside the results so the dataset can be re-run
    under a different profile without the user re-uploading it. That is a third
    copy of the data in memory, which is the deliberate cost of making the
    profile selector actually do something once a file is loaded.
    """
    result = run_pipeline_on_frame(source, profile)
    st.session_state["pipeline"] = {
        "prepared": result.prepared,
        "profile": result.profile,
        "audit": result.audit,
        "analytics": result.analytics,
        "filename": filename,
        "source": source,
    }
    for key in _DERIVED_KEYS:
        st.session_state.pop(key, None)
    return result.audit


@st.cache_data(show_spinner=False)
def profile_label(profiles: dict[str, Path], profile_id: str) -> str:
    """Human label for a profile id, falling back when its YAML is invalid."""
    try:
        return load_profile_file(profiles[profile_id]).grant_name
    except (ProfileValidationError, KeyError, OSError):
        return profile_id


def agent() -> DataAnalystAgent:
    if "agent" not in st.session_state:
        pipeline = st.session_state["pipeline"]
        st.session_state["agent"] = DataAnalystAgent(
            pipeline["analytics"],
            pipeline["audit"],
            pipeline["profile"],
            provider=get_provider(),
        )
    return st.session_state["agent"]


def require_data(page: str) -> bool:
    if not loaded():
        theme.page_header(
            page,
            eyebrow="No dataset loaded",
            subtitle="Load a CSV or Excel extract on the Upload & Profile page to activate "
            "this view.",
        )
        st.info(
            "Go to **Upload & Profile** in the left rail, choose a grant profile, and run "
            "the pipeline."
        )
        return False
    return True


def output_dir() -> Path:
    if "output_dir" not in st.session_state:
        st.session_state["output_dir"] = Path(tempfile.mkdtemp(prefix="grant_assistant_"))
    return st.session_state["output_dir"]


def score_tone(score: float) -> str:
    if score >= 90:
        return "good"
    if score >= 75:
        return "warning"
    return "critical"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"
