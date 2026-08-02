"""
In-Silico NSQ Agent — Root Cause Analysis & GxP Compliance Workbench
=====================================================================

A Python (Streamlit) port of the original single-file React/TSX prototype.
Same data (CDSCO NSQ Drug Alerts catalog), same seven journey blocks (D1-D7),
now using a colorblind-safe scientific palette (Okabe-Ito): precise
borders, warm neutrals, and accessible categorical colors.

Run with:
    streamlit run nsq_agent_platform.py
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import os
import sys
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from intelligence.ui_components import (
    SCIENTIFIC_CSS,
    anime_entrance,
    bioicon_inline,
    feature_card,
    mock_data_badge,
    stepper,
)
from intelligence.palette import css_variables


# ---------------------------------------------------------------------------
# Page configuration — must be the first Streamlit call.
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CDMO Off-Patent Intelligence Engine",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Custom CSS — Swiss editorial / scientific theme.
# Mirrors the Tailwind palette used in the React prototype:
# slate-50 / slate-100 / slate-200 / slate-500 / slate-800 / slate-900
# No gradients, no glows. Borders, padding, and typography do the work.
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
  /* Tighten the default Streamlit chrome so it feels like a workbench. */
  .stApp { background-color: #fafafa; }

  /* Sans-serif body, mono for code, scientific neutral ramp. */
  html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter,
                 Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #1a1a1a;
  }

  /* Header bar */
  .nsq-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 20px;
    background: #ffffff;
    border-bottom: 1px solid #d9d9d9;
    box-shadow: 0 1px 0 rgba(26,26,26,0.02);
    flex-wrap: nowrap;
    gap: 16px;
    overflow: hidden;
    width: 100%;
    box-sizing: border-box;
  }
  .nsq-header-title-group {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
  }
  .nsq-header-titles {
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
  }
  .nsq-header-titles h1 {
    font-size: 16px;
    font-weight: 800;
    margin: 0;
    color: #1a1a1a;
    letter-spacing: -0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .nsq-header-titles p {
    font-size: 10px;
    color: #737373;
    margin: 2px 0 0 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .nsq-header-status {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
    flex-shrink: 0;
  }
  .nsq-header-status .pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 999px;
    white-space: nowrap;
    line-height: 1;
    height: auto;
    min-height: 0;
    vertical-align: middle;
  }
  .nsq-header-status .pill svg,
  .nsq-header-status .pill::before {
    width: 8px;
    height: 8px;
    display: inline-block;
    flex: 0 0 8px;
    line-height: 1;
  }
  @media (max-width: 640px) {
    .nsq-header { padding: 10px 12px; gap: 10px; }
    .nsq-header-status { flex-direction: column; align-items: flex-end; }
    .nsq-header-status .pill { font-size: 9px; }
  }

  /* Section cards (white, hairline border, tight shadow) */
  .nsq-card {
    background: #ffffff; border: 1px solid #d9d9d9;
    border-radius: 6px; padding: 20px; box-shadow: 0 1px 2px rgba(26,26,26,0.03);
  }
  .nsq-card + .nsq-card { margin-top: 24px; }

  /* Section eyebrow (D1, D2, …) */
  .nsq-eyebrow {
    font-size: 10px; font-weight: 800; text-transform: uppercase;
    letter-spacing: 0.08em; color: #737373;
  }
  .nsq-eyebrow-row { display: flex; justify-content: space-between; align-items: center;
    padding-bottom: 8px; border-bottom: 1px solid #d9d9d9; margin-bottom: 12px; }

  /* Big product title */
  .nsq-title { font-size: 22px; font-weight: 900; color: #1a1a1a; margin: 4px 0 0 0; letter-spacing: -0.02em; }

  /* VigiBase risk tiles */
  .risk-tile { background: #ffebe6; border: 1px solid #f5b9a8; border-radius: 4px; padding: 10px; }
  .risk-tile .hazard { font-size: 12px; font-weight: 700; color: #8a2b0a; display: block; }
  .risk-tile .desc   { font-size: 11px; color: #8a2b0a; margin-top: 4px; line-height: 1.45; }

  /* Excipient list rows */
  .ex-row { display: flex; justify-content: space-between; align-items: center;
    padding: 10px; background: #fafafa; border: 1px solid #d9d9d9; border-radius: 4px;
    font-size: 12px; }
  .ex-row + .ex-row { margin-top: 8px; }
  .ex-row .role { margin-left: 8px; padding: 2px 6px; background: #d9d9d9;
    color: #4a4a4a; border-radius: 3px; font-size: 9px; font-weight: 800; text-transform: uppercase; }
  .ex-row .ratio { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700; color: #4a4a4a; }
  .ex-row .desc { font-size: 10px; color: #b0b0b0; margin-top: 4px; }

  /* Pharmacopeia tiles */
  .pharma-tile { border: 1px solid #f2f2f2; padding: 12px; border-radius: 4px;
    background: #fafafa80; }
  .pharma-tile h5 { font-size: 12px; font-weight: 800; text-transform: uppercase;
    color: #262626; margin: 0 0 8px 0; padding-bottom: 4px; border-bottom: 1px solid #d9d9d9; }
  .pharma-tile p  { font-size: 11px; color: #4a4a4a; margin: 0 0 6px 0; line-height: 1.5; }

  /* Catalog sidebar item */
  .cat-item { padding: 14px; cursor: pointer; border-bottom: 1px solid #f2f2f2; }
  .cat-item:hover { background: #fafafa; }
  .cat-item.active { background: #f2f2f2; border-left: 4px solid #0072B2; }
  .cat-item h4 { font-size: 13px; font-weight: 700; margin: 0; color: #1a1a1a; }
  .cat-item p  { font-size: 11px; color: #737373; margin: 2px 0 0 0; }
  .alerts-pill { font-size: 10px; background: #ffebe6; color: #8a2b0a;
    font-weight: 800; padding: 2px 6px; border-radius: 3px; }

  /* Process parameter row */
  .pp-label  { display: flex; justify-content: space-between; font-size: 11px; }
  .pp-label .name { font-weight: 600; color: #4a4a4a; }
  .pp-label .val  { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700; color: #1a1a1a; }
  .pp-bounds { display: flex; justify-content: space-between; font-size: 9px; color: #b0b0b0; }

  /* Grade badge */
  .grade-badge { width: 56px; height: 56px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    border: 2px solid; font-size: 22px; font-weight: 900; }
  .grade-A { background: #e6f5f1; border-color: #009E73; color: #009E73; }
  .grade-B { background: #e6f5f1; border-color: #009E73; color: #009E73; }
  .grade-C { background: #fff9e6; border-color: #E69F00; color: #8c6b00; }
  .grade-D { background: #ffebe6; border-color: #D55E00; color: #8a2b0a; }
  .grade-F { background: #ffebe6; border-color: #D55E00; color: #8a2b0a; }

  /* Feedback list */
  .fb-item { font-size: 12px; padding: 8px; border-radius: 4px;
    display: flex; align-items: flex-start; gap: 6px; }
  .fb-err  { background: #ffebe6; color: #8a2b0a; border: 1px solid #f5b9a8; }
  .fb-ok   { background: #e6f5f1; color: #009E73; border: 1px solid #a3d9c5; }

  /* Diagnostic log block — preserve line breaks, mono */
  .diag-log { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px; color: #4a4a4a; line-height: 1.55;
    background: #fafafa; border: 1px solid #d9d9d9; border-radius: 4px;
    padding: 12px; white-space: pre-wrap; }

  /* Catalog footer (CDSCO file reference) */
  .cat-footer { font-size: 11px; color: #b0b0b0; line-height: 1.5; }
  .cat-footer code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 10px; color: #4a4a4a; background: #ffffff; border: 1px solid #d9d9d9;
    padding: 4px; border-radius: 3px; display: block; word-break: break-all; }

  /* Empty-state placeholder */
  .empty-state { background: #ffffff; border: 1px dashed #d9d9d9; border-radius: 6px;
    padding: 40px; text-align: center; color: #b0b0b0; font-size: 12px; }

  /* Settings bar */
  .settings-bar { background: #ffffff; border-bottom: 1px solid #d9d9d9;
    padding: 16px 24px; }

  /* Small utility */
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .muted { color: #b0b0b0; }

  /* Slider polish: keep rail subtle, knob sharp */
  .stSlider [data-baseweb="slider"] [role="slider"] {
    background-color: #0072B2 !important; border: 2px solid #0072B2 !important;
  }
  .stSlider [data-baseweb="slider"] > div > div > div {
    background-color: #0072B2 !important;
  }
  .stSlider [data-baseweb="slider"] [data-testid="stTickBar"] { display: none; }

  /* Primary button: scientific blue, no glow */
  .stButton > button {
    background: #0072B2 !important; color: #ffffff !important;
    border: 1px solid #0072B2 !important; border-radius: 4px !important;
    font-weight: 700 !important; font-size: 12px !important;
  }
  .stButton > button:hover { background: #005a8e !important; }
  .stButton > button:disabled { background: #d9d9d9 !important; border-color: #d9d9d9 !important; }

  /* Subtle dividers between columns in main area */
  section.main > div { gap: 0; }

  /* Tighter input borders */
  .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {
    border: 1px solid #d9d9d9 !important; border-radius: 4px !important;
    background: #ffffff !important; font-size: 12px !important;
  }
</style>
"""

