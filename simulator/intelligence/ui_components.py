"""Shared UI components for the CDMO intelligence Streamlit app.

Provides a professional, monochrome design system:
- Monochrome bio/medical SVG icons
- Feature cards with brief explainers and click navigation
- Stepper component for workflow guidance
- Mock-data indicator badge
- anime.js entrance animations via streamlit.components.v1
- Plotly chart helpers with scientific annotations (labels, sources, n/stats)
"""

from __future__ import annotations

import json
from typing import Any

import plotly.graph_objects as go
import streamlit as st
from streamlit.components.v1 import html

from intelligence.palette import (
    BLUE,
    BLUISH_GREEN,
    CHART_COLORWAY,
    CONTINUOUS_SCALE,
    DARK_GREY,
    GREY,
    MID_GREY,
    ORANGE,
    REDDISH_PURPLE,
    THEME,
    VERMILION,
    WHITE,
    css_variables,
    tier_color,
)


# ---------------------------------------------------------------------------
# Monochrome SVG icon library
# ---------------------------------------------------------------------------
_BIOICONS: dict[str, str] = {
    "dna": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M2 15c6.667-6 13.333 0 20-6"/>
      <path d="M9 22c1.798-4.103 5.102-7.497 10-9"/>
      <path d="M15 2c-1.798 4.103-5.102 7.497-10 9"/>
      <path d="M22 9c-6.667 6-13.333 0-20 6"/>
    </svg>
    """,
    "pill": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/>
      <path d="m8.5 8.5 7 7"/>
    </svg>
    """,
    "factory": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M2 22h20"/>
      <path d="M8 21V10l6-3v14"/>
      <path d="M18 21V10l-4-2"/>
      <path d="M22 7a2 2 0 0 0-2-2h-6V3a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v1"/>
    </svg>
    """,
    "microscope": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M6 18h12"/>
      <path d="M3 22h18"/>
      <path d="M14 12a3 3 0 1 0-4 0 3 3 0 0 0 4 0Z"/>
      <path d="M12 15v5"/>
      <path d="M8 9l-2 5"/>
      <path d="M16 9l2 5"/>
      <path d="M10 6h4"/>
    </svg>
    """,
    "chart": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 3v18h18"/>
      <path d="m19 9-5 5-4-4-3 3"/>
    </svg>
    """,
    "beaker": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 3h15"/>
      <path d="M6 3v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V3"/>
      <path d="M6 14h12"/>
    </svg>
    """,
    "flask": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10 2v7.31"/>
      <path d="M14 2v7.31"/>
      <path d="M8.5 2h7"/>
      <path d="m14 9-5.27 8.17a2.5 2.5 0 0 0 2.1 3.83h3.34a2.5 2.5 0 0 0 2.1-3.83L10 9"/>
    </svg>
    """,
    "molecule": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <circle cx="5" cy="5" r="2"/>
      <circle cx="19" cy="5" r="2"/>
      <circle cx="19" cy="19" r="2"/>
      <circle cx="5" cy="19" r="2"/>
      <path d="M10 10 7 7"/>
      <path d="m14 10 3-3"/>
      <path d="m10 14-3 3"/>
      <path d="m14 14 3 3"/>
    </svg>
    """,
    "calendar": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>
      <path d="M16 2v4"/>
      <path d="M8 2v4"/>
      <path d="M3 10h18"/>
    </svg>
    """,
    "document": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <path d="M14 2v6h6"/>
      <path d="M16 13H8"/>
      <path d="M16 17H8"/>
      <path d="M10 9H8"/>
    </svg>
    """,
    "warning": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
      <path d="M12 9v4"/>
      <path d="M12 17h.01"/>
    </svg>
    """,
    "rocket": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z"/>
      <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.3 22.3 0 0 1-4 2Z"/>
      <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
      <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
    </svg>
    """,
    "search": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="8"/>
      <path d="m21 21-4.3-4.3"/>
    </svg>
    """,
    "filter": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
    </svg>
    """,
    "download": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <path d="M7 10 12 15 17 10"/>
      <path d="M12 15V3"/>
    </svg>
    """,
    "info": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <path d="M12 16v-4"/>
      <path d="M12 8h.01"/>
    </svg>
    """,
    "check": """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M20 6 9 17l-5-5"/>
    </svg>
    """,
}


def bioicon(name: str, size: int = 24, color: str = THEME["primary"]) -> str:
    """Return a scientific-themed SVG icon as a raw HTML string."""
    svg = _BIOICONS.get(name, _BIOICONS["molecule"])
    return f"""
    <div class="bioicon" style="display:inline-flex; width:{size}px; height:{size}px; color:{color}; vertical-align:middle;">
      {svg}
    </div>
    """


def bioicon_inline(name: str, size: int = 20, color: str = THEME["primary"], margin_right: int = 4) -> str:
    """Return a smaller inline icon suitable for labels and badges."""
    svg = _BIOICONS.get(name, _BIOICONS["molecule"])
    # Strip embedded newlines/indentation so the SVG doesn't collapse in tight
    # inline-flex contexts, and force it to fill its wrapper.
    svg = " ".join(svg.split())
    if 'width="100%"' not in svg:
        svg = svg.replace("<svg ", '<svg width="100%" height="100%" ', 1)
    return f"""
    <span class="bioicon-inline" style="display:inline-flex; align-items:center; justify-content:center; width:{size}px; height:{size}px; min-width:{size}px; min-height:{size}px; color:{color}; flex: 0 0 {size}px; vertical-align:middle; margin-right:{margin_right}px;">
      {svg}
    </span>
    """


# ---------------------------------------------------------------------------
# Enum / label humanization
# ---------------------------------------------------------------------------
# Known abbreviations that must not be Title-cased (would yield "Iv", "Im").
_ENUM_DISPLAY_OVERRIDES: dict[str, str] = {
    "iv": "IV",
    "im": "IM",
    "sc": "SC",
    "mo": "MO",
    "mab": "Monoclonal antibody",
    "po": "Oral",
}


def humanize_enum(token: str | None) -> str:
    """Display a snake_case enum token as a human-readable, sentence-cased label.

    Known abbreviations are expanded via an overrides map (e.g. ``iv`` ->
    ``IV``); everything else is split on underscores and sentence-cased — only
    the first word is capitalised (e.g. ``small_molecule`` -> ``Small
    molecule``, ``prefilled_pen`` -> ``Prefilled pen``, ``monoclonal_antibody``
    -> ``Monoclonal antibody``). Sentence case is the scientific convention;
    title-casing made classifications read as proper nouns (``Small Molecule``).
    Returns ``"—"`` for missing/empty values so callers can pass raw API tokens
    directly without leaking internal identifiers into the UI.
    """
    if token is None or str(token).strip() == "":
        return "—"
    t = str(token).strip()
    return _ENUM_DISPLAY_OVERRIDES.get(t, t.replace("_", " ").strip().capitalize())


