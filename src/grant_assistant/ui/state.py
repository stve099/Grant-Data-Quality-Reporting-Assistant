"""Shared Streamlit session-state and formatting helpers."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from grant_assistant.agents import DataAnalystAgent, get_provider
from grant_assistant.configuration import (
    GrantProfile,
    ProfileValidationError,
    load_profile_file,
)
from grant_assistant.corrections import (
    ApplyReport,
    CorrectionImpact,
    apply_corrections,
    corrected_download,
    read_worksheet_bytes,
)
from grant_assistant.history import HistorySummary, default_db_path, load_history_summary
from grant_assistant.models import AuditResult
from grant_assistant.ui import theme
from grant_assistant.workflow import run_pipeline_on_frame

#: Session keys derived from the pipeline. They must be dropped whenever it is
#: replaced, or a new dataset is narrated by an agent still holding the old one.
_DERIVED_KEYS = (
    "agent",
    "chat_history",
    "report_html",
    "report_docx",
    "report_pdf",
    "correction_outcome",
    "corrected_dataset",
    # Prepared download bytes. They are built from a specific audit and analytics,
    # so a workbook left over from before a re-run or a correction would offer the
    # old figures under a page reporting the new ones.
    "export_audit",
    "export_analytics",
    "export_corrections",
    # Runs this session recorded for the dataset being replaced; see aging below.
    "recorded_run_ids",
)

#: Rows above which the pre-mapping source frame is dropped rather than kept in
#: session state. Retaining it costs a third copy of the dataset per browser
#: session, which one analyst on a laptop will not notice and a shared server
#: with several large extracts open certainly will. Raise it with
#: GRANT_ASSISTANT_MAX_RETAINED_ROWS where memory is not the binding constraint.
DEFAULT_MAX_RETAINED_SOURCE_ROWS = 25_000

#: Shown wherever a feature is unavailable because the frame was too large to keep.
SOURCE_DROPPED_NOTE = (
    "This dataset is too large to keep a second copy of in memory, so re-running it "
    "under another profile and applying corrections in the app are unavailable. "
    "Re-upload the file to switch profiles, or use the `grant-assistant` CLI, which "
    "reads from disk and has no such limit."
)


def max_retained_source_rows() -> int:
    """Row ceiling for retaining the source frame, overridable by environment."""
    configured = os.environ.get("GRANT_ASSISTANT_MAX_RETAINED_ROWS", "").strip()
    if not configured:
        return DEFAULT_MAX_RETAINED_SOURCE_ROWS
    try:
        return max(0, int(configured))
    except ValueError:
        return DEFAULT_MAX_RETAINED_SOURCE_ROWS


def loaded() -> bool:
    return "pipeline" in st.session_state


def source_frame() -> pd.DataFrame | None:
    """The retained pre-mapping frame, or None when it was too large to keep."""
    if not loaded():
        return None
    source: pd.DataFrame | None = st.session_state["pipeline"].get("source")
    return source


def store_pipeline(source: pd.DataFrame, profile: GrantProfile, filename: str) -> AuditResult:
    """Run the pipeline over a source frame and make it the session's dataset.

    The source frame is kept alongside the results so the dataset can be re-run
    under a different profile, or corrected in place, without the user
    re-uploading it. That is a third copy of the data in memory, which is the
    deliberate cost of those two features — up to
    :func:`max_retained_source_rows`, past which the copy is dropped and the
    features that need it say so rather than silently doubling a server's
    footprint.
    """
    result = run_pipeline_on_frame(source, profile)
    st.session_state["pipeline"] = {
        "prepared": result.prepared,
        "profile": result.profile,
        "audit": result.audit,
        "analytics": result.analytics,
        "filename": filename,
        "source": source if len(source) <= max_retained_source_rows() else None,
    }
    for key in _DERIVED_KEYS:
        st.session_state.pop(key, None)
    return result.audit


@dataclass(frozen=True)
class CorrectionOutcome:
    """One applied worksheet: what was written, and what it changed."""

    report: ApplyReport
    impact: CorrectionImpact
    filename: str


def apply_correction_upload(payload: bytes, filename: str) -> CorrectionOutcome:
    """Apply a returned worksheet to the loaded dataset and re-audit in place.

    This is the step that used to require leaving the app for a terminal. It
    edits the retained source frame, not the prepared one: a correction is
    written in the user's own columns and then re-prepared, so the fix is proved
    by the same pipeline that found the problem.

    Raises:
        ValueError: nothing to apply, or the upload is not a worksheet.
    """
    pipeline = st.session_state["pipeline"]
    source = source_frame()
    if source is None:
        raise ValueError(SOURCE_DROPPED_NOTE)

    corrections = read_worksheet_bytes(payload, filename)
    if not corrections:
        raise ValueError(
            "No corrections found — fill in the 'Corrected Value' column before uploading."
        )
    corrected, report = apply_corrections(source, corrections, pipeline["prepared"])

    before = pipeline["audit"]
    stem = Path(pipeline["filename"]).stem
    # store_pipeline clears the derived keys, this outcome among them, so the
    # session is written after it rather than before.
    after = store_pipeline(corrected, pipeline["profile"], f"{stem} (corrected).csv")
    outcome = CorrectionOutcome(report, CorrectionImpact.between(before, after), filename)
    st.session_state["correction_outcome"] = outcome
    st.session_state["corrected_dataset"] = corrected_download(corrected, pipeline["filename"])
    return outcome


@st.cache_data(show_spinner=False)
def profile_label(profiles: dict[str, Path], profile_id: str) -> str:
    """Human label for a profile id, falling back when its YAML is invalid."""
    try:
        return load_profile_file(profiles[profile_id]).grant_name
    except (ProfileValidationError, KeyError, OSError):
        return profile_id


def session_history() -> HistorySummary | None:
    """Recorded runs behind the loaded dataset, for the report and the analyst.

    Runs this session recorded for the loaded dataset are excluded: they say what
    the current audit already says, so counting them would age every finding by
    one and let the analyst describe a trend against itself.
    """
    if not loaded():
        return None
    pipeline = st.session_state["pipeline"]
    return load_history_summary(
        default_db_path(),
        pipeline["profile"].profile_id,
        pipeline["audit"],
        exclude_run_ids=set(st.session_state.get("recorded_run_ids", set())),
    )


def agent() -> DataAnalystAgent:
    if "agent" not in st.session_state:
        pipeline = st.session_state["pipeline"]
        st.session_state["agent"] = DataAnalystAgent(
            pipeline["analytics"],
            pipeline["audit"],
            pipeline["profile"],
            provider=get_provider(),
            history=session_history(),
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


def score_tone(score: float) -> theme.Tone:
    if score >= 90:
        return "good"
    if score >= 75:
        return "warning"
    return "critical"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"
