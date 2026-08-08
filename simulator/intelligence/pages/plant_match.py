"""Streamlit page: Plant Match + QbD/NSQ risk overlay.

Select a molecule and a plant asset to see a fit score, predicted NSQ flags,
and recommended Critical Quality Attributes / Critical Process Parameters.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from intelligence.api_client import get_molecule, get_molecule_complexity, get_plant, list_molecules, list_plants, score
from intelligence.capability_catalog import (
    CAPABILITY_BY_TOKEN,
    SECTIONS,
)
from intelligence.intelligence_scorer import MOLECULE_CAPABILITY_HINTS
from intelligence.ui_components import (
    anime_entrance,
    metric_tile,
    mock_data_badge,
    page_header,
    render_chart,
    render_gmp_pillars,
    scientific_bullet_chart,
    scientific_gap_matrix,
    scientific_nested_ring,
    tier_badge,
)


def render() -> None:
    page_header(
        pillar="Pillar D — Plant Expertise & Shop-Floor AI",
        title="Plant Match",
        subtitle="Match molecule requirements to plant capability and preview predicted NSQ risk.",
        icon="factory",
    )

    molecules = list_molecules()
    plants = list_plants()

    if not molecules or not plants:
        st.warning(
            "Molecule or plant data not loaded. Run `just load-intelligence` to seed Redis."
        )
        return

    mol_options = {m["brand_name"]: m["molecule_key"] for m in molecules}
    mol_labels = list(mol_options.keys())
    plant_options = {f"{p['site_name']} ({p['asset_id']})": p["asset_id"] for p in plants}

    # Pre-select a molecule sent from the Product Catalog.
    pending_molecule_key = st.session_state.pop("pending_molecule_key", None)
    mol_default_index = 0
    if pending_molecule_key:
        mol_default_index = next(
            (i for i, label in enumerate(mol_labels) if mol_options[label] == pending_molecule_key),
            0,
        )

    # Pre-select a plant that was just created in the Plant Builder.
    pending_plant_id = st.session_state.pop("pending_plant_id", None)
    plant_labels = list(plant_options.keys())
    plant_default_index = 0
    if pending_plant_id:
        plant_default_index = next(
            (i for i, label in enumerate(plant_labels) if plant_options[label] == pending_plant_id),
            0,
        )

    with st.expander("Filter & select candidates", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            selected_brand = st.selectbox(
                "Molecule",
                mol_labels,
                index=mol_default_index,
            )
        with col2:
            selected_plant_label = st.selectbox(
                "Plant line",
                plant_labels,
                index=plant_default_index,
            )

    molecule_key = mol_options[selected_brand]
    plant_id = plant_options[selected_plant_label]

    run_match = st.button(
        "Run Plant Match",
        type="primary",
        width="stretch",
    )

    if not run_match:
        return

    with st.spinner("Matching molecule to plant line…"):
        result = score(molecule_key, plant_id)
        mol_data = get_molecule(molecule_key)
        complexity = get_molecule_complexity(molecule_key)
        plant_full = get_plant(plant_id)

    plant_caps: set[str] = set()
    if plant_full:
        plant_caps.update((c or "").lower() for c in plant_full.get("capabilities", []))
        for train in plant_full.get("equipment_trains") or []:
            cap = (train.get("capability") or "").lower()
            if cap:
                plant_caps.add(cap)

    anime_entrance("#plant-match-results", "slideUp")
    st.markdown('<div id="plant-match-results">', unsafe_allow_html=True)

    with st.container():
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            metric_tile("Patent", f"{result.patent_readiness_score:.0f}")
        with c2:
            metric_tile("Regulatory", f"{result.regulatory_clarity_score:.0f}")
        with c3:
            metric_tile("Demand", f"{result.demand_attractiveness_score:.0f}")
        with c4:
            metric_tile("Plant Fit", f"{result.plant_fit_score:.0f}")
        with c5:
            metric_tile("Total", f"{result.total_score:.0f}")

        st.markdown("<br>", unsafe_allow_html=True)

        tier_label = result.explanation.get("tier", "strategic")
        st.markdown(
            f"**Overall tier:** {tier_badge(tier_label)} &nbsp;|&nbsp; **FTO risk:** {tier_badge(result.fto_risk)}",
            unsafe_allow_html=True,
        )

    # Visual score profile: nested multi-ring radial bar chart
    st.markdown("### Decision rationale")
    score_labels = ["Patent", "Regulatory", "Demand", "Plant Fit"]
    score_values = [
        result.patent_readiness_score,
        result.regulatory_clarity_score,
        result.demand_attractiveness_score,
        result.plant_fit_score,
    ]
    ring_fig = scientific_nested_ring(
        dict(zip(score_labels, score_values)),
        max_value=100,
        title="Pillar score profile",
        source="engine scoring model | representative seed data",
    )
    render_chart(ring_fig)

    # Bullet bars with rationale as captions
    bullet_fig = scientific_bullet_chart(
        dict(zip(score_labels, score_values)),
        target=80,
        max_value=100,
        title="Score completion vs. target",
        source="engine scoring model",
    )
    render_chart(bullet_fig)
    for pillar, text in result.explanation.items():
        if pillar == "tier":
            continue
        st.caption(f"**{pillar.title()}:** {text}")

    if result.warnings:
        st.markdown("### Warnings")
        for w in result.warnings:
            st.warning(w)

    plant_row = next((p for p in plants if p["asset_id"] == plant_id), None)
    if plant_full:
        st.markdown("### Plant capability overview")
        caps = pd.DataFrame({"Capability": plant_full.get("capabilities", [])})
        forms = pd.DataFrame({"Approved forms": plant_full.get("approved_forms", [])})
        c_l, c_r = st.columns(2)
        c_l.dataframe(caps, width="stretch", hide_index=True)
        c_r.dataframe(forms, width="stretch", hide_index=True)

        # Capability gap matrix
        st.markdown("### Required capability match")
        molecule_class = "small_molecule_oral"
        if complexity:
            molecule_class = complexity.get("modality", "small_molecule_oral")
            if molecule_class in ("monoclonal_antibody", "recombinant_protein", "fusion_protein"):
                molecule_class = "mab"
            elif molecule_class == "peptide":
                molecule_class = "peptide"
            elif complexity.get("drug_form") in ("injection", "vial"):
                molecule_class = "small_molecule_injectable"
        required = set(MOLECULE_CAPABILITY_HINTS.get(molecule_class, MOLECULE_CAPABILITY_HINTS["small_molecule_oral"]))
        sections: dict[str, list[str]] = {}
        for token in required:
            cap = CAPABILITY_BY_TOKEN.get(token)
            section_title = "General"
            if cap:
                section = next((s for s in SECTIONS if s.section_id == cap.section_id), None)
                if section:
                    section_title = section.title
            sections.setdefault(section_title, []).append(token)

        if required:
            gap_fig = scientific_gap_matrix(
                sorted(required),
                plant_caps,
                sections,
                title="Molecule requirements vs. plant capabilities",
                source="capability catalog + plant asset",
            )
            render_chart(gap_fig)

    st.markdown("### Predicted NSQ risk overlay")
    if mol_data:
        st.markdown(
            f"Therapeutic area: **{mol_data.get('therapeutic_area', 'Unknown')}**. "
            f"FTO risk: **{mol_data.get('fto_risk', 'Unknown')}**."
        )

    st.markdown("### GMP methodological context")
    gmp_html = render_gmp_pillars(
        complexity.get("gmp_pillars") or [] if complexity else [],
        plant_capabilities=plant_caps,
        show_title=False,
    )
    if gmp_html:
        st.markdown(gmp_html, unsafe_allow_html=True)
    else:
        st.caption("No GMP pillar context inferred for this molecule.")

    mock_data_badge()
    st.markdown("</div>", unsafe_allow_html=True)