def attribute_strip(attributes: list[tuple[str, str]]) -> str:
    """Compact one-line label/value strip for card attribute rows.

    Styling lives in the ``.cdmo-attr-*`` classes in ``SCIENTIFIC_CSS`` (single
    source of truth); this helper only emits structure, never inline styles.
    Each label/value pair is grouped (muted, uppercase, tracked label beside
    its value) and the pairs are separated by a thin middot whose size/color are
    pinned in CSS so it cannot inherit the surrounding paragraph font-size and
    render oversized. Container ``gap`` spaces pairs and separators symmetrically
    so the dot is never glued to a value, and each pair is kept on one line so a
    value can't wrap mid-phrase.

    Returns an HTML string for ``st.markdown(..., unsafe_allow_html=True)``.
    """
    def _pair(label: str, value: str) -> str:
        return (
            '<span class="cdmo-attr-pair">'
            f'<span class="cdmo-attr-label">{label}</span>'
            f'<span class="cdmo-attr-value">{value}</span>'
            "</span>"
        )

    sep = '<span class="cdmo-attr-sep">·</span>'
    return (
        '<div class="cdmo-attr-strip">'
        + sep.join(_pair(label, value) for label, value in attributes)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Global theme + layout helpers
# ---------------------------------------------------------------------------
SCIENTIFIC_CSS = """
<style>
  .stApp { background-color: var(--nsq-bg); }
  html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif;
    color: var(--nsq-text);
  }
  /* Hide Streamlit default sidebar on engine pages */
  [data-testid="stSidebar"] { display: none; }
  [data-testid="collapsedControl"] { display: none; }
  /* Section title */
  .cdmo-section-title {
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--nsq-text-muted);
  }
  .cdmo-page-title {
    font-size: 22px;
    font-weight: 900;
    color: var(--nsq-text);
    margin: 4px 0 0 0;
  }
  .cdmo-page-subtitle {
    font-size: 12px;
    color: var(--nsq-text-secondary);
    margin: 4px 0 0 0;
  }
  /* Feature cards */
  .cdmo-card-wrapper {
    position: relative;
    min-height: 92px;
  }
  .cdmo-card-wrapper [data-testid="stButton"] {
    position: absolute !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    margin: 0 !important;
    z-index: 1 !important;
  }
  .cdmo-card-wrapper [data-testid="stButton"] button {
    width: 100% !important;
    height: 100% !important;
    opacity: 0 !important;
    min-height: 92px !important;
  }
  .cdmo-card-wrapper [data-testid="stButton"] button > div {
    display: none !important;
  }
  .cdmo-feature-card {
    background: var(--nsq-surface);
    border: 1px solid var(--nsq-border);
    border-radius: 6px;
    padding: 16px;
    cursor: pointer;
    transition: border-color 0.2s, box-shadow 0.2s;
    height: 100%;
    pointer-events: none;
  }
  .cdmo-feature-card:hover {
    border-color: var(--nsq-border-strong);
    box-shadow: 0 2px 8px rgba(26,26,26,0.05);
  }
  .cdmo-feature-card.active {
    border-color: var(--nsq-primary);
    box-shadow: 0 2px 8px rgba(0,114,178,0.10);
  }
  .cdmo-feature-icon {
    width: 28px;
    height: 28px;
    color: var(--nsq-primary);
    margin-bottom: 8px;
  }
  .cdmo-feature-title {
    font-size: 13px;
    font-weight: 800;
    color: var(--nsq-text);
    margin: 0 0 4px 0;
  }
  .cdmo-feature-desc {
    font-size: 11px;
    color: var(--nsq-text-secondary);
    line-height: 1.4;
    margin: 0;
  }
  /* Metric tile */
  .cdmo-metric {
    text-align: center;
    border: 1px solid var(--nsq-border);
    border-radius: 4px;
    padding: 12px;
    background: var(--nsq-surface);
  }
  .cdmo-metric-value {
    font-size: 28px;
    font-weight: 900;
    color: var(--nsq-primary);
  }
  .cdmo-metric-label {
    font-size: 10px;
    color: var(--nsq-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 4px;
  }
  /* Icon sizing: make every SVG fill its wrapper */
  .bioicon svg, .bioicon-inline svg, .cdmo-step-icon svg {
    width: 100%;
    height: 100%;
    display: block;
  }
  /* Stepper */
  .cdmo-stepper {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    background: var(--nsq-surface);
    border: 1px solid var(--nsq-border);
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 16px;
    gap: 6px;
    overflow-x: auto;
    scrollbar-width: thin;
  }
  .cdmo-stepper::-webkit-scrollbar { height: 4px; }
  .cdmo-stepper::-webkit-scrollbar-thumb { background: var(--nsq-border-strong); border-radius: 2px; }
  .cdmo-step {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 700;
    color: var(--nsq-text-muted);
    white-space: nowrap;
    flex: 0 0 auto;
  }
  .cdmo-step.active {
    color: var(--nsq-primary);
  }
  .cdmo-step.completed {
    color: var(--nsq-success);
  }
  .cdmo-step-number {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid currentColor;
    font-size: 10px;
    flex: 0 0 20px;
  }
  .cdmo-step-icon {
    width: 14px;
    height: 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 14px;
    color: var(--nsq-success);
  }
  .cdmo-step-check { color: var(--nsq-success); }
  .cdmo-step-divider {
    flex: 0 0 auto;
    width: 16px;
    min-width: 16px;
    height: 1px;
    background: var(--nsq-border);
    margin: 0;
  }
  .cdmo-step-label { display: inline; white-space: nowrap; }
  @media (max-width: 768px) {
    .cdmo-stepper { padding: 8px; gap: 4px; }
    .cdmo-step-label { display: none; }
    .cdmo-step-divider { width: 10px; min-width: 10px; }
    .cdmo-step-number { width: 18px; height: 18px; flex: 0 0 18px; font-size: 9px; }
  }
  /* Mock-data badge */
  .cdmo-mock-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 8px;
    background: #fff9e6;
    color: #8c6b00;
    border: 1px solid #f0e442;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  /* Chart annotation */
  .cdmo-chart-caption {
    font-size: 10px;
    color: var(--nsq-text-muted);
    margin-top: 4px;
  }
  /* Attribute strip (ranked-candidate attribute line) — single source of truth.
     Pages must never re-inline these styles; change them here. The strip sets
     its own font-size so the middot separator does not inherit the surrounding
     paragraph size and render oversized relative to the 9px/12px labels. */
  .cdmo-attr-strip {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    font-size: 12px;
    line-height: 1.4;
    color: var(--nsq-text);
  }
  .cdmo-attr-pair {
    display: inline-flex;
    align-items: baseline;
    white-space: nowrap;
  }
  .cdmo-attr-label {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--nsq-text-muted);
    margin-right: 5px;
  }
  .cdmo-attr-value {
    font-size: 12px;
    color: var(--nsq-text);
  }
  .cdmo-attr-sep {
    color: var(--nsq-border-strong);
    font-size: 12px;
    line-height: 1;
  }
  /* GMP methodological pillar cards — single source of truth for their
     styling. Pages must never re-inline these styles; change them here. */
  .gmp-card {
    border: 1px solid var(--nsq-border);
    border-radius: 4px;
    padding: 10px;
    margin-bottom: 8px;
    background: var(--nsq-surface);
  }
  .gmp-card--summary { background: #fff9e6; }
  .gmp-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 6px;
  }
  .gmp-card-heading {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .gmp-pillar-icon {
    font-size: 14px;
    line-height: 1;
    color: var(--nsq-primary);
    flex: 0 0 auto;
  }
  .gmp-pillar-title {
    font-size: 12px;
    font-weight: 700;
    color: var(--nsq-text);
  }
  .gmp-rationale {
    font-size: 11px;
    color: var(--nsq-text-secondary);
    margin-top: 4px;
    line-height: 1.4;
  }
  .gmp-detail {
    font-size: 10px;
    color: var(--nsq-text-muted);
    margin-top: 6px;
    line-height: 1.4;
  }
  .gmp-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 6px;
  }
  .gmp-control-chip {
    padding: 2px 6px;
    border-radius: 3px;
    background: var(--nsq-surface-subtle);
    color: var(--nsq-text-secondary);
    font-size: 10px;
  }
  .gmp-missing-block { margin-top: 6px; }
  .gmp-missing-block-label,
  .gmp-missing-group-label {
    font-size: 9px;
    color: var(--nsq-text-muted);
    font-weight: 600;
    margin-bottom: 3px;
  }
  .gmp-missing-group { margin-bottom: 6px; }
  .gmp-missing-group:last-child { margin-bottom: 0; }
  .gmp-missing-chip {
    padding: 2px 6px;
    border-radius: 3px;
    background: #ffebe6;
    color: #8a2b0a;
    font-size: 9px;
    font-weight: 700;
    border: 1px solid #ffccbc;
  }
  .gmp-badge {
    padding: 2px 6px;
    border-radius: 3px;
    color: #fff;
    font-size: 9px;
    font-weight: 800;
    flex: 0 0 auto;
  }
  .gmp-badge--danger { background: var(--nsq-danger); }
  .gmp-badge--warning { background: var(--nsq-warning); }
  .gmp-badge--success { background: var(--nsq-success); }
</style>
"""


def apply_global_theme() -> None:
    """Inject the scientific color theme and collapse the default sidebar."""
    st.markdown(css_variables(), unsafe_allow_html=True)
    st.markdown(SCIENTIFIC_CSS, unsafe_allow_html=True)
    st.set_page_config(
        page_title="CDMO Off-Patent Intelligence Engine",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="collapsed",
    )


def page_header(pillar: str, title: str, subtitle: str, icon: str = "molecule") -> None:
    """Render a consistent page header with eyebrow, title, and subtitle."""
    st.markdown(
        f"""
        <div style="padding-bottom: 12px; border-bottom: 1px solid {THEME['border']}; margin-bottom: 16px;">
          <div class="cdmo-section-title">{bioicon_inline(icon, 14, THEME['text_muted'])}{pillar}</div>
          <h2 class="cdmo-page-title">{title}</h2>
          <p class="cdmo-page-subtitle">{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def feature_card(
    key: str,
    title: str,
    description: str,
    icon: str,
    active: bool = False,
) -> bool:
    """Render a clickable feature card. Returns True if clicked this turn.

    Uses a hidden Streamlit button absolutely positioned over the visible card
    so the whole card area is clickable.
    """
    cls = "cdmo-feature-card active" if active else "cdmo-feature-card"
    st.markdown(
        f'<div class="cdmo-card-wrapper" id="wrapper-{key}">',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="{cls}" id="card-{key}">
          <div class="cdmo-feature-icon">{bioicon(icon, 28, THEME['primary'])}</div>
          <div class="cdmo-feature-title">{title}</div>
          <div class="cdmo-feature-desc">{description}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    clicked = st.button(
        title,
        key=f"nav_card_{key}",
        help=None,
        width="stretch",
    )
    st.markdown("</div>", unsafe_allow_html=True)
    return clicked


def stepper(steps: list[str], current_index: int) -> None:
    """Render a horizontal stepper with the current step highlighted.

    Steps collapse gracefully on narrow viewports: labels hide on small screens
    and only the icon/number remains.
    """
    html_steps = []
    for i, label in enumerate(steps):
        if i < current_index:
            cls = "cdmo-step completed"
            num = f'<div class="cdmo-step-icon cdmo-step-check">{_BIOICONS["check"]}</div>'
            label_html = f'<span class="cdmo-step-label">{label}</span>'
        elif i == current_index:
            cls = "cdmo-step active"
            num = f'<div class="cdmo-step-number" style="background:{THEME["primary"]};color:#fff;border-color:{THEME["primary"]};">{i+1}</div>'
            label_html = f'<span class="cdmo-step-label">{label}</span>'
        else:
            cls = "cdmo-step"
            num = f'<div class="cdmo-step-number">{i+1}</div>'
            label_html = f'<span class="cdmo-step-label">{label}</span>'
        html_steps.append(f'<div class="{cls}">{num}{label_html}</div>')
        if i < len(steps) - 1:
            html_steps.append('<div class="cdmo-step-divider"></div>')
    st.markdown(
        f'<div class="cdmo-stepper">{ "".join(html_steps) }</div>',
        unsafe_allow_html=True,
    )


def mock_data_badge(use_mock: bool = True) -> None:
    """Render a persistent mock-data indicator badge."""
    if not use_mock:
        return
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
          <span class="cdmo-mock-badge">{bioicon_inline('warning', 12, '#8c6b00')}Representative seed data — not live API</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_tile(label: str, value: str | int | float, help_text: str = "") -> None:
    """Render a monochrome metric tile."""
    st.markdown(
        f"""
        <div class="cdmo-metric" title="{help_text}">
          <div class="cdmo-metric-value">{value}</div>
          <div class="cdmo-metric-label">{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# anime.js wrapper
# ---------------------------------------------------------------------------
def anime_entrance(selector: str = ".cdmo-feature-card", duration: int = 600, effect: str = "slideUp") -> None:
    """Trigger a subtle fade/slide entrance animation via anime.js.

    `effect` can be 'slideUp' (default) or 'fadeIn'.
    """
    if effect == "fadeIn":
        transform_js = ""
    else:
        transform_js = "translateY: [12, 0],"
    script = f"""
    <script src="https://cdnjs.cloudflare.com/ajax/libs/animejs/3.2.1/anime.min.js"></script>
    <script>
      document.addEventListener('DOMContentLoaded', function() {{
        anime({{
          targets: '{selector}',
          opacity: [0, 1],
          {transform_js}
          easing: 'easeOutQuad',
          duration: {duration},
          delay: anime.stagger(80)
        }});
      }});
    </script>
    """
    html(script, height=0)


def anime_pulse(selector: str = ".cdmo-metric-value") -> None:
    """Trigger a subtle pulse on metric values after load."""
    script = f"""
    <script src="https://cdnjs.cloudflare.com/ajax/libs/animejs/3.2.1/anime.min.js"></script>
    <script>
      document.addEventListener('DOMContentLoaded', function() {{
        anime({{
          targets: '{selector}',
          scale: [1, 1.04, 1],
          easing: 'easeInOutQuad',
          duration: 600,
          delay: 300
        }});
      }});
    </script>
    """
    html(script, height=0)


# ---------------------------------------------------------------------------
# Plotly chart helpers with scientific annotations
# ---------------------------------------------------------------------------
def _scientific_layout() -> dict[str, Any]:
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "colorway": CHART_COLORWAY,
        "font": {"family": "Inter, -apple-system, BlinkMacSystemFont, sans-serif", "color": THEME["text"], "size": 11},
        "margin": {"l": 48, "r": 16, "t": 48, "b": 64},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    }


def scientific_bar_chart(
    df: Any,
    x: str,
    y: str,
    title: str,
    y_label: str,
    source: str,
    stat_note: str = "",
    color: str = BLUE,
    hover_template: str = "%{x}<br>%{y:.1f}<extra></extra>",
) -> go.Figure:
    """Create a publication-style horizontal or vertical bar chart."""
    fig = go.Figure(
        data=go.Bar(
            x=df[x],
            y=df[y],
            marker_color=color,
            hovertemplate=hover_template,
        )
    )
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis_title=x.replace("_", " ").title(),
        yaxis_title=y_label,
        **_scientific_layout(),
    )
    fig.add_annotation(
        text=f"Source: {source}. {stat_note}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": THEME["text_muted"]},
        align="left",
    )
    return fig


