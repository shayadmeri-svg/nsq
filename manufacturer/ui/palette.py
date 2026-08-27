"""Colorblind-safe scientific palette for the manufacturer (Q-engine) app.

Okabe-Ito for all chart colorways and semantic accents (the de-facto
standard for accessible, publication-quality scientific figures), plus
the Figma's *neutral* surface/text/border tokens — which are plain greys
(#FFFFFF / #F5F5F5 / #1E1E1E / #757575 / #D9D9D9) and therefore already
compatible with the scientific tone.

The Figma's accent purples/pinks (#0D99FF / #9747FF / #FF24BD) are
deliberately NOT used here — the UI/UX tone rule makes the scientific
palette the color authority for /manufacturer, and the Figma the
layout/component-shape authority only. See the ui-ux-tone-guidelines and
figma-q-engine-design memories.

This file is fresh and small (not synced from simulator/) — it is the
manufacturer app's own palette. simulator/intelligence/palette.py stays
the source of truth for the simulator's colors.
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Okabe-Ito base colors (chart colorway + semantic accents)
# -----------------------------------------------------------------------------
ORANGE = "#E69F00"
SKY_BLUE = "#56B4E9"
BLUISH_GREEN = "#009E73"
YELLOW = "#F0E442"
BLUE = "#0072B2"
VERMILION = "#D55E00"
REDDISH_PURPLE = "#CC79A7"
GREY = "#999999"

# -----------------------------------------------------------------------------
# Neutral surface / text / border tokens (Figma neutrals — all grey)
# -----------------------------------------------------------------------------
WHITE = "#FFFFFF"
SURFACE_SUBTLE = "#F5F5F5"   # Figma secondary surface
TEXT = "#1E1E1E"             # Figma primary text
TEXT_SECONDARY = "#4A4A4A"
TEXT_MUTED = "#757575"       # Figma fill_97744796
BORDER = "#D9D9D9"           # Figma fill_fef61db7
BORDER_STRONG = "#B3B3B3"
PALE_GREY = "#F2F2F2"

# -----------------------------------------------------------------------------
# Theme map
# -----------------------------------------------------------------------------
THEME = {
    "background": WHITE,
    "surface": WHITE,
    "surface_subtle": SURFACE_SUBTLE,
    "text": TEXT,
    "text_secondary": TEXT_SECONDARY,
    "text_muted": TEXT_MUTED,
    "border": BORDER,
    "border_strong": BORDER_STRONG,
    "primary": BLUE,
    "primary_hover": "#005A8E",
    "success": BLUISH_GREEN,
    "warning": ORANGE,
    "danger": VERMILION,
    "info": SKY_BLUE,
    "accent": REDDISH_PURPLE,
    "disabled": GREY,
}

# Plotly chart colorway (Okabe-Ito order — high contrast first).
CHART_COLORWAY = [
    BLUE,
    ORANGE,
    BLUISH_GREEN,
    VERMILION,
    SKY_BLUE,
    REDDISH_PURPLE,
    YELLOW,
    GREY,
]

# Sequential heatmap scale — white surface → primary blue. A single-hue
# sequential ramp keeps a count matrix readable and on-tone (no rainbow).
HEATMAP_SCALE = [
    [0.0, WHITE],
    [0.5, "#9ECBE4"],
    [1.0, BLUE],
]


# -----------------------------------------------------------------------------
# Semantic helpers
# -----------------------------------------------------------------------------
def failure_category_color(label: str) -> str:
    """Stable Okabe-Ito color for an NSQ failure-category label."""
    palette = [BLUE, ORANGE, BLUISH_GREEN, VERMILION, SKY_BLUE,
               REDDISH_PURPLE, YELLOW, GREY]
    return palette[abs(hash(label)) % len(palette)]


def form_color(label: str) -> str:
    """Stable Okabe-Ito color for a dosage-form bucket."""
    palette = [BLUISH_GREEN, BLUE, ORANGE, VERMILION, SKY_BLUE,
               REDDISH_PURPLE, GREY]
    return palette[abs(hash(label)) % len(palette)]


# -----------------------------------------------------------------------------
# CSS injection
# -----------------------------------------------------------------------------
def css_variables() -> str:
    """Return a CSS <style> block with palette variables + base rules for
    the manufacturer app. Inject once via st.markdown(..., unsafe_allow_html=True)."""
    return f"""
