"""Dashboard render functions for the manufacturer app (phase 1).

Pure render helpers — each takes the already-scoped tenant frame (and
the tenant where needed) and emits Streamlit output. No data loading
happens here (see tenant_scope.py), and no Figma accent colors (see
ui/palette.py). The Figma is the layout/component-shape authority; the
scientific tone is the color/icon authority.

Maps onto the Figma 'Home Page' / Dashboard screen:
  - KPI row (NSQ alerts / Products / Period)
  - Issue by type (donut) + Issue over time (line) + dosage-form (bar)
    + form × issue heatmap
  - NSQ issue list (strapline, "Include issues to analyse" selector,
    all issue cards in a single scrollable container, disabled "Deep dive")
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tenant_scope import tenant_period, tenant_product_count
from tenants import Tenant
from ui.charts import bar_by_form, donut_issue_by_type, heatmap_form_vs_issue, line_over_time
from ui.components import ACTIVE_TAB_KEY, DIAG_TAB, kpi_tile

ISSUE_LIST_KEY = "dashboard_issue_list"
DIAG_INDEX_KEY = "mq_diag_issue_idx"


def _deep_dive_into(idx: int) -> None:
    """Pin a specific issue and switch to the diagnostics tab."""
    st.session_state[ACTIVE_TAB_KEY] = DIAG_TAB
    st.session_state[DIAG_INDEX_KEY] = idx
    st.rerun()


def render_kpi_row(df: pd.DataFrame) -> None:
    """Figma KPI row: NSQ alerts / Products / Period."""
    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_tile("NSQ alerts", len(df),
                 help_text="Not-of-standard-quality alerts for this manufacturer.")
    with c2:
        kpi_tile("Products", tenant_product_count(df),
                 help_text="Distinct products flagged (canonicalized).")
    with c3:
        kpi_tile("Period", tenant_period(df),
                 help_text="Span of reporting months covered.")


def render_charts(df: pd.DataFrame) -> None:
    """Figma chart row: issue-by-type donut + over-time line, then the
    dosage-form bar and the form × issue heatmap full-width below."""
    donut = donut_issue_by_type(df)
    line = line_over_time(df)

    left, right = st.columns(2)
    with left:
        st.markdown("**Issue by type**")
        if donut is not None:
            st.plotly_chart(donut, use_container_width=True)
            st.caption("Distribution of NSQ failure categories for this manufacturer.")
        else:
            st.caption("No failure-category data available.")
    with right:
        st.markdown("**Issue over time**")
        if line is not None:
            st.plotly_chart(line, use_container_width=True)
            st.caption("Monthly NSQ alert volume.")
        else:
            st.caption("No reporting-date data available.")

    st.markdown("**NSQ alerts by dosage form**")
    bar = bar_by_form(df)
    if bar is not None:
        st.plotly_chart(bar, use_container_width=True)
        st.caption("NSQ alerts grouped by dosage form bucket.")

    st.markdown("**Form × issue type**")
    heat = heatmap_form_vs_issue(df)
    if heat is not None:
        st.plotly_chart(heat, use_container_width=True)
        st.caption("NSQ alert counts by dosage form and failure category.")
    else:
        st.caption("No form / failure-category data available.")


def render_issue_list(df: pd.DataFrame) -> None:
    """Figma NSQ issue list: strapline, 'Include issues to analyse'
    selector (selection stored in session state), then ALL issue cards in a
    single scrollable container (no pagination). Each card carries a real
    'Deep dive' button that pins that issue and switches to the Q-engine
    diagnostics tab."""
    st.markdown(
        "Use Q-engine to deep dive into root cause analysis as well as "
        "corrective & preventive actions.",
        help="Click Deep dive on any issue to run Q-engine diagnostics on it.",
    )

    if df.empty:
        st.info("No NSQ issues for this manufacturer.")
        return

    # Selector of issues to carry into a diagnostics run.
    product_col = ("Product_Name_Canonical" if "Product_Name_Canonical" in df.columns
                   else "Name of Product")
    options = df[product_col].fillna("—").tolist()
    selected = st.multiselect(
        "Include issues to analyse",
        options=options,
        default=[],
        key=ISSUE_LIST_KEY,
        help="Selected issues will feed the Q-engine diagnostics flow.",
    )
    if selected:
        st.caption(f"{len(selected)} issue(s) selected for analysis.")

    # All cards in one scrollable container (no pagination). Each card is a
    # bordered Streamlit container with a Deep-dive st.button on the right.
    with st.container(height=520):
        for idx, (_, row) in enumerate(df.iterrows()):
            product = (row.get("Product_Name_Canonical")
                       or row.get("Name of Product", "—"))
            batch = row.get("Batch No", "—")
            result = row.get("NSQ Result", "—")
            lab = row.get("Reporting by Lab/State", "—")
            month = row.get("Reporting Month & Year", "—")
            with st.container(border=True):
                left, right = st.columns([5, 2])
                with left:
                    st.markdown(f"**{product}**")
                    st.caption(f"Batch {batch} · {lab} · {month}")
                with right:
                    st.markdown(
                        f'<span class="mq-ic-result">{result}</span>',
                        unsafe_allow_html=True,
                    )
                    if st.button("Deep dive", key=f"dd_{idx}",
                                 use_container_width=True):
                        _deep_dive_into(idx)
    st.caption(f"{len(df)} issue(s) listed.")


def render_dashboard(df: pd.DataFrame, tenant: Tenant) -> None:
    """Render the full dashboard for a scoped tenant frame."""
    if df.empty:
        st.warning(
            f"No records found for tenant **{tenant.canonical}** "
            f"(ontology key `{tenant.ontology_key}`)."
        )
        return
    render_kpi_row(df)
    st.markdown("---")
    render_charts(df)
    st.markdown("---")
    render_issue_list(df)