def scientific_count_bar_chart(
    counts: dict[str, int],
    title: str = "",
    source: str = "",
    unit: str = "candidates",
    sort: str = "descending",
    color: str = BLUE,
) -> go.Figure:
    """Horizontal ranked bar chart for a categorical count distribution.

    One bar per category on a shared count axis, with the count and share of
    total annotated inline and surfaced on hover. Use for distributions (tier
    counts, modality mix) where comparing magnitudes across categories matters.

    A concentric-ring encoding is wrong for this data: each ring sits at a
    different radius so arc lengths are not perceptually comparable across
    categories, and the hover reduces to a meaningless fraction ("5.0/20").

    ``sort`` controls category order: ``"descending"`` (default) or
    ``"ascending"`` sort by count; ``"none"`` preserves the caller's insertion
    order — use that for ordinal categories like commercial-fit tiers where the
    order itself carries meaning and should not be reshuffled by magnitude.
    """
    items = list(counts.items())
    if sort == "descending":
        items.sort(key=lambda kv: kv[1], reverse=True)
    elif sort == "ascending":
        items.sort(key=lambda kv: kv[1])
    # sort == "none": keep insertion order.
    labels = [k for k, _ in items]
    vals = [int(v) for _, v in items]
    total = sum(vals) or 1
    shares = [v / total for v in vals]

    fig = go.Figure(
        go.Bar(
            y=labels,
            x=vals,
            orientation="h",
            marker_color=color,
            customdata=shares,
            text=[f"{v}  ·  {s:.0%}" for v, s in zip(vals, shares)],
            textposition="outside",
            textfont={"size": 10, "color": THEME["text_secondary"]},
            hovertemplate=(
                f"<b>%{{y}}</b><br>%{{x}} {unit} (%{{customdata:.0%}} of {total})"
                f"<extra></extra>"
            ),
            showlegend=False,
        )
    )
    x_max = max(vals) if vals else 1
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis={"title": "Count", "range": [0, x_max * 1.25 + 1e-6], "dtick": max(1, x_max // 5)},
        yaxis={"categoryorder": "array", "categoryarray": list(reversed(labels)),
               "title": None, "tickfont": {"size": 11, "color": THEME["text"]}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 11},
        margin={"l": 110, "r": 48, "t": 48, "b": 40},
        height=max(140, len(labels) * 34 + 64),
        annotations=[
            {"x": 0, "y": -0.16, "xref": "paper", "yref": "paper",
             "text": f"Source: {source}".strip(), "showarrow": False,
             "font": {"size": 9, "color": THEME["text_muted"]}, "align": "left"},
        ],
    )
    return fig


def scientific_scatter(
    df: Any,
    x: str,
    y: str,
    title: str,
    x_label: str,
    y_label: str,
    source: str,
    stat_note: str = "",
    color_col: str | None = None,
    size_col: str | list | None = None,
    hover_name: str | None = None,
) -> go.Figure:
    """Create a publication-style scatter plot.

    ``size_col`` may be a column name (``str``), an explicit sequence of
    per-point sizes, or ``None`` to fall back to a uniform marker size.
    """
    if size_col is None:
        marker_size: Any = 10
    elif isinstance(size_col, str):
        marker_size = df[size_col]
    else:
        marker_size = size_col
    if color_col is None:
        marker_color: Any = BLUE
    else:
        marker_color = df[color_col]
    fig = go.Figure(
        data=go.Scatter(
            x=df[x],
            y=df[y],
            mode="markers",
            marker={
                "size": marker_size,
                "color": marker_color,
                "colorscale": CONTINUOUS_SCALE,
                "showscale": bool(color_col),
                "colorbar": {"title": color_col.replace("_", " ").title() if color_col else ""},
                "line": {"width": 1, "color": WHITE},
            },
            text=df[hover_name] if hover_name else None,
            hovertemplate=(
                "%{text}<br>" + f"{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>"
                if hover_name
                else f"{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis_title=x_label,
        yaxis_title=y_label,
        **_scientific_layout(),
    )
    fig.add_annotation(
        text=f"Source: {source}. {stat_note}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": THEME["text_muted"]},
        align="left",
    )
    return fig


def scientific_box_or_strip(
    df: Any,
    x: str,
    y: str,
    title: str,
    y_label: str,
    source: str,
    stat_note: str = "",
) -> go.Figure:
    """Create a publication-style box + strip overlay."""
    fig = go.Figure()
    for val in sorted(df[x].unique()):
        subset = df[df[x] == val]
        fig.add_trace(
            go.Box(
                y=subset[y],
                name=str(val),
                boxpoints="all",
                jitter=0.3,
                pointpos=-1.8,
                marker_color=BLUE,
                line_color=MID_GREY,
                fillcolor="rgba(0,114,178,0.06)",
                hovertemplate=f"{x}: %{{x}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
            )
        )
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis_title=x.replace("_", " ").title(),
        yaxis_title=y_label,
        **_scientific_layout(),
    )
    fig.add_annotation(
        text=f"Source: {source}. {stat_note}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": THEME["text_muted"]},
        align="left",
    )
    return fig


