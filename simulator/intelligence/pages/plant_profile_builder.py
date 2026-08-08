"""Streamlit page: Plant Profile Builder.

Lets a user create a custom digital plant profile by selecting capabilities from
a searchable catalog organized into 7 GMP infrastructure sections. The profile is
persisted as a PlantAsset in Redis and becomes available for comparison in Plant
Match / Plant Readiness.

UX notes
--------
- The section selector is a row of tabs (not pills, not a dropdown, and not an
  expander), so it never collapses when a capability is selected.
- Capabilities render as plain checkboxes inside a non-collapsing two-column
  grid inside each tab.  This is better for dense scientific labels than
  toggles or chips, because the label text stays fully readable and the
  checkbox state is obvious.
- Search filters capabilities within the active tab.
- A live selection-summary panel is always visible below the grid.
- All section icons come from the shared `bioicon` SVG library; no emoji.
"""

from __future__ import annotations

import streamlit as st

from intelligence.api_client import create_plant, get_capability_taxonomy
from intelligence.capability_catalog import (
    SECTIONS,
    CAPABILITY_BY_TOKEN,
    infer_plant_defaults,
)
from intelligence.palette import THEME
from intelligence.ui_components import (
    anime_entrance,
    bioicon_inline,
    mock_data_badge,
    page_header,
)


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------


def _cap_checkbox_key(token: str) -> str:
    return f"cap_checkbox_{token}"


def _selected_capabilities() -> set[str]:
    """Return all capability tokens whose checkboxes are currently on."""
    return {
        key.replace("cap_checkbox_", "")
        for key in st.session_state
        if key.startswith("cap_checkbox_") and st.session_state[key]
    }


def _clear_builder_state() -> None:
    """Reset the builder form after a successful save."""
    for key in list(st.session_state.keys()):
        if key.startswith("cap_checkbox_"):
            del st.session_state[key]
    st.session_state["plant_builder_name"] = ""
    st.session_state["plant_builder_search"] = ""
    st.session_state["plant_builder_section"] = SECTIONS[0].section_id


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _render_capability_chip(token: str) -> str:
    cap = CAPABILITY_BY_TOKEN.get(token)
    label = cap.label if cap else token
    section = None
    if cap:
        for s in SECTIONS:
            if s.section_id == cap.section_id:
                section = s
                break
    color = THEME["primary"] if section is None else _section_color(section.section_id)
    return (
        f'<span style="padding:2px 6px; border-radius:3px; background:{color}22; '
        f'color:{color}; font-size:9px; font-weight:700; border:1px solid {color}44; margin:0 4px 4px 0;" '
        f'title="Canonical token: {token}">'
        f'{label}</span>'
    )


_SECTION_COLORS: dict[str, str] = {
    "architectural_hvac": "#0072B2",
    "biologics_fill_finish": "#009E73",
    "hpapi_osd": "#D55E00",
    "qc_analytical": "#CC79A7",
    "process_utilities": "#E69F00",
    "automation_digital": "#56B4E9",
    "warehousing_coldchain": "#F0E442",
}


def _section_color(section_id: str) -> str:
    return _SECTION_COLORS.get(section_id, THEME["primary"])


def _render_selected_summary(selected: set[str]) -> None:
    if not selected:
        st.caption("No capabilities selected yet.")
        return

    by_section: dict[str, list[str]] = {}
    for token in sorted(selected):
        cap = CAPABILITY_BY_TOKEN.get(token)
        if cap is None:
            continue
        by_section.setdefault(cap.section_id, []).append(token)

    total = len(selected)
    st.markdown(f"**{total}** {'capability' if total == 1 else 'capabilities'} selected")

    lines: list[str] = []
    for section in SECTIONS:
        tokens = by_section.get(section.section_id, [])
        if not tokens:
            continue
        color = _section_color(section.section_id)
        chips = "".join(_render_capability_chip(t) for t in tokens)
        icon_html = bioicon_inline(section.icon, size=12, color=color)
        lines.append(
            f'<div style="margin-bottom:8px;">'
            f'<div style="font-size:10px; font-weight:800; color:{color}; margin-bottom:3px; display:flex; align-items:center; gap:4px;">'
            f'{icon_html} {section.title}</div>'
            f'<div style="display:flex; flex-wrap:wrap;">{chips}</div>'
            f'</div>'
        )
    if lines:
        st.markdown(
            f'<div style="border:1px solid {THEME["border"]}; border-radius:4px; padding:10px; background:{THEME["surface"]};">'
            + "".join(lines)
            + "</div>",
            unsafe_allow_html=True,
        )


def _capability_matches(cap: "Capability", query: str) -> bool:
    """Return True if a capability matches the search query."""
    if not query:
        return True
    q = query.lower()
    section = None
    for s in SECTIONS:
        if s.section_id == cap.section_id:
            section = s
            break
    return (
        q in cap.label.lower()
        or q in cap.token.lower()
        or (section is not None and q in section.title.lower())
    )


