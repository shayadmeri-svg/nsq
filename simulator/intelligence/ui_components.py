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


def bioicon(name: str, size: int = 24, color: str = "#0f172a") -> str:
    """Return a monochrome SVG icon as a raw HTML string."""
    svg = _BIOICONS.get(name, _BIOICONS["molecule"])
    return f"""
    <div class="bioicon" style="display:inline-flex; width:{size}px; height:{size}px; color:{color}; vertical-align:middle;">
      {svg}
    </div>
    """


def bioicon_inline(name: str, size: int = 20, color: str = "#0f172a", margin_right: int = 4) -> str:
    """Return a smaller inline icon suitable for labels and badges."""
    svg = _BIOICONS.get(name, _BIOICONS["molecule"])
    return f"""
    <span class="bioicon-inline" style="display:inline-flex; align-items:center; justify-content:center; width:{size}px; height:{size}px; color:{color}; flex: 0 0 {size}px; vertical-align:middle; margin-right:{margin_right}px;">
      {svg}
    </span>
    """


# ---------------------------------------------------------------------------
# Global theme + layout helpers
# ---------------------------------------------------------------------------
MONOCHROME_CSS = """
<style>
  .stApp { background-color: #f8fafc; }
  html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #0f172a;
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
    color: #64748b;
  }
  .cdmo-page-title {
    font-size: 22px;
    font-weight: 900;
    color: #0f172a;
    margin: 4px 0 0 0;
  }
  .cdmo-page-subtitle {
    font-size: 12px;
    color: #64748b;
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
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 16px;
    cursor: pointer;
    transition: border-color 0.2s, box-shadow 0.2s;
    height: 100%;
    pointer-events: none;
  }
  .cdmo-feature-card:hover {
    border-color: #94a3b8;
    box-shadow: 0 2px 8px rgba(15,23,42,0.05);
  }
  .cdmo-feature-card.active {
    border-color: #0f172a;
    box-shadow: 0 2px 8px rgba(15,23,42,0.08);
  }
  .cdmo-feature-icon {
    width: 28px;
    height: 28px;
    color: #0f172a;
    margin-bottom: 8px;
  }
  .cdmo-feature-title {
    font-size: 13px;
    font-weight: 800;
    color: #0f172a;
    margin: 0 0 4px 0;
  }
  .cdmo-feature-desc {
    font-size: 11px;
    color: #64748b;
    line-height: 1.4;
    margin: 0;
  }
  /* Metric tile */
  .cdmo-metric {
    text-align: center;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    padding: 12px;
    background: #ffffff;
  }
  .cdmo-metric-value {
    font-size: 28px;
    font-weight: 900;
    color: #0f172a;
  }
  .cdmo-metric-label {
    font-size: 10px;
    color: #64748b;
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
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 16px;
    gap: 6px;
    overflow-x: auto;
    scrollbar-width: thin;
  }
  .cdmo-stepper::-webkit-scrollbar { height: 4px; }
  .cdmo-stepper::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 2px; }
  .cdmo-step {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
    white-space: nowrap;
    flex: 0 0 auto;
  }
  .cdmo-step.active {
    color: #0f172a;
  }
  .cdmo-step.completed {
    color: #15803d;
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
    color: #15803d;
  }
  .cdmo-step-check { color: #15803d; }
  .cdmo-step-divider {
    flex: 0 0 auto;
    width: 16px;
    min-width: 16px;
    height: 1px;
    background: #e2e8f0;
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
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fde68a;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  /* Chart annotation */
  .cdmo-chart-caption {
    font-size: 10px;
    color: #64748b;
    margin-top: 4px;
  }
</style>
"""