def render_chart(fig: go.Figure, caption: str = "", key: str | None = None) -> None:
    """Display a Plotly chart with an optional scientific caption.

    ``key`` is required when the same chart shape is rendered many times in one
    run (e.g. the per-card "Pillar profile" bullet chart): Streamlit derives an
    element id from the figure spec, so identical figures collide with
    ``StreamlitDuplicateElementId``. A unique key disambiguates them.
    """
    kwargs = {"use_container_width": True, "config": {"displayModeBar": False}}
    if key is not None:
        kwargs["key"] = key
    st.plotly_chart(fig, **kwargs)
    if caption:
        st.markdown(f'<div class="cdmo-chart-caption">{caption}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Small convenience components
# ---------------------------------------------------------------------------
def tier_badge(tier: str, tiers: dict[str, str] | str | None = None) -> str:
    """Return a colored badge for a tier or risk label.

    `tiers` can be:
      - a dict mapping label -> CSS color or semantic name
        (success/warning/danger/info)
      - a single semantic/color string applied to this badge
    Defaults to the Okabe-Ito scientific palette.
    """
    color = tier_color(tier)
    if isinstance(tiers, dict):
        mapped = tiers.get(tier, tier)
        color = tier_color(mapped)
    elif isinstance(tiers, str):
        color = tier_color(tiers)
    return f'<span style="padding:2px 6px; border-radius:3px; background:{color}; color:#fff; font-size:10px; font-weight:800; text-transform:uppercase;">{tier}</span>'


def inline_warning(text: str) -> str:
    return f"""
    <div style="padding:8px 10px; background:#ffebe6; border-left:3px solid {VERMILION}; margin-bottom:8px; font-size:12px; color:#8a2b0a;">
      {bioicon_inline('warning', 14, VERMILION)}{text}
    </div>
    """


def inline_info(text: str) -> str:
    return f"""
    <div style="padding:8px 10px; background:{THEME['surface_subtle']}; border-left:3px solid {MID_GREY}; margin-bottom:8px; font-size:12px; color:{DARK_GREY};">
      {bioicon_inline('info', 14, MID_GREY)}{text}
    </div>
    """


# ---------------------------------------------------------------------------
# Extended scientific chart vocabulary
# ---------------------------------------------------------------------------

def _score_color(value: float, target: float = 80.0) -> str:
    """Return a semantic color for a 0-100 score against a target."""
    if value >= target:
        return BLUISH_GREEN
    if value >= target / 2:
        return ORANGE
    return VERMILION


def scientific_bullet_chart(
    values: dict[str, float],
    target: float = 80.0,
    max_value: float = 100.0,
    title: str = "",
    source: str = "",
) -> go.Figure:
    """Horizontal bullet bars for one or more 0-max_value metrics.

    Each row shows a faint background track, a colored bar to the value, and a
    vertical target marker.
    """
    labels = list(values.keys())
    vals = list(values.values())
    colors = [_score_color(v, target) for v in vals]
    fig = go.Figure()

    # Background tracks
    fig.add_trace(
        go.Bar(
            y=labels,
            x=[max_value] * len(labels),
            orientation="h",
            marker_color=MID_GREY,
            opacity=0.15,
            hoverinfo="skip",
            showlegend=False,
        )
    )
    # Value bars
    fig.add_trace(
        go.Bar(
            y=labels,
            x=vals,
            orientation="h",
            marker_color=colors,
            text=[f"{v:.0f}" for v in vals],
            textposition="inside",
            textfont={"color": WHITE, "size": 11, "weight": 700},
            hovertemplate="%{y}: %{x:.1f}<extra></extra>",
            showlegend=False,
        )
    )
    # Target markers as vertical lines
    for i, label in enumerate(labels):
        fig.add_vline(
            x=target,
            line={"color": DARK_GREY, "width": 1, "dash": "dot"},
            opacity=0.7,
        )

    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis={"range": [0, max_value], "title": None, "dtick": max_value / 5},
        yaxis={"autorange": "reversed", "title": None},
        barmode="overlay",
        height=max(180, len(labels) * 36 + 80),
        margin={"l": 120, "r": 16, "t": 48, "b": 48},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 11},
        annotations=[
            {
                "x": 0,
                "y": -0.12,
                "xref": "paper",
                "yref": "paper",
                "text": f"Source: {source}. Target line = {target:.0f}.".strip(),
                "showarrow": False,
                "font": {"size": 9, "color": THEME["text_muted"]},
                "align": "left",
            }
        ],
    )
    return fig