st.markdown(css_variables(), unsafe_allow_html=True)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Inject scientific engine theme on top of legacy CSS.
st.markdown(SCIENTIFIC_CSS, unsafe_allow_html=True)
anime_entrance(".cdmo-feature-card")


# ---------------------------------------------------------------------------
# Product catalog — verbatim port of the React PRODUCT_CATALOG.
# Each drug carries:
#   D6  nsqStats            (CDSCO alert counts + common defects)
#   D4  vigibaseRisks       (pharmacovigilance hazards)
#   D2  gmpReference        (patent, process, excipients, parameters)
#   D1  testingGuidelines   (IP 2026 + Ph. Eur. monographs)
# ---------------------------------------------------------------------------
@dataclass
class Excipient:
    name: str
    role: str
    ratio: float
    description: str


@dataclass
class ParamSpec:
    label: str
    min: float
    max: float
    ideal: float
    unit: str


@dataclass
class TestingGuidelines:
    assay: str
    dissolution: str
    impurities: str


@dataclass
class Drug:
    id: str
    name: str
    dose: str
    dosage_form: str
    total_alerts: int
    source_file: str
    common_alerts: list[str]
    vigibase_risks: list[dict[str, str]]
    patent_ref: str
    patent_link: str | None
    optimal_process: str
    ideal_excipients: list[Excipient]
    ideal_parameters: dict[str, ParamSpec]
    ip2026: TestingGuidelines
    ph_eur: TestingGuidelines


def _g(assay: str, dissolution: str, impurities: str) -> TestingGuidelines:
    return TestingGuidelines(assay=assay, dissolution=dissolution, impurities=impurities)