def apply_global_theme() -> None:
    """Inject monochrome CSS and collapse the default sidebar."""
    st.markdown(MONOCHROME_CSS, unsafe_allow_html=True)
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
        <div style="padding-bottom: 12px; border-bottom: 1px solid #e2e8f0; margin-bottom: 16px;">
          <div class="cdmo-section-title">{bioicon_inline(icon, 14, '#64748b')}{pillar}</div>
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
          <div class="cdmo-feature-icon">{bioicon(icon, 28, '#0f172a')}</div>
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
        use_container_width=True,
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
            num = f'<div class="cdmo-step-number" style="background:#0f172a;color:#fff;border-color:#0f172a;">{i+1}</div>'
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
          <span class="cdmo-mock-badge">{bioicon_inline('warning', 12, '#92400e')}Representative seed data — not live API</span>
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
def _slate_layout() -> dict[str, Any]:
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Inter, -apple-system, BlinkMacSystemFont, sans-serif", "color": "#0f172a", "size": 11},
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
    color: str = "#0f172a",
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
        title={"text": title, "font": {"size": 14, "color": "#0f172a"}, "x": 0, "xanchor": "left"},
        xaxis_title=x.replace("_", " ").title(),
        yaxis_title=y_label,
        **_slate_layout(),
    )
    fig.add_annotation(
        text=f"Source: {source}. {stat_note}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": "#64748b"},
        align="left",
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
        marker_color: Any = "#0f172a"
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
                "colorscale": "Greys",
                "showscale": bool(color_col),
                "colorbar": {"title": color_col.replace("_", " ").title() if color_col else ""},
                "line": {"width": 1, "color": "#ffffff"},
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
        title={"text": title, "font": {"size": 14, "color": "#0f172a"}, "x": 0, "xanchor": "left"},
        xaxis_title=x_label,
        yaxis_title=y_label,
        **_slate_layout(),
    )
    fig.add_annotation(
        text=f"Source: {source}. {stat_note}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": "#64748b"},
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
                marker_color="#0f172a",
                line_color="#64748b",
                fillcolor="rgba(15,23,42,0.04)",
                hovertemplate=f"{x}: %{{x}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
            )
        )
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": "#0f172a"}, "x": 0, "xanchor": "left"},
        xaxis_title=x.replace("_", " ").title(),
        yaxis_title=y_label,
        **_slate_layout(),
    )
    fig.add_annotation(
        text=f"Source: {source}. {stat_note}".strip(),
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": "#64748b"},
        align="left",
    )
    return fig


def render_chart(fig: go.Figure, caption: str = "") -> None:
    """Display a Plotly chart with an optional scientific caption."""
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
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
    Defaults to the commercial-fit color palette.
    """
    palette = {
        "success": "#15803d",
        "core": "#0ea5e9",
        "adjacent": "#eab308",
        "stretch": "#ef4444",
        "strategic": "#15803d",
        "warning": "#eab308",
        "danger": "#ef4444",
        "info": "#64748b",
        "low": "#15803d",
        "medium": "#eab308",
        "high": "#ef4444",
    }
    color = palette.get(tier, "#64748b")
    if isinstance(tiers, dict):
        mapped = tiers.get(tier, tier)
        color = palette.get(mapped, mapped)
    elif isinstance(tiers, str):
        color = palette.get(tiers, tiers)
    return f"""
    <span style="padding:2px 6px; border-radius:3px; background:{color}; color:#fff; font-size:10px; font-weight:800; text-transform:uppercase;">
      {tier}
    </span>
    """


def inline_warning(text: str) -> str:
    return f"""
    <div style="padding:8px 10px; background:#fef2f2; border-left:3px solid #ef4444; margin-bottom:8px; font-size:12px; color:#991b1b;">
      {bioicon_inline('warning', 14, '#991b1b')}{text}
    </div>
    """


def inline_info(text: str) -> str:
    return f"""
    <div style="padding:8px 10px; background:#f8fafc; border-left:3px solid #64748b; margin-bottom:8px; font-size:12px; color:#475569;">
      {bioicon_inline('info', 14, '#475569')}{text}
    </div>
    """