def scientific_nested_ring(
    values: dict[str, float],
    max_value: float = 100.0,
    title: str = "",
    source: str = "",
    value_labels: dict[str, str] | None = None,
) -> go.Figure:
    """Nested multi-ring radial bar chart.

    Each category gets a concentric ring; the filled arc length is proportional
    to value / max_value.  Good for 3-6 comparable dimensions (4-pillar score
    profile, customer-fit dimensions, monograph coverage).

    ``value_labels`` optionally maps each category to a human-readable status
    (e.g. ``{"IP 2026": "Available", "Ph. Eur.": "Not available"}``). When
    supplied, the legend and hover tooltip show that status instead of a raw
    number — use it for categorical/binary encodings where ``"1.0/1"`` would be
    meaningless. An empty (zero-value) category then renders as a clearly
    visible empty track carrying the status, rather than a near-invisible
    sliver. The default numeric behaviour is unchanged for 0–100 score callers.
    """
    labels = list(values.keys())
    vals = list(values.values())
    n = len(labels)
    palette = CHART_COLORWAY[:n]
    categorical = value_labels is not None
    fig = go.Figure()

    for i, (label, value) in enumerate(zip(labels, vals)):
        frac = value / max_value if max_value else 0
        # Ring radius increases outward; ring width ~ 0.18
        inner = 0.2 + i * 0.22
        outer = inner + 0.18
        theta_end = frac * 360
        color = palette[i % len(palette)]
        display = value_labels.get(label, "") if value_labels else None

        if categorical:
            legend_name = f"{label}: {display}"
            hover = f"{label}: {display}<extra></extra>"
        else:
            legend_name = f"{label}: {value:.0f}"
            hover = f"{label}: {value:.1f}/{max_value:.0f}<extra></extra>"

        if categorical and value == 0:
            # Empty category: the visible track carries the status label + hover
            # so the crosshair is informative and the legend still lists it. No
            # filled arc is drawn (avoids a misleading sliver at 0°).
            fig.add_trace(
                go.Barpolar(
                    r=[outer],
                    theta=[360],
                    width=[outer - inner],
                    base=[inner],
                    marker_color=MID_GREY,
                    opacity=0.35,
                    name=legend_name,
                    hovertemplate=hover,
                    showlegend=True,
                )
            )
            continue

        # Background arc (unfilled portion). Fainter in numeric mode; in
        # categorical mode the non-zero category still gets a subtle track.
        fig.add_trace(
            go.Barpolar(
                r=[outer],
                theta=[360],
                width=[outer - inner],
                base=[inner],
                marker_color=MID_GREY,
                opacity=0.30 if categorical else 0.12,
                hoverinfo="skip",
                showlegend=False,
            )
        )
        # Filled arc
        fig.add_trace(
            go.Barpolar(
                r=[outer],
                theta=[theta_end / 2],  # center the bar at half the arc
                width=[outer - inner],
                base=[inner],
                marker_color=color,
                name=legend_name,
                hovertemplate=hover,
                showlegend=True,
            )
        )

    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0.5},
        polar={
            "radialaxis": {"visible": False, "range": [0, 1.0]},
            "angularaxis": {"visible": False, "rotation": 90, "direction": "clockwise"},
            "bgcolor": "rgba(0,0,0,0)",
        },
        showlegend=True,
        legend={"orientation": "h", "yanchor": "top", "y": -0.12, "xanchor": "center", "x": 0.5, "font": {"size": 10}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 11},
        margin={"l": 32, "r": 32, "t": 56, "b": 56},
        height=360,
        annotations=[
            {
                "x": 0.5,
                "y": -0.16,
                "xref": "paper",
                "yref": "paper",
                "text": f"Source: {source}".strip(),
                "showarrow": False,
                "font": {"size": 9, "color": THEME["text_muted"]},
                "align": "center",
            }
        ],
    )
    return fig


def scientific_gauge(
    value: float,
    title: str = "",
    max_value: float = 100.0,
    source: str = "",
) -> go.Figure:
    """Half-ring gauge for a single headline score."""
    color = _score_color(value, target=max_value * 0.8)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"font": {"size": 28, "color": THEME["text"], "weight": 700}},
            gauge={
                "axis": {"range": [0, max_value], "tickwidth": 1, "tickcolor": THEME["border_strong"]},
                "bar": {"color": color, "thickness": 0.75},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, max_value * 0.5], "color": "rgba(213,94,0,0.08)"},
                    {"range": [max_value * 0.5, max_value * 0.8], "color": "rgba(230,159,0,0.08)"},
                    {"range": [max_value * 0.8, max_value], "color": "rgba(0,158,115,0.08)"},
                ],
                "threshold": {
                    "line": {"color": DARK_GREY, "width": 2},
                    "thickness": 0.8,
                    "value": max_value * 0.8,
                },
            },
        )
    )
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0.5},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 11},
        margin={"l": 24, "r": 24, "t": 48, "b": 24},
        height=240,
        annotations=[
            {
                "x": 0.5,
                "y": -0.08,
                "xref": "paper",
                "yref": "paper",
                "text": f"Source: {source}".strip(),
                "showarrow": False,
                "font": {"size": 9, "color": THEME["text_muted"]},
                "align": "center",
            }
        ],
    )
    return fig


