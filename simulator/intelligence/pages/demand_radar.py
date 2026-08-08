"""Streamlit page: Demand Radar for the off-patent drug intelligence engine.

Shows a sortable drug list with brief pillar A/B/C scores, cluster filters,
and lets the user pick a drug + plant line to evaluate the full four-pillar
score (pillar D).
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from intelligence.api_client import (
    get_molecule,
    get_molecule_demand,
    get_molecule_regulatory,
    list_demand,
    list_molecules,
    list_plants,
    list_regulatory,
    score,
)
from intelligence.palette import THEME, cluster_color, risk_color
from intelligence.ui_components import (
    mock_data_badge,
    page_header,
    render_chart,
    scientific_bullet_chart,
    scientific_gauge,
    scientific_nested_ring,
    scientific_stacked_bar,
)


def _badge(label: str, color: str) -> str:
    return f"<span style='padding:2px 6px; border-radius:3px; background:{color}; color:#fff; font-size:10px; font-weight:800; text-transform:uppercase;'>{label}</span>"


def _fto_color(risk: str) -> str:
    return risk_color(risk)


def _cluster_color(cluster: str) -> str:
    return cluster_color(cluster)


def _demand_score_breakdown(d: dict) -> dict[str, float]:
    """Replicate the demand scorer component breakdown for visualization.

    Returns the raw additive components so they can be stacked.
    """
    components: dict[str, float] = {"base": 10.0}
    combined = (d.get("disease_prevalence_global_millions", 0) or 0) + (d.get("disease_prevalence_india_millions", 0) or 0)
    components["prevalence"] = min(25.0, 8.0 * math.log10(combined + 1)) if combined > 0 else 0.0

    trend = (d.get("growth_trend") or "").lower()
    components["trend"] = {"growing": 15.0, "stable": 5.0, "declining": -10.0}.get(trend, 0.0)

    p3 = d.get("trial_count_phase_3_plus", 0) or 0
    components["pipeline"] = min(20.0, p3 * 2.0)

    cluster_scores = {
        "oncology": 15,
        "specialty injectable": 14,
        "immunology": 13,
        "lifestyle / chronic": 9,
        "lifestyle/chronic": 9,
        "lifestyle": 9,
        "commodity": 4,
    }
    components["cluster_premium"] = float(cluster_scores.get((d.get("cluster") or "").lower(), 8))

    momentum = ((d.get("buyer_activity_score", 0) or 0) + (d.get("market_momentum_score", 0) or 0)) / 2.0
    components["momentum"] = min(15.0, momentum * 0.15)
    return components


def _merge_pillar_summary(molecules, demand_list, regulatory_list):
    """Build a list of dicts with A/B/C summary fields joined by molecule_key."""
    demand_by_key = {d["molecule_key"]: d for d in demand_list}
    reg_by_key = {r["molecule_key"]: r for r in regulatory_list}
    rows = []
    for m in molecules:
        key = m["molecule_key"]
        d = demand_by_key.get(key, {})
        r = reg_by_key.get(key, {})
        components = _demand_score_breakdown(d)
        loe = m.get("earliest_loe")
        rows.append({
            "molecule_key": key,
            "brand_name": m.get("brand_name", ""),
            "api_name": m.get("api_name", ""),
            "therapeutic_area": m.get("therapeutic_area", ""),
            "fto_risk": m.get("fto_risk", "medium"),
            "loe": loe or "off-patent / unknown",
            "export_eligible_count": m.get("export_eligible_count", 0),
            "total_geo_count": m.get("total_geo_count", 0),
            "cluster": d.get("cluster", ""),
            "growth_trend": d.get("growth_trend", ""),
            "disease_area": d.get("disease_area", ""),
            "trial_count_phase_3_plus": d.get("trial_count_phase_3_plus", 0),
            "buyer_activity_score": d.get("buyer_activity_score", 0),
            "market_momentum_score": d.get("market_momentum_score", 0),
            "te_rating": r.get("te_rating", ""),
            "readiness": r.get("readiness", ""),
            "bcs_class": r.get("bcs_class", ""),
            "demand_heat": sum(components.values()),
            **components,
        })
    return rows


def render() -> None:
    page_header(
        pillar="Pillar C — Multi-Factor Demand Trends",
        title="Demand Radar",
        subtitle="Compare molecules by patent, regulatory, and demand signals. Select a drug and plant line to run the full four-pillar evaluation.",
        icon="chart",
    )
    mock_data_badge(use_mock=True)

    molecules = list_molecules()
    demand_list = list_demand()
    regulatory_list = list_regulatory()
    plants = list_plants()

    if not molecules:
        st.warning("No patent intelligence found. Run `just load-patents`.")
        return
    if not demand_list:
        st.warning("No demand signals found. Run `just load-demand`.")
        return

    rows = _merge_pillar_summary(molecules, demand_list, regulatory_list)
    df = pd.DataFrame(rows)

    # Contextual in-page filters
    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            clusters = sorted({c for c in df["cluster"].dropna() if c})
            selected_clusters = st.multiselect("Therapeutic cluster", clusters, default=clusters)
        with c2:
            fto_filter = st.multiselect("FTO risk", ["low", "medium", "high"], default=["low", "medium", "high"])
        with c3:
            trend_filter = st.multiselect("Growth trend", ["growing", "stable", "declining"], default=["growing", "stable", "declining"])
        with c4:
            min_export = st.slider("Min export-eligible markets", 0, int(df["total_geo_count"].max() or 10), 0)

    filtered = df[
        df["cluster"].isin(selected_clusters)
        & df["fto_risk"].isin(fto_filter)
        & df["growth_trend"].isin(trend_filter)
        & (df["export_eligible_count"] >= min_export)
    ].copy()

    st.markdown(f"**{len(filtered)}** molecules match the selected filters.")

    if filtered.empty:
        st.info("No molecules match the current filters.")
        return

    # Decomposed demand stacked bar: each bar is a molecule, segments are the
    # additive components that the demand scorer uses (prevalence, trend, pipeline,
    # cluster premium, momentum).  This is more actionable than a synthetic
    # "demand heat" scatter against LOE.
    stack_cols = ["prevalence", "trend", "pipeline", "cluster_premium", "momentum"]
    bar_df = filtered[["brand_name"] + stack_cols].copy()
    bar_df = bar_df.sort_values(by=stack_cols, ascending=False).head(15)
    stack_fig = scientific_stacked_bar(
        bar_df,
        label_col="brand_name",
        segment_cols=stack_cols,
        title="Demand attractiveness composition (top 15 molecules)",
        source="engine demand signals; n={} molecules".format(len(filtered)),
    )
    render_chart(stack_fig)

    display = filtered.sort_values("demand_heat", ascending=False)[[
        "molecule_key", "brand_name", "api_name", "therapeutic_area",
        "cluster", "fto_risk", "loe", "export_eligible_count", "total_geo_count",
        "growth_trend", "trial_count_phase_3_plus", "te_rating", "readiness",
    ]].copy()
    display.columns = [
        "Key", "Brand", "API", "Therapeutic Area", "Cluster", "FTO", "LOE",
        "Export Mkt", "Total Geo", "Trend", "P3+ Trials", "TE", "Regulatory",
    ]

    st.dataframe(display, width="stretch", hide_index=True)

    # Drug selector for four-pillar scoring
    st.markdown("---")
    st.markdown("### Evaluate plant fit against a selected drug")
    selected_brand = st.selectbox("Select molecule", filtered["brand_name"].tolist())
    selected_key = filtered[filtered["brand_name"] == selected_brand]["molecule_key"].iloc[0]

    if plants:
        plant_options = {f"{p['site_name']} ({p['asset_id']})": p["asset_id"] for p in plants}
        selected_plant_label = st.selectbox("Select plant line / asset", list(plant_options.keys()))
        selected_plant_id = plant_options[selected_plant_label]
    else:
        st.warning("No plant assets found. Run `just load-plant-assets`.")
        selected_plant_id = None

    col1, col2 = st.columns(2)
    with col1:
        weights = {
            "patent": st.slider("Patent weight", 0.0, 1.0, 0.25, 0.05, key="dr_patent"),
            "regulatory": st.slider("Regulatory weight", 0.0, 1.0, 0.20, 0.05, key="dr_regulatory"),
            "demand": st.slider("Demand weight", 0.0, 1.0, 0.25, 0.05, key="dr_demand"),
            "plant": st.slider("Plant weight", 0.0, 1.0, 0.30, 0.05, key="dr_plant"),
        }
    with col2:
        if st.button("Run four-pillar evaluation", type="primary", width="stretch") and selected_plant_id:
            with st.spinner("Scoring…"):
                result = score(selected_key, selected_plant_id, weights=weights)
                st.session_state["last_demand_score"] = result.model_dump(mode="json")

    if "last_demand_score" in st.session_state:
        r = st.session_state["last_demand_score"]
        st.markdown("### Four-pillar score")

        pillar_scores = {
            "Patent": r["patent_readiness_score"],
            "Regulatory": r["regulatory_clarity_score"],
            "Demand": r["demand_attractiveness_score"],
            "Plant Fit": r["plant_fit_score"],
        }
        ring_fig = scientific_nested_ring(
            pillar_scores,
            max_value=100,
            title="Pillar score profile",
            source="engine scoring model",
        )
        render_chart(ring_fig)

        bullet_fig = scientific_bullet_chart(
            pillar_scores,
            target=80,
            max_value=100,
            title="Score completion vs. target",
            source="engine scoring model",
        )
        render_chart(bullet_fig)

        total_col1, total_col2 = st.columns([1, 3])
        with total_col1:
            gauge_fig = scientific_gauge(
                r["total_score"],
                title="Total CDMO Score",
                source="weighted four-pillar composite",
            )
            render_chart(gauge_fig)
        with total_col2:
            st.markdown("#### Rationale")
            for pillar, text in r["explanation"].items():
                if pillar == "tier":
                    continue
                st.caption(f"**{pillar.title()}:** {text}")

        if r["warnings"]:
            st.markdown("#### Warnings")
            for w in r["warnings"]:
                st.warning(w)

    # Optional detail cards for selected molecule
    with st.expander("Selected molecule detail"):
        mol = get_molecule(selected_key) or {}
        dem = get_molecule_demand(selected_key) or {}
        reg = get_molecule_regulatory(selected_key)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Patent**")
            st.write(f"FTO risk: {mol.get('fto_risk', '—')}")
            st.write(f"Earliest LOE: {mol.get('earliest_loe') or '—'}")
            st.write(f"Export markets: {mol.get('export_eligible_count', 0)}/{mol.get('total_geo_count', 0)}")
        with c2:
            st.markdown("**Regulatory**")
            if reg:
                st.write(f"RLD: {reg.get('rld', '—')}")
                st.write(f"TE rating: {reg.get('te_rating', '—')}")
                st.write(f"BCS: {reg.get('bcs_class', '—')}")
                st.write(f"Readiness: {reg.get('readiness', '—')}")
            else:
                st.write("No regulatory passport loaded.")
        with c3:
            st.markdown("**Demand**")
            if dem:
                st.write(f"Cluster: {dem.get('cluster', '—')}")
                st.write(f"Disease area: {dem.get('disease_area', '—')}")
                st.write(f"Growth trend: {dem.get('growth_trend', '—')}")
                st.write(f"P3+ trials: {dem.get('trial_count_phase_3_plus', 0)}")
            else:
                st.write("No demand profile loaded.")
