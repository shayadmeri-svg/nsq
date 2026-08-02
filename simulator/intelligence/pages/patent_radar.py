"""Streamlit page: Patent Radar for the off-patent drug intelligence engine.

Displays a 3–5 year LOE horizon, FTO risk table, and candidate shortlist builder.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from intelligence.api_client import list_molecules, score
from intelligence.palette import THEME, risk_color
from intelligence.ui_components import mock_data_badge, page_header, render_chart, scientific_scatter


def _risk_color(risk: str) -> str:
    return risk_color(risk)


def _loe_days(loe: str | None) -> int | None:
    if not loe:
        return None
    try:
        d = date.fromisoformat(loe)
        return (d - date.today()).days
    except ValueError:
        return None


def render() -> None:
    page_header(
        pillar="Pillar A — Patent Intelligence",
        title="Patent Radar",
        subtitle="Global loss-of-exclusivity mapping, FTO risk flags, and candidate shortlist builder.",
        icon="dna",
    )
    mock_data_badge(use_mock=True)

    if "shortlist" not in st.session_state:
        st.session_state.shortlist = []

    molecules = list_molecules()
    if not molecules:
        st.warning(
            "No patent intelligence found in Redis. Run `just load-patents` to seed the engine."
        )
        return

    df = pd.DataFrame(molecules)
    df["loe_days"] = df["earliest_loe"].apply(_loe_days)
    df["loe_label"] = df["earliest_loe"].fillna("off-patent / unknown")
    df["loe_years"] = df["loe_days"].apply(lambda d: round(d / 365.25, 2) if d is not None else None)
    df["geo_badge"] = df.apply(
        lambda r: f"{r.get('export_eligible_count', 0)}/{r.get('total_geo_count', 0)} export-eligible",
        axis=1,
    )

    # Filters + shortlist summary
    with st.expander("Shortlist & filters", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            st.markdown(f"**{len(st.session_state.shortlist)}** candidates selected")
            if st.session_state.shortlist:
                st.markdown(
                    ", ".join(f"`{m}`" for m in st.session_state.shortlist)
                )
        with c2:
            fto_filter = st.multiselect("FTO risk", ["low", "medium", "high"], default=["low", "medium", "high"], key="pr_fto")
        with c3:
            if st.session_state.shortlist and st.button("Clear shortlist"):
                st.session_state.shortlist = []
                st.rerun()

    filtered = df[df["fto_risk"].isin(fto_filter)].copy()

    # Scientific scatter: LOE horizon vs. export market count
    scatter_df = filtered.dropna(subset=["loe_years"]).copy()
    if not scatter_df.empty:
        fig = scientific_scatter(
            scatter_df,
            x="loe_years",
            y="export_eligible_count",
            title="LOE horizon vs. export-eligible market count",
            x_label="Years to earliest LOE",
            y_label="Export-eligible countries",
            source="Engine patent intelligence; n={} molecules".format(len(scatter_df)),
            stat_note="Point color = FTO risk; missing LOE dates excluded.",
            color_col="loe_days",
            size_col=[10] * len(scatter_df),
            hover_name="brand_name",
        )
        render_chart(fig)
    else:
        st.info("No LOE dates available for the loaded molecules.")

    # Patent table
    st.subheader("Molecule Patent Passport")
    display = filtered[[
        "brand_name", "api_name", "therapeutic_area", "fto_risk", "loe_label", "loe_days", "geo_badge"
    ]].copy()
    display.columns = ["Brand", "API", "Therapeutic Area", "FTO Risk", "Earliest LOE", "Days to LOE", "Export Markets"]

    def _badge(risk: str) -> str:
        color = _risk_color(risk)
        return f"<span style='padding:2px 6px; border-radius:3px; background:{color}; color:#fff; font-size:10px; font-weight:800; text-transform:uppercase;'>{risk}</span>"

    st.markdown(
        display.to_html(escape=False, index=False, classes="table"),
        unsafe_allow_html=True,
    )

    # Add-to-shortlist per molecule
    st.subheader("Add candidates")
    cols = st.columns(3)
    for idx, row in filtered.iterrows():
        with cols[idx % 3]:
            key = row["molecule_key"]
            selected = key in st.session_state.shortlist
            st.markdown(
                f"""
                <div style="border:1px solid {THEME['border']}; border-radius:6px; padding:12px; background:{THEME['surface']};">
                  <div style="font-weight:700; color:{THEME['text']};">{row['brand_name']}</div>
                  <div style="font-size:11px; color:{THEME['text_secondary']};">{row['api_name']} · {row['therapeutic_area']}</div>
                  <div style="margin-top:6px;">{_badge(row['fto_risk'])}</div>
                  <div style="font-size:11px; color:{THEME['text_muted']}; margin-top:4px;">LOE: {row['loe_label']}</div>
                  <div style="font-size:11px; color:{THEME['text_secondary']}; margin-top:4px;">{row['geo_badge']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if selected:
                if st.button(f"Remove {key}", key=f"remove_{key}"):
                    st.session_state.shortlist.remove(key)
                    st.rerun()
            else:
                if st.button(f"Add {key}", key=f"add_{key}"):
                    st.session_state.shortlist.append(key)
                    st.rerun()

    # Quick score against a default plant if candidates selected
    if st.session_state.shortlist:
        st.subheader("Quick score shortlist")
        plants = [p for p in ["baddi-osd-a"] if p]
        selected_plant = st.selectbox("Plant line", plants, key="pr_plant")
        weights = {
            "patent": st.slider("Patent weight", 0.0, 1.0, 0.25, 0.05, key="pr_w_patent"),
            "regulatory": st.slider("Regulatory weight", 0.0, 1.0, 0.20, 0.05, key="pr_w_regulatory"),
            "demand": st.slider("Demand weight", 0.0, 1.0, 0.25, 0.05, key="pr_w_demand"),
            "plant": st.slider("Plant weight", 0.0, 1.0, 0.30, 0.05, key="pr_w_plant"),
        }
        if st.button("Score shortlist", type="primary"):
            with st.spinner("Scoring candidates…"):
                results = []
                for key in st.session_state.shortlist:
                    try:
                        result = score(key, selected_plant, weights=weights)
                        results.append(result.model_dump(mode="json"))
                    except Exception as exc:
                        st.error(f"Failed to score {key}: {exc}")
                if results:
                    score_df = pd.DataFrame(results)
                    score_df = score_df[["molecule_key", "patent_readiness_score", "plant_fit_score", "total_score", "fto_risk"]]
                    score_df.columns = ["Molecule", "Patent", "Plant Fit", "Total", "FTO Risk"]
                    st.dataframe(score_df.sort_values("Total", ascending=False), use_container_width=True, hide_index=True)