def scientific_status_dot_chart(
    items: dict[str, bool],
    title: str = "",
    source: str = "",
    on_label: str = "Available",
    off_label: str = "Not available",
    detail: dict[str, str] | None = None,
) -> go.Figure:
    """Horizontal boolean status dot chart.

    One row per category; a filled dot marks the ``on`` state and a hollow dot
    the ``off`` state, with the status word shown inline next to the dot. Use
    for binary categorical availability (e.g. pharmacopoeia monographs) where a
    ring chart's quantitative arc-length encoding would be misleading — here
    every category is either present or absent, with no magnitude to encode.

    ``detail`` optionally maps each category to a longer text snippet shown only
    on hover, so the crosshair carries information the static chart cannot
    (e.g. the monograph description) instead of just repeating the status word.
    """
    labels = list(items.keys())
    states = list(items.values())
    detail = detail or {}
    on_count = sum(1 for s in states if s)
    subtitle = f"{on_count} of {len(labels)} {on_label.lower()}"

    fig = go.Figure()
    # Add traces in natural order; the explicit categoryarray below fixes the
    # vertical order (first category at the top) deterministically.
    for label, state in zip(labels, states):
        word = on_label if state else off_label
        snippet = detail.get(label, "")
        if len(snippet) > 200:
            snippet = snippet[:197].rstrip() + "…"
        hover = f"<b>{label}</b><br>{word}"
        if snippet:
            hover += f"<br><br>{snippet}"
        hover += "<extra></extra>"
        fig.add_trace(
            go.Scatter(
                x=[1],
                y=[label],
                mode="markers+text",
                marker=(
                    {"symbol": "circle", "size": 16, "color": BLUISH_GREEN,
                     "line": {"width": 1, "color": WHITE}}
                    if state
                    else {"symbol": "circle-open", "size": 16, "color": MID_GREY,
                          "line": {"width": 2, "color": MID_GREY}}
                ),
                text=[word],
                textposition="middle right",
                textfont={"size": 11, "color": THEME["text"] if state else THEME["text_muted"]},
                hovertemplate=hover,
                showlegend=False,
            )
        )

    fig.update_layout(
        title={"text": f"{title}  <span style='font-size:10px;color:{THEME['text_muted']}'>"
                        f"{subtitle}</span>",
              "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis={"visible": False, "range": [0.85, 1.35], "fixedrange": True},
        yaxis={"visible": True, "showgrid": False, "showline": False, "zeroline": False,
               "categoryorder": "array", "categoryarray": list(reversed(labels)),
               "tickfont": {"size": 11, "color": THEME["text"]}, "fixedrange": True},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 11},
        margin={"l": 96, "r": 24, "t": 48, "b": 8},
        height=40 * max(len(labels), 1) + 64,
        hovermode="closest",
        hoverlabel={"bgcolor": THEME["surface"], "font": {"size": 11, "color": THEME["text"]},
                    "bordercolor": THEME["border"]},
        annotations=[
            {"x": 0, "y": -0.18, "xref": "paper", "yref": "paper",
             "text": f"Source: {source}".strip(), "showarrow": False,
             "font": {"size": 9, "color": THEME["text_muted"]}, "align": "left"},
        ],
    )
    return fig


def scientific_quadrant_scatter(
    df: Any,
    x: str,
    y: str,
    color_col: str,
    size_col: str,
    x_med: float,
    y_med: float,
    x_label: str,
    y_label: str,
    title: str,
    source: str,
    hover_name: str | None = None,
) -> go.Figure:
    """Scatter plot with median reference lines and quadrant labels.

    Useful for portfolio demand vs. plant fit and patent attractiveness.
    """
    colors = df[color_col] if color_col in df.columns else BLUE
    sizes = df[size_col] if size_col in df.columns else 10
    hover = df[hover_name] if hover_name and hover_name in df.columns else None

    fig = go.Figure(
        go.Scatter(
            x=df[x],
            y=df[y],
            mode="markers",
            marker={
                "size": sizes,
                "color": colors,
                "colorscale": CONTINUOUS_SCALE,
                "showscale": bool(color_col in df.columns),
                "colorbar": {"title": color_col.replace("_", " ").title() if color_col in df.columns else ""},
                "line": {"width": 1, "color": WHITE},
            },
            text=hover,
            hovertemplate=(
                f"%{{text}}<br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>"
                if hover is not None
                else f"{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>"
            ),
        )
    )
    # Reference lines
    fig.add_vline(x=x_med, line={"color": MID_GREY, "width": 1, "dash": "dash"})
    fig.add_hline(y=y_med, line={"color": MID_GREY, "width": 1, "dash": "dash"})

    # Quadrant labels
    x_max = df[x].max()
    x_min = df[x].min()
    y_max = df[y].max()
    y_min = df[y].min()
    x_pad = (x_max - x_min) * 0.03 if x_max != x_min else 1
    y_pad = (y_max - y_min) * 0.03 if y_max != y_min else 1
    annotations = [
        {"x": x_max - x_pad, "y": y_max - y_pad, "text": "High fit / High demand", "align": "right", "valign": "top"},
        {"x": x_min + x_pad, "y": y_max - y_pad, "text": "Low fit / High demand", "align": "left", "valign": "top"},
        {"x": x_max - x_pad, "y": y_min + y_pad, "text": "High fit / Low demand", "align": "right", "valign": "bottom"},
        {"x": x_min + x_pad, "y": y_min + y_pad, "text": "Low fit / Low demand", "align": "left", "valign": "bottom"},
    ]
    for a in annotations:
        fig.add_annotation(
            x=a["x"],
            y=a["y"],
            text=a["text"],
            showarrow=False,
            font={"size": 9, "color": THEME["text_muted"]},
            align=a["align"],
            valign=a["valign"],
        )

    base_layout = _scientific_layout()
    base_layout["margin"] = {"l": 56, "r": 16, "t": 56, "b": 64}
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis_title=x_label,
        yaxis_title=y_label,
        **base_layout,
    )
    fig.add_annotation(
        text=f"Source: {source}. Median reference lines shown.".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": THEME["text_muted"]},
        align="left",
    )
    return fig


