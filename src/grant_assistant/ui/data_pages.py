"""Streamlit upload and data-preview pages."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from grant_assistant import schema
from grant_assistant.configuration import (
    ProfileValidationError,
    list_profiles,
    load_profile_file,
)
from grant_assistant.ingestion import (
    IngestionError,
    load_dataset,
    merge_uploaded_datasets,
)
from grant_assistant.ui import theme
from grant_assistant.ui.state import (
    SOURCE_DROPPED_NOTE as _SOURCE_DROPPED_NOTE,
)
from grant_assistant.ui.state import (
    loaded as _loaded,
)
from grant_assistant.ui.state import (
    profile_label as _profile_label,
)
from grant_assistant.ui.state import (
    require_data as _require_data,
)
from grant_assistant.ui.state import (
    source_frame as _source_frame,
)
from grant_assistant.ui.state import (
    store_pipeline as _store_pipeline,
)
from grant_assistant.ui.theme import Kpi


def page_upload() -> None:
    pills = [theme.pill("Synthetic demo data only", "warning")]
    if _loaded():
        p = st.session_state["pipeline"]
        pills.insert(0, theme.pill(f"Loaded · {p['filename']}", "good"))
    theme.page_header(
        "Upload & Profile",
        eyebrow="Workspace",
        subtitle="Select the grant reporting profile that matches your funder, then load a "
        "client-level enrollment extract. Never upload real client data to a demo "
        "environment.",
        pills=pills,
    )

    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        theme.panel_title("1 · Grant profile")
        profiles = list_profiles()
        if not profiles:
            st.error("No profiles found in configs/. Add a YAML profile to continue.")
            return
        # Show the grant name, not the profile id. The id is an internal key —
        # a user picking their funder should see "Stable Homes Grant", not
        # "housing_stability" — but the id stays the selected value because it
        # is what every other layer keys on.
        profile_id = st.selectbox(
            "Grant profile",
            sorted(profiles),
            key="profile_choice",
            label_visibility="collapsed",
            format_func=lambda pid: _profile_label(profiles, pid),
        )
        try:
            profile = load_profile_file(profiles[profile_id])
        except ProfileValidationError as exc:
            st.error(str(exc))
            return
        theme.kpis(
            [
                Kpi("Programs", str(len(profile.programs))),
                Kpi("Measures", str(len(profile.performance_measures))),
                Kpi("Follow-ups", str(len(profile.followup_schedule))),
            ],
            min_width=120,
        )
        st.markdown(
            f"**{profile.grant_name}**  \n"
            f"{profile.grantor or 'No grantor specified'}  \n"
            f"Reporting period: {profile.reporting_period.label}"
        )
        with st.expander("Profile detail"):
            st.markdown(f"**Programs:** {', '.join(profile.program_names)}")
            st.markdown(
                "**Performance measures:**\n"
                + "\n".join(
                    f"- {m.name} — target {m.target}" + (f" ({m.program})" if m.program else "")
                    for m in profile.performance_measures
                )
            )

    with col2:
        theme.panel_title("2 · Data extract")
        uploaded = st.file_uploader(
            "CSV or Excel enrollment extract",
            type=["csv", "xlsx", "xls", "xlsm"],
            label_visibility="collapsed",
        )
        st.caption(
            "Samples in `sample_data/`: `housing_program_clean.csv` audits at 100/100, "
            "`housing_program_flawed.csv` contains 23 documented injected error types."
        )

        related = st.file_uploader(
            "Related extracts to flatten in (optional)",
            type=["csv", "xlsx", "xls", "xlsm"],
            accept_multiple_files=True,
            help="One row per client in each related file. Columns already present in the "
            "primary extract are kept; related files only add new ones.",
        )

        theme.panel_title("3 · Run pipeline")
        if uploaded is None and _loaded():
            # A demo visitor arrives with a dataset already audited. Telling them to
            # upload one contradicts the "Loaded" pill above and sends them looking
            # for work that is already done.
            p = st.session_state["pipeline"]
            audit = p["audit"]
            st.success(
                f"**{p['filename']}** is loaded and audited — {len(p['prepared'].df)} rows, "
                f"data quality score {audit.overall_score:.1f}/100 (grade {audit.grade}). "
                "Open **Audit Dashboard** in the left rail to see the findings."
            )
            source = _source_frame()
            different_profile = profile.profile_id != p["profile"].profile_id
            if different_profile and source is None:
                st.caption(_SOURCE_DROPPED_NOTE)
            elif different_profile and source is not None:
                # Selecting a different funder used to change nothing until the user
                # re-uploaded. Re-running from the retained source frame is the whole
                # reason it is kept.
                if st.button(
                    f"Re-run this dataset as **{profile.grant_name}**",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        _store_pipeline(source, profile, p["filename"])
                    except (IngestionError, ProfileValidationError) as exc:
                        st.error(str(exc))
                        return
                    st.rerun()
                st.caption(
                    f"Currently audited as **{p['profile'].grant_name}**. Re-running applies "
                    f"{profile.grant_name}'s field mappings, vocabularies, and targets to the "
                    "same rows."
                )
            else:
                st.caption("Upload a file above to audit your own extract instead.")
        elif uploaded is None:
            st.info("Upload a file to enable the audit and analytics pipeline.")
        elif st.button("Run audit + analytics", type="primary", use_container_width=True):
            try:
                raw = load_dataset(io.BytesIO(uploaded.getvalue()), filename=uploaded.name)
                if related:
                    raw = merge_uploaded_datasets(
                        raw, [(f.name, f.getvalue()) for f in related], profile
                    )
                audit = _store_pipeline(raw, profile, uploaded.name)
            except (IngestionError, ProfileValidationError) as exc:
                st.error(str(exc))
                return
            prepared = st.session_state["pipeline"]["prepared"]
            merged_note = f" (flattened with {len(related)} related file(s))" if related else ""
            st.success(
                f"Processed **{uploaded.name}**{merged_note} — {len(prepared.df)} rows, data "
                f"quality score {audit.overall_score:.1f}/100 (grade {audit.grade})."
            )
            if audit.pii_warnings:
                st.error(
                    "**Possible personal information in this upload.** This tool is built "
                    "for pseudonymous extracts — remove or hash these columns and re-upload.\n\n- "
                    + "\n- ".join(audit.pii_warnings[:5])
                )
            if audit.injection_warnings:
                st.warning(
                    "Security note — possible prompt-injection text found in uploaded cells. "
                    "It is neutralized before any AI processing.\n\n- "
                    + "\n- ".join(audit.injection_warnings[:5])
                )


# ---------------------------------------------------------------------------
# Page: Data Preview
# ---------------------------------------------------------------------------


def page_preview() -> None:
    if not _require_data("Data Preview"):
        return
    p = st.session_state["pipeline"]
    prepared = p["prepared"]
    theme.page_header(
        "Data Preview",
        eyebrow="Workspace",
        subtitle="Source columns mapped onto the canonical schema, with dates and numerics "
        "coerced. Invalid values are preserved in the audit trail rather than silently "
        "dropped.",
        pills=[theme.pill(p["filename"], "info")],
    )
    theme.kpis(
        [
            Kpi("Rows", f"{len(prepared.df):,}"),
            Kpi("Mapped columns", str(len(prepared.mapped_columns)), tone="good"),
            Kpi(
                "Unmapped source columns",
                str(len(prepared.unmapped_source_columns)),
                tone="warning" if prepared.unmapped_source_columns else "neutral",
            ),
            Kpi(
                "Missing canonical columns",
                str(len(prepared.missing_canonical_columns)),
                tone="warning" if prepared.missing_canonical_columns else "neutral",
            ),
        ]
    )

    theme.panel_title("Prepared data", "canonical schema")
    st.dataframe(
        prepared.df.drop(columns=[schema.PROGRAM_RAW], errors="ignore"),
        use_container_width=True,
        height=430,
    )

    with st.expander("Field mapping applied"):
        st.dataframe(
            pd.DataFrame(
                [
                    {"Source column": s, "Canonical column": c}
                    for s, c in prepared.mapped_columns.items()
                ]
            ),
            use_container_width=True,
        )
        if prepared.unmapped_source_columns:
            st.warning("Ignored columns: " + ", ".join(prepared.unmapped_source_columns))
        if prepared.missing_canonical_columns:
            st.info(
                "Canonical columns absent from the upload: "
                + ", ".join(prepared.missing_canonical_columns)
            )


# ---------------------------------------------------------------------------
# Page: Audit Dashboard
# ---------------------------------------------------------------------------
