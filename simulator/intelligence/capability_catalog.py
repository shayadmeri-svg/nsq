"""Central capability taxonomy for the digital plant-profile builder.

Capabilities are grouped into 7 GMP infrastructure sections and use canonical
tokens that the scoring engine already understands (e.g. `wet_granulation`,
`aseptic_fill`, `potent_containment`).  Additional descriptive tokens are also
included; they do not break scoring and can be expanded later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Capability:
    """One selectable plant capability."""

    token: str
    label: str
    section_id: str


@dataclass(frozen=True)
class CapabilitySection:
    """One of the 7 infrastructure sections."""

    section_id: str
    title: str
    icon: str
    description: str
    capabilities: list[Capability] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capability catalog organized into the 7 infrastructure sections from the
# user's GMP plant-design context.
# ---------------------------------------------------------------------------
_CAPABILITIES: list[Capability] = [
    # 1. Architectural, HVAC & Environmental Segregation Infrastructure
    Capability("building_in_building_segregation", "Building-in-building physical segregation", "architectural_hvac"),
    Capability("grade_a_cleanroom", "Grade A/B cleanroom (positive pressure)", "architectural_hvac"),
    Capability("grade_c_cleanroom", "Grade C/D bioprocessing cleanroom", "architectural_hvac"),
    Capability("positive_pressure_hvac", "Positive-pressure HVAC cascade (biologics)", "architectural_hvac"),
    Capability("negative_pressure_hvac", "Negative-pressure HVAC cascade (HPAPI)", "architectural_hvac"),
    Capability("hepa_terminal_filtration", "Terminal HEPA / ULPA filtration", "architectural_hvac"),
    Capability("hepa_bibo_exhaust", "Push-push HEPA exhaust with BIBO change-out", "architectural_hvac"),
    Capability("personnel_airlock", "Personnel airlock (PAL) with interlocks/showers", "architectural_hvac"),
    Capability("material_airlock", "Material airlock (MAL) with VHP pass-through", "architectural_hvac"),
    Capability("cold_chain_airlocks", "2–8 °C cold-chain airlocks", "architectural_hvac"),

    # 2. Upstream, Downstream & Fill-Finish Biologics Infrastructure
    Capability("cryo_cell_bank", "Cryogenic cell banking (LN2, MCB/WCB)", "biologics_fill_finish"),
    Capability("inoculum_expansion", "Inoculum expansion suite", "biologics_fill_finish"),
    Capability("single_use_bioreactor", "Single-use bioreactor train", "biologics_fill_finish"),
    Capability("stainless_bioreactor", "Stainless-steel bioreactor train (CIP/SIP)", "biologics_fill_finish"),
    Capability("continuous_media_prep", "Continuous media preparation", "biologics_fill_finish"),
    Capability("centrifuge_clarification", "Disc-stack centrifuge clarification", "biologics_fill_finish"),
    Capability("depth_filtration", "Depth filtration clarification", "biologics_fill_finish"),
    Capability("acoustic_clarification", "Acoustic wave clarification", "biologics_fill_finish"),
    Capability("protein_a_chromatography", "Protein A affinity chromatography", "biologics_fill_finish"),
    Capability("cex_chromatography", "Cation-exchange (CEX) chromatography", "biologics_fill_finish"),
    Capability("aex_chromatography", "Anion-exchange (AEX) chromatography", "biologics_fill_finish"),
    Capability("hic_chromatography", "Hydrophobic interaction (HIC) chromatography", "biologics_fill_finish"),
    Capability("viral_inactivation", "Low-pH viral inactivation", "biologics_fill_finish"),
    Capability("viral_nanofiltration", "Viral-retentive nanofiltration (15–20 nm)", "biologics_fill_finish"),
    Capability("uf_df_tff", "UF/DF tangential-flow filtration", "biologics_fill_finish"),
    Capability("rhuph20_coformulation", "Subcutaneous rHuPH20 co-formulation", "biologics_fill_finish"),
    Capability("barrier_isolator_filling", "Barrier isolator filling line", "biologics_fill_finish"),
    Capability("vial_filling", "Glass vial filling line", "biologics_fill_finish"),
    Capability("pfs_filling", "Pre-filled syringe (PFS) filling line", "biologics_fill_finish"),
    Capability("cartridge_filling", "Cartridge filling line", "biologics_fill_finish"),
    Capability("depyrogenation_tunnel", "Component depyrogenation tunnel", "biologics_fill_finish"),
    Capability("hvld_ccit", "HVLD leak detection", "biologics_fill_finish"),
    Capability("vacuum_decay_ccit", "Vacuum decay CCIT", "biologics_fill_finish"),
    Capability("automated_visual_inspection", "Automated visual inspection", "biologics_fill_finish"),
    Capability("bioreactor", "Bioreactor / cell culture", "biologics_fill_finish"),
    Capability("cell_culture", "Cell culture expansion", "biologics_fill_finish"),
    Capability("protein_a", "Protein A capture", "biologics_fill_finish"),
    Capability("bioassay", "Cell-based / binding bioassay", "biologics_fill_finish"),
    Capability("aseptic_fill", "Aseptic fill-finish", "biologics_fill_finish"),
    Capability("isolator_technology", "Isolator / RABS technology", "biologics_fill_finish"),
    Capability("sterility_testing", "Sterility testing", "biologics_fill_finish"),
    Capability("visual_inspection", "Visual inspection", "biologics_fill_finish"),

    # 3. High-Potency Small Molecule (HPAPI) OSD Infrastructure
    Capability("high_containment_isolator", "High-containment isolator / glovebox", "hpapi_osd"),
    Capability("split_butterfly_valve", "Split butterfly valve (SBV) transfer", "hpapi_osd"),
    Capability("vacuum_powder_transfer", "Vacuum powder transfer (nitrogen inerted)", "hpapi_osd"),
    Capability("potent_containment", "Potent-compound containment", "hpapi_osd"),
    Capability("dust_extraction", "Continuous dust extraction", "hpapi_osd"),
    Capability("dedicated_equipment", "Dedicated equipment / cytotoxic suite", "hpapi_osd"),
    Capability("high_shear_wet_granulation", "High-shear wet granulation", "hpapi_osd"),
    Capability("wet_granulation", "Wet granulation", "hpapi_osd"),
    Capability("fluid_bed_drying", "Fluid bed drying", "hpapi_osd"),
    Capability("roller_compaction", "Roller compaction / dry granulation", "hpapi_osd"),
    Capability("dry_granulation", "Dry granulation", "hpapi_osd"),
    Capability("hot_melt_extrusion", "Hot-melt extrusion (HME)", "hpapi_osd"),
    Capability("spray_drying", "Closed-cycle spray drying", "hpapi_osd"),
    Capability("high_containment_tablet_press", "High-containment tablet press", "hpapi_osd"),
    Capability("containment_capsule_filler", "Containment capsule filler", "hpapi_osd"),
    Capability("compression", "Tablet compression", "hpapi_osd"),
    Capability("enclosed_film_coater", "Enclosed film coater", "hpapi_osd"),
    Capability("film_coating", "Film coating", "hpapi_osd"),
    Capability("enteric_coating", "Enteric coating", "hpapi_osd"),
    Capability("high_barrier_blister", "High-barrier blister line", "hpapi_osd"),
    Capability("al_al_blister", "Al-Al cold-form blister", "hpapi_osd"),
    Capability("blister_packing", "Blister packing", "hpapi_osd"),
    Capability("bottle_packing", "Bottle packing", "hpapi_osd"),
    Capability("vision_inspection", "100% vision inspection", "hpapi_osd"),

    # 4. QC Analytical & Microbiological Testing Infrastructure
    Capability("sec_hplc", "SEC-HPLC / UHPLC for aggregates", "qc_analytical"),
    Capability("icief", "Imaged capillary isoelectric focusing", "qc_analytical"),
    Capability("cex_hplc", "CEX-HPLC charge-variant analysis", "qc_analytical"),
    Capability("ce_sds", "CE-SDS purity", "qc_analytical"),
    Capability("spr_biacore", "SPR / Biacore binding kinetics", "qc_analytical"),
    Capability("bli", "Bio-layer interferometry (BLI)", "qc_analytical"),
    Capability("microplate_reader", "Microplate reader", "qc_analytical"),
    Capability("flow_cytometry", "Flow cytometry", "qc_analytical"),
    Capability("hrms_lc_ms", "HRMS / LC-MS peptide mapping", "qc_analytical"),
    Capability("rp_uplc", "RP-UPLC / HPLC", "qc_analytical"),
    Capability("gc_ms", "Headspace GC-MS", "qc_analytical"),
    Capability("ftir", "FTIR / ATR raw-material ID", "qc_analytical"),
    Capability("xrpd", "XRPD polymorph characterization", "qc_analytical"),
    Capability("dsc", "Differential scanning calorimetry", "qc_analytical"),
    Capability("tga", "Thermogravimetric analysis", "qc_analytical"),
    Capability("icp_ms", "ICP-MS elemental impurities", "qc_analytical"),
    Capability("dissolution_testing", "Dissolution testing", "qc_analytical"),
    Capability("sterility_testing_isolator", "Sterility testing isolator", "qc_analytical"),
    Capability("endotoxin_testing", "Endotoxin / LAL testing", "qc_analytical"),
    Capability("particulate_testing", "Particulate / subvisible testing", "qc_analytical"),
    Capability("analytical_qc", "Analytical QC lab", "qc_analytical"),
    Capability("analytical_development", "Analytical development", "qc_analytical"),
    Capability("method_validation", "Method validation", "qc_analytical"),
    Capability("stability_testing", "Stability testing", "qc_analytical"),
    Capability("lims", "Laboratory information management system", "qc_analytical"),

    # 5. Process Utilities, Environmental & Waste Management
    Capability("wfi_generation", "Water-for-injection generation", "process_utilities"),
    Capability("purified_water_generation", "Purified water generation", "process_utilities"),
    Capability("clean_steam_generator", "Clean steam generator", "process_utilities"),
    Capability("compressed_air", "Oil-free compressed air", "process_utilities"),
    Capability("inert_gases", "Inert gas distribution (N₂/O₂/CO₂)", "process_utilities"),
    Capability("bio_kill_thermal_inactivation", "Bio-kill thermal inactivation", "process_utilities"),
    Capability("hpapi_neutralization", "HPAPI neutralization", "process_utilities"),
    Capability("solvent_recovery", "Solvent recovery / collection", "process_utilities"),

    # 6. GMP Automation, Digital Infrastructure & Quality Systems
    Capability("dcs_scada", "DCS / SCADA", "automation_digital"),
    Capability("mes_ebr", "MES with electronic batch records", "automation_digital"),
    Capability("qms", "Quality management system", "automation_digital"),
    Capability("edms", "Electronic document management", "automation_digital"),
    Capability("serialization_aggregation", "Serialization & aggregation", "automation_digital"),
    Capability("serialization", "Serialization", "automation_digital"),
    Capability("track_and_trace", "Track-and-trace / DSCSA-FMD", "automation_digital"),
    Capability("process_validation", "Process validation", "automation_digital"),
    Capability("validated_cleaning", "Validated cleaning", "automation_digital"),

    # 7. Warehousing, Cold Chain & GDP Logistics Infrastructure
    Capability("ultra_low_freezer", "Ultra-low freezer (−80 °C / −20 °C)", "warehousing_coldchain"),
    Capability("cold_room", "Cold room (2–8 °C)", "warehousing_coldchain"),
    Capability("controlled_room_temperature", "Controlled room-temperature ASRS", "warehousing_coldchain"),
    Capability("flammable_solvent_storage", "Flammable solvent storage (ATEX)", "warehousing_coldchain"),
    Capability("hpapi_secure_vault", "HPAPI secure vault", "warehousing_coldchain"),
    Capability("cold_chain_packaging", "Cold-chain packaging qualification", "warehousing_coldchain"),
    Capability("datalogger_programming", "Datalogger programming", "warehousing_coldchain"),
    Capability("temperature_monitored_dock", "Temperature-monitored shipping dock", "warehousing_coldchain"),
    Capability("cold_chain_logistics", "Cold-chain logistics", "warehousing_coldchain"),
    Capability("ccit_testing", "Container-closure integrity testing", "warehousing_coldchain"),
]

SECTIONS: list[CapabilitySection] = [
    CapabilitySection(
        section_id="architectural_hvac",
        title="Architectural, HVAC & Environmental Segregation",
        icon="factory",
        description="Physical segregation, cleanroom zoning, pressure cascades, and airlocks.",
        capabilities=[c for c in _CAPABILITIES if c.section_id == "architectural_hvac"],
    ),
    CapabilitySection(
        section_id="biologics_fill_finish",
        title="Upstream, Downstream & Fill-Finish Biologics",
        icon="dna",
        description="Cell banking, bioreactors, chromatography, viral clearance, aseptic fill-finish, inspection.",
        capabilities=[c for c in _CAPABILITIES if c.section_id == "biologics_fill_finish"],
    ),
    CapabilitySection(
        section_id="hpapi_osd",
        title="High-Potency Small Molecule (HPAPI) OSD",
        icon="pill",
        description="Containment, granulation, solid dispersions, tableting, coating, and packaging for potent solids.",
        capabilities=[c for c in _CAPABILITIES if c.section_id == "hpapi_osd"],
    ),
    CapabilitySection(
        section_id="qc_analytical",
        title="QC Analytical & Microbiological Testing",
        icon="microscope",
        description="Biologic and small-molecule analytical suites plus microbiology testing.",
        capabilities=[c for c in _CAPABILITIES if c.section_id == "qc_analytical"],
    ),
    CapabilitySection(
        section_id="process_utilities",
        title="Process Utilities, Environment & Waste",
        icon="beaker",
        description="WFI/PW, clean steam, gases, bio-kill, and HPAPI/solvent waste handling.",
        capabilities=[c for c in _CAPABILITIES if c.section_id == "process_utilities"],
    ),
    CapabilitySection(
        section_id="automation_digital",
        title="GMP Automation, Digital & Quality Systems",
        icon="chart",
        description="DCS/SCADA, MES, LIMS, QMS, serialization, and validation systems.",
        capabilities=[c for c in _CAPABILITIES if c.section_id == "automation_digital"],
    ),
    CapabilitySection(
        section_id="warehousing_coldchain",
        title="Warehousing, Cold Chain & GDP Logistics",
        icon="document",
        description="Multi-temperature storage, hazardous vaults, cold-chain packaging, and serialization.",
        capabilities=[c for c in _CAPABILITIES if c.section_id == "warehousing_coldchain"],
    ),
]

CAPABILITY_BY_TOKEN: dict[str, Capability] = {c.token: c for c in _CAPABILITIES}

# Canonical tokens that the scoring engine already recognises.
SCORING_TOKENS: set[str] = {
    "wet_granulation",
    "dry_granulation",
    "compression",
    "film_coating",
    "enteric_coating",
    "blister_packing",
    "bottle_packing",
    "fluid_bed_drying",
    "liquid_oral_filling",
    "suspension_manufacturing",
    "aseptic_fill",
    "isolator_technology",
    "sterility_testing",
    "bioreactor",
    "visual_inspection",
    "potent_containment",
    "dust_extraction",
    "dedicated_equipment",
    "analytical_qc",
    "validated_cleaning",
    "process_validation",
    "analytical_development",
    "stability_testing",
    "method_validation",
    "ccit_testing",
    "serialization",
    "cold_chain_logistics",
    "cell_culture",
    "protein_a",
    "bioassay",
    "solid_phase_synthesis",
    "chromatography",
    "sterile_liquid",
    "lyophilization",
}

# ---------------------------------------------------------------------------
# Helpers for UI and model construction
# ---------------------------------------------------------------------------


def section_for_token(token: str) -> CapabilitySection | None:
    """Return the section that owns the given capability token."""
    cap = CAPABILITY_BY_TOKEN.get(token)
    if cap is None:
        return None
    for section in SECTIONS:
        if section.section_id == cap.section_id:
            return section
    return None


def infer_plant_defaults(selected_capabilities: list[str]) -> dict[str, Any]:
    """Given selected capability tokens, infer sensible PlantAsset defaults.

    This keeps the UI focused on capabilities while still producing a plant
    that scores meaningfully against molecules.
    """
    caps = set((c or "").lower() for c in selected_capabilities)

    # Experience flags
    biologic_tokens = {
        "cryo_cell_bank",
        "inoculum_expansion",
        "single_use_bioreactor",
        "stainless_bioreactor",
        "continuous_media_prep",
        "centrifuge_clarification",
        "depth_filtration",
        "acoustic_clarification",
        "protein_a_chromatography",
        "cex_chromatography",
        "aex_chromatography",
        "hic_chromatography",
        "viral_inactivation",
        "viral_nanofiltration",
        "uf_df_tff",
        "rhuph20_coformulation",
        "barrier_isolator_filling",
        "vial_filling",
        "pfs_filling",
        "cartridge_filling",
        "depyrogenation_tunnel",
        "hvld_ccit",
        "vacuum_decay_ccit",
        "cell_culture",
        "protein_a",
        "bioassay",
        "bioreactor",
        "aseptic_fill",
        "sterility_testing",
        "lyophilization",
    }
    small_molecule_tokens = {
        "wet_granulation",
        "dry_granulation",
        "compression",
        "film_coating",
        "enteric_coating",
        "blister_packing",
        "bottle_packing",
        "fluid_bed_drying",
        "liquid_oral_filling",
        "suspension_manufacturing",
        "high_shear_wet_granulation",
        "roller_compaction",
        "hot_melt_extrusion",
        "spray_drying",
        "high_containment_tablet_press",
        "containment_capsule_filler",
        "enclosed_film_coater",
        "high_barrier_blister",
        "al_al_blister",
        "vision_inspection",
    }

    biologics_experience = bool(caps & biologic_tokens)
    small_molecule_experience = bool(caps & small_molecule_tokens)

    # Containment class priority: cytotoxic > potent > biologic_GMP > standard
    containment_class = "standard"
    if "dedicated_equipment" in caps or "hpapi_neutralization" in caps:
        containment_class = "cytotoxic"
    elif "potent_containment" in caps or "high_containment_isolator" in caps or "hpapi_secure_vault" in caps:
        containment_class = "potent"
    elif biologics_experience and "aseptic_fill" in caps:
        containment_class = "biologic_GMP"

    # Certifications
    certifications_active: list[str] = ["WHO_GMP"]
    if "grade_a_cleanroom" in caps or "aseptic_fill" in caps or "sterility_testing" in caps:
        certifications_active.append("EU_GMP")
    if small_molecule_experience and "analytical_qc" in caps:
        certifications_active.append("USFDA")
    if biologics_experience:
        certifications_active.append("biologic_gmp")
    if containment_class in ("potent", "cytotoxic"):
        certifications_active.append("cytotoxic_licensing")

    # Approved forms
    approved_forms: list[str] = []
    if "compression" in caps or "wet_granulation" in caps or "dry_granulation" in caps:
        approved_forms.append("solid_oral")
    if "enteric_coating" in caps:
        approved_forms.append("enteric_tablet")
    if "containment_capsule_filler" in caps:
        approved_forms.append("capsule")
    if "sterile_liquid" in caps or "aseptic_fill" in caps:
        approved_forms.append("injection")
    if "vial_filling" in caps or "bioreactor" in caps:
        approved_forms.append("vial")
    if "pfs_filling" in caps:
        approved_forms.append("prefilled_syringe")
    if "cartridge_filling" in caps:
        approved_forms.append("prefilled_pen")
    if "liquid_oral_filling" in caps:
        approved_forms.append("syrup")
    if "suspension_manufacturing" in caps:
        approved_forms.append("suspension")

    # Talent depth — modest baseline scores that improve when implied by caps.
    talent_depth: dict[str, float] = {
        "formulation": 55.0 if small_molecule_experience else 25.0,
        "analytical": 55.0 if ("analytical_qc" in caps or "analytical_development" in caps) else 30.0,
        "regulatory_affairs": 60.0,
        "quality": 60.0,
        "bioprocess": 60.0 if ("cell_culture" in caps or "bioreactor" in caps) else 15.0,
        "sterile_manufacturing": 60.0 if ("aseptic_fill" in caps or "sterility_testing" in caps) else 15.0,
        "cytotoxic_handling": 60.0 if containment_class in ("potent", "cytotoxic") else 10.0,
        "packaging": 50.0 if ("blister_packing" in caps or "bottle_packing" in caps) else 20.0,
    }

    # Highlight equipment derived from selected capabilities
    equipment_highlights: list[str] = []
    for token in sorted(caps):
        cap = CAPABILITY_BY_TOKEN.get(token)
        if cap is None:
            continue
        if token in SCORING_TOKENS:
            equipment_highlights.append(cap.label)
    if not equipment_highlights:
        equipment_highlights.append("Custom plant profile")

    return {
        "city": "",
        "state": "",
        "country": "India",
        "capabilities": sorted(caps),
        "approved_forms": approved_forms,
        "containment_class": containment_class,
        "batch_capacity_kg": None,
        "certifications": certifications_active,
        "certifications_active": certifications_active,
        "small_molecule_experience": small_molecule_experience,
        "biologics_experience": biologics_experience,
        "small_molecule_experience_years": 12 if small_molecule_experience else 0,
        "biologics_experience_years": 8 if biologics_experience else 0,
        "api_sourcing_experience": bool(caps & {"analytical_qc", "analytical_development", "lims"}),
        "talent_profile": [k for k, v in talent_depth.items() if v >= 50],
        "talent_depth": talent_depth,
        "equipment_highlights": equipment_highlights[:12],
        "equipment_trains": [],
        "notes": "User-created digital plant profile. Capabilities were selected from the 7-section GMP infrastructure catalog.",
    }


def validate_capabilities(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Return (valid_tokens, invalid_tokens) for a requested capability list."""
    valid: list[str] = []
    invalid: list[str] = []
    for t in tokens:
        if t in CAPABILITY_BY_TOKEN:
            valid.append(t)
        else:
            invalid.append(t)
    return valid, invalid