def scientific_bubble_chart(
    df: Any,
    x: str,
    y: str,
    size_col: str,
    color_col: str,
    x_label: str,
    y_label: str,
    title: str,
    source: str,
    hover_name: str | None = None,
    reference_bands: list[tuple[float, float]] | None = None,
) -> go.Figure:
    """Publication-style bubble chart for multi-factor attractiveness.

    Bubble size encodes a third quantitative variable; color encodes a
    categorical cluster.  Optional vertical reference bands can highlight
    decision windows (e.g. the 2–5 year LOE sweet spot).
    """
    categories = sorted(df[color_col].unique()) if color_col in df.columns else []
    color_map = {cat: CHART_COLORWAY[i % len(CHART_COLORWAY)] for i, cat in enumerate(categories)}

    fig = go.Figure()
    for cat in categories:
        sub = df[df[color_col] == cat]
        hover = sub[hover_name] if hover_name and hover_name in sub.columns else None
        fig.add_trace(
            go.Scatter(
                x=sub[x],
                y=sub[y],
                mode="markers",
                name=str(cat),
                marker={
                    "size": sub[size_col] if size_col in sub.columns else 10,
                    "sizemode": "area",
                    "sizeref": 2.0 * max(df[size_col].max() if size_col in df.columns else 10, 1) / (40**2),
                    "color": color_map.get(cat, BLUE),
                    "line": {"width": 1, "color": WHITE},
                },
                text=hover,
                hovertemplate=(
                    f"%{{text}}<br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y}}<br>Size: %{{marker.size:.1f}}<extra>%{{fullData.name}}</extra>"
                    if hover is not None
                    else f"{x_label}: %{{x:.1f}}<br>{y_label}: %{{y}}<br>Size: %{{marker.size:.1f}}<extra>%{{fullData.name}}</extra>"
                ),
            )
        )

    for low, high in (reference_bands or []):
        fig.add_vrect(
            x0=low,
            x1=high,
            fillcolor=BLUISH_GREEN,
            opacity=0.08,
            line_width=0,
        )
        fig.add_vline(x=low, line={"color": MID_GREY, "width": 1, "dash": "dash"})
        fig.add_vline(x=high, line={"color": MID_GREY, "width": 1, "dash": "dash"})

    base_layout = _scientific_layout()
    base_layout["margin"] = {"l": 56, "r": 16, "t": 56, "b": 64}
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis_title=x_label,
        yaxis_title=y_label,
        **base_layout,
    )
    band_note = " Shaded band = decision window." if reference_bands else ""
    fig.add_annotation(
        text=f"Source: {source}.{band_note}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": THEME["text_muted"]},
        align="left",
    )
    return fig


def scientific_stacked_bar(
    df: Any,
    label_col: str,
    segment_cols: list[str],
    title: str,
    source: str,
    palette: list[str] | None = None,
    normalize: bool = False,
) -> go.Figure:
    """Horizontal stacked bar chart for decomposing a score or count.

    If normalize=True, each bar is scaled to 100 so the composition is visible.
    """
    palette = palette or CHART_COLORWAY
    fig = go.Figure()
    labels = df[label_col].tolist()
    # Limit to top 15 labels for readability
    if len(labels) > 15:
        labels = labels[:15]
        df = df.head(15)

    for idx, col in enumerate(segment_cols):
        fig.add_trace(
            go.Bar(
                name=col.replace("_", " ").title(),
                y=labels,
                x=df[col].tolist(),
                orientation="h",
                marker_color=palette[idx % len(palette)],
                hovertemplate=f"{col.replace('_', ' ').title()}: %{{x:.1f}}<extra></extra>",
            )
        )

    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis_title="Score contribution" + (" (normalized %)" if normalize else ""),
        yaxis_title=None,
        barmode="stack",
        height=max(240, len(labels) * 26 + 80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 11},
        margin={"l": 120, "r": 16, "t": 56, "b": 64},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        yaxis={"autorange": "reversed"},
    )
    fig.add_annotation(
        text=f"Source: {source}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": THEME["text_muted"]},
        align="left",
    )
    return fig


