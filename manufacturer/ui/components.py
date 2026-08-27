"""Figma-shaped Streamlit components for the manufacturer app.

Each component mirrors a shape from the Q-engine Figma (header, nav
pills, KPI/metric card, issue card, sign-in card) but is rendered with
the scientific palette (see palette.py). Layout authority = Figma;
color/icon authority = the scientific tone rule.

These are thin render helpers — they take already-scoped data and emit
``st.markdown``/``st.columns``/``st.button`` calls. No data loading here.
"""

from __future__ import annotations

import streamlit as st

import auth
from ui.icons import bioicon, wordmark
from ui.palette import THEME


# Phase-1 nav: only Dashboard is enabled. The other tabs land in phase 2
# (diagnostics / mitigation / simulator) and beyond (export / data access).
NAV_TABS: tuple[tuple[str, str, bool], ...] = (
    # (label, bioicon, enabled)
    ("Dashboard", "chart", True),
    ("Q-engine diagnostics", "microscope", True),
    ("Q-engine mitigation", "check", False),
    ("Export readiness", "download", False),
    ("Data access", "document", False),
)

# The diagnostics nav-tab label — shared by components.nav_pills, app.py
# routing, and diagnostics.py so the active-tab key stays in lockstep.
DIAG_TAB = "Q-engine diagnostics"
DASHBOARD_TAB = "Dashboard"

# Session-state key holding the active nav tab.
ACTIVE_TAB_KEY = "mq_active_tab"


def render_header() -> None:
    """Top bar: Q-engine wordmark (Figma Header shape, neutral)."""
    st.markdown(wordmark(), unsafe_allow_html=True)


def _goto_tab(label: str) -> None:
    """Set the active tab in session state and rerun. Clicking the diagnostics
    tab clears any pinned issue index so the view picks a fresh random one."""
    st.session_state[ACTIVE_TAB_KEY] = label
    if label == DIAG_TAB:
        st.session_state["mq_diag_issue_idx"] = None
    st.rerun()


def nav_pills(active: str = DASHBOARD_TAB) -> None:
    """Figma 'Navigation Pill List' — a row of tab controls. Enabled tabs are
    real ``st.button``s (active tab rendered as primary); not-yet-enabled tabs
    render as disabled pill placeholders. Streamlit buttons are text-only, so
    the bioicon is dropped on interactive pills (the disabled placeholders
    keep their icon for visual continuity with the Figma)."""
    cols = st.columns([1, 1.5, 1.4, 1.2, 1.1])
    for col, (label, _icon, enabled) in zip(cols, NAV_TABS):
        with col:
            if enabled:
                is_active = label == active
                if st.button(
                    label,
                    key=f"mq_nav_{label}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                ):
                    _goto_tab(label)
            else:
                st.markdown(
                    f'<span class="mq-pill mq-disabled">'
                    f'{bioicon(_icon, 13, "currentColor")}{label}</span>',
                    unsafe_allow_html=True,
                )


def render_signin_card() -> None:
    """Sign-in gate card (replaces the old manufacturer context block).

    Establishes session context — which manufacturer (tenant) the user is
    acting as and which persona they hold — before the dashboard is
    shown. Session-only; see auth.py. Renders nothing but the card and
    returns; the caller should skip the dashboard when not authenticated.
    """
    st.markdown("<div class='mq-signin-wrap'>", unsafe_allow_html=True)
    st.markdown(
        f'<div class="mq-signin-card">'
        f'  <div class="mq-signin-title">{bioicon("qmark", 22, "var(--mq-primary)")} Sign in to Q-engine</div>'
        f'  <div class="mq-signin-sub">Select your manufacturer and role to continue.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    choices = auth.tenant_choices()
    keys = [k for k, _ in choices]
    default_idx = 0
    tenant_key = st.selectbox(
        "Manufacturer",
        options=keys,
        index=default_idx,
        format_func=lambda k: dict(choices)[k],
        key="mq_signin_tenant",
    )
    persona = st.selectbox(
        "Persona",
        options=list(auth.PERSONAS),
        key="mq_signin_persona",
    )
    st.caption("Session-only — no credentials are stored.")
    if st.button("Sign in", type="primary", use_container_width=True,
                 key="mq_signin_submit"):
        auth.sign_in(tenant_key, persona)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_auth_header(canonical: str, city: str, persona: str) -> None:
    """Header row: Q-engine wordmark on the left, a signed-in pill +
    Sign out button on the right (replaces the manufacturer context
    block with the identity established at sign-in)."""
    left, right = st.columns([3, 2])
    with left:
        st.markdown(wordmark(), unsafe_allow_html=True)
    with right:
        st.markdown(
            f'<div class="mq-user-pill">'
            f'{bioicon("factory", 14, "var(--mq-primary)")}'
            f'<span class="mq-user-persona">{persona}</span>'
            f'<span class="mq-user-sep">·</span>'
            f'<span class="mq-user-tenant">{canonical} — {city}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("Sign out", key="mq_signout", use_container_width=True):
            auth.sign_out()
            st.rerun()


def kpi_tile(label: str, value, help_text: str = "") -> None:
    """Figma metric-card shape. ``value`` is rendered large; optional
    one-line help below."""
    help_html = f'<div class="mq-kpi-help">{help_text}</div>' if help_text else ""
    st.markdown(
        f'<div class="mq-kpi">'
        f'  <div class="mq-kpi-label">{label}</div>'
        f'  <div class="mq-kpi-value">{value}</div>'
        f'  {help_html}'
        f'</div>',
        unsafe_allow_html=True,
    )