PRODUCT_CATALOG: dict[str, Drug] = {
    d.id: d
    for d in [
        Drug(
            id="paracetamol",
            name="Paracetamol",
            dose="650 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=124,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Assay (Sub-potency of active ingredient)",
                "Dissolution (Fails rate of release at 30 minutes)",
                "Disintegration (Exceeds 15-minute standard limit)",
                "Related Substances (Excess Free 4-aminophenol / Impurity K > 0.1%)",
                "Description (Tablet Capping / Lamination)",
            ],
            vigibase_risks=[
                {"hazard": "Hepatotoxicity Acceleration",
                 "desc": "Hydrolysis product 4-aminophenol significantly elevates liver toxicity profile."},
                {"hazard": "Therapeutic Failure",
                 "desc": "Delayed dissolution causes sub-therapeutic plasma concentrations during acute pyrexia."},
            ],
            patent_ref="US Patent 9,231,104B2 (Stable Paracetamol Compaction)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("PVP K30", "Binder", 4.0, "Polyvinylpyrrolidone prevents tablet capping."),
                Excipient("Crospovidone", "Disintegrant", 5.0, "Superdisintegrant facilitating rapid dissolution."),
                Excipient("Microcrystalline Cellulose", "Diluent", 5.0, "Improves flow and compression properties."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Limits capping when kept under 1.5%."),
            ],
            ideal_parameters={
                "moistureLOD": ParamSpec("Granule Moisture (LOD %)", 1.5, 2.5, 2.0, "%"),
                "compForce":   ParamSpec("Main Compression Force (kN)", 10, 16, 13, "kN"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Water/Methanol/Glacial Acetic Acid (70:30:1). Flow rate: 1.0 mL/min.",
                "USP Apparatus 2 (Paddle) at 50 RPM; Medium: 900 mL Phosphate Buffer pH 5.8; Limit: NLT 80% dissolved in 30 minutes.",
                "Free 4-aminophenol: Maximum 0.1%.",
            ),
            ph_eur=_g(
                "UV Spectrophotometry at 249 nm on reconstituted standard.",
                "Paddle Apparatus at 50 RPM; Medium: Water; Limit: NLT 80% (Q) in 45 minutes.",
                "Impurity K: Maximum 0.15%.",
            ),
        ),
        Drug(
            id="tamoxifen",
            name="Tamoxifen Citrate",
            dose="20 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=38,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails release criteria due to polymorphic transition)",
                "Uniformity of Content (Active ingredient segregation in dry blend)",
                "Assay (Sub-potency of active tamoxifen citrate content)",
            ],
            vigibase_risks=[
                {"hazard": "Oncology Sub-Potency Risk",
                 "desc": "Active assay loss or failing dissolution can trigger breast cancer recurrence."},
                {"hazard": "Localized GI Distress",
                 "desc": "Agglomerated high-concentration local deposits lead to direct mucosal irritation."},
            ],
            patent_ref="WO Patent WO2000064416A2 (Stable Tamoxifen Formulations)",
            patent_link="https://patents.google.com/patent/WO2000064416A2/en",
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Anhydrous Lactose", "Diluent", 75.0, "Provides excellent flowability and mechanical properties."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 4.0, "Superdisintegrant promoting rapid bursting."),
                Excipient("Colloidal Silicon Dioxide", "Glidant", 0.5, "Optimizes blend flow and reduces segregation."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Sufficient lubrication without coating the hydrophobic API."),
            ],
            ideal_parameters={
                "mixTime":   ParamSpec("Dry Blending Time (mins)", 15, 25, 20, "mins"),
                "pressSpeed": ParamSpec("Rotary Press Speed (RPM)", 20, 40, 30, "RPM"),
            },
            ip2026=_g(
                "Liquid Chromatography on a C18 packing column with UV detection at 240 nm.",
                "USP Apparatus 2 at 50 RPM; 900 mL 0.02 N HCl; Limit: NLT 75% in 30 minutes.",
                "Total related chemical substances: Maximum 1.0%.",
            ),
            ph_eur=_g(
                "HPLC assay compared with tamoxifen citrate chemical reference standards.",
                "Apparatus 2 at 50 RPM; Medium: 0.02 M Hydrochloric acid; Limit: NLT 75% in 30 minutes.",
                "E-isomer content: Maximum 1.0%.",
            ),
        ),
        Drug(
            id="rabeprazole",
            name="Rabeprazole Sodium",
            dose="20 mg",
            dosage_form="Enteric-Coated Tablet",
            total_alerts=45,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Acid Resistance (Enteric polymer coat gastric decay failure)",
                "Description (Maillard Browning color failure under humidity)",
                "Assay (Sub-potency from chemical degradation in acid environment)",
                "Dissolution (Fails rate of release in intestinal buffer stage)",
            ],
            vigibase_risks=[
                {"hazard": "Gastric Acid Rebound",
                 "desc": "Premature enteric degradation renders the PPI inactive, causing severe mucosal irritation."},
                {"hazard": "Esophageal Erosion Progression",
                 "desc": "Therapeutic failures lead directly to worsening of untreated GERD and gastric ulcers."},
            ],
            patent_ref="EP Patent 1,224,931A1 (Alkaline Stabilization of Benzimidazoles)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Sodium Carbonate", "Alkalizer", 5.0, "Establishes a basic microenvironment to prevent acid degradation."),
                Excipient("Mannitol", "Diluent", 12.0, "Non-reducing sugar; prevents browning."),
                Excipient("HPMC K100", "Enteric Polymer", 6.0, "Provides stomach-acid-resistant coat."),
                Excipient("Magnesium Stearate", "Lubricant", 1.2, "Ensures punch release."),
            ],
            ideal_parameters={
                "ambientRH":  ParamSpec("Cleanroom Relative Humidity (%)", 15, 30, 22, "%"),
                "rollerForce": ParamSpec("Roller Compactor Force (kN/cm)", 4.0, 8.0, 6.0, "kN/cm"),
            },
            ip2026=_g(
                "HPLC validation. Standard C18 column, Mobile Phase: Phosphate buffer pH 7.0/Acetonitrile (65:35).",
                "Acid Stage: 0.1M HCl for 2 hours (NMT 10% dissolved); Buffer Stage: pH 6.8 Phosphate Buffer (NLT 75% in 45 mins).",
                "Total related substances: NMT 1.0%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography standard matching pharmacopeia guidelines.",
                "Dual-stage test replicating gastric to intestinal transit fluid boundaries.",
                "Individual unspecified impurities: NMT 0.1%.",
            ),
        ),
        Drug(
            id="pantoprazole",
            name="Pantoprazole Sodium",
            dose="40 mg",
            dosage_form="Delayed-Release Tablet",
            total_alerts=52,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails pH 6.8 buffer-stage rate of release)",
                "Assay (Sub-potency from active hydrolytic decomposition)",
                "Acid Resistance (Enteric shell early dissolution in acid stage)",
            ],
            vigibase_risks=[
                {"hazard": "Acid Breakthrough GERD",
                 "desc": "Uncontrolled proton pump inhibition failure resulting in chemical burns of the esophagus."},
                {"hazard": "Duodenal Ulcer Bleeding",
                 "desc": "Low systemic assay levels fail to raise gastric pH above 4.0, delaying mucosal healing."},
            ],
            patent_ref="US Patent 5,948,789 (Pantoprazole Sodium Stabilization)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Sodium Carbonate anhydrous", "Alkalizer", 8.0, "Alkaline buffer to maintain basic environment for acid-labile core."),
                Excipient("Crospovidone", "Disintegrant", 4.5, "Ensures rapid tablet burst during pH 6.8 buffer stage."),
                Excipient("Methacrylic Acid Copolymer Type C", "Enteric Polymer", 12.0, "Provides stomach-acid-resistant enteric barrier."),
                Excipient("Calcium Stearate", "Lubricant", 1.0, "Preferred over magnesium stearate to avoid alkaline interaction drifts."),
            ],
            ideal_parameters={
                "ambientRH":  ParamSpec("Compression Room RH (%)", 10, 25, 18, "%"),
                "rollerForce": ParamSpec("Roller Compactor Force (kN/cm)", 3.0, 6.0, 4.5, "kN/cm"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Phosphate buffer pH 7.0/Acetonitrile (60:40).",
                "Acid Stage: 0.1M HCl (NMT 10% in 120 mins); Buffer Stage: pH 6.8 Phosphate Buffer (NLT 75% in 45 mins).",
                "Pantoprazole Sulfone / N-oxide impurities: Maximum 0.2%.",
            ),
            ph_eur=_g(
                "Liquid chromatography with UV detection at 290 nm.",
                "Dual pH stage test; Buffer stage limit: NLT 75% in 45 minutes.",
                "Any individual impurity: Maximum 0.1%.",
            ),
        ),
        Drug(
            id="esomeprazole",
            name="Esomeprazole Magnesium",
            dose="40 mg",
            dosage_form="Delayed-Release Tablet",
            total_alerts=29,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Premature dissolution in acid stage from pellet coat rupture)",
                "Assay (Sub-potency due to enteric pellet degradation during compression)",
                "Uniformity of Content (Variable active pellet distribution inside tablet core)",
            ],
            vigibase_risks=[
                {"hazard": "Gastric Mucosal Degradation",
                 "desc": "Rupturing of enteric pellets inside MUPS triggers immediate active ingredient breakdown in the stomach."},
                {"hazard": "Active Assay Degradation",
                 "desc": "Exposure to gastric pH transforms active Esomeprazole to inactive sulfonamides."},
            ],
            patent_ref="US Patent 6,368,581 (Multi-Unit Particulate System MUPS Tableting)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose Spheres", "Diluent", 45.0, "Acts as cushioning agent to prevent enteric pellet breakage."),
                Excipient("Crospovidone", "Disintegrant", 5.0, "Swells rapidly to release enteric-coated pellets."),
                Excipient("Enteric Coated Esomeprazole Pellets", "Active Component", 35.0, "Pre-coated active pellets."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.0, "Avoids hydrophobic capping during compression."),
            ],
            ideal_parameters={
                "compForce": ParamSpec("Main Compression Force (kN)", 4.0, 8.0, 6.0, "kN"),
                "feedRate":  ParamSpec("Pellet Feeder Rate (kg/hr)", 15, 30, 22, "kg/hr"),
            },
            ip2026=_g(
                "HPLC system with C8 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 7.6.",
                "Acid Phase: 0.1M HCl (NMT 10% in 2 hours); Buffer Phase: pH 6.8 Buffer (NLT 80% in 30 mins).",
                "Related compound A: Maximum 0.15%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standards at UV 302 nm.",
                "MUPS specific dissolution test; Buffer stage: NLT 80% in 30 mins.",
                "Total unspecified degradation products: Maximum 0.5%.",
            ),
        ),
        Drug(
            id="telmisartan",
            name="Telmisartan",
            dose="40 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=68,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails release in pH 7.5 buffer due to meglumine crystallization)",
                "Description (Hygroscopic liquefaction and severe sticking in blister packaging)",
                "Assay (Sub-potency driven by solid-state crystal transitions)",
            ],
            vigibase_risks=[
                {"hazard": "Hypertensive Crisis",
                 "desc": "Failure to dissolve leads to instant loss of blood pressure control and risk of stroke."},
                {"hazard": "Blister Integrity Degradation",
                 "desc": "Moisture ingress causes tablet deliquescence, introducing biological contaminants."},
            ],
            patent_ref="US Patent 6,358,986B1 (Telmisartan Solubilized Core Matrix)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Meglumine", "Alkalizer", 6.0, "Increases local pH to solubilize the acidic drug."),
                Excipient("Sorbitol", "Diluent", 14.0, "Ensures compaction stability."),
                Excipient("Poloxamer 188", "Surfactant", 3.0, "Enhances surface wetting."),
                Excipient("Magnesium Stearate", "Lubricant", 1.5, "Ensures tablet release."),
            ],
            ideal_parameters={
                "mixTime":   ParamSpec("Dry Blending Time (mins)", 15, 25, 20, "mins"),
                "pressSpeed": ParamSpec("Rotary Press Speed (RPM)", 20, 45, 32, "RPM"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Ammonium acetate buffer pH 4.0/Methanol (40:60).",
                "USP Apparatus 2 (Paddle) at 75 RPM; Medium: 900 mL pH 7.5 Phosphate Buffer; Limit: NLT 75% in 45 minutes.",
                "Total related degradation products: NMT 0.5%.",
            ),
            ph_eur=_g(
                "Liquid chromatography standard using reference standards.",
                "Paddle apparatus at 75 RPM in pH 7.5 media; Limit: NLT 75% in 45 minutes.",
                "Individual degradation products: NMT 0.2%.",
            ),
        ),
        Drug(
            id="metformin",
            name="Metformin HCl",
            dose="500 mg",
            dosage_form="Extended-Release Tablet",
            total_alerts=82,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Weight Variation (Fails tablet weight limits from poor powder flow)",
                "Dissolution (Dose dumping / uncontrolled rapid release of hydrophilic matrix)",
                "Assay (Sub-potency from raw material blend segregation)",
            ],
            vigibase_risks=[
                {"hazard": "Lactic Acidosis Spike",
                 "desc": "Dose dumping releases excessive Metformin rapidly, pushing kidney filtration boundaries."},
                {"hazard": "Erratic Blood Glucose",
                 "desc": "Weight and content variations between tablets trigger uncoordinated glycemic highs and lows."},
            ],
            patent_ref="US Patent 6,610,324 (Swellable Hydrophilic Metformin Matrix)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("HPMC K100M", "Binder", 28.0, "Forms swellable gel matrix that controls drug release rate."),
                Excipient("Sodium Carboxymethylcellulose", "Disintegrant", 8.0, "Synergistic hydrophilic polymer promoting uniform gel boundary."),
                Excipient("Microcrystalline Cellulose", "Diluent", 15.0, "Provides compaction matrix strength."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Lubricant for dense high-volume tableting."),
            ],
            ideal_parameters={
                "binderVolume": ParamSpec("Granulation Water (L)", 8.0, 12.0, 10.0, "L"),
                "dryTime":      ParamSpec("Fluid Bed Dryer Time (mins)", 30, 50, 40, "mins"),
            },
            ip2026=_g(
                "Spectrophotometric assessment at 233 nm using verified standard references.",
                "USP Apparatus 1 (Basket) at 100 RPM; Medium: pH 6.8 Buffer; Limit: 1 hr (20-40%), 3 hr (45-65%), 8 hr (NLT 85%).",
                "Dicyandiamide impurity: Maximum 0.02%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing raw metformin standard curves.",
                "Apparatus 1 at 100 RPM; pH 6.8 buffer parameters matching pharmacopeial standards.",
                "Total related degradation products: Maximum 0.1%.",
            ),
        ),
        Drug(
            id="glimepiride",
            name="Glimepiride",
            dose="2 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=31,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Uniformity of Content (Severe failures in microgram-scale distribution)",
                "Assay (Sub-potency and super-potency hot-spots from powder segregation)",
                "Dissolution (Fails rate of release due to active particle agglomeration)",
            ],
            vigibase_risks=[
                {"hazard": "Severe Hypoglycemia Shock",
                 "desc": "Hotspots (excess API) in poorly mixed batches cause acute, life-threatening blood sugar drops."},
                {"hazard": "Persistent Hyperglycemia",
                 "desc": "Sub-potency tablets due to powder segregation lead to chronic elevated HbA1c levels."},
            ],
            patent_ref="US Patent 6,180,660 (Uniform Low-Dose Sulfonylurea Formulations)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("Lactose Monohydrate", "Diluent", 65.0, "Main diluent carrier providing uniform density."),
                Excipient("PVP K25", "Binder", 3.5, "Binds microgram active particles evenly onto carrier granules."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 4.0, "Promotes rapid tablet disintegration."),
                Excipient("Magnesium Stearate", "Lubricant", 0.8, "Lubricates punch boundaries."),
            ],
            ideal_parameters={
                "mixSpeed":  ParamSpec("High-Shear Mixer Speed (RPM)", 100, 200, 150, "RPM"),
                "micronSize": ParamSpec("API Micronized Particle Size (µm)", 2.0, 8.0, 5.0, "µm"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 3.5.",
                "Apparatus 2 at 75 RPM; Medium: pH 7.8 Phosphate Buffer; Limit: NLT 80% in 15 minutes.",
                "Glimepiride cis-isomer limit: Maximum 0.4%.",
            ),
            ph_eur=_g(
                "HPLC comparing validation peaks at UV 228 nm.",
                "Paddle at 75 RPM in pH 7.8 media; Limit: NLT 80% in 15 minutes.",
                "Total related chemical compounds: Maximum 0.5%.",
            ),
        ),
        Drug(
            id="amlodipine",
            name="Amlodipine Besylate",
            dose="5 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=41,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Assay (Active transesterification and hydrolytic degradation)",
                "Dissolution (Fails rate of release due to solid-state hydrate transitions)",
                "Related Substances (Excess Amlodipine pyridine derivative Impurity D > 0.3%)",
            ],
            vigibase_risks=[
                {"hazard": "Loss of Angina Control",
                 "desc": "Decomposed active ester fails to maintain steady calcium channel blockade."},
                {"hazard": "Sudden BP Spikes",
                 "desc": "Hydrate shifts prevent rapid dissolution, causing unpredictable delay in emergency drug release."},
            ],
            patent_ref="US Patent 4,879,303 (Stable Amlodipine Besylate Compact)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose PH102", "Diluent", 70.0, "Dry binder/diluent with low moisture content."),
                Excipient("Anhydrous Dibasic Calcium Phosphate", "Diluent", 22.0, "Non-hygroscopic carrier preventing hydrolysis."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 3.0, "Swells without adsorbing moisture from atmosphere."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Ensures reliable ejection."),
            ],
            ideal_parameters={
                "packagingRH":   ParamSpec("Packaging Environment RH (%)", 10, 30, 20, "%"),
                "mainPressForce": ParamSpec("Compaction Force (kN)", 8.0, 14.0, 11.0, "kN"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Water/Acetonitrile/Methanol with Triethylamine.",
                "Apparatus 2 at 75 RPM; Medium: 0.01M HCl; Limit: NLT 75% in 30 minutes.",
                "Amlodipine impurity D (pyridine derivative): Maximum 0.3%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard besylate curves.",
                "Paddle at 75 RPM; 0.01M HCl; Limit: NLT 75% in 30 minutes.",
                "Total unspecified impurities: Maximum 0.25%.",
            ),
        ),
        Drug(
            id="losartan",
            name="Losartan Potassium",
            dose="50 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=34,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails release criteria due to film-coat sintering barrier)",
                "Identification (Chemical identity overlap during baseline raw materials testing)",
                "Assay (Sub-potency driven by core degradation during aqueous coating)",
            ],
            vigibase_risks=[
                {"hazard": "Vasoconstriction Recurrence",
                 "desc": "Dissolution drift delays active AT_1 block, causing dangerous vascular spasms."},
                {"hazard": "Allergenic Core Degradants",
                 "desc": "Moisture trapped during coating sintering triggers micro-hydrolysis into reactive fragments."},
            ],
            patent_ref="US Patent 5,608,075 (Stable Film Coated Losartan)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose", "Diluent", 55.0, "Compactible base filler."),
                Excipient("Lactose Monohydrate", "Diluent", 30.0, "Provides fast release characteristics."),
                Excipient("Opadry II Coating System", "Enteric Polymer", 3.5, "Moisture protection film layer."),
                Excipient("Magnesium Stearate", "Lubricant", 1.2, "Ensures lubrication on rotary compaction."),
            ],
            ideal_parameters={
                "coatingTemp": ParamSpec("Coating Bed Temperature (°C)", 38.0, 46.0, 42.0, "°C"),
                "sprayRate":   ParamSpec("Coating Spray Rate (mL/min)", 10.0, 25.0, 18.0, "mL/min"),
            },
            ip2026=_g(
                "HPLC validation utilizing C18 column, Phosphate buffer/Acetonitrile mobile phase.",
                "Apparatus 2 at 50 RPM; Medium: Water; Limit: NLT 75% in 30 minutes.",
                "Total related degradants: Maximum 0.2%.",
            ),
            ph_eur=_g(
                "Spectrophotometric identity and assay comparison at UV 254 nm.",
                "Paddle at 50 RPM; Water medium; Limit: NLT 75% in 30 minutes.",
                "Individual degradation products: Maximum 0.1%.",
            ),
        ),
        Drug(
            id="ramipril",
            name="Ramipril",
            dose="5 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=49,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess diketopiperazine (DKP) cyclization degradants > 0.5%)",
                "Assay (Severe sub-potency from moisture-driven intramolecular cyclization)",
                "Dissolution (Erratic core release profile from degraded active molecules)",
            ],
            vigibase_risks=[
                {"hazard": "Cardiovascular Risk Spikes",
                 "desc": "Conversion of ramipril to inactive diketopiperazine (DKP) results in untreated chronic hypertension."},
                {"hazard": "Severe ACE-Inhibitor Failure",
                 "desc": "Hydrolytic degradation destroys therapeutic efficacy, exposing patients to post-MI risks."},
            ],
            patent_ref="EP Patent 0,317,478 (In-Situ Stabilization of Ramipril with Alumina)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Colloidal Aluminum Hydroxide", "Alkalizer", 5.0, "Provides complexation shield preventing intramolecular cyclization."),
                Excipient("Pregelatinized Starch (Low Moisture)", "Diluent", 40.0, "Inert starch containing less than 1.0% water."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.0, "Provides necessary punch release without shearing the drug."),
            ],
            ideal_parameters={
                "coreMoisture": ParamSpec("Tablet Core Moisture LOD (%)", 0.5, 1.5, 1.0, "%"),
                "compForce":    ParamSpec("Punch Compression Force (kN)", 6.0, 12.0, 9.0, "kN"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Methanol/Water with Perchloric acid.",
                "Apparatus 1 (Basket) at 50 RPM; Medium: 0.1M HCl; Limit: NLT 80% in 45 minutes.",
                "Diketopiperazine (DKP Impurity): Maximum 0.5%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing ramiprilat chemical references.",
                "Basket at 50 RPM in acid medium; Limit: NLT 80% in 45 minutes.",
                "Total unspecified impurities: Maximum 0.25%.",
            ),
        ),
        Drug(
            id="atenolol",
            name="Atenolol",
            dose="50 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=23,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Dissolution (Fails rate of release due to mechanical hydrate-state transitions)",
                "Assay (Potency loss from high compaction shear during dry compounding)",
                "Disintegration (Delayed core physical breakdown under standard buffer)",
            ],
            vigibase_risks=[
                {"hazard": "Tachycardia Breakthrough",
                 "desc": "Hydrate-anhydrous shifts compromise tablet dissolving speed, causing angina breakthrough."},
                {"hazard": "Arrhythmia Escalation",
                 "desc": "Low dissolution profile leads to insufficient plasma concentration during physical exertion."},
            ],
            patent_ref="US Patent 3,836,671 (Atenolol Compaction and Solubilisation Profiles)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose", "Diluent", 45.0, "Ensures high physical matrix binding."),
                Excipient("PVP K30", "Binder", 4.0, "Provides strong granule binding during wet massing."),
                Excipient("Crospovidone", "Disintegrant", 5.0, "Rapid water absorption and expansion matrix."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Limits capping risk."),
            ],
            ideal_parameters={
                "dryTemp":   ParamSpec("Dryer Inlet Air Temperature (°C)", 45.0, 60.0, 52.0, "°C"),
                "shearForce": ParamSpec("Granulator Shear Rate (kN)", 5.0, 15.0, 10.0, "kN"),
            },
            ip2026=_g(
                "Spectrophotometric evaluation of atenolol standard references at 275 nm.",
                "Apparatus 2 at 50 RPM; Medium: 0.1M HCl; Limit: NLT 75% in 30 minutes.",
                "Atenolol related compound A: Maximum 0.3%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard validations at UV 226 nm.",
                "Paddle at 50 RPM; Acid medium; Limit: NLT 75% in 30 minutes.",
                "Total unspecified degradation products: Maximum 0.25%.",
            ),
        ),
        Drug(
            id="atorvastatin",
            name="Atorvastatin Calcium",
            dose="10 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=57,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess acid-catalyzed lactonization impurity > 0.3%)",
                "Dissolution (Fails rate of release due to hydrophobic wetting failure)",
                "Assay (Active content decline in acidic excipient microenvironments)",
            ],
            vigibase_risks=[
                {"hazard": "Rebound Hypercholesterolemia",
                 "desc": "Acidic degradation converts active statin to inactive lactone, triggering hepatic LDL receptor drops."},
                {"hazard": "Coronary Plaque Instability",
                 "desc": "Erratic dissolution blocks proper vascular protective therapy."},
            ],
            patent_ref="US Patent 5,686,104 (Atorvastatin Calcium Buffering System)",
            patent_link=None,
            optimal_process="Wet Granulation",
            ideal_excipients=[
                Excipient("Calcium Carbonate", "Alkalizer", 6.0, "Acts as microenvironmental alkaline buffer protecting drug from acid degradation."),
                Excipient("Lactose Monohydrate", "Diluent", 50.0, "Provides highly soluble dispersion matrix."),
                Excipient("Poloxamer 188", "Disintegrant", 2.0, "Surfactant that lowers surface tension to wet the hydrophobic API."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Standard tableting release lubricant."),
            ],
            ideal_parameters={
                "calciumCarbonateRatio": ParamSpec("Alkalizer Buffer Ratio (%)", 4.0, 8.0, 6.0, "%"),
                "binderSprayRate":       ParamSpec("Granulator Spray Rate (g/min)", 40.0, 80.0, 60.0, "g/min"),
            },
            ip2026=_g(
                "HPLC utilizing C18 column, Mobile Phase: Acetonitrile/Tetrahydrofuran/Water/Ammonium Acetate buffer.",
                "Apparatus 2 at 75 RPM; Medium: pH 6.8 Buffer; Limit: NLT 75% in 30 minutes.",
                "Atorvastatin lactone related substance: Maximum 0.3%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard curves at UV 244 nm.",
                "Paddle at 75 RPM in pH 6.8 media; Limit: NLT 75% in 30 minutes.",
                "Total unspecified degradation products: Maximum 0.15%.",
            ),
        ),
        Drug(
            id="rosuvastatin",
            name="Rosuvastatin Calcium",
            dose="10 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=39,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess photo-oxidation of heptenoic acid chain)",
                "Assay (Sub-potency driven by ambient UV exposure during dry granulation)",
                "Description (Discoloration and yellowing under cleanroom lighting)",
            ],
            vigibase_risks=[
                {"hazard": "Inadequate Lipid Management",
                 "desc": "Oxidized active complex fails to inhibit HMG-CoA reductase effectively."},
                {"hazard": "Intestinal Tract Toxicity",
                 "desc": "Photo-degradants cause direct lipid oxidation across the mucosal linings of the intestinal tract."},
            ],
            patent_ref="US Patent 6,316,460 (Stabilised Rosuvastatin Complex)",
            patent_link=None,
            optimal_process="Dry Granulation",
            ideal_excipients=[
                Excipient("Dibasic Calcium Phosphate anhydrous", "Diluent", 40.0, "Inert calcium carrier stabilizing the calcium chelate structure."),
                Excipient("Butylated Hydroxyanisole (BHA)", "Disintegrant", 0.1, "Crucial antioxidant that halts heptenoic acid chain oxidation."),
                Excipient("Microcrystalline Cellulose PH101", "Diluent", 45.0, "Dry granulator compaction aid."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.0, "Oxidatively inert lubricant."),
            ],
            ideal_parameters={
                "cleanroomLux": ParamSpec("Cleanroom UV Filtering Light (Lux)", 100.0, 300.0, 200.0, "Lux"),
                "rollerForce":  ParamSpec("Roller Compactor Compression (kN/cm)", 4.0, 8.0, 6.0, "kN/cm"),
            },
            ip2026=_g(
                "HPLC method using C18 column with Mobile Phase: Acetonitrile/Phosphate Buffer pH 3.0.",
                "Apparatus 2 at 50 RPM; Medium: 0.05M Phosphate Buffer pH 6.8; Limit: NLT 75% in 45 minutes.",
                "Rosuvastatin diastereomer: Maximum 0.2%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing standard calibrations at UV 242 nm.",
                "Paddle at 50 RPM; pH 6.8 buffer; Limit: NLT 75% in 45 minutes.",
                "Total related degradation products: Maximum 0.5%.",
            ),
        ),
        Drug(
            id="sitagliptin",
            name="Sitagliptin Phosphate",
            dose="100 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=27,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Assay (Potency loss from interfacial nucleophilic cross-migration in bilayer)",
                "Related Substances (Traces of degradation products at bilayer interface)",
                "Dissolution (Fails rate of release profile validation under neutral buffer)",
            ],
            vigibase_risks=[
                {"hazard": "Glycemic Instability Spike",
                 "desc": "Bilayer degradation limits the active DPP-4 blockade, leading to rapid postprandial glucose peaks."},
                {"hazard": "Immunosuppressant Failure",
                 "desc": "Uncontrolled cross-migration degradation yields active breakdown complexes."},
            ],
            patent_ref="US Patent 7,326,708 (Stable Sitagliptin Bilayer Solid Oral Core)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Microcrystalline Cellulose PH200", "Diluent", 50.0, "Large particle MCC acting as an interface physical barrier."),
                Excipient("Calcium Hydrogen Phosphate", "Diluent", 35.0, "Inert dicalcium base preventing chemical migration."),
                Excipient("Croscarmellose Sodium", "Disintegrant", 4.0, "Superdisintegrant for rapid release."),
                Excipient("Sodium Stearyl Fumarate", "Lubricant", 1.5, "Inert tablet release lubricant."),
            ],
            ideal_parameters={
                "barrierLayerThick": ParamSpec("Bilayer Interfacial Barrier (mm)", 0.5, 1.5, 1.0, "mm"),
                "bilayerCompForce":  ParamSpec("Secondary Compression Force (kN)", 12.0, 20.0, 16.0, "kN"),
            },
            ip2026=_g(
                "HPLC validation. Standard C18 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 6.5.",
                "Apparatus 2 at 75 RPM; Medium: Water; Limit: NLT 75% in 30 minutes.",
                "Total unspecified related compounds: Maximum 0.5%.",
            ),
            ph_eur=_g(
                "Liquid Chromatography comparing raw sitagliptin standards.",
                "Paddle at 75 RPM; Water medium; Limit: NLT 75% in 30 minutes.",
                "Individual degradation products: Maximum 0.15%.",
            ),
        ),
        Drug(
            id="vildagliptin",
            name="Vildagliptin",
            dose="50 mg",
            dosage_form="Solid Oral Tablet",
            total_alerts=33,
            source_file="CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv",
            common_alerts=[
                "Related Substances (Excess hygroscopic cyclization degradation product > 0.4%)",
                "Description (Tablet softening and core gelation under accelerated humidity stress)",
                "Assay (Low active potency in standard stability chamber storage)",
            ],
            vigibase_risks=[
                {"hazard": "Loss of Glycemic Regulation",
                 "desc": "Moisture ingress catalyzes rapid active molecule cyclization, transforming active drug to inactive cyclic degradants."},
                {"hazard": "Diabetic Instability Escalation",
                 "desc": "Softened tablet matrices result in incomplete active dose absorption."},
            ],
            patent_ref="US Patent 6,011,155 (Vildagliptin Stable Solid Formulations)",
            patent_link=None,
            optimal_process="Direct Compression",
            ideal_excipients=[
                Excipient("Anhydrous Lactose", "Diluent", 60.0, "Moisture-free binder matrix."),
                Excipient("Microcrystalline Cellulose (Ultra Dry)", "Diluent", 30.0, "Provides compaction support without carrying water."),
                Excipient("Sodium Starch Glycolate", "Disintegrant", 3.0, "Superdisintegrant with high moisture-absorbing tolerances."),
                Excipient("Magnesium Stearate", "Lubricant", 1.0, "Limits capping under direct compression."),
            ],
            ideal_parameters={
                "environmentRH":    ParamSpec("Cleanroom Relative Humidity (%)", 10, 25, 18, "%"),
                "blisterFoilThick": ParamSpec("Alu-Alu Blister Foil Thickness (µm)", 20, 35, 28, "µm"),
            },
            ip2026=_g(
                "HPLC method using C18 column, Mobile Phase: Acetonitrile/Phosphate Buffer pH 7.0.",
                "Apparatus 2 at 50 RPM; Medium: Phosphate Buffer pH 6.8; Limit: NLT 75% in 30 minutes.",
                "Vildagliptin cyclic degradation compound: Maximum 0.4%.",
            ),
            ph_eur=_g(
                "Liquid chromatography compared with vildagliptin reference standards.",
                "Paddle at 50 RPM; pH 6.8 media; Limit: NLT 75% in 30 minutes.",
                "Total related degradation products: Maximum 0.5%.",
            ),
        ),
    ]
}


# ---------------------------------------------------------------------------
# Live-data enrichment — pulls real NSQ alert counts from Redis (same
# nsq:record:* hashes the analytics service reads) and overlays them onto
# the simulator's static catalog. Falls back silently to the hardcoded
# `total_alerts` / `common_alerts` above if Redis isn't reachable or a
# drug name isn't found, so the simulator still runs standalone.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))
from nsq_redis import load_dataframe as _load_redis_dataframe  # noqa: E402


@st.cache_data(ttl=300)
def _load_live_alert_stats() -> dict[str, dict[str, Any]]:
    """Return {drug_id: {"total_alerts": int, "common_alerts": [str, ...]}}."""
    try:
        df = _load_redis_dataframe()
    except Exception:
        return {}
    if df.empty:
        return {}

    name_col = "Name of Product" if "Name of Product" in df.columns else None
    reason_col = "NSQ Result" if "NSQ Result" in df.columns else None
    if name_col is None:
        return {}

    product_text = df[name_col].fillna("").astype(str).str.lower()
    stats: dict[str, dict[str, Any]] = {}
    for drug_id in PRODUCT_CATALOG:
        mask = product_text.str.contains(drug_id, case=False, na=False)
        matched = df[mask]
        if matched.empty:
            continue
        common: list[str] = []
        if reason_col:
            top = (
                matched[reason_col]
                .fillna("")
                .astype(str)
                .value_counts()
                .head(5)
            )
            common = [reason for reason in top.index if reason.strip()]
        stats[drug_id] = {
            "total_alerts": int(len(matched)),
            "common_alerts": common,
        }
    return stats


