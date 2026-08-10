"""Streamlit AI analyst and insight pages."""

from __future__ import annotations

import streamlit as st

from grant_assistant.agents.workflows import should_stream
from grant_assistant.ui import theme
from grant_assistant.ui.state import (
    agent as _agent,
)
from grant_assistant.ui.state import (
    require_data as _require_data,
)


def page_chat() -> None:
    if not _require_data("Analyst Chat"):
        return
    agent = _agent()
    mode_pill = (
        theme.pill("AI mode · Claude with tool use", "good")
        if agent.ai_enabled
        else theme.pill("Deterministic mode · no API key", "warning")
    )
    theme.page_header(
        "Analyst Chat",
        eyebrow="AI Analyst",
        subtitle="A senior-analyst agent grounded in the calculated metrics. It retrieves "
        "values through typed tools, never invents numbers, and keeps answers aggregated.",
        pills=[mode_pill],
    )

    examples = [
        "Which program had the highest successful exit rate?",
        "Which clients are overdue for follow-up?",
        "Summarize grant outcomes for the reporting period.",
        "Which data quality issues could affect this report?",
        "Are any metrics distorted by small sample sizes?",
        "Which outcomes are below target?",
    ]
    with st.expander("Example questions"):
        for example in examples:
            st.markdown(f"- {example}")

    history: list[dict[str, str]] = st.session_state.setdefault("chat_history", [])
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    response_mode = st.radio(
        "Response mode",
        ["Automatic", "Always stream", "Always use tools"],
        horizontal=True,
        help="Automatic streams narrative questions and uses the lookup tools for "
        "anything that needs a specific figure. Streaming cannot run the tool loop, "
        "so a streamed number comes from the fact sheet rather than a traced "
        "retrieval — which is why picking per question was never the user's job.",
        disabled=not agent.ai_enabled,
    )

    question: str | None = st.chat_input("Ask the senior data analyst…")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        if response_mode == "Always stream":
            stream_this = True
        elif response_mode == "Always use tools":
            stream_this = False
        else:
            stream_this = should_stream(question)

        with st.chat_message("assistant"):
            if stream_this and agent.ai_enabled:
                answer = st.write_stream(agent.ask_stream(question, history=history[-8:]))
            else:
                with st.spinner("Retrieving values…" if agent.ai_enabled else "Analyzing…"):
                    answer = agent.ask(question, history=history[-8:])
                    st.markdown(answer)
                if agent.ai_enabled and response_mode == "Automatic":
                    st.caption("Answered with lookup tools, so every figure is retrieved.")
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": str(answer)})

    usage = getattr(agent.provider, "usage", None)
    if usage is not None and usage.calls:
        st.caption(f"Session usage — {usage.session_summary()}")


# ---------------------------------------------------------------------------
# Page: Proactive Insights
# ---------------------------------------------------------------------------


def page_insights() -> None:
    if not _require_data("Proactive Insights"):
        return
    agent = _agent()
    report = agent.proactive_insights()
    theme.page_header(
        "Proactive Insights",
        eyebrow="AI Analyst",
        subtitle="A senior-analyst review generated automatically from the calculated "
        "results — anomalies, trends, risks, and recommended actions. Works with or "
        "without an API key.",
        pills=[
            theme.pill(f"{sum(len(v) for v in report.sections().values())} observations", "info")
        ],
    )

    tone_by_section: dict[str, str] = {
        "Anomalies Detected": "warning",
        "Data Quality Risks": "critical",
        "Program Concerns": "warning",
        "Program Strengths": "good",
        "Recommended Actions": "info",
    }
    left, right = st.columns(2, gap="large")
    sections = [(title, items) for title, items in report.sections().items() if items]
    for index, (title, items) in enumerate(sections):
        target = left if index % 2 == 0 else right
        with target:
            theme.panel_title(title)
            tone = tone_by_section.get(title, "neutral")
            body = "\n".join(f"- {item}" for item in items)
            if tone == "critical":
                st.error(body)
            elif tone == "warning":
                st.warning(body)
            elif tone == "good":
                st.success(body)
            else:
                st.markdown(body)

    if agent.ai_enabled:
        theme.panel_title("AI narrative")
        if st.button("Generate AI-polished narrative"):
            with st.spinner("Narrating insights…"):
                st.markdown(agent.narrated_insights())


# ---------------------------------------------------------------------------
# Page: Report Builder
# ---------------------------------------------------------------------------
