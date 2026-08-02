"""Streamlit page: Plant Readiness & Manufacturing Roadmap.

Evaluates a selected plant line against a molecule's manufacturing complexity,
customer profile fit (infrastructure, talent, certifications), and generates a
modality-specific roadmap:
- Off-patent small molecules: API buy/build, scale-up, regulatory/BE, NSQ prevention.
- Biosimilars / peptides: reference characterization, protocol design, development
  & testing, clinical/PK-PD, scale-up.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from intelligence.api_client import (
    get_molecule,
    get_molecule_complexity,
    get_molecule_regulatory,
    get_molecule_roadmap,
    get_plant_fit_summary,
    list_molecules,
    list_plants,
    score,
)
from intelligence.palette import THEME
from intelligence.ui_components import (
    anime_entrance,
    metric_tile,
    mock_data_badge,
    page_header,
    render_chart,
    scientific_bar_chart,
    tier_badge,
)


def _render_complexity(complexity: dict | None) -> None:
    if not complexity:
        st.warning("No manufacturing complexity data available.")
        return

    cols = st.columns(4)
    metrics = [
        ("Modality", complexity.get("modality", "—")),
        ("Drug form", complexity.get("drug_form", "—")),
        ("Route", complexity.get("route_of_administration", "—")),
        ("Sterility", "Required" if complexity.get("sterility_required") else "Not required"),
    ]
    for col, (label, value) in zip(cols, metrics):
        with col:
            metric_tile(label, value)

    st.markdown("#### Critical Quality Attributes")
    cqas = complexity.get("critical_quality_attributes") or []
    if cqas:
        st.markdown(
            "".join(
                f"<span style='padding:2px 6px; border-radius:3px; background:{THEME['surface_subtle']}; color:{THEME['text_secondary']}; font-size:10px; margin-right:6px;'>{c}</span>"
                for c in cqas
            ),
            unsafe_allow_html=True,
        )
    else:
        st.caption("No CQAs inferred.")

    st.markdown("#### Complexity scores")
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_tile("Process", f"{complexity.get('process_complexity_score', 0):.1f}")
    with c2:
        metric_tile("Analytical", f"{complexity.get('analytical_complexity_score', 0):.1f}")
    with c3:
        metric_tile("Biologic", f"{complexity.get('biologic_complexity_score', 0):.1f}")

    notes = complexity.get("notes", "")
    if notes:
        st.caption(notes)


def _render_customer_fit(fit: dict | None) -> None:
    if not fit:
        return

    tier = fit.get("commercial_fit_tier", "stretch")
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div><strong>Commercial fit tier:</strong> {tier_badge(tier)}</div>
          <div><strong>Overall fit score:</strong> {fit.get('customer_profile_fit_score', 0):.0f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        metric_tile("Infrastructure", f"{fit.get('infrastructure_fit_score', 0):.0f}")
    with c2:
        metric_tile("Talent", f"{fit.get('talent_fit_score', 0):.0f}")
    with c3:
        metric_tile("Certifications", f"{fit.get('certification_fit_score', 0):.0f}")

    gaps = fit.get("gaps") or []
    if gaps:
        st.markdown("#### Capability / certification / talent gaps")
        for g in gaps:
            st.error(g)


def _render_roadmap(roadmap: list[dict] | None, government_notes: str = "", nsq_notes: str = "") -> None:
    if not roadmap:
        st.info("No roadmap generated.")
        return

    st.markdown("#### Manufacturing roadmap")
    total_months = sum(p.get("estimated_duration_months", 0) for p in roadmap)
    st.caption(
        f"Estimated total duration: **{total_months} months** "
        f"({total_months // 12} years, {total_months % 12} months)"
    )

    for idx, phase in enumerate(roadmap, 1):
        with st.expander(
            f"{idx}. {phase.get('title', 'Phase')} ({phase.get('estimated_duration_months', 0)} mo)",
            expanded=False,
        ):
            st.markdown("**Activities**")
            for a in phase.get("activities", []):
                st.markdown(f"- {a}")
            st.markdown("**Deliverables**")
            for d in phase.get("deliverables", []):
                st.markdown(f"- {d}")
            st.markdown("**Readiness gates**")
            for g in phase.get("readiness_gates", []):
                st.markdown(f"- {g}")
            req = phase.get("required_capabilities") or []
            if req:
                st.markdown("**Required capabilities:** " + ", ".join(req))

    if government_notes:
        st.markdown("#### Government support / incentives")
        st.info(government_notes)

    if nsq_notes:
        st.markdown("#### NSQ / QbD risk note")
        st.info(nsq_notes)


def render() -> None:
    page_header(
        pillar="Pillar D — Plant Expertise & Shop-Floor AI",
        title="Plant Readiness & Roadmap",
        subtitle="Patent mining → biochemistry analytics → customer profile fit → manufacturing roadmap (small molecule or biosimilar).",
        icon="microscope",
    )

    molecules = list_molecules()
    plants = list_plants()

    if not molecules:
        st.warning("No patent intelligence found. Run `just load-patents`.")
        return
    if not plants:
        st.warning("No plant assets found. Run `just load-plant-assets`.")
        return

    with st.expander("Filter & select candidate", expanded=True):
        options = {m["brand_name"]: m["molecule_key"] for m in molecules}
        selected_brand = st.selectbox("Molecule", list(options.keys()))
        selected_key = options[selected_brand]

        plant_options = {f"{p['site_name']} ({p['asset_id']})": p["asset_id"] for p in plants}
        selected_plant_label = st.selectbox("Plant line / asset", list(plant_options.keys()))
        selected_plant_id = plant_options[selected_plant_label]

    complexity = get_molecule_complexity(selected_key)
    roadmap_data = get_molecule_roadmap(selected_key, selected_plant_id)
    fit_summary = get_plant_fit_summary(selected_plant_id, selected_key)
    molecule = get_molecule(selected_key) or {}
    regulatory = get_molecule_regulatory(selected_key)

    anime_entrance("#readiness-results", "fadeIn")
    st.markdown('<div id="readiness-results">', unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1], gap="medium")
    with col1:
        st.markdown("### Biochemistry / manufacturing analytics")
        _render_complexity(complexity)
    with col2:
        st.markdown("### Customer profile fit")
        _render_customer_fit(fit_summary.get("customer_profile_fit") if fit_summary else None)

    st.markdown("---")
    _render_roadmap(
        roadmap_data.get("roadmap") if roadmap_data else None,
        government_notes=roadmap_data.get("government_support_notes", "") if roadmap_data else "",
        nsq_notes=roadmap_data.get("nsq_risk_notes", "") if roadmap_data else "",
    )

    st.markdown("---")
    st.markdown("### Four-pillar score for this molecule × plant")
    try:
        result = score(selected_key, selected_plant_id).model_dump(mode="json")
    except Exception as exc:
        st.error(f"Could not score: {exc}")
        return

    score_df = pd.DataFrame(
        [
            {"Pillar": "Patent readiness", "Score": result["patent_readiness_score"]},
            {"Pillar": "Regulatory clarity", "Score": result["regulatory_clarity_score"]},
            {"Pillar": "Demand attractiveness", "Score": result["demand_attractiveness_score"]},
            {"Pillar": "Plant fit", "Score": result["plant_fit_score"]},
        ]
    )
    fig = scientific_bar_chart(
        score_df,
        x="Pillar",
        y="Score",
        title="Four-pillar score profile",
        y_label="Score (0–100)",
        source="engine scoring model",
        stat_note="n=4 pillars; weighted composite shown separately",
    )
    render_chart(fig)

    total = result.get("total_score", 0)
    metric_tile("Total CDMO Score", f"{total:.0f}")

    warnings = result.get("warnings") or []
    if warnings:
        for w in warnings:
            st.warning(w)

    with st.expander("Molecule patent & regulatory summary"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Patent**")
            st.write(f"FTO risk: {molecule.get('fto_risk', '—')}")
            st.write(f"Earliest LOE: {molecule.get('earliest_loe') or '—'}")
            st.write(
                f"Export markets: {molecule.get('export_eligible_count', 0)}/{molecule.get('total_geo_count', 0)}"
            )
        with c2:
            st.markdown("**Regulatory**")
            if regulatory:
                st.write(f"RLD: {regulatory.get('rld', '—')}")
                st.write(f"TE rating: {regulatory.get('te_rating', '—')}")
                st.write(f"BCS: {regulatory.get('bcs_class', '—')}")
                st.write(f"Readiness: {regulatory.get('readiness', '—')}")
            else:
                st.write("No regulatory passport loaded.")

    mock_data_badge()
    st.markdown("</div>", unsafe_allow_html=True)