def _render_capability_checkboxes(
    capabilities: list["Capability"],
    selected: set[str],
    *,
    two_columns: bool = True,
) -> None:
    """Render a stable grid of checkboxes for the given capabilities.

    Checkboxes are placed inside a plain container (no expander / no tab), so
    the panel never collapses on selection.  State is stored under stable keys
    so it survives search filtering and section switching.
    """
    # Ensure deterministic initial state for every rendered checkbox.
    for cap in capabilities:
        key = _cap_checkbox_key(cap.token)
        if key not in st.session_state:
            st.session_state[key] = cap.token in selected

    if two_columns:
        cols = st.columns(2)
        for idx, cap in enumerate(capabilities):
            with cols[idx % 2]:
                st.checkbox(
                    cap.label,
                    key=_cap_checkbox_key(cap.token),
                    help=f"Canonical token: `{cap.token}`",
                )
    else:
        for cap in capabilities:
            st.checkbox(
                cap.label,
                key=_cap_checkbox_key(cap.token),
                help=f"Canonical token: `{cap.token}`",
            )


def _render_section_header(section: "CapabilitySection", selected: set[str]) -> None:
    """Render the section title, bioicon, description, and selection count."""
    color = _section_color(section.section_id)
    icon_html = bioicon_inline(section.icon, size=14, color=color)
    selected_count = sum(1 for c in section.capabilities if c.token in selected)
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">'
        f'{icon_html}'
        f'<span style="font-size:13px; font-weight:800; color:{THEME["text"]};">{section.title}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"{section.description} — {selected_count}/{len(section.capabilities)} selected"
    )


def _render_capability_selector() -> set[str]:
    """Render the search box, section tabs, and persistent checkbox grid.

    Returns the current set of selected capability tokens.
    """
    search = st.text_input(
        "Search capabilities",
        value=st.session_state.get("plant_builder_search", ""),
        key="plant_builder_search",
        placeholder="e.g. isolator, granulation, serialization…",
    )
    query = search.lower().strip()

    selected = _selected_capabilities()

    # Tab labels are plain text — no emoji.  Streamlit tabs manage their own
    # active state on the frontend, so selecting a checkbox never collapses the
    # panel.  We render content inside every tab; only the active tab is visible.
    section_labels = [s.title for s in SECTIONS]
    tabs = st.tabs(section_labels)
    for idx, tab in enumerate(tabs):
        with tab:
            section = SECTIONS[idx]
            _render_section_header(section, selected)
            visible = [c for c in section.capabilities if _capability_matches(c, query)]
            if query and not visible:
                st.caption("No capabilities match your search in this section.")
            _render_capability_checkboxes(visible, selected)

    return _selected_capabilities()


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------


def render() -> None:
    page_header(
        pillar="Pillar D — Plant Expertise & Shop-Floor AI",
        title="Plant Profile Builder",
        subtitle="Create a digital plant profile from 7 GMP infrastructure sections, then compare it to molecules.",
        icon="factory",
    )

    # Load taxonomy once per session.
    if "capability_taxonomy" not in st.session_state:
        st.session_state["capability_taxonomy"] = get_capability_taxonomy()

    anime_entrance("#plant-builder", "fadeIn")
    st.markdown('<div id="plant-builder">', unsafe_allow_html=True)

    # Plant name
    st.markdown("### 1. Name your plant")
    name = st.text_input(
        "Plant name",
        value=st.session_state.get("plant_builder_name", ""),
        key="plant_builder_name",
        placeholder="e.g. Hyderabad HPAPI OSD + Biologics Hub",
    )

    # Capability selector
    st.markdown("### 2. Select capabilities")
    selected = _render_capability_selector()

    # Live summary
    st.markdown("### 3. Selection summary")
    _render_selected_summary(selected)

    # Save
    st.markdown("### 4. Save profile")
    can_save = bool(name.strip()) and bool(selected)

    col_save, col_status = st.columns([1, 3])
    with col_save:
        save_clicked = st.button(
            "Save Plant Profile",
            type="primary",
            disabled=not can_save,
            width="stretch",
        )

    if save_clicked:
        with st.spinner("Saving plant profile…"):
            result = create_plant(name, sorted(selected))
        if result and result.get("asset_id"):
            asset_id = result["asset_id"]
            st.success(
                f"Saved **{name}** as `{asset_id}`. "
                f"The plant is now available in Plant Match and Plant Readiness."
            )
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("Compare in Plant Match", width="stretch"):
                    st.session_state["active_tab_index"] = 3
                    st.session_state["pending_plant_id"] = asset_id
                    _clear_builder_state()
                    st.rerun()
            with c2:
                if st.button("Compare in Plant Readiness", width="stretch"):
                    st.session_state["active_tab_index"] = 4
                    st.session_state["pending_plant_id"] = asset_id
                    _clear_builder_state()
                    st.rerun()
            with c3:
                if st.button("Build another plant", width="stretch"):
                    _clear_builder_state()
                    st.rerun()
        else:
            st.error("Could not save plant profile. Check that the engine is healthy and reachable.")

    elif not name.strip():
        col_status.info("Enter a plant name to enable saving.")
    elif not selected:
        col_status.info("Select at least one capability to enable saving.")

    mock_data_badge()
    st.markdown("</div>", unsafe_allow_html=True)
