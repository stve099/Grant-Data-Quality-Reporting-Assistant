"""Enterprise dashboard chrome for the Streamlit application.

Streamlit's defaults read as "demo app": emoji radio lists, stock metric
widgets, generic headers. This module replaces that chrome with a product
look — a dark navigation rail, a page header band, and custom KPI/status
components — using the design tokens in ``docs/design_system.md``.

All helpers escape data-derived strings before injecting HTML.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Literal

import streamlit as st

Tone = Literal["neutral", "good", "warning", "critical", "info"]

# Navigation rail (dark) tokens — the chart/report surface tokens stay light.
NAV_BG = "#101f38"
NAV_BG_ACTIVE = "#1c3557"
NAV_TEXT = "#c9d4e4"
NAV_TEXT_ACTIVE = "#ffffff"
NAV_ACCENT = "#4d94ec"
NAV_RULE = "rgba(255,255,255,0.10)"

PAGE_BG = "#f4f5f7"
CARD_BG = "#ffffff"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BRAND = "#2a78d6"
BRAND_DEEP = "#1c5cab"

TONE_COLORS: dict[Tone, tuple[str, str]] = {
    # tone -> (text/border color, soft background)
    "neutral": (INK_2, "#f0efec"),
    "good": ("#0a7d0a", "#e2f4e2"),
    "warning": ("#8a6206", "#fdf3d9"),
    "critical": ("#b32f2f", "#fbe4e4"),
    "info": (BRAND_DEEP, "#e4eefb"),
}

_CSS = f"""
<style>
/* ---------- App shell ---------- */
.stApp {{ background: {PAGE_BG}; }}
[data-testid="stAppViewContainer"] > .main {{ background: {PAGE_BG}; }}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
/* Hide Streamlit's Deploy/menu chrome so the app reads as a product, not a demo. */
[data-testid="stToolbar"] {{ display: none; }}
[data-testid="stDecoration"] {{ display: none; }}
#MainMenu {{ display: none; }}
footer {{ display: none; }}
[data-testid="stMainBlockContainer"] {{ padding: 1.6rem 2.4rem 4rem; max-width: 1500px; }}

/* ---------- Navigation rail ---------- */
section[data-testid="stSidebar"] {{
  background: {NAV_BG};
  border-right: none;
  width: 268px !important;
}}
section[data-testid="stSidebar"] > div {{ padding-top: 0; }}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding: 0 0 2rem; }}
section[data-testid="stSidebar"] * {{ color: {NAV_TEXT}; }}
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] svg,
section[data-testid="stSidebar"] button[kind="header"] svg {{ fill: {NAV_TEXT}; }}

.ga-brand {{
  padding: 22px 20px 18px;
  border-bottom: 1px solid {NAV_RULE};
  margin-bottom: 10px;
}}
.ga-brand-mark {{
  display: flex; align-items: center; gap: 11px;
}}
.ga-brand-logo {{
  width: 34px; height: 34px; border-radius: 9px; flex: none;
  background: linear-gradient(140deg, {NAV_ACCENT}, {BRAND_DEEP});
  display: flex; align-items: center; justify-content: center;
  color: #fff !important; font-weight: 700; font-size: 15px; letter-spacing: -0.02em;
}}
.ga-brand-name {{
  color: #fff !important; font-weight: 650; font-size: 14.5px; line-height: 1.15;
  letter-spacing: -0.01em;
}}
.ga-brand-sub {{
  color: rgba(255,255,255,0.55) !important; font-size: 11px; margin-top: 2px;
  text-transform: uppercase; letter-spacing: .08em;
}}

