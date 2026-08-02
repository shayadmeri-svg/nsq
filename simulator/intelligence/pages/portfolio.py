"""Streamlit page: Portfolio Decision Engine (Phase 5).

Provides a ranked, filterable portfolio of molecule × plant candidates,
configurable pillar weights, decision cards with NSQ/roadmap context,
a launch-calendar Gantt view, and CSV/JSON export.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from intelligence.api_client import export_portfolio, list_demand, list_molecules, list_plants, load_portfolio, save_portfolio, score_portfolio
from intelligence.intelligence_models import PortfolioScenario
from intelligence.ui_components import (
    bioicon_inline,
    feature_card,
    metric_tile,
    mock_data_badge,
    page_header,
    render_chart,
    scientific_bar_chart,
    scientific_scatter,
    tier_badge,
)


def _cluster_color(cluster: str) -> str:
    return {
        "oncology": "#8b5cf6",
        "specialty injectable": "#06b6d4",
        "immunology": "#f97316",
        "lifestyle / chronic": "#0ea5e9",
        "lifestyle/chronic": "#0ea5e9",
        "lifestyle": "#0ea5e9",
        "commodity": "#64748b",
    }.get((cluster or "").lower(), "#64748b")


def _build_scenario_from_ui(portfolio_id: str, name: str, description: str, use_mock: bool) -> PortfolioScenario:
    """Collect scenario parameters from the filter panel."""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        w_patent = st.slider("Patent weight", 0.0, 1.0, 0.25, 0.05, key="w_patent")
    with col2:
        w_regulatory = st.slider("Regulatory weight", 0.0, 1.0, 0.20, 0.05, key="w_regulatory")
    with col3:
        w_demand = st.slider("Demand weight", 0.0, 1.0, 0.25, 0.05, key="w_demand")
    with col4:
        w_plant = st.slider("Plant weight", 0.0, 1.0, 0.30, 0.05, key="w_plant")

    total = w_patent + w_regulatory + w_demand + w_plant or 1.0
    weights = {
        "patent": round(w_patent / total, 4),
        "regulatory": round(w_regulatory / total, 4),
        "demand": round(w_demand / total, 4),
        "plant": round(w_plant / total, 4),
    }

    plants = list_plants()
    plant_options = [p["asset_id"] for p in plants]
    plant_labels = {p["asset_id"]: f"{p['site_name']} ({p['asset_id']})" for p in plants}

    demands = list_demand()
    clusters = sorted({d.get("cluster", "") for d in demands if d.get("cluster")})

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        selected_plants = st.multiselect("Plant lines", [plant_labels[a] for a in plant_options], default=[plant_labels[a] for a in plant_options], key="pf_plants")
        plant_asset_ids = [a for a in plant_options if plant_labels[a] in selected_plants]
    with c2:
        selected_clusters = st.multiselect("Therapeutic clusters", clusters, default=clusters, key="pf_clusters")
    with c3:
        fto_allowed = st.multiselect("FTO risk allowed", ["low", "medium", "high"], default=["low", "medium"], key="pf_fto")
    with c4:
        min_score = st.slider("Minimum total score", 0, 100, 50, key="pf_min_score")

    max_loe = st.slider("Max LOE horizon (years)", 0.0, 15.0, 10.0, 0.5, key="pf_max_loe")
    include_stretch = st.toggle("Include stretch candidates", value=False, key="pf_stretch")

    return PortfolioScenario(
        scenario_id=portfolio_id,
        name=name,
        description=description,
        weights=weights,
        plant_asset_ids=plant_asset_ids,
        clusters=selected_clusters,
        min_total_score=float(min_score),
        max_loe_years=max_loe,
        fto_risks_allowed=fto_allowed,
        include_stretch=include_stretch,
        use_mock_data=use_mock,
    )


def _rank_table(entries: list[dict]) -> pd.DataFrame:
    rows = []
    for idx, e in enumerate(entries, 1):
        rows.append({
            "Rank": idx,
            "Molecule": e.get("brand_name") or e.get("molecule_key"),
            "API": e.get("api_name", ""),
            "Plant": e.get("plant_site_name", ""),
            "Cluster": e.get("cluster", ""),
            "Tier": e.get("commercial_fit_tier", ""),
            "Patent": round(e.get("patent_readiness_score", 0), 1),
            "Regulatory": round(e.get("regulatory_clarity_score", 0), 1),
            "Demand": round(e.get("demand_attractiveness_score", 0), 1),
            "Plant Fit": round(e.get("plant_fit_score", 0), 1),
            "Total": round(e.get("total_score", 0), 1),
            "Roadmap (mo)": e.get("estimated_roadmap_months", 0),
            "FTO": e.get("fto_risk", ""),
            "LOE (yr)": e.get("loe_years") if e.get("loe_years") is not None else "—",
        })
    return pd.DataFrame(rows)


def _render_summary(summary: dict) -> None:
    cols = st.columns(6)
    metrics = [
        ("Candidates", summary.get("included_count", 0)),
        ("Mean score", summary.get("mean_total_score", 0)),
        ("Strategic", summary.get("strategic_count", 0)),
        ("Core", summary.get("core_count", 0)),
        ("Adjacent", summary.get("adjacent_count", 0)),
        ("Stretch", summary.get("stretch_count", 0)),
    ]
    for col, (label, value) in zip(cols, metrics):
        with col:
            metric_tile(label, value)


def _render_decision_cards(entries: list[dict]) -> None:
    st.markdown("### Ranked candidates")
    for idx, e in enumerate(entries[:20], 1):  # cap interactive cards at 20
        with st.expander(f"#{idx} {e.get('brand_name') or e.get('molecule_key')} @ {e.get('plant_site_name')} — Total {e.get('total_score', 0):.0f}", expanded=idx <= 3):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(
                    f"""
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                      {tier_badge(e.get('commercial_fit_tier', 'stretch'))}
                      <span style="font-size:12px; color:#64748b;">Modality: {e.get('modality', '—')} | Form: {e.get('drug_form', '—')} | Sterility: {'Yes' if e.get('sterility_required') else 'No'}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                score_cols = st.columns(4)
                score_cols[0].metric("Patent", f"{e.get('patent_readiness_score', 0):.0f}")
                score_cols[1].metric("Regulatory", f"{e.get('regulatory_clarity_score', 0):.0f}")
                score_cols[2].metric("Demand", f"{e.get('demand_attractiveness_score', 0):.0f}")
                score_cols[3].metric("Plant Fit", f"{e.get('plant_fit_score', 0):.0f}")

                gaps = e.get("gaps") or []
                if gaps:
                    st.markdown("**Capability / certification / talent gaps**")
                    for g in gaps:
                        st.markdown(f"- {g}")
                warnings = e.get("warnings") or []
                if warnings:
                    st.markdown("**Risk warnings**")
                    for w in warnings:
                        st.warning(w)
            with c2:
                st.metric("Roadmap", f"{e.get('estimated_roadmap_months', 0)} mo")
                st.metric("LOE", f"{e.get('loe_years'):.1f} yr" if e.get("loe_years") is not None else "—")
                st.markdown(
                    f"[Open Plant Readiness →](/Plant_Readiness)"
                    if False
                    else f"*Use Plant Readiness tab for detailed roadmap.*"
                )


def _render_charts(entries: list[dict], weights: dict) -> None:
    if not entries:
        return
    df = pd.DataFrame(entries)

    c1, c2 = st.columns(2)
    with c1:
        top10 = df.head(10).copy()
        top10["label"] = top10["brand_name"].fillna(top10["molecule_key"]) + " @ " + top10["plant_site_name"].fillna(top10["plant_asset_id"])
        fig = scientific_bar_chart(
            top10,
            x="total_score",
            y="label",
            title="Top 10 candidates by total CDMO score",
            y_label="Candidate",
            source="Engine four-pillar scoring; n={} molecule×plant combinations".format(len(df)),
            stat_note="Score = weighted mean of patent ({:.0f}%), regulatory ({:.0f}%), demand ({:.0f}%), plant ({:.0f}%).".format(
                weights["patent"] * 100, weights["regulatory"] * 100, weights["demand"] * 100, weights["plant"] * 100
            ),
            color="#0f172a",
            hover_template="%{y}<br>Total score: %{x:.1f}<extra></extra>",
        )
        fig.update_layout(yaxis=dict(autorange="reversed"))
        render_chart(fig)

    with c2:
        fig2 = scientific_scatter(
            df,
            x="plant_fit_score",
            y="demand_attractiveness_score",
            title="Demand attractiveness vs. plant fit",
            x_label="Plant fit score (0–100)",
            y_label="Demand attractiveness (0–100)",
            source="Engine scoring; candidate population n={}".format(len(df)),
            stat_note="Each point is one molecule × plant line; point size ∝ total score.",
            color_col="total_score",
            size_col="total_score",
            hover_name="brand_name",
        )
        render_chart(fig2)


