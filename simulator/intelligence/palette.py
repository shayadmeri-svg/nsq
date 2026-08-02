"""Colorblind-safe scientific color palette for the NSQ apps.

Uses the Okabe-Ito palette — the de-facto standard for accessible,
publication-quality scientific figures. All UI accents, chart colorways,
and semantic badge colors are centralized here so the simulator and
analytics apps stay consistent.

References:
- Okabe, M. & Ito, K. (2008). Color universal design (CUD).
  https://jfly.uni-fly.org/color/
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Okabe-Ito base colors
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
# Neutral scientific greys / backgrounds
# -----------------------------------------------------------------------------
BLACK = "#1a1a1a"
NEAR_BLACK = "#262626"
DARK_GREY = "#4a4a4a"
MID_GREY = "#737373"
LIGHT_GREY = "#b0b0b0"
BORDER_GREY = "#d9d9d9"
PALE_GREY = "#f2f2f2"
OFF_WHITE = "#fafafa"
WHITE = "#ffffff"

# -----------------------------------------------------------------------------
# Theme map for CSS / inline styles
# -----------------------------------------------------------------------------
THEME = {
    "background": OFF_WHITE,
    "surface": WHITE,
    "surface_subtle": PALE_GREY,
    "text": BLACK,
    "text_secondary": DARK_GREY,
    "text_muted": MID_GREY,
    "border": BORDER_GREY,
    "border_strong": LIGHT_GREY,
    "primary": BLUE,
    "primary_hover": "#005a8e",
    "success": BLUISH_GREEN,
    "warning": ORANGE,
    "danger": VERMILION,
    "info": SKY_BLUE,
    "accent": REDDISH_PURPLE,
    "disabled": GREY,
}

# -----------------------------------------------------------------------------
# Plotly / chart defaults
# -----------------------------------------------------------------------------
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

CONTINUOUS_SCALE = [
    [0.0, PALE_GREY],
    [0.25, SKY_BLUE],
    [0.5, BLUE],
    [0.75, REDDISH_PURPLE],
    [1.0, VERMILION],
]

# -----------------------------------------------------------------------------
# Semantic helpers
# -----------------------------------------------------------------------------
def risk_color(risk: str) -> str:
    """Return a color for low/medium/high risk labels."""
    return {
        "low": BLUISH_GREEN,
        "medium": ORANGE,
        "high": VERMILION,
    }.get((risk or "").lower(), GREY)


def cluster_color(cluster: str) -> str:
    """Return a stable color for a therapeutic / manufacturing cluster."""
    return {
        "oncology": REDDISH_PURPLE,
        "specialty injectable": BLUE,
        "immunology": ORANGE,
        "lifestyle / chronic": BLUISH_GREEN,
        "lifestyle/chronic": BLUISH_GREEN,
        "lifestyle": BLUISH_GREEN,
        "commodity": GREY,
    }.get((cluster or "").lower(), GREY)


def grade_color(grade: str) -> str:
    """Return foreground color for a grade badge."""
    return {
        "a": BLUISH_GREEN,
        "b": BLUISH_GREEN,
        "c": ORANGE,
        "d": VERMILION,
        "f": VERMILION,
    }.get((grade or "").strip().lower(), GREY)


def grade_background(grade: str) -> str:
    """Return a subtle background color for a grade badge."""
    return {
        "a": "#e6f5f1",
        "b": "#e6f5f1",
        "c": "#fff4e6",
        "d": "#ffebe6",
        "f": "#ffebe6",
    }.get((grade or "").strip().lower(), PALE_GREY)


def tier_color(tier: str) -> str:
    """Return a badge color for portfolio / strategy tiers."""
    palette = {
        "success": BLUISH_GREEN,
        "core": BLUE,
        "adjacent": ORANGE,
        "stretch": VERMILION,
        "strategic": BLUISH_GREEN,
        "warning": ORANGE,
        "danger": VERMILION,
        "info": GREY,
        "low": BLUISH_GREEN,
        "medium": ORANGE,
        "high": VERMILION,
    }
    return palette.get((tier or "").lower(), GREY)


# -----------------------------------------------------------------------------
# CSS snippet helpers
# -----------------------------------------------------------------------------
def css_variables() -> str:
    """Return a CSS :root block with palette variables for inline injection."""
    return f"""
<style>
  :root {{
    --nsq-bg: {THEME["background"]};
    --nsq-surface: {THEME["surface"]};
    --nsq-surface-subtle: {THEME["surface_subtle"]};
    --nsq-text: {THEME["text"]};
    --nsq-text-secondary: {THEME["text_secondary"]};
    --nsq-text-muted: {THEME["text_muted"]};
    --nsq-border: {THEME["border"]};
    --nsq-border-strong: {THEME["border_strong"]};
    --nsq-primary: {THEME["primary"]};
    --nsq-primary-hover: {THEME["primary_hover"]};
    --nsq-success: {THEME["success"]};
    --nsq-warning: {THEME["warning"]};
    --nsq-danger: {THEME["danger"]};
    --nsq-info: {THEME["info"]};
    --nsq-accent: {THEME["accent"]};
    --nsq-disabled: {THEME["disabled"]};
  }}
</style>
"""