/* Radio list -> navigation rows */
section[data-testid="stSidebar"] div[role="radiogroup"] {{ gap: 1px; padding: 0 12px; }}
section[data-testid="stSidebar"] div[role="radiogroup"] > label {{
  width: 100%;
  padding: 9px 12px;
  border-radius: 8px;
  border-left: 3px solid transparent;
  cursor: pointer;
  transition: background .12s ease, color .12s ease;
  margin: 0;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {{
  background: rgba(255,255,255,0.06);
}}
/* Streamlit nests the radio glyph as label > div > div > div:first-child */
section[data-testid="stSidebar"] div[role="radiogroup"] > label > div > div > div:first-child {{
  display: none !important;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label > div,
section[data-testid="stSidebar"] div[role="radiogroup"] > label > div > div {{
  width: 100%;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label p {{
  font-size: 13.5px; font-weight: 500; color: {NAV_TEXT} !important; margin: 0;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {{
  background: {NAV_BG_ACTIVE};
  border-left-color: {NAV_ACCENT};
}}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p {{
  color: {NAV_TEXT_ACTIVE} !important; font-weight: 620;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] + div,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{ display: none; }}

.ga-nav-group {{
  color: rgba(255,255,255,0.42) !important;
  font-size: 10.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  padding: 16px 24px 6px;
}}
.ga-rail-card {{
  margin: 14px 16px 0; padding: 12px 14px;
  background: rgba(255,255,255,0.05);
  border: 1px solid {NAV_RULE};
  border-radius: 10px;
}}
.ga-rail-card .r {{
  display: flex; justify-content: space-between; gap: 10px;
  font-size: 12px; padding: 3px 0;
}}
.ga-rail-card .r span:first-child {{ color: rgba(255,255,255,0.55) !important; }}
.ga-rail-card .r span:last-child {{ color: #fff !important; font-weight: 600; }}
.ga-rail-note {{
  margin: 10px 16px 0; font-size: 11px; color: rgba(255,255,255,0.45) !important;
  padding: 0 14px;
}}

/* ---------- Page header band ---------- */
.ga-head {{
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 24px; flex-wrap: wrap;
  padding: 4px 0 16px; margin-bottom: 20px;
  border-bottom: 1px solid {GRID};
}}
.ga-eyebrow {{
  font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: {BRAND}; margin-bottom: 5px;
}}
.ga-title {{
  font-size: 27px; font-weight: 700; letter-spacing: -0.02em; color: {INK};
  margin: 0; line-height: 1.15;
}}
.ga-sub {{ font-size: 13.5px; color: {INK_2}; margin: 7px 0 0; max-width: 78ch; line-height: 1.5; }}
.ga-head-meta {{ display: flex; gap: 8px; flex-wrap: wrap; padding-bottom: 3px; }}

/* ---------- Pills ---------- */
.ga-pill {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 11px; border-radius: 999px;
  font-size: 12px; font-weight: 600; white-space: nowrap;
}}

/* ---------- KPI cards ---------- */
.ga-kpis {{ display: grid; gap: 14px; margin-bottom: 22px; }}
.ga-kpi {{
  background: {CARD_BG}; border: 1px solid {GRID}; border-radius: 12px;
  padding: 15px 17px 14px; position: relative; overflow: hidden;
}}
.ga-kpi::before {{
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: {BRAND};
}}
.ga-kpi.good::before {{ background: #0ca30c; }}
.ga-kpi.warning::before {{ background: #fab219; }}
.ga-kpi.critical::before {{ background: #d03b3b; }}
.ga-kpi.neutral::before {{ background: {GRID}; }}
.ga-kpi-label {{
  font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  color: {MUTED};
}}
.ga-kpi-value {{
  font-size: 29px; font-weight: 700; color: {INK}; line-height: 1.15; margin-top: 7px;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
}}
.ga-kpi-unit {{ font-size: 15px; font-weight: 600; color: {MUTED}; margin-left: 2px; }}
.ga-kpi-note {{ font-size: 12px; margin-top: 6px; color: {INK_2}; }}
.ga-kpi-note.good {{ color: #0a7d0a; }}
.ga-kpi-note.critical {{ color: #b32f2f; }}
.ga-kpi-note.warning {{ color: #8a6206; }}

/* ---------- Panels & typography ---------- */
.ga-panel-title {{
  font-size: 15px; font-weight: 700; color: {INK}; letter-spacing: -0.01em;
  margin: 26px 0 10px; display: flex; align-items: center; gap: 9px;
}}
.ga-panel-title::before {{
  content: ""; width: 3px; height: 15px; border-radius: 2px; background: {BRAND};
}}
.ga-panel-title .hint {{ font-weight: 400; font-size: 12.5px; color: {MUTED}; }}

h1, h2, h3, h4 {{ color: {INK}; letter-spacing: -0.015em; }}
[data-testid="stMainBlockContainer"] h2 {{ font-size: 19px; margin-top: 12px; }}
[data-testid="stMainBlockContainer"] h3 {{ font-size: 15.5px; }}

/* ---------- Widgets ---------- */
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {{
  border: 1px solid {GRID}; border-radius: 10px; overflow: hidden; background: {CARD_BG};
}}
[data-testid="stMetric"] {{
  background: {CARD_BG}; border: 1px solid {GRID}; border-radius: 12px; padding: 13px 16px;
}}
[data-testid="stMetricValue"] {{ color: {INK}; font-variant-numeric: tabular-nums; }}
div[data-testid="stExpander"] {{
  border: 1px solid {GRID}; border-radius: 10px; background: {CARD_BG};
}}
.stTabs [data-baseweb="tab-list"] {{ gap: 2px; border-bottom: 1px solid {GRID}; }}
.stTabs [data-baseweb="tab"] {{
  font-size: 13.5px; font-weight: 600; color: {INK_2}; padding: 9px 15px;
}}
.stTabs [aria-selected="true"] {{ color: {BRAND_DEEP}; }}
.stButton > button {{ border-radius: 8px; font-weight: 600; font-size: 13.5px; }}
.stButton > button[kind="primary"] {{ background: {BRAND}; border-color: {BRAND}; }}
.stButton > button[kind="primary"]:hover {{ background: {BRAND_DEEP}; border-color: {BRAND_DEEP}; }}
.stDownloadButton > button {{ border-radius: 8px; font-weight: 600; font-size: 13.5px; }}
[data-testid="stFileUploaderDropzone"] {{
  background: {CARD_BG}; border: 1.5px dashed #b9c2cf; border-radius: 10px;
}}
[data-testid="stChatInput"] {{ border-radius: 10px; }}
.js-plotly-plot {{
  background: {CARD_BG}; border: 1px solid {GRID}; border-radius: 12px; padding: 6px 4px 2px;
}}
[data-testid="stAlert"] {{ border-radius: 10px; }}
</style>
"""


def inject() -> None:
    """Inject the app stylesheet. Call once, immediately after set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def _esc(value: object) -> str:
    return html.escape(str(value))


# ---------------------------------------------------------------------------
# Navigation rail
# ---------------------------------------------------------------------------


def brand() -> None:
    """Product mark at the top of the navigation rail."""
    st.markdown(
        """
<div class="ga-brand">
  <div class="ga-brand-mark">
    <div class="ga-brand-logo">GA</div>
    <div>
      <div class="ga-brand-name">Grant Assistant</div>
      <div class="ga-brand-sub">Data Quality &amp; Reporting</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def nav_group(label: str) -> None:
    st.markdown(f'<div class="ga-nav-group">{_esc(label)}</div>', unsafe_allow_html=True)


def rail_card(rows: list[tuple[str, str]]) -> None:
    """Compact key/value card in the navigation rail (session context)."""
    body = "".join(
        f'<div class="r"><span>{_esc(k)}</span><span>{_esc(v)}</span></div>' for k, v in rows
    )
    st.markdown(f'<div class="ga-rail-card">{body}</div>', unsafe_allow_html=True)


def rail_note(text: str) -> None:
    st.markdown(f'<div class="ga-rail-note">{_esc(text)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------


def pill(label: str, tone: Tone = "neutral") -> str:
    """Return the HTML for a status pill (compose several into a header)."""
    color, background = TONE_COLORS[tone]
    return (
        f'<span class="ga-pill" style="color:{color};background:{background}">{_esc(label)}</span>'
    )


def page_header(
    title: str,
    eyebrow: str = "",
    subtitle: str = "",
    pills: list[str] | None = None,
) -> None:
    """Render the page title band with optional status pills on the right."""
    parts = ['<div class="ga-head"><div>']
    if eyebrow:
        parts.append(f'<div class="ga-eyebrow">{_esc(eyebrow)}</div>')
    parts.append(f'<h1 class="ga-title">{_esc(title)}</h1>')
    if subtitle:
        parts.append(f'<p class="ga-sub">{_esc(subtitle)}</p>')
    parts.append("</div>")
    if pills:
        parts.append(f'<div class="ga-head-meta">{"".join(pills)}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def panel_title(title: str, hint: str = "") -> None:
    """Section heading inside a page."""
    extra = f'<span class="hint">{_esc(hint)}</span>' if hint else ""
    st.markdown(f'<div class="ga-panel-title">{_esc(title)}{extra}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------


@dataclass
class Kpi:
    """One KPI card."""

    label: str
    value: str
    unit: str = ""
    note: str = ""
    tone: Tone = "info"
    note_tone: Tone | None = None


@dataclass
class KpiRow:
    """A responsive row of KPI cards."""

    items: list[Kpi] = field(default_factory=list)
    min_width: int = 168


def kpis(items: list[Kpi], min_width: int = 168) -> None:
    """Render a responsive grid of KPI cards."""
    cards = []
    for item in items:
        tone_class = item.tone if item.tone in {"good", "warning", "critical", "neutral"} else ""
        unit = f'<span class="ga-kpi-unit">{_esc(item.unit)}</span>' if item.unit else ""
        note = ""
        if item.note:
            note_tone = item.note_tone or "neutral"
            note_class = note_tone if note_tone in {"good", "warning", "critical"} else ""
            note = f'<div class="ga-kpi-note {note_class}">{_esc(item.note)}</div>'
        cards.append(
            f'<div class="ga-kpi {tone_class}">'
            f'<div class="ga-kpi-label">{_esc(item.label)}</div>'
            f'<div class="ga-kpi-value">{_esc(item.value)}{unit}</div>'
            f"{note}</div>"
        )
    st.markdown(
        f'<div class="ga-kpis" style="grid-template-columns:repeat(auto-fit,minmax('
        f'{min_width}px,1fr))">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
