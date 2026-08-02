"""Streamlit page: Plant Match + QbD/NSQ risk overlay.

Select a molecule and a plant asset to see a fit score, predicted NSQ flags,
and recommended Critical Quality Attributes / Critical Process Parameters.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from intelligence.api_client import get_molecule, list_molecules, list_plants, score
from intelligence.palette import BLUE, THEME
from intelligence.ui_components import (
    anime_entrance,
    metric_tile,
    mock_data_badge,
    page_header,
    render_chart,
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
    plant_options = {f"{p['site_name']} ({p['asset_id']})": p["asset_id"] for p in plants}

    with st.expander("Filter & select candidates", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            selected_brand = st.selectbox("Molecule", list(mol_options.keys()))
        with col2:
            selected_plant_label = st.selectbox("Plant line", list(plant_options.keys()))

    molecule_key = mol_options[selected_brand]
    plant_id = plant_options[selected_plant_label]

    run_match = st.button(
        "🏭 Run Plant Match",
        type="primary",
        use_container_width=True,
    )

    if not run_match:
        return

    with st.spinner("Matching molecule to plant line…"):
        result = score(molecule_key, plant_id)
        mol_data = get_molecule(molecule_key)

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

    st.subheader("Decision rationale")
    for pillar, text in result.explanation.items():
        if pillar == "tier":
            continue
        st.markdown(f"**{pillar.title()}:** {text}")

    if result.warnings:
        st.subheader("Warnings")
        for w in result.warnings:
            st.warning(w)

    plant_row = next((p for p in plants if p["asset_id"] == plant_id), None)
    if plant_row:
        st.subheader("Plant capability overview")
        caps = pd.DataFrame({"Capability": plant_row.get("capabilities", [])})
        forms = pd.DataFrame({"Approved forms": plant_row.get("approved_forms", [])})
        c_l, c_r = st.columns(2)
        c_l.dataframe(caps, use_container_width=True, hide_index=True)
        c_r.dataframe(forms, use_container_width=True, hide_index=True)

    st.subheader("Predicted NSQ risk overlay")
    if mol_data:
        st.markdown(
            f"Therapeutic area: **{mol_data.get('therapeutic_area', 'Unknown')}**. "
            f"FTO risk: **{mol_data.get('fto_risk', 'Unknown')}**."
        )

    score_labels = ["Patent", "Regulatory", "Demand", "Plant Fit"]
    score_values = [
        result.patent_readiness_score,
        result.regulatory_clarity_score,
        result.demand_attractiveness_score,
        result.plant_fit_score,
    ]
    fig = go.Figure(
        go.Scatterpolar(
            r=score_values + [score_values[0]],
            theta=score_labels + [score_labels[0]],
            fill="toself",
            line_color=BLUE,
            fillcolor="rgba(0,114,178,0.12)",
            name=f"{selected_brand} × {selected_plant_label}",
        )
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        margin=dict(l=32, r=32, t=48, b=32),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=12, color=THEME["text"]),
        title=dict(
            text="Pillar score profile (n=4 weighted dimensions)",
            font=dict(size=14),
        ),
        annotations=[
            dict(
                x=0.5,
                y=-0.12,
                xref="paper",
                yref="paper",
                text="Source: engine scoring model | Representative seed data",
                showarrow=False,
                font=dict(size=10, color=THEME["text_muted"]),
            )
        ],
    )
    render_chart(fig)

    mock_data_badge()
    st.markdown("</div>", unsafe_allow_html=True)