def _apply_live_stats(catalog: dict[str, Drug], stats: dict[str, dict[str, Any]]) -> None:
    for drug_id, values in stats.items():
        drug = catalog.get(drug_id)
        if drug is None:
            continue
        drug.total_alerts = values["total_alerts"]
        if values["common_alerts"]:
            drug.common_alerts = values["common_alerts"]


LIVE_ALERT_STATS = _load_live_alert_stats()
_apply_live_stats(PRODUCT_CATALOG, LIVE_ALERT_STATS)
USING_LIVE_DATA = bool(LIVE_ALERT_STATS)


# ---------------------------------------------------------------------------
# D3 / D5 — Failure diagnostic engine.
#
# This function mirrors the React `explainNsqFailureWithAgent` function.
# When an API key is provided, it calls Google's Gemini API (with
# exponential backoff) for live generative analysis. Otherwise it falls
# back to a deterministic, scientifically-grounded local heuristic engine
# that reproduces the original TypeScript behavior.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """Act as an expert pharmaceutical chemical analyst and regulatory auditor.
Evaluate a product quality issue from a "Not of Standard Quality" (NSQ) lab result.
Format your response cleanly using bullet points and professional terminology. Break it down into:
1. Root Cause Analysis (Chemical/Physical mechanics of the failure).
2. Process Parameter Gaps (Why the provided process values failed).
3. Corrective Action & Preventive Action (CAPA) steps."""


def _local_heuristic(drug_id: str, alert_type: str, input_params: dict[str, float]) -> str:
    """D3 deterministic fallback. Mirrors the original TypeScript implementation."""
    drug = PRODUCT_CATALOG.get(drug_id, PRODUCT_CATALOG["paracetamol"])
    alert_label = alert_type or drug.common_alerts[0]
    patent = drug.patent_ref
    parameters_info = ", ".join(f"{k} at {v}" for k, v in input_params.items())

    if drug_id == "paracetamol":
        moisture_val = input_params.get("moistureLOD", 2.0)
        force_val = input_params.get("compForce", 13)
        root_cause = (
            f"Paracetamol is a high-dose molecule with extremely poor natural compressibility. "
            f"The detected defect (\"{alert_label}\") stems from the high mass fraction of the "
            f"API (>80% of formulation). If moisture is high ({moisture_val}%), water acts as a "
            f"catalytic driver for hydrolytic cleavage at the amide bond, forming toxic 4-aminophenol. "
            f"If compression force is high ({force_val} kN), air becomes entrapped in the dense "
            f"powder bed, releasing during decompression to cause lamination/capping."
        )
        gaps = (
            f"Provided process LOD of {moisture_val}% is "
            f"{'above' if moisture_val > 2.5 else 'deviated from'} the critical design space "
            f"corridor of 1.5% - 2.5%. Provided compaction pressure of {force_val} kN "
            f"{'exceeds the mechanical limit, fracturing' if force_val > 16 else 'is outside the cohesive window of'} "
            f"the wet granules."
        )
        capa = (
            "- Reduce drying air dew-point in Fluid Bed Dryer to target a precise LOD of 1.8% - 2.0%.\n"
            "- Re-validate compaction matrix; optimize pre-compression force to 2.5 kN to "
            "pre-de-aerate the granules before the main tablet compress."
        )
    elif drug_id == "rabeprazole":
        rh_val = input_params.get("ambientRH", 22)
        roller_val = input_params.get("rollerForce", 6.0)
        root_cause = (
            f"Rabeprazole Sodium is an extremely acid-labile proton pump inhibitor containing an "
            f"amine matrix highly sensitive to electrophilic attack. In high ambient relative "
            f"humidity ({rh_val}%), moisture absorption initiates immediate molecular destabilization. "
            f"Furthermore, if reducing sugars (such as lactose) are present, moisture acts as a "
            f"solvent facilitating Maillard browning reactions, causing description (color) failures."
        )
        gaps = (
            f"Cleanroom Relative Humidity is currently at {rh_val}%, which "
            f"{'severely violates the low-humidity limit of 30%' if rh_val > 30 else 'exceeds safe limits'}. "
            f"Roller force of {roller_val} kN/cm is "
            f"{'too high, causing localized heat buildup and drug discoloration' if roller_val > 8.0 else 'under-compacting the ribbons'}."
        )
        capa = (
            "- Upgrade cleanroom desiccant systems to maintain strict humidity controls below 25% RH.\n"
            "- Re-evaluate formulation recipe; immediately remove reducing sugars and switch diluents "
            "to mannitol or calcium phosphate to mitigate Maillard browning risks."
        )
    elif drug_id == "telmisartan":
        mix_val = input_params.get("mixTime", 20)
        speed_val = input_params.get("pressSpeed", 32)
        root_cause = (
            f"Telmisartan is a BCS Class II drug possessing highly hydrophobic crystalline structures "
            f"that are practically insoluble at standard physiological gastric pH. Complete dissolution "
            f"relies on establishing a microenvironmental basic pH via Meglumine. Insufficient blending "
            f"time ({mix_val} mins) or excessive press speed ({speed_val} RPM) causes "
            f"active-excipient segregation, resulting in individual tablets lacking the alkalizing agent "
            f"and failing dissolution."
        )
        gaps = (
            f"The process mixing duration of {mix_val} minutes is "
            f"{'insufficient to achieve a homogeneous blend' if mix_val < 15 else 'deviated from ideal'}. "
            f"Tablet press speed of {speed_val} RPM is "
            f"{'too high, reducing dwell time and leading to severe weight and assay variation' if speed_val > 45 else 'outside optimum limits'}."
        )
        capa = (
            "- Establish a minimum wet/dry blending standard of 20 minutes to secure the Critical Mixing Index (Im).\n"
            "- Run tablet press at a constant speed of 30-35 RPM to optimize die filling and uniformity of content."
        )
    else:
        root_cause = (
            f"The observed defect \"{alert_label}\" for active tablet {drug.name} stems from solid-state "
            f"crystallization transitions and chemical instabilites under operational boundaries "
            f"({parameters_info}). The formulation undergoes active decomposition or physical delamination "
            f"when exposed to microenvironmental stresses outside its crystalline design space."
        )
        gaps = (
            f"The physical processing parameters provided ({parameters_info}) depart directly from the "
            f"optimal compliance corridor designated by {patent}. This mismatch decreases compaction "
            f"homogeneity, altering tablet binding and triggering accelerated degradation kinetics."
        )
        capa = (
            f"- Re-evaluate the critical material attributes (CMAs) of the functional diluents and binder ratios.\n"
            f"- Execute a multi-point process validation program to match target specifications described under {patent}.\n"
            "- Target immediate optimization of moisture levels, mixing parameters, and environmental relative humidity."
        )

    return f"""### 1. Root Cause Analysis
{root_cause}