def _render_launch_calendar(entries: list[dict]) -> None:
    if not entries:
        return
    st.markdown("### Launch calendar")
    df = pd.DataFrame(entries[:15]).copy()
    df["label"] = df["brand_name"].fillna(df["molecule_key"]) + " @ " + df["plant_site_name"].fillna(df["plant_asset_id"])
    df["start"] = 0
    df["duration"] = df["estimated_roadmap_months"].fillna(0)
    df["color"] = df["cluster"].apply(_cluster_color)

    fig = go.Figure()
    for _, row in df.iterrows():
        fig.add_trace(
            go.Bar(
                y=[row["label"]],
                x=[row["duration"]],
                base=[row["start"]],
                orientation="h",
                marker_color=row["color"],
                hovertemplate="%{y}<br>Roadmap: %{x} mo<extra></extra>",
                showlegend=False,
            )
        )
    fig.update_layout(
        title={"text": "Estimated roadmap duration by candidate", "font": {"size": 14, "color": "#0f172a"}, "x": 0, "xanchor": "left"},
        xaxis_title="Months",
        yaxis_title="",
        barmode="stack",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, sans-serif", "color": "#0f172a", "size": 11},
        margin={"l": 160, "r": 16, "t": 48, "b": 64},
        yaxis=dict(autorange="reversed"),
    )
    fig.add_annotation(
        text="Source: Manufacturing roadmap phases generated from patent/regulatory signals. Durations are indicative estimates.",
        xref="paper",
        yref="paper",
        x=0,
        y=-0.18,
        showarrow=False,
        font={"size": 9, "color": "#64748b"},
        align="left",
    )
    render_chart(fig)


def render() -> None:
    page_header(
        pillar="Phase 5 — Portfolio Decision Engine",
        title="Portfolio Builder",
        subtitle="Rank molecule × plant candidates by configurable pillar weights, compare scenarios, and export launch calendars.",
        icon="chart",
    )

    mock_data_badge(use_mock=True)

    molecules = list_molecules()
    plants = list_plants()
    if not molecules or not plants:
        st.warning("Molecule or plant data not loaded. Run `just load-intelligence` to seed Redis.")
        return

    with st.expander("Scenario settings", expanded=True):
        c1, c2 = st.columns([2, 1])
        with c1:
            portfolio_id = st.text_input("Scenario ID", value="default-portfolio", key="pf_id")
        with c2:
            portfolio_name = st.text_input("Scenario name", value="Base case", key="pf_name")
        portfolio_description = st.text_area("Description", value="Mid-tier CDMO base-case portfolio weights.", key="pf_desc", height=60)

        scenario = _build_scenario_from_ui(portfolio_id, portfolio_name, portfolio_description, use_mock=True)

        run_clicked = st.button("Run portfolio scoring", type="primary", use_container_width=True)

    if run_clicked:
        with st.spinner("Ranking candidates across molecules and plant lines…"):
            snapshot = score_portfolio(scenario)

        if snapshot is None:
            st.error("Could not compute portfolio. Ensure the engine and Redis are available.")
            return

        st.session_state["last_portfolio_snapshot"] = snapshot
        st.session_state["last_portfolio_scenario"] = scenario

    snapshot = st.session_state.get("last_portfolio_snapshot")
    if not snapshot:
        st.info("Configure the scenario above and click **Run portfolio scoring**.")
        return

    entries = snapshot.get("entries", [])
    summary = snapshot.get("summary", {})
    weights = summary.get("weights_applied", scenario.weights)

    st.markdown("---")
    _render_summary(summary)

    st.markdown("---")
    _render_charts(entries, weights)

    st.markdown("---")
    _render_decision_cards(entries)

    st.markdown("---")
    _render_launch_calendar(entries)

    st.markdown("---")
    st.markdown("### Export & save")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Save to Redis", use_container_width=True):
            result = save_portfolio(portfolio_id, scenario)
            if result:
                st.success(f"Saved portfolio `{portfolio_id}` to Redis.")
            else:
                st.error("Could not save portfolio via API.")
    with c2:
        if st.button("Export JSON", use_container_width=True):
            exported = export_portfolio(portfolio_id, "json")
            if exported:
                st.download_button(
                    label="Download JSON",
                    data=json.dumps(exported, indent=2),
                    file_name=f"{portfolio_id}.json",
                    mime="application/json",
                    use_container_width=True,
                )
    with c3:
        if st.button("Export CSV", use_container_width=True):
            exported = export_portfolio(portfolio_id, "csv")
            if exported:
                st.download_button(
                    label="Download CSV",
                    data=json.dumps(exported),
                    file_name=f"{portfolio_id}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