def scientific_gap_matrix(
    required: list[str],
    available: set[str],
    sections: dict[str, list[str]],
    title: str = "",
    source: str = "",
) -> go.Figure:
    """Dot matrix: rows = capabilities, columns = Required / Available.

    Filled dot = present, empty dot = missing.  Rows are grouped by section.
    """
    y_labels: list[str] = []
    x_positions: list[int] = []
    y_positions: list[int] = []
    colors: list[str] = []
    symbols: list[str] = []
    hover_texts: list[str] = []

    row_idx = 0
    for section_title, caps in sections.items():
        section_caps = [c for c in caps if c in required]
        if not section_caps:
            continue
        for cap in section_caps:
            is_required = cap in required
            is_available = cap in available
            for col_idx, col_name in enumerate(["Required", "Available"]):
                present = (col_name == "Required" and is_required) or (col_name == "Available" and is_available)
                y_labels.append(f"[{section_title}] {cap.replace('_', ' ').title()}")
                x_positions.append(col_idx)
                y_positions.append(row_idx)
                colors.append(BLUISH_GREEN if present else VERMILION)
                symbols.append("circle" if present else "circle-open")
                hover_texts.append(f"{cap.replace('_', ' ').title()} — {col_name}: {'yes' if present else 'no'}")
            row_idx += 1

    fig = go.Figure(
        go.Scatter(
            x=x_positions,
            y=y_positions,
            mode="markers",
            marker={
                "size": 14,
                "color": colors,
                "symbol": symbols,
                "line": {"width": 1.5, "color": THEME["text_muted"]},
            },
            text=hover_texts,
            hovertemplate="%{text}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis={"tickmode": "array", "tickvals": [0, 1], "ticktext": ["Required", "Available"], "range": [-0.5, 1.5]},
        yaxis={"tickmode": "array", "tickvals": list(range(len(y_labels) // 2)), "ticktext": [y_labels[i * 2] for i in range(len(y_labels) // 2)], "autorange": "reversed"},
        height=max(200, len(y_labels) // 2 * 24 + 80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 10},
        margin={"l": 220, "r": 16, "t": 56, "b": 48},
        annotations=[
            {
                "x": 0,
                "y": -0.12,
                "xref": "paper",
                "yref": "paper",
                "text": f"Source: {source}".strip(),
                "showarrow": False,
                "font": {"size": 9, "color": THEME["text_muted"]},
                "align": "left",
            }
        ],
    )
    return fig


def scientific_phase_gantt(
    phases: list[dict[str, Any]],
    title: str = "",
    source: str = "",
) -> go.Figure:
    """Horizontal Gantt of roadmap phase durations."""
    labels = [p.get("title", f"Phase {i + 1}") for i, p in enumerate(phases)]
    durations = [p.get("estimated_duration_months", 0) for p in phases]
    starts = []
    cumulative = 0
    for d in durations:
        starts.append(cumulative)
        cumulative += d

    fig = go.Figure()
    for label, start, duration in zip(labels, starts, durations):
        fig.add_trace(
            go.Bar(
                y=[label],
                x=[duration],
                base=[start],
                orientation="h",
                marker_color=BLUE,
                hovertemplate=f"{label}<br>Start: %{{base}} mo<br>Duration: %{{x}} mo<extra></extra>",
                showlegend=False,
            )
        )

    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": THEME["text"]}, "x": 0, "xanchor": "left"},
        xaxis_title="Months from start",
        yaxis_title=None,
        barmode="stack",
        height=max(200, len(labels) * 32 + 80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": THEME["text"], "size": 11},
        margin={"l": 160, "r": 16, "t": 56, "b": 64},
        yaxis={"autorange": "reversed"},
    )
    fig.add_annotation(
        text=f"Source: {source}. Total duration = {cumulative} months.".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": THEME["text_muted"]},
        align="left",
    )
    return fig


# ---------------------------------------------------------------------------
# GMP pillar contextualization
# ---------------------------------------------------------------------------
# Monochrome geometric symbols keep the GMP pillar cards serious and avoid
# both emoji and Streamlit's unsafe_allow_html SVG sanitizer issues.
_PILLAR_SYMBOLS = {
    "aseptic": "◆",
    "hpapi": "▲",
    "cleaning": "■",
    "lifecycle": "●",
    "packaging": "□",
}


def render_gmp_pillars(
    pillars: list[dict[str, Any]],
    plant_capabilities: set[str] | None = None,
    show_title: bool = True,
) -> str:
    """Render a compact GMP pillar card as HTML for Streamlit markdown.

    All styling lives in the ``.gmp-*`` classes in ``SCIENTIFIC_CSS`` so the
    visual vocabulary has a single source of truth; this function only emits
    semantic structure and the dynamic status text/labels.

    Args:
        pillars: list of GmpPillar dicts from the API (must contain pillar_id,
                 title, applies, rationale, key_controls, required_capabilities).
        plant_capabilities: optional set of lower-case capability tokens for the
                            selected plant; used to color-code readiness.
        show_title: whether to include the section eyebrow/title.

    Returns:
        HTML string to pass to st.markdown(..., unsafe_allow_html=True).
    """
    if not pillars:
        return ""

    applicable = [p for p in pillars if p.get("applies")]
    if not applicable:
        return ""

    parts: list[str] = []
    if show_title:
        # Section eyebrow — a section title, not a warning state, so no icon.
        parts.append(
            '<div class="cdmo-section-title" style="margin-bottom:8px;">'
            "Core GMP Methodological Pillars</div>"
        )

    # Bucket each applicable pillar by readiness against the plant.
    gap_pillars: list[dict[str, Any]] = []
    partial_pillars: list[dict[str, Any]] = []
    ready_pillars: list[dict[str, Any]] = []
    for p in applicable:
        required = set((c or "").lower() for c in (p.get("required_capabilities") or []))
        if plant_capabilities is not None and required:
            matched = required & plant_capabilities
            readiness = round(100.0 * len(matched) / len(required))
        else:
            matched = required
            readiness = 100
        missing = sorted(required - plant_capabilities) if plant_capabilities is not None else []
        bucket = {"pillar": p, "readiness": readiness, "matched": matched, "missing": missing}
        if readiness == 0:
            gap_pillars.append(bucket)
        elif readiness < 80:
            partial_pillars.append(bucket)
        else:
            ready_pillars.append(bucket)

    # ---- helpers ---------------------------------------------------------
    def _badge(readiness: int) -> tuple[str, str]:
        """Return (badge text, status class key) for a readiness percentage."""
        if readiness == 0:
            return "Gap", "danger"
        if readiness < 80:
            return f"{readiness}% match", "warning"
        return f"{readiness}% ready", "success"

    def _plural(n: int, word: str) -> str:
        return f"{n} {word}{'s' if n != 1 else ''}"

    def _chips(items, chip_cls: str, prefix: str = "") -> str:
        """Render a ``.gmp-chip-row`` of spans with the given class."""
        if not items:
            return ""
        inner = "".join(
            f'<span class="{chip_cls}">{prefix}{c}</span>' for c in items
        )
        return f'<div class="gmp-chip-row">{inner}</div>'

    def _missing_groups_html(buckets: list[dict[str, Any]]) -> str:
        groups = []
        for b in buckets:
            missing = b["missing"]
            if not missing:
                continue
            chips = "".join(
                f'<span class="gmp-missing-chip">missing: {c}</span>' for c in missing
            )
            groups.append(
                f'<div class="gmp-missing-group">'
                f'<div class="gmp-missing-group-label">{b["pillar"].get("title", "")}</div>'
                f'<div class="gmp-chip-row">{chips}</div>'
                f"</div>"
            )
        if not groups:
            return ""
        return f'<div class="gmp-missing-block">{"".join(groups)}</div>'

    def _summary_card(status: str, badge_text: str, body: str,
                      buckets: list[dict[str, Any]], detail_html: str = "") -> str:
        """One parameterized summary card for gap / partial / mixed states."""
        detail = f'<div class="gmp-detail">{detail_html}</div>' if detail_html else ""
        return (
            f'<div class="gmp-card gmp-card--summary">'
            f'<div class="gmp-card-header">'
            f'<div class="gmp-card-heading"><strong class="gmp-pillar-title">'
            f"GMP readiness gaps</strong></div>"
            f'<span class="gmp-badge gmp-badge--{status}">{badge_text}</span>'
            f"</div>"
            f'<div class="gmp-rationale">{body}</div>'
            f"{detail}"
            f'{_missing_groups_html(buckets)}'
            f"</div>"
        )

    def _pillar_card(bucket: dict[str, Any]) -> str:
        p = bucket["pillar"]
        pid = p.get("pillar_id", "")
        title = p.get("title", "")
        rationale = p.get("rationale", "")
        controls = p.get("key_controls") or []
        missing = bucket["missing"]
        badge_text, status = _badge(bucket["readiness"])
        icon = _PILLAR_SYMBOLS.get(pid, "●")

        controls_html = _chips(controls, "gmp-control-chip")
        if missing:
            missing_html = (
                f'<div class="gmp-missing-block">'
                f'<div class="gmp-missing-block-label">'
                f"Missing capabilities ({len(missing)}):</div>"
                + _chips(missing, "gmp-missing-chip", prefix="missing: ")
                + "</div>"
            )
        else:
            missing_html = ""

        return (
            f'<div class="gmp-card">'
            f'<div class="gmp-card-header">'
            f'<div class="gmp-card-heading">'
            f'<span class="gmp-pillar-icon">{icon}</span>'
            f'<strong class="gmp-pillar-title">{title}</strong>'
            f"</div>"
            f'<span class="gmp-badge gmp-badge--{status}">{badge_text}</span>'
            f"</div>"
            f'<div class="gmp-rationale">{rationale}</div>'
            f"{controls_html}"
            f"{missing_html}"
            f"</div>"
        )

    # ---- summary card for the appropriate permutation --------------------
    if gap_pillars and partial_pillars:
        gap_titles = [b["pillar"].get("title", "") for b in gap_pillars]
        partial_titles = [f"{b['pillar'].get('title', '')} ({b['readiness']}% match)" for b in partial_pillars]
        partial_verb = "is" if len(partial_pillars) == 1 else "are"
        body = (
            f"{_plural(len(gap_pillars), 'pillar')} are unsupported and "
            f"{_plural(len(partial_pillars), 'pillar')} {partial_verb} only partially matched. "
            "Typical for a development/pilot asset lacking commercial fill-finish, "
            "containment, or validation infrastructure."
        )
        lines = []
        if gap_titles:
            lines.append(f"<strong>Unsupported:</strong> {', '.join(gap_titles)}")
        if partial_titles:
            lines.append(f"<strong>Partial:</strong> {', '.join(partial_titles)}")
        parts.append(_summary_card("warning", "Mixed", body,
                                   gap_pillars + partial_pillars, "<br>".join(lines)))
    elif gap_pillars:
        titles = [b["pillar"].get("title", "") for b in gap_pillars]
        body = (
            f"{_plural(len(gap_pillars), 'GMP pillar')} not supported by this plant: "
            f"{', '.join(titles)}. Expected for a development/pilot asset where "
            "commercial fill-finish or containment is not installed."
        )
        parts.append(_summary_card("danger", "Gap", body, gap_pillars))
    elif partial_pillars:
        titles = [f"{b['pillar'].get('title', '')} ({b['readiness']}% match)" for b in partial_pillars]
        body = (
            f"{_plural(len(partial_pillars), 'pillar')} partially matched: {', '.join(titles)}. "
            "Additional capability investment is needed to reach commercial readiness."
        )
        parts.append(_summary_card("warning", "Partial", body, partial_pillars))

    # Detail cards are self-contained: they always show their own missing
    # capabilities (with a compact label) even when the summary already
    # displayed them grouped, so any single card reads on its own.
    for b in partial_pillars:
        parts.append(_pillar_card(b))
    for b in ready_pillars:
        parts.append(_pillar_card(b))

    return "".join(parts)
