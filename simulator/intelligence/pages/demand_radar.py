"""Streamlit page: Demand Radar for the off-patent drug intelligence engine.

Shows a sortable drug list with brief pillar A/B/C scores, cluster filters,
and lets the user pick a drug + plant line to evaluate the full four-pillar
score (pillar D).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from intelligence.api_client import (
    get_molecule,
    get_molecule_demand,
    get_molecule_regulatory,
    list_demand,
    list_molecules,
    list_plants,
    score,
)
from intelligence.palette import BLUE, THEME, cluster_color, risk_color
from intelligence.ui_components import mock_data_badge, page_header, scientific_scatter, render_chart


def _badge(label: str, color: str) -> str:
    return f"<span style='padding:2px 6px; border-radius:3px; background:{color}; color:#fff; font-size:10px; font-weight:800; text-transform:uppercase;'>{label}</span>"


def _fto_color(risk: str) -> str:
    return risk_color(risk)


def _cluster_color(cluster: str) -> str:
    return cluster_color(cluster)


def _merge_pillar_summary(molecules, demand_list, regulatory_list):
    """Build a list of dicts with A/B/C summary fields joined by molecule_key."""
    demand_by_key = {d["molecule_key"]: d for d in demand_list}
    reg_by_key = {r["molecule_key"]: r for r in regulatory_list}
    rows = []
    for m in molecules:
        key = m["molecule_key"]
        d = demand_by_key.get(key, {})
        r = reg_by_key.get(key, {})
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

    # Scientific scatter: demand heat vs. LOE horizon
    filtered["demand_heat"] = filtered["buyer_activity_score"] + filtered["market_momentum_score"]
    scatter_df = filtered.copy()
    scatter_df["loe_numeric"] = pd.to_numeric(scatter_df["loe"].replace("off-patent / unknown", pd.NA), errors="coerce")
    fig = scientific_scatter(
        scatter_df,
        x="loe_numeric",
        y="demand_heat",
        title="Demand heat vs. LOE horizon",
        x_label="Years to earliest LOE",
        y_label="Demand heat proxy (buyer + momentum, 0–200)",
        source="Engine demand signals; n={} molecules".format(len(scatter_df)),
        stat_note="Higher values indicate stronger near-term demand; missing LOE shown as off-patent/unknown.",
        color_col="trial_count_phase_3_plus",
        size_col="market_momentum_score",
        hover_name="brand_name",
    )
    render_chart(fig)

    display = filtered.sort_values("demand_heat", ascending=False)[[
        "molecule_key", "brand_name", "api_name", "therapeutic_area",
        "cluster", "fto_risk", "loe", "export_eligible_count", "total_geo_count",
        "growth_trend", "trial_count_phase_3_plus", "te_rating", "readiness",
    ]].copy()
    display.columns = [
        "Key", "Brand", "API", "Therapeutic Area", "Cluster", "FTO", "LOE",
        "Export Mkt", "Total Geo", "Trend", "P3+ Trials", "TE", "Regulatory",
    ]

    st.dataframe(display, use_container_width=True, hide_index=True)

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
        if st.button("Run four-pillar evaluation", type="primary", use_container_width=True) and selected_plant_id:
            with st.spinner("Scoring…"):
                result = score(selected_key, selected_plant_id, weights=weights)
                st.session_state["last_demand_score"] = result.model_dump(mode="json")

    if "last_demand_score" in st.session_state:
        r = st.session_state["last_demand_score"]
        st.markdown("#### Four-pillar score")
        score_df = pd.DataFrame([{
            "Pillar": "Patent readiness",
            "Score": r["patent_readiness_score"],
            "Explanation": r["explanation"]["patent"],
        }, {
            "Pillar": "Regulatory clarity",
            "Score": r["regulatory_clarity_score"],
            "Explanation": r["explanation"]["regulatory"],
        }, {
            "Pillar": "Demand attractiveness",
            "Score": r["demand_attractiveness_score"],
            "Explanation": r["explanation"]["demand"],
        }, {
            "Pillar": "Plant fit",
            "Score": r["plant_fit_score"],
            "Explanation": r["explanation"]["plant"],
        }])
        st.dataframe(score_df, use_container_width=True, hide_index=True)
        st.markdown(
            f"""
            <div style="border:1px solid {THEME['border']}; border-radius:6px; padding:16px; background:{THEME['surface']}; text-align:center;">
              <div style="font-size:12px; color:{THEME['text_muted']};">Total CDMO Score</div>
              <div style="font-size:40px; font-weight:900; color:{THEME['primary']};">{r['total_score']:.0f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if r["warnings"]:
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
