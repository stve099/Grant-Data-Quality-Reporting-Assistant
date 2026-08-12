"""Streamlit run-history page.

The history store answers the question a funder actually asks — "is this getting
better?" — but every writer into it was a command line: ``record-run``, ``batch
--record``, ``scheduled-audit``. A program manager working in the browser built
no history at all, so the aging and trend machinery was invisible to exactly the
person it was written for. This page is the missing writer and reader.
"""

from __future__ import annotations

import streamlit as st

from grant_assistant.analytics.charts import history_trend_chart
from grant_assistant.history import (
    DB_PATH_ENV_VAR,
    default_db_path,
    history_frame,
    load_history,
    record_run,
    resolved_since_last_run,
    rule_ages,
    score_trend,
)
from grant_assistant.ui import theme
from grant_assistant.ui.state import (
    loaded as _loaded,
)
from grant_assistant.ui.state import (
    score_tone as _score_tone,
)
from grant_assistant.ui.theme import Kpi


def _trend_tone(trend: float | None) -> theme.Tone:
    if trend is None:
        return "neutral"
    return "good" if trend >= 0 else "critical"


def page_history() -> None:
    db_path = default_db_path()
    pipeline = st.session_state["pipeline"] if _loaded() else None
    # Scope to one profile always: two funders' scores in one series would be a
    # comparison of different rules, not a trend. The loaded dataset names the
    # profile when there is one; otherwise the reader has to choose, because a
    # database holding several grants has no single answer.
    if pipeline is not None:
        profile_id: str | None = pipeline["profile"].profile_id
    else:
        profile_id = _profile_picker(db_path)
    entries = load_history(db_path, profile_id) if profile_id else []

    pills = [theme.pill(f"{len(entries)} recorded run(s)", "info")]
    if pipeline:
        pills.append(theme.pill(pipeline["profile"].grant_name, "neutral"))
    theme.page_header(
        "Run History",
        eyebrow="Analysis",
        subtitle="Each recorded run stores the data quality score, the findings behind it, "
        "and every calculated metric, so improvement can be shown across reporting "
        "periods rather than asserted.",
        pills=pills,
    )

    _record_panel(pipeline, db_path, entries)

    if not entries:
        st.info(
            "No runs recorded yet for this profile. Load a dataset and record it to start "
            "the trend."
        )
        _storage_note(db_path)
        return

    trend = score_trend(entries)
    latest = entries[-1]
    theme.kpis(
        [
            Kpi("Recorded runs", str(len(entries))),
            Kpi(
                "Latest recorded score",
                f"{latest.score:.1f}",
                note=f"grade {latest.grade}",
                tone=_score_tone(latest.score),
            ),
            Kpi(
                "Since the first run",
                "n/a" if trend is None else f"{trend:+.1f}",
                note="needs two runs" if trend is None else "points of data quality",
                tone=_trend_tone(trend),
            ),
            # Named "recorded" throughout: the loaded dataset may not be the last
            # thing recorded, and reading these as its figures would mislead.
            Kpi("Findings, latest recorded run", str(latest.findings)),
        ]
    )

    metric_names = sorted({name for entry in entries for name in entry.metrics})
    metric = st.selectbox(
        "Plot a metric alongside the score",
        ["(none)", *metric_names],
        help="Any measure recorded with these runs. A metric a profile gained later "
        "simply has no earlier points.",
    )
    st.plotly_chart(
        history_trend_chart(entries, None if metric == "(none)" else metric),
        use_container_width=True,
    )

    theme.panel_title("Recorded runs")
    st.dataframe(history_frame(entries), use_container_width=True, hide_index=True)

    if pipeline is not None:
        _aging_panel(entries, pipeline["audit"])
    _storage_note(db_path)


def _profile_picker(db_path) -> str | None:
    """Which profile's history to show when no dataset names one."""
    profiles = sorted({entry.profile_id for entry in load_history(db_path)})
    if not profiles:
        return None
    if len(profiles) == 1:
        return profiles[0]
    return st.selectbox(
        "Profile",
        profiles,
        help="Runs are scoped to one profile: scores from different funders are "
        "calculated under different rules and do not belong on one trend.",
    )


def _record_panel(pipeline: dict | None, db_path, entries: list) -> None:
    """The write half: add the loaded dataset's audit to the history."""
    theme.panel_title("Record this run", "adds the loaded dataset to the trend")
    if pipeline is None:
        st.caption(
            "Load a dataset on **Upload & Profile** to record a run. Runs already recorded "
            "are shown below."
        )
        return

    audit = pipeline["audit"]
    col1, col2 = st.columns([2, 1], gap="large")
    label = col1.text_input(
        "Label this run",
        placeholder="Q3 FY26",
        help="How this run should read on the trend, e.g. a reporting period.",
    )
    with col2:
        st.write("")
        if st.button("Record run", type="primary", use_container_width=True):
            run_id = record_run(
                pipeline["profile"],
                audit,
                pipeline["analytics"],
                db_path,
                label=label.strip(),
                source=pipeline["filename"],
            )
            previous = entries[-1] if entries else None
            message = (
                f"Recorded run #{run_id} — score {audit.overall_score:.1f} "
                f"({audit.grade}), {audit.total_findings} finding(s)."
            )
            if previous is not None:
                message += f" {audit.overall_score - previous.score:+.1f} versus the last run."
            st.session_state["history_recorded"] = message
            # Remember what this dataset was recorded as. Aging treats the loaded
            # audit as the current run, so counting its own row from history as a
            # prior observation would age every finding by one run per click.
            recorded: set[int] = st.session_state.setdefault("recorded_run_ids", set())
            recorded.add(run_id)
            st.rerun()

    if "history_recorded" in st.session_state:
        st.success(st.session_state["history_recorded"])


def _aging_panel(entries: list, audit) -> None:
    """How long each current finding has been open, against *prior* runs.

    The loaded audit is the current run, and :func:`rule_ages` counts it as one.
    Recording it adds a row saying the same thing, so that row has to come back
    out — otherwise one dataset recorded three times reads as a finding open for
    three consecutive runs, which is the exact claim the aging panel exists to
    make and the exact claim that would be false.
    """
    recorded = st.session_state.get("recorded_run_ids", set())
    prior = [entry for entry in entries if entry.run_id not in recorded]

    theme.panel_title("Issue aging", "the loaded dataset against earlier runs")
    resolved = resolved_since_last_run(prior, audit)
    if resolved:
        st.success("Resolved since the last recorded run: " + ", ".join(resolved))

    ages = rule_ages(prior, audit)
    persistent = [age for age in ages if age.is_persistent]
    if persistent:
        st.warning(
            "Open for three or more consecutive runs — a process, not a slip:\n\n- "
            + "\n- ".join(age.describe() for age in persistent)
        )
    if ages:
        # Every finding, not only the two extremes: one carried over from a single
        # earlier run is neither new nor yet persistent, and listing only those two
        # groups dropped it off the page entirely.
        with st.expander(f"All {len(ages)} current finding(s), with age"):
            for age in ages:
                st.write(f"- {age.describe()}")
    elif not resolved:
        st.caption("Nothing to age yet — record a second run to compare against.")


def _storage_note(db_path) -> None:
    st.caption(
        f"History is stored in `{db_path}`. Set `{DB_PATH_ENV_VAR}` to keep it somewhere "
        "durable — on a hosted demo the container's disk does not survive a restart."
    )