### 2. Process Parameter Gaps
{gaps}

### 3. Corrective Action & Preventive Action (CAPA)
{capa}"""


def _call_gemini(drug_id: str, alert_type: str, input_params: dict[str, float], api_key: str) -> str:
    """Call Gemini with exponential backoff (3 attempts)."""
    user_query = (
        f"Analyze this quality failure event:\n"
        f"- Drug Product: {drug_id}\n"
        f"- Observed NSQ Defect Label: {alert_type}\n"
        f"- Process Parameters Used: {json.dumps(input_params)}\n\n"
        f"Reference the CDSCO regulatory standards and pharmacopeial monographs "
        f"(IP/USP/Ph.Eur) in your reasoning."
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3-flash-preview:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
    }

    delay = 1.0
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.ok:
                result = response.json()
                return (
                    result.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text")
                    or "No response received from agent."
                )
            if response.status_code == 429 and attempt < 2:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP Error {response.status_code}")
        except Exception as exc:
            if attempt == 2:
                raise RuntimeError(f"LLM API connection failed after 3 attempts: {exc}") from exc
    return "No response received from agent."


def explain_nsq_failure(drug_id: str, alert_type: str, input_params: dict[str, float], api_key: str) -> str:
    """Public entry point — local heuristic or live API."""
    if not api_key:
        time.sleep(0.4)  # Mimic the original 800 ms async delay (perceived state)
        return _local_heuristic(drug_id, alert_type, input_params)
    return _call_gemini(drug_id, alert_type, input_params, api_key)


# ---------------------------------------------------------------------------
# Session state — same role as React's useState.
# ---------------------------------------------------------------------------
def _init_state() -> None:
    defaults: dict[str, Any] = {
        "selected_drug_id": "paracetamol",
        "search_query": "",
        "excipients": list(PRODUCT_CATALOG["paracetamol"].ideal_excipients),
        "process_params": {},
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
        "show_settings": False,
        "is_analyzing": False,
        "grading_result": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


def _reset_for_drug(drug_id: str) -> None:
    """Sync the workbench when the user picks a new drug (mirrors the useEffect)."""
    drug = PRODUCT_CATALOG[drug_id]
    st.session_state.excipients = list(drug.ideal_excipients)
    st.session_state.grading_result = None
    # Defaults 15% above max limit — triggers NSQ failures out of the gate.
    st.session_state.process_params = {
        k: round(spec.max * 1.15, 1) for k, spec in drug.ideal_parameters.items()
    }


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
def render_header() -> None:
    api_active = bool(st.session_state.api_key)
    data_status = "LIVE CDSCO" if USING_LIVE_DATA else "STATIC CATALOG"
    title_group = f"""
    <div class="nsq-header-title-group">
      {bioicon_inline('molecule', 28, '#1a1a1a')}
      <div class="nsq-header-titles">
        <h1>CDMO Off-Patent Intelligence Engine</h1>
        <p>Patent · Regulatory · Demand · Plant Readiness · Portfolio</p>
      </div>
    </div>
    """
    status_group = f"""
    <div class="nsq-header-status">
      <span class="pill" style="color:{'#009E73' if api_active else '#737373'}; background:{'#e6f5f1' if api_active else '#fafafa'}; border:1px solid {'#a3d9c5' if api_active else '#d9d9d9'};">
        {'● Gemini API active' if api_active else '○ Local AI mode'}
      </span>
      <span class="pill" style="color:{'#009E73' if USING_LIVE_DATA else '#8c6b00'}; background:{'#e6f5f1' if USING_LIVE_DATA else '#fffbeb'}; border:1px solid {'#a3d9c5' if USING_LIVE_DATA else '#fde68a'};">
        ● {data_status} · {len(LIVE_ALERT_STATS)} drugs
      </span>
    </div>
    """
    st.markdown(
        f"""
        <div class="nsq-header">
          {title_group}
          {status_group}
        </div>
        """,
        unsafe_allow_html=True,
    )

    mock_data_badge(use_mock=True)

    # Settings toggle (replaces React's settings modal — uses an expander)
    with st.expander("⚙  Modular Gemini-3-Flash API", expanded=st.session_state.show_settings):
        st.markdown(
            "Provide an API key to switch from deterministic heuristic prediction "
            "directly to real-time generative neural diagnostics."
        )
        cols = st.columns([3, 1])
        api_input = cols[0].text_input(
            "API Key",
            value=st.session_state.api_key,
            type="password",
            placeholder="Paste Gemini API Key…",
            label_visibility="collapsed",
        )
        if api_input != st.session_state.api_key:
            st.session_state.api_key = api_input
            st.rerun()
        if st.session_state.api_key and cols[1].button("Clear Key"):
            st.session_state.api_key = ""
            st.rerun()


# ---------------------------------------------------------------------------
# In-page product catalog (replaces the legacy sidebar catalog)
# ---------------------------------------------------------------------------
def render_catalog() -> None:
    st.markdown(
        """
        <div style="padding: 12px 0; border-bottom: 1px solid #d9d9d9; margin-bottom: 12px;">
          <div class="cdmo-section-title">Product Catalog &amp; Active Alerts</div>
          <p style="font-size:11px; color:#b0b0b0; margin:4px 0 0 0;">Sourced from CDSCO regulatory histories.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    query = st.text_input(
        "Filter formulations",
        value=st.session_state.search_query,
        placeholder=f"Filter {len(PRODUCT_CATALOG)} solid formulations…",
    )
    if query != st.session_state.search_query:
        st.session_state.search_query = query
        st.rerun()

    q = query.lower().strip()
    matches = [
        (k, d) for k, d in PRODUCT_CATALOG.items()
        if q in d.name.lower() or q in d.dosage_form.lower()
    ]

    if not matches:
        st.markdown(
            "<div style='padding:32px; text-align:center; color:#b0b0b0; font-size:11px;"
            "border:1px dashed #d9d9d9; border-radius:6px;'>No solid tablets match query.</div>",
            unsafe_allow_html=True,
        )
        return

    # Render catalog as a horizontal scrollable row of cards.
    cols = st.columns(min(len(matches), 4))
    for i, (drug_id, drug) in enumerate(matches[:16]):
        active = drug_id == st.session_state.selected_drug_id
        border = "#1a1a1a" if active else "#d9d9d9"
        bg = "#ffffff" if active else "#fafafa"
        with cols[i % len(cols)]:
            if st.button(
                f"{drug.name}\n{drug.dose} • {drug.dosage_form}",
                key=f"drug_{drug_id}",
                use_container_width=True,
            ):
                if drug_id != st.session_state.selected_drug_id:
                    st.session_state.selected_drug_id = drug_id
                    _reset_for_drug(drug_id)
                    st.rerun()
            st.markdown(
                f"""
                <div style="background:{bg}; border:1px solid {border}; border-radius:4px; padding:10px; margin-top:-8px;">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:10px; font-weight:700; color:#1a1a1a;">{drug.name}</span>
                    <span class="alerts-pill">{drug.total_alerts} Alerts</span>
                  </div>
                  <div style="font-size:10px; color:#737373; margin-top:4px;">{drug.dose} • {drug.dosage_form}</div>
                  <div style="margin-top:6px; background:#ffffff; border:1px solid #d9d9d9; padding:6px 8px; border-radius:3px; font-size:10px;">
                    <span style="font-weight:600; color:#8a2b0a;">♥ VigiBase Risk Profile</span>
                    <p style="color:#4a4a4a; margin:4px 0 0 0; font-size:9px; line-height:1.4;">{drug.vigibase_risks[0]['hazard']}: {drug.vigibase_risks[0]['desc']}</p>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        """
        <div class="cat-footer" style="padding:12px 0; margin-top:12px; border-top:1px solid #d9d9d9;">
          <span style="font-weight:700; color:#4a4a4a; font-size:11px;">Linked Database:</span>
          <code style="font-size:10px;">CDSCO Not of Standard Quality (NSQ) Drug Alerts List - Consolidated(1)_2.csv</code>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main workbench — three columns: excipient editor / pharmacopeia / process
# (matches the React two-column workspace).
# ---------------------------------------------------------------------------
def render_active_drug(drug: Drug) -> None:
    # Header card (D6 / D4)
    patent_html = (
        f'<a href="{drug.patent_link}" target="_blank" rel="noopener noreferrer" '
        f'class="mono" style="color:#4f46e5; font-size:11px; text-decoration:none;">'
        f'{drug.patent_ref} ↗</a>'
        if drug.patent_link
        else f'<span class="mono" style="color:#4f46e5; font-size:11px;">{drug.patent_ref}</span>'
    )
    st.markdown(
        f"""
        <div class="nsq-card">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;
                      border-bottom:1px solid #d9d9d9; padding-bottom:16px; margin-bottom:16px;">
            <div>
              <div class="nsq-eyebrow">Selected Formulation Core</div>
              <h2 class="nsq-title">{drug.name}</h2>
              <p style="font-size:12px; color:#737373; margin:4px 0 0 0;">
                GMP Baseline: {patent_html}
              </p>
            </div>
            <div style="text-align:right;">
              <div class="nsq-eyebrow">CDSCO Ref Status</div>
              <div class="mono" style="font-size:11px; color:#4a4a4a; margin-top:4px;">
                Indexed in database
              </div>
            </div>
          </div>

          <div style="margin-top:8px;">
            <div class="nsq-eyebrow" style="display:flex; align-items:center; gap:6px; margin-bottom:8px;">
              <span style="color:#dc2626;">♥</span> Active VigiBase Signals
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
              {''.join(
                f'<div class="risk-tile"><span class="hazard">{r["hazard"]}</span>'
                f'<span class="desc">{r["desc"]}</span></div>'
                for r in drug.vigibase_risks
              )}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_excipient_editor() -> None:
    """D2 — Formula Core & Excipients (add/remove)."""
    st.markdown(
        """
        <div class="nsq-card">
          <div class="nsq-eyebrow-row">
            <span class="nsq-eyebrow">Formula Core & Excipients (D2)</span>
            <span class="mono" style="font-size:11px; color:#b0b0b0;">
              Current items: <span id="ex-count">0</span>
            </span>
          </div>
        """,
        unsafe_allow_html=True,
    )

    # Render each excipient row with a delete button
    for idx, ex in enumerate(list(st.session_state.excipients)):
        cols = st.columns([6, 2, 1])
        cols[0].markdown(
            f"""
            <div>
              <strong style="color:#1a1a1a;">{ex.name}</strong>
              <span style="margin-left:8px; padding:2px 6px; background:#d9d9d9; color:#4a4a4a;
                           border-radius:3px; font-size:9px; font-weight:800; text-transform:uppercase;">
                {ex.role}
              </span>
              <p style="font-size:10px; color:#b0b0b0; margin:4px 0 0 0;">{ex.description}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f'<div style="text-align:right; font-family:ui-monospace,monospace; '
            f'font-weight:700; color:#4a4a4a; padding-top:8px;">{ex.ratio:.1f}%</div>',
            unsafe_allow_html=True,
        )
        if cols[2].button("🗑", key=f"del_{idx}"):
            st.session_state.excipients.pop(idx)
            st.rerun()

    # Add-excipient form
    with st.form("add_excipient", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([5, 4, 2, 1])
        new_name = c1.text_input("Excipient Name", placeholder="e.g., Lactose Monohydrate", label_visibility="collapsed")
        new_role = c2.selectbox(
            "Functional Role",
            ["Diluent", "Binder", "Disintegrant", "Lubricant", "Alkalizer", "Enteric Polymer"],
            label_visibility="collapsed",
        )
        new_ratio = c3.number_input("Ratio (%)", min_value=0.1, value=2.0, step=0.1, label_visibility="collapsed")
        submitted = c4.form_submit_button("➕")
        if submitted and new_name.strip():
            st.session_state.excipients.append(
                Excipient(
                    name=new_name.strip(),
                    role=new_role,
                    ratio=float(new_ratio),
                    description="Custom formulation additive.",
                )
            )
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_pharmacopeia(drug: Drug) -> None:
    """D1 — Pharmacopeia compliance protocols."""
    st.markdown(
        f"""
        <div class="nsq-card">
          <div class="nsq-eyebrow" style="display:flex; align-items:center; gap:6px;">
            <span style="color:#4f46e5;">📖</span> Pharmacopeia Compliance Protocols (D1)
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px;">
            <div class="pharma-tile">
              <h5>IP 2026 Standards</h5>
              <p><strong>Assay:</strong> {drug.ip2026.assay}</p>
              <p><strong>Dissolution:</strong> {drug.ip2026.dissolution}</p>
              <p><strong>Impurities Limit:</strong> {drug.ip2026.impurities}</p>
            </div>
            <div class="pharma-tile">
              <h5>Ph. Eur. Standards</h5>
              <p><strong>Assay:</strong> {drug.ph_eur.assay}</p>
              <p><strong>Dissolution:</strong> {drug.ph_eur.dissolution}</p>
              <p><strong>Impurities Limit:</strong> {drug.ph_eur.impurities}</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_process_deck(drug: Drug) -> None:
    """D5 — Scale-Up Parameter Deck (sliders)."""
    st.markdown(
        """
        <div class="nsq-card">
          <div class="nsq-eyebrow">Scale-Up Parameter Deck</div>
          <p style="font-size:11px; color:#b0b0b0; margin:4px 0 0 0;">
            Simulate process values to trigger predictive failure diagnostics.
          </p>
        """,
        unsafe_allow_html=True,
    )

    # Ensure every parameter has a value (first render)
    for k, spec in drug.ideal_parameters.items():
        if k not in st.session_state.process_params:
            st.session_state.process_params[k] = round(spec.max * 1.15, 1)

    for key, spec in drug.ideal_parameters.items():
        slider_min = round(spec.min * 0.5, 1)
        slider_max = round(spec.max * 1.5, 1)
        current = float(st.session_state.process_params.get(key, spec.ideal))
        new_val = st.slider(
            f"{spec.label} ({spec.unit})",
            min_value=slider_min,
            max_value=slider_max,
            value=current,
            step=0.1,
            key=f"pp_{drug.id}_{key}",
            help=f"Ideal: {spec.ideal}{spec.unit} • Range: {spec.min}–{spec.max}{spec.unit}",
        )
        if new_val != current:
            st.session_state.process_params[key] = new_val

    run_clicked = st.button("⚙  Analyze Process (D5)", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if run_clicked:
        _run_analysis(drug)


# ---------------------------------------------------------------------------
# D3 + D5 — Run the analysis (grade + heuristic/LLM explanation)
# ---------------------------------------------------------------------------
def _run_analysis(drug: Drug) -> None:
    st.session_state.is_analyzing = True
    try:
        reference = drug.ideal_parameters
        current_values: dict[str, float] = {
            k: float(st.session_state.process_params.get(k, reference[k].ideal))
            for k in reference
        }

        # Score
        score = 100
        feedback: list[str] = []
        for k, spec in reference.items():
            val = current_values[k]
            if val < spec.min or val > spec.max:
                score -= 25
                feedback.append(
                    f"Parameter '{spec.label}' ({val}{spec.unit}) violates ideal GMP "
                    f"corridor of {spec.min}{spec.unit} - {spec.max}{spec.unit}."
                )

        # Chemical compatibility checks
        has_alkalizer = any(ex.role == "Alkalizer" for ex in st.session_state.excipients)
        has_reducing = any("lactose" in ex.name.lower() for ex in st.session_state.excipients)

        if drug.id in {"rabeprazole", "pantoprazole"}:
            if not has_alkalizer:
                score -= 20
                feedback.append(
                    "Missing pH-stabilizing Alkalizer (e.g. Sodium Carbonate) "
                    "in gastro-resistant coating substrate."
                )
            if has_reducing:
                score -= 15
                feedback.append(
                    "Severe incompatibility detected: Benzimidazole amine matrix blended "
                    "with reducing sugars, promoting Maillard browning."
                )

        if drug.id == "telmisartan" and not has_alkalizer:
            score -= 25
            feedback.append(
                "Critically missing Meglumine alkalizer. Telmisartan remains insoluble "
                "at physiological pH."
            )

        if drug.id == "ramipril" and has_alkalizer:
            score -= 15
            feedback.append(
                "Caution: Basic excipients catalyze ramipril intramolecular cyclization "
                "to diketopiperazine (DKP)."
            )

        # Grade
        if score >= 90:
            grade = "A"
        elif score >= 75:
            grade = "B"
        elif score >= 60:
            grade = "C"
        elif score >= 45:
            grade = "D"
        else:
            grade = "F"

        primary_alert = drug.common_alerts[0]
        try:
            explanation = explain_nsq_failure(
                drug.id, primary_alert, current_values, st.session_state.api_key
            )
            st.session_state.grading_result = {
                "grade": grade,
                "score": max(10, score),
                "feedback": feedback,
                "explanation": explanation,
            }
        except Exception as exc:
            st.session_state.grading_result = {
                "grade": "F",
                "score": 0,
                "feedback": [f"Critical Engine Failure: {exc}"],
                "explanation": "Unable to process failure diagnostics. Check your LLM configurations.",
            }
    finally:
        st.session_state.is_analyzing = False


def render_results() -> None:
    """D3 + D5 output — grade card and diagnostic log."""
    result = st.session_state.grading_result
    if not result:
        st.markdown(
            """
            <div class="empty-state">
              <div style="font-size:24px; color:#d9d9d9;">🧪</div>
              <p style="font-weight:600; margin:8px 0 4px 0; color:#737373;">No active analysis.</p>
              <p style="font-size:10px; color:#b0b0b0;">
                Initialize the process parameters on the left and execute the
                process review engine.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    grade = result["grade"]
    grade_class = f"grade-{grade}"
    feedback_html = (
        f"""
        <div class="fb-item fb-ok">
          <span>✓</span>
          <span>Process operates safely inside the ideal GMP corridor.</span>
        </div>
        """
        if not result["feedback"]
        else "".join(
            f'<div class="fb-item fb-err"><span>⚠</span><span>{item}</span></div>'
            for item in result["feedback"]
        )
    )

    st.markdown(
        f"""
        <div class="nsq-card">
          <div style="display:flex; justify-content:space-between; align-items:center;
                      border-bottom:1px solid #d9d9d9; padding-bottom:12px;">
            <div>
              <div class="nsq-eyebrow">Process Assessment Grade</div>
              <p style="font-size:10px; color:#b0b0b0; margin:4px 0 0 0;">
                Based on reference compliance matching.
              </p>
            </div>
            <div class="grade-badge {grade_class}">{grade}</div>
          </div>

          <div style="margin-top:12px;">
            <div class="nsq-eyebrow" style="margin-bottom:6px;">Compliance Gaps</div>
            {feedback_html}
          </div>

          <div style="margin-top:16px; padding-top:12px; border-top:1px solid #d9d9d9;">
            <div class="nsq-eyebrow" style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
              <span>📄</span> Agent Diagnostic Log
            </div>
            <div class="diag-log">{result["explanation"]}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Feature-card navigation + stepper
# ---------------------------------------------------------------------------
_FEATURE_CARDS = [
    ("catalog", "NSQ Catalog", "CDSCO alert history, formulation core, excipient editor, process diagnostics.", "pill", 0),
    ("demand", "Demand Radar", "Compare molecules by patent, regulatory, and demand signals.", "chart", 1),
    ("patent", "Patent Radar", "LOE timelines, export-eligible geographies, and FTO heatmaps.", "dna", 2),
    ("plant", "Plant Match", "Score molecule requirements against plant capability.", "factory", 3),
    ("readiness", "Plant Readiness", "Manufacturing complexity, customer fit, and roadmaps.", "microscope", 4),
    ("regulatory", "Regulatory Passport", "Pharmacopeia monographs, RLD/TE, and exclusivity.", "document", 5),
    ("portfolio", "Portfolio Builder", "Rank candidates, tune weights, export launch calendar.", "beaker", 6),
]


def render_feature_cards(active_tab_index: int) -> None:
    """Render clickable feature-card navigation above the tab bar."""
    st.markdown('<div style="margin-bottom: 8px;">', unsafe_allow_html=True)
    cols = st.columns(len(_FEATURE_CARDS))
    for col, (key, title, desc, icon, tab_index) in zip(cols, _FEATURE_CARDS):
        with col:
            if feature_card(key, title, desc, icon, active=tab_index == active_tab_index):
                st.session_state["active_tab_index"] = tab_index
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


def render_stepper(active_tab_index: int) -> None:
    """Render a stepper that matches the selected feature-card tab."""
    step_labels = ["Catalog", "Demand", "Patent", "Match Plant", "Readiness", "Regulatory", "Portfolio"]
    stepper(step_labels, current_index=active_tab_index)


# ---------------------------------------------------------------------------
# Page composition
# ---------------------------------------------------------------------------
def main() -> None:
    render_header()

    active_tab = st.session_state.get("active_tab_index", 6)
    if active_tab >= 7:
        active_tab = 6

    render_stepper(active_tab)
    render_feature_cards(active_tab)

    if active_tab == 0:
        render_catalog()
        drug = PRODUCT_CATALOG[st.session_state.selected_drug_id]
        render_active_drug(drug)
        left, right = st.columns([2.2, 1], gap="medium")
        with left:
            render_excipient_editor()
            render_pharmacopeia(drug)
        with right:
            render_process_deck(drug)
            render_results()
    elif active_tab == 1:
        from intelligence.pages import demand_radar
        demand_radar.render()
    elif active_tab == 2:
        from intelligence.pages import patent_radar
        patent_radar.render()
    elif active_tab == 3:
        from intelligence.pages import plant_match
        plant_match.render()
    elif active_tab == 4:
        from intelligence.pages import plant_readiness
        plant_readiness.render()
    elif active_tab == 5:
        from intelligence.pages import regulatory_passport
        regulatory_passport.render()
    elif active_tab == 6:
        from intelligence.pages import portfolio
        portfolio.render()


main()
