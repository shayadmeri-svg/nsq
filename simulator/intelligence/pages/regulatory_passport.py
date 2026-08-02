"""Streamlit page: Regulatory Passport for the off-patent drug intelligence engine.

Displays pharmacopeia monographs, Orange Book RLD/TE/exclusivity data, BCS class,
and export-eligible geographies for a selected molecule.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from intelligence.api_client import (
    get_molecule,
    get_molecule_geo,
    get_molecule_regulatory,
    list_molecules,
    score,
)
from intelligence.palette import THEME, VERMILION
from intelligence.ui_components import (
    anime_entrance,
    metric_tile,
    mock_data_badge,
    page_header,
    tier_badge,
)


def _render_passport(passport: dict) -> None:
    rld = passport.get("rld", "")
    applicant = passport.get("rld_applicant", "")
    te_code = passport.get("te_code", "")
    te_rating = passport.get("te_rating", "")
    bcs = passport.get("bcs_class", "")
    dosage = passport.get("dosage_form", "")
    strength = passport.get("strength", "")
    readiness = passport.get("readiness", "partial")

    te_level = {"A": "success", "B": "danger"}.get(te_rating, "warning")
    readiness_level = {"ready": "success", "partial": "warning"}.get(readiness, "danger")

    st.markdown(
        f"""
        <div style="border:1px solid #d9d9d9; border-radius:6px; padding:16px; background:#ffffff; margin-bottom:16px;">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div class="cdmo-section-title">Reference Listed Drug</div>
              <div style="font-size:18px; font-weight:800; color:#1a1a1a; margin-top:2px;">{rld or '—'}</div>
              <div style="font-size:11px; color:#737373; margin-top:2px;">{applicant or '—'}</div>
            </div>
            <div style="text-align:right;">
              {tier_badge(f'TE {te_code} / {te_rating}', te_level) if te_code else tier_badge('No TE', 'warning')}
              <div style="margin-top:6px;">{tier_badge(readiness, readiness_level)}</div>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-top:16px;">
            <div><div style="font-size:10px; color:#b0b0b0;">Dosage Form</div>
            <div style="font-size:13px; font-weight:600; color:#1a1a1a;">{dosage or '—'}</div></div>
            <div><div style="font-size:10px; color:#b0b0b0;">Strength</div>
            <div style="font-size:13px; font-weight:600; color:#1a1a1a;">{strength or '—'}</div></div>
            <div><div style="font-size:10px; color:#b0b0b0;">BCS Class</div>
            <div style="font-size:13px; font-weight:600; color:#1a1a1a;">{bcs or '—'}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Pharmacopeia Monographs")
    cols = st.columns(3)
    for idx, (title, key) in enumerate(
        [
            ("IP 2026", "ip_2026_monograph"),
            ("Ph. Eur.", "ph_eur_monograph"),
            ("USP", "usp_monograph"),
        ]
    ):
        with cols[idx]:
            text = passport.get(key, "")
            if text:
                st.markdown(
                    f"""
                    <div style="border:1px solid #d9d9d9; border-radius:4px; padding:10px; background:#fafafa; height:100%;">
                      <div style="font-size:10px; font-weight:800; text-transform:uppercase; color:#737373; margin-bottom:6px;">{title}</div>
                      <div style="font-size:11px; color:#4a4a4a; line-height:1.45;">{text}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.caption(f"{title}: No monograph curated")

    specs = passport.get("analytical_specs") or []
    if specs:
        st.markdown("#### Analytical / QC Specs")
        st.markdown(
            "".join(
                f"<span style='padding:2px 6px; border-radius:3px; background:#d9d9d9; color:#4a4a4a; font-size:10px; margin-right:6px;'>{s}</span>"
                for s in specs
            ),
            unsafe_allow_html=True,
        )

    stability = passport.get("stability_conditions", "")
    if stability:
        st.markdown("#### Stability Conditions")
        st.markdown(f"<div style='font-size:12px; color:#4a4a4a;'>{stability}</div>", unsafe_allow_html=True)

    exclusivity = passport.get("exclusivity") or []
    if exclusivity:
        st.markdown("#### Active Exclusivity")
        for ex in exclusivity:
            expiry = ex.get("expiry_date") or "—"
            desc = ex.get("description", "")
            st.markdown(
                f"""
                <div style="border-left:3px solid {VERMILION}; padding:8px 12px; background:#ffebe6; margin-bottom:6px;">
                  <div style="font-size:12px; font-weight:700; color:#8a2b0a;">{ex.get('type', '')} until {expiry}</div>
                  <div style="font-size:11px; color:#8a2b0a; margin-top:2px;">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    be_notes = passport.get("bioequivalence_notes", "")
    if be_notes:
        st.markdown("#### Bioequivalence Notes")
        st.markdown(f"<div style='font-size:12px; color:#4a4a4a;'>{be_notes}</div>", unsafe_allow_html=True)

    notes = passport.get("notes", "")
    if notes:
        st.markdown("#### Notes")
        st.markdown(f"<div style='font-size:12px; color:#4a4a4a;'>{notes}</div>", unsafe_allow_html=True)


def _render_geo(geo_data: dict | None) -> None:
    if not geo_data:
        st.info("No geography data available for this molecule.")
        return

    eligible = geo_data.get("export_eligible", []) or []
    all_geo = geo_data.get("all_geo", []) or []

    st.markdown("#### Export-Eligible Geographies")
    if eligible:
        codes = [g.get("country_code", "") for g in eligible]
        st.markdown(
            f"Eligible for generic export to: **{', '.join(codes)}**",
        )
        df = pd.DataFrame(eligible)
        df = df[["country_code", "country_name", "market_status", "loe_date", "patent_barrier", "notes"]]
        df.columns = ["Code", "Country", "Status", "LOE Date", "Barrier", "Notes"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("No export-eligible geographies. Active patents or device/formulation barriers block export.")

    with st.expander("All geographies", expanded=False):
        df = pd.DataFrame(all_geo)
        df = df[["country_code", "country_name", "market_status", "loe_date", "export_eligible", "patent_barrier", "notes"]]
        df.columns = ["Code", "Country", "Status", "LOE Date", "Export Eligible", "Barrier", "Notes"]
        st.dataframe(df, use_container_width=True, hide_index=True)


def render() -> None:
    page_header(
        pillar="Pillar B — Market Access & Regulatory Rules",
        title="Regulatory Passport",
        subtitle="Pharmacopeia monographs, Orange Book RLD/TE/exclusivity, and geography-level LOE eligibility.",
        icon="document",
    )

    molecules = list_molecules()
    if not molecules:
        st.warning("No patent intelligence found in Redis. Run `just load-patents` to seed the engine.")
        return

    with st.expander("Filter & select molecule", expanded=True):
        options = {m["brand_name"]: m["molecule_key"] for m in molecules}
        selected_brand = st.selectbox("Molecule", list(options.keys()))
        selected_key = options[selected_brand]

    molecule = get_molecule(selected_key) or {}
    passport = get_molecule_regulatory(selected_key)
    geo = get_molecule_geo(selected_key)

    if passport is None:
        st.warning(f"No regulatory passport found for `{selected_key}`. Run `just load-regulatory` to seed it.")
        return

    try:
        score_result = score(selected_key).model_dump(mode="json")
    except Exception:
        score_result = None

    anime_entrance("#regulatory-results", "slideUp")
    st.markdown('<div id="regulatory-results">', unsafe_allow_html=True)

    if score_result:
        reg_score = score_result.get("regulatory_clarity_score", 0)
        total_score = score_result.get("total_score", 0)
        c1, c2 = st.columns(2)
        with c1:
            metric_tile("Regulatory Clarity", f"{reg_score:.0f}")
        with c2:
            metric_tile("Total CDMO Score", f"{total_score:.0f}")

    col1, col2 = st.columns([3, 2], gap="medium")
    with col1:
        _render_passport(passport)
    with col2:
        _render_geo(geo)

    mock_data_badge()
    st.markdown("</div>", unsafe_allow_html=True)