<style>
  :root {{
    --mq-bg: {THEME["background"]};
    --mq-surface: {THEME["surface"]};
    --mq-surface-subtle: {THEME["surface_subtle"]};
    --mq-text: {THEME["text"]};
    --mq-text-secondary: {THEME["text_secondary"]};
    --mq-text-muted: {THEME["text_muted"]};
    --mq-border: {THEME["border"]};
    --mq-border-strong: {THEME["border_strong"]};
    --mq-primary: {THEME["primary"]};
    --mq-primary-hover: {THEME["primary_hover"]};
    --mq-success: {THEME["success"]};
    --mq-warning: {THEME["warning"]};
    --mq-danger: {THEME["danger"]};
    --mq-info: {THEME["info"]};
    --mq-accent: {THEME["accent"]};
    --mq-disabled: {THEME["disabled"]};
  }}

  /* Tighten Streamlit chrome toward the Figma's clean white surfaces.
     Hide Streamlit's default top header (the "Deploy" button + main-menu
     bar) — it floats above the content and overlaps the wordmark. The
     Q-engine wordmark below IS the app header, per the Figma. */
  header[data-testid="stHeader"] {{ display: none !important; }}
  .stApp, .stApp > header {{ background: var(--mq-bg); }}
  .block-container {{ padding-top: 2rem; max-width: 1200px; }}

  /* Q-engine wordmark (logo stand-in — text + bioicon mark, no raster). */
  .mq-wordmark {{
    display: inline-flex; align-items: center; gap: 8px;
    font-weight: 700; font-size: 18px; color: var(--mq-text);
    letter-spacing: -0.01em;
  }}
  .mq-wordmark svg {{ color: var(--mq-primary); }}

  /* Navigation pills (Figma "Navigation Pill List" shape). */
  .mq-nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 20px; }}
  .mq-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 14px; border-radius: 999px;
    font-size: 13px; font-weight: 500;
    border: 1px solid var(--mq-border); color: var(--mq-text-muted);
    background: var(--mq-surface);
  }}
  .mq-pill.mq-active {{
    color: var(--mq-primary); border-color: var(--mq-primary);
    background: rgba(0,114,178,0.06);
  }}
  .mq-pill.mq-disabled {{
    color: var(--mq-disabled); border-color: var(--mq-border);
    cursor: not-allowed; opacity: 0.7;
  }}

  /* Sign-in gate card (replaces the manufacturer context block). */
  .mq-signin-wrap {{ max-width: 460px; margin: 8vh auto 0; }}
  .mq-signin-card {{ margin-bottom: 18px; }}
  .mq-signin-title {{
    display: flex; align-items: center; gap: 8px;
    font-size: 20px; font-weight: 700; color: var(--mq-text);
  }}
  .mq-signin-title svg {{ color: var(--mq-primary); }}
  .mq-signin-sub {{ font-size: 13px; color: var(--mq-text-muted); margin-top: 6px; }}

  /* Signed-in user pill (header right side). */
  .mq-user-pill {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 12px; border-radius: 999px;
    border: 1px solid var(--mq-border); background: var(--mq-surface);
    font-size: 13px; color: var(--mq-text);
    white-space: nowrap; margin-bottom: 6px;
  }}
  .mq-user-pill svg {{ color: var(--mq-primary); }}
  .mq-user-persona {{ font-weight: 600; }}
  .mq-user-sep {{ color: var(--mq-text-muted); }}
  .mq-user-tenant {{ color: var(--mq-text-secondary); }}

  /* KPI tile (Figma metric-card shape). */
  .mq-kpi {{
    border: 1px solid var(--mq-border); border-radius: 10px;
    padding: 16px 18px; background: var(--mq-surface);
  }}
  .mq-kpi .mq-kpi-label {{ font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.05em; color: var(--mq-text-muted); }}
  .mq-kpi .mq-kpi-value {{ font-size: 30px; font-weight: 700;
    color: var(--mq-text); margin-top: 6px; line-height: 1.1; }}
  .mq-kpi .mq-kpi-help {{ font-size: 12px; color: var(--mq-text-muted); margin-top: 6px; }}

  /* Issue card (Figma "Card" shape — body / text-links / button-group). */
  .mq-issue-card {{
    border: 1px solid var(--mq-border); border-radius: 10px;
    padding: 14px 16px; background: var(--mq-surface);
    display: grid; grid-template-columns: 1fr auto; gap: 4px 12px;
    align-items: center;
  }}
  .mq-issue-card .mq-ic-product {{ font-weight: 600; color: var(--mq-text); font-size: 15px; }}
  .mq-issue-card .mq-ic-meta {{ font-size: 12px; color: var(--mq-text-muted); }}
  .mq-issue-card .mq-ic-result {{
    font-size: 12px; font-weight: 600; color: var(--mq-danger);
    border: 1px solid var(--mq-border); border-radius: 6px; padding: 2px 8px;
  }}

  /* Scrollable issue list — all cards in one container, no pagination. */
  .mq-issue-list {{
    max-height: 520px; overflow-y: auto;
    border: 1px solid var(--mq-border); border-radius: 10px;
    padding: 10px; background: var(--mq-surface-subtle);
  }}
  .mq-issue-list .mq-issue-card {{ margin-bottom: 8px; }}
  .mq-issue-list .mq-issue-card:last-child {{ margin-bottom: 0; }}
  .mq-issue-list::-webkit-scrollbar {{ width: 8px; }}
  .mq-issue-list::-webkit-scrollbar-thumb {{
    background: var(--mq-border-strong); border-radius: 8px; }}
  .mq-issue-list::-webkit-scrollbar-track {{ background: transparent; }}

  .mq-caption {{ font-size: 12px; color: var(--mq-text-muted); margin-top: 4px; }}
  .mq-strapline {{ font-size: 14px; color: var(--mq-text-secondary); margin: 8px 0 16px; }}
</style>
"""