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
    humanize_enum,
    metric_tile,
    mock_data_badge,
    page_header,
    render_chart,
    render_gmp_pillars,
    scientific_bullet_chart,
    scientific_gauge,
    scientific_nested_ring,
    scientific_phase_gantt,
    tier_badge,
)


def _render_complexity(complexity: dict | None) -> None:
    if not complexity:
        st.warning("No manufacturing complexity data available.")
        return

    cols = st.columns(4)
    metrics = [
        ("Modality", humanize_enum(complexity.get("modality"))),
        ("Drug form", humanize_enum(complexity.get("drug_form"))),
        ("Route", humanize_enum(complexity.get("route_of_administration"))),
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
    complexity_scores = {
        "Process": complexity.get("process_complexity_score", 0),
        "Analytical": complexity.get("analytical_complexity_score", 0),
        "Biologic": complexity.get("biologic_complexity_score", 0),
    }
    complexity_fig = scientific_bullet_chart(
        complexity_scores,
        target=7.0,
        max_value=10.0,
        title="Manufacturing complexity vs. high-complexity benchmark",
        source="engine complexity model (0–10 scale)",
    )
    render_chart(complexity_fig)
    st.caption(f"GMP methodological pillars triggered: **{len(complexity.get('gmp_pillars', []))}**")

    notes = complexity.get("notes", "")
    if notes:
        st.caption(notes)


def _render_gmp_pillars_card(complexity: dict | None, plant_row: dict | None) -> None:
    pillars = complexity.get("gmp_pillars") or [] if complexity else []
    if not pillars:
        return

    plant_caps: set[str] = set()
    if plant_row:
        plant_caps.update((c or "").lower() for c in plant_row.get("capabilities", []))
        for train in plant_row.get("equipment_trains") or []:
            cap = (train.get("capability") or "").lower()
            if cap:
                plant_caps.add(cap)

    html = render_gmp_pillars(pillars, plant_capabilities=plant_caps, show_title=True)
    if html:
        st.markdown(html, unsafe_allow_html=True)


def _render_customer_fit(fit: dict | None) -> None:
    if not fit:
        return

    tier = fit.get("commercial_fit_tier", "stretch")
    overall = fit.get("customer_profile_fit_score", 0)
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div><strong>Commercial fit tier:</strong> {tier_badge(tier)}</div>
          <div><strong>Overall fit score:</strong> {overall:.0f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    fit_values = {
        "Infrastructure": fit.get("infrastructure_fit_score", 0),
        "Talent": fit.get("talent_fit_score", 0),
        "Certifications": fit.get("certification_fit_score", 0),
        "GMP Readiness": fit.get("gmp_readiness_score", 0),
    }
    ring_fig = scientific_nested_ring(
        fit_values,
        max_value=100,
        title="Customer profile fit dimensions",
        source="engine customer-profile scoring",
    )
    render_chart(ring_fig)

    gaps = fit.get("gaps") or []
    if gaps:
        st.markdown("#### Capability / certification / talent gaps")
        for g in gaps:
            st.error(g)


def _render_roadmap(roadmap: list[dict] | None, government_notes: str = "", nsq_notes: str = "") -> None:
    if not roadmap:
        st.info("No roadmap generated.")
        return

    st.markdown("### Manufacturing roadmap")
    total_months = sum(p.get("estimated_duration_months", 0) for p in roadmap)
    st.caption(
        f"Estimated total duration: **{total_months} months** "
        f"({total_months // 12} years, {total_months % 12} months)"
    )

    gantt_fig = scientific_phase_gantt(
        roadmap,
        title="Roadmap phase timeline",
        source="manufacturing roadmap generated from patent/regulatory signals",
    )
    render_chart(gantt_fig)

    st.markdown("#### Phase details")
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

    # Pre-select a molecule sent from the Product Catalog.
    pending_molecule_key = st.session_state.pop("pending_molecule_key", None)
    options = {m["brand_name"]: m["molecule_key"] for m in molecules}
    option_labels = list(options.keys())
    mol_default_index = 0
    if pending_molecule_key:
        mol_default_index = next(
            (i for i, label in enumerate(option_labels) if options[label] == pending_molecule_key),
            0,
        )

    # Pre-select a plant that was just created in the Plant Builder.
    pending_plant_id = st.session_state.pop("pending_plant_id", None)
    plant_options = {f"{p['site_name']} ({p['asset_id']})": p["asset_id"] for p in plants}
    plant_labels = list(plant_options.keys())
    plant_default_index = 0
    if pending_plant_id:
        plant_default_index = next(
            (i for i, label in enumerate(plant_labels) if plant_options[label] == pending_plant_id),
            0,
        )

    with st.expander("Filter & select candidate", expanded=True):
        selected_brand = st.selectbox(
            "Molecule",
            option_labels,
            index=mol_default_index,
        )
        selected_key = options[selected_brand]

        selected_plant_label = st.selectbox(
            "Plant line / asset",
            plant_labels,
            index=plant_default_index,
        )
        selected_plant_id = plant_options[selected_plant_label]

    plant_row = next((p for p in plants if p["asset_id"] == selected_plant_id), None)

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

    st.markdown("### GMP methodological context")
    _render_gmp_pillars_card(complexity, plant_row)

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

    pillar_scores = {
        "Patent readiness": result["patent_readiness_score"],
        "Regulatory clarity": result["regulatory_clarity_score"],
        "Demand attractiveness": result["demand_attractiveness_score"],
        "Plant fit": result["plant_fit_score"],
    }
    bullet_fig = scientific_bullet_chart(
        pillar_scores,
        target=80,
        max_value=100,
        title="Four-pillar score completion vs. target",
        source="engine scoring model",
    )
    render_chart(bullet_fig)

    total = result.get("total_score", 0)
    total_col1, total_col2 = st.columns([1, 3])
    with total_col1:
        gauge_fig = scientific_gauge(
            total,
            title="Total CDMO Score",
            source="weighted four-pillar composite",
        )
        render_chart(gauge_fig)
    with total_col2:
        st.markdown("#### Score rationale")
        for pillar, text in result.get("explanation", {}).items():
            if pillar == "tier":
                continue
            st.caption(f"**{pillar.title()}:** {text}")

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
