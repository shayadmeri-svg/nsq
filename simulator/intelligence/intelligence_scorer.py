"""Four-pillar scoring logic for the CDMO off-patent intelligence engine.

Version 0 (this brick):
- Patent pillar: fully implemented using PatentIntelligence.
- Plant-fit pillar: implemented using PlantAsset and a molecule capability map.
- Regulatory and Demand pillars: structured placeholders that return neutral
  scores with explanatory text so the API contract is stable.

The scoring function is intentionally deterministic and dependency-free so it
runs the same in the FastAPI container and in a Streamlit import.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from intelligence_models import CandidateScore, DemandProfile, PatentIntelligence, PlantAsset, RegulatoryPassport
from intelligence_store import load_demand, load_plant_asset, load_regulatory

# Default weights for the four pillars. Sum should be 1.0.
DEFAULT_WEIGHTS = {
    "patent": 0.25,
    "regulatory": 0.20,
    "demand": 0.25,
    "plant": 0.30,
}

# Capability requirements implied by therapeutic area / molecule class.
# Keys are canonical capability tokens; values are sets of required capability
# keywords that a plant must satisfy at least one of.
MOLECULE_CAPABILITY_HINTS: dict[str, list[str]] = {
    "mab": ["bioreactor", "cell_culture", "protein_a", "aseptic_fill", "lyophilization"],
    "small_molecule_oral": ["granulation", "compression", "film_coating", "blister_packing"],
    "small_molecule_injectable": ["sterile_liquid", "aseptic_fill", "lyophilization"],
    "peptide": ["solid_phase_synthesis", "chromatography", "aseptic_fill"],
}

# Form families each plant asset approves, mapped to rough molecule classes.
FORM_TO_CLASS = {
    "solid_oral": "small_molecule_oral",
    "enteric_tablet": "small_molecule_oral",
    "injection": "small_molecule_injectable",
    "vial": "small_molecule_injectable",
    "prefilled_pen": "mab",
    "prefilled_syringe": "mab",
    "biologic_vial": "mab",
}


def _days_until(target: Optional[date]) -> int:
    if target is None:
        return -1
    return (target - date.today()).days


def score_patent(patent: Optional[PatentIntelligence]) -> tuple[float, dict[str, Any]]:
    """Return a 0–100 score and explanation dict for the patent pillar.

    Logic:
    - Base 40 points for having any patent record at all.
    - Up to 30 points for proximity to LOE (closer = better for a CDMO wanting
      to prepare early, but not too close that launch prep is impossible).
    - Up to 20 points for low FTO risk.
    - Up to 10 points for market size.
    """
    if patent is None:
        return 0.0, {
            "summary": "No patent intelligence available.",
            "loe_window": "unknown",
            "fto": "unknown",
        }

    explanation: dict[str, Any] = {
        "summary": "",
        "loe_window": "",
        "fto": patent.fto_risk,
        "patent_count": patent.patent_count(),
    }

    score = 40.0

    earliest = patent.earliest_loe()
    if earliest:
        days = _days_until(earliest)
        explanation["loe_window"] = f"{days} days until earliest LOE ({earliest.isoformat()})"
        # Ideal prep window: 3–5 years out (1095–1825 days)
        if days < 0:
            score += 25  # already off-patent = high readiness
            explanation["loe_window"] += " — already off-patent in at least one market"
        elif 730 <= days <= 1825:
            score += 30  # sweet spot
        elif 365 <= days < 730:
            score += 20  # tight but actionable
        elif days < 365:
            score += 10  # very tight
        else:
            score += 15  # far out, long wait
    else:
        explanation["loe_window"] = "no LOE date available"

    fto_bonus = {"low": 20, "medium": 12, "high": 0}.get(patent.fto_risk, 10)
    score += fto_bonus

    if patent.market_size_usd_bn:
        # Cap at 10 points for >= $5B
        score += min(10, patent.market_size_usd_bn * 2)
        explanation["market_size"] = f"${patent.market_size_usd_bn:.1f}B peak sales"

    score = max(0.0, min(100.0, score))
    explanation["summary"] = f"Patent readiness {score:.0f}/100 — {patent.fto_risk} FTO risk, {explanation['loe_window']}"
    return score, explanation


def _exclusivity_active(exclusivity: list[dict[str, Any]]) -> bool:
    """Return True if any exclusivity entry has a future expiry_date."""
    for item in exclusivity:
        expiry_raw = item.get("expiry_date")
        if not expiry_raw:
            continue
        try:
            expiry = date.fromisoformat(str(expiry_raw))
            if expiry >= date.today():
                return True
        except ValueError:
            continue
    return False


def score_regulatory(
    regulatory: Optional[RegulatoryPassport],
    patent: Optional[PatentIntelligence],
) -> tuple[float, dict[str, Any]]:
    """Return a 0–100 regulatory clarity score and explanation.

    Scoring:
    - Base 20 for having a regulatory record.
    - Up to 30 points for pharmacopeia monograph coverage (10 each).
    - 25 points for A TE rating; 10 for B; 15 if none / unknown.
    - Up to 15 points for export-eligible geography count.
    - 10 points for BCS class + stability conditions present.
    - -20 penalty if active regulatory exclusivity remains.
    """
    if regulatory is None:
        return 50.0, {
            "summary": "Regulatory clarity placeholder (50/100) — no regulatory passport loaded.",
            "detail": "Run `just load-regulatory` to populate cdmo:regulatory:* keys.",
            "readiness": "placeholder",
        }

    score = 20.0
    details: list[str] = []

    monographs = 0
    if regulatory.ip_2026_monograph:
        monographs += 1
    if regulatory.ph_eur_monograph:
        monographs += 1
    if regulatory.usp_monograph:
        monographs += 1
    score += monographs * 10
    details.append(f"{monographs}/3 pharmacopeia monographs available")

    te = (regulatory.te_rating or "").upper()
    if te == "A":
        score += 25
        details.append(f"A-rated TE code ({regulatory.te_code}) — bioequivalent to RLD")
    elif te == "B":
        score += 10
        details.append(f"B-rated TE code ({regulatory.te_code}) — not yet therapeutically equivalent")
    else:
        score += 15
        details.append("No TE rating assigned / pending ANDA approval")

    eligible_count = patent.export_eligible_count() if patent else 0
    geo_bonus = min(15.0, eligible_count * 2.5)
    score += geo_bonus
    details.append(f"{eligible_count} export-eligible geographies")

    if regulatory.bcs_class and regulatory.stability_conditions:
        score += 10
        details.append(f"BCS class {regulatory.bcs_class} and stability conditions documented")

    if _exclusivity_active(regulatory.exclusivity):
        score -= 20
        details.append("Active FDA/regulatory exclusivity blocks immediate generic launch")

    score = max(0.0, min(100.0, score))
    summary = f"Regulatory clarity {score:.0f}/100 — {regulatory.readiness}"
    if regulatory.rld:
        summary += f" | RLD: {regulatory.rld}"
    return score, {
        "summary": summary,
        "detail": "; ".join(details),
        "readiness": regulatory.readiness,
    }


def score_demand(
    demand: Optional[DemandProfile],
    molecule_key: str,
) -> tuple[float, dict[str, Any]]:
    """Return a 0–100 demand attractiveness score and explanation.

    Scoring:
    - Base 10 for having a demand profile.
    - Up to 25 points for disease burden (combined global + India prevalence,
      log-scaled to avoid massive commodity molecules dominating).
    - Up to 15 points for growth trend (growing +15, stable +5, declining -10).
    - Up to 20 points for late-stage clinical trial pipeline (phase 3+).
    - Up to 15 points for therapeutic cluster premium (oncology/specialty
      injectable/immunology score higher than lifestyle/chronic; commodity lowest).
    - Up to 15 points for buyer activity / market momentum proxy.
    """
    if demand is None:
        return 50.0, {
            "summary": "Demand attractiveness placeholder (50/100) — no demand profile loaded.",
            "detail": "Run `just load-demand` to populate cdmo:demand:* keys.",
            "trend": "stable",
        }

    score = 10.0
    details: list[str] = []

    # Prevalence: log-scaled combined global + India burden
    combined_prevalence = demand.disease_prevalence_global_millions + demand.disease_prevalence_india_millions
    if combined_prevalence > 0:
        import math
        prevalence_score = min(25.0, 8.0 * math.log10(combined_prevalence + 1))
        score += prevalence_score
        details.append(f"combined prevalence {combined_prevalence:.1f}M → {prevalence_score:.0f} pts")
    else:
        details.append("no prevalence data")

    trend = (demand.growth_trend or "").lower()
    if trend == "growing":
        score += 15
        details.append("growing demand trend +15")
    elif trend == "stable":
        score += 5
        details.append("stable demand trend +5")
    elif trend == "declining":
        score -= 10
        details.append("declining demand trend -10")
    else:
        details.append("unknown trend")

    p3 = demand.trial_count_phase_3_plus
    trial_score = min(20.0, p3 * 2.0)
    score += trial_score
    details.append(f"{p3} phase-3+ trials → {trial_score:.0f} pts")

    cluster = (demand.cluster or "").lower()
    cluster_scores = {
        "oncology": 15,
        "specialty injectable": 14,
        "immunology": 13,
        "lifestyle / chronic": 9,
        "lifestyle/chronic": 9,
        "lifestyle": 9,
        "commodity": 4,
    }
    cluster_score = cluster_scores.get(cluster, 8)
    score += cluster_score
    details.append(f"{demand.cluster} cluster +{cluster_score}")

    momentum = (demand.buyer_activity_score + demand.market_momentum_score) / 2.0
    momentum_score = min(15.0, momentum * 0.15)
    score += momentum_score
    details.append(f"buyer/momentum proxy {momentum:.0f} → {momentum_score:.0f} pts")

    score = max(0.0, min(100.0, score))
    summary = f"Demand attractiveness {score:.0f}/100 — {demand.cluster or 'unknown cluster'}"
    if trend:
        summary += f", {trend} trend"
    return score, {
        "summary": summary,
        "detail": "; ".join(details),
        "trend": trend or "unknown",
    }


def _molecule_class(patent: Optional[PatentIntelligence]) -> str:
    """Heuristic molecule class from patent therapeutic area / known names."""
    if patent is None:
        return "small_molecule_oral"
    t = (patent.therapeutic_area or "").lower()
    api = (patent.api_name or "").lower()
    brand = (patent.brand_name or "").lower()
    combined = f"{t} {api} {brand}"
    if any(k in combined for k in ("mab", "monoclonal", "pembrolizumab", "nivolumab", "durvalumab", "daratumumab", "dupilumab")):
        return "mab"
    if "semaglutide" in combined:
        return "peptide"
    if "osimertinib" in combined or "palbociclib" in combined or "abemaciclib" in combined or "ribociclib" in combined:
        return "small_molecule_oral"
    if "injectable" in combined or "injection" in combined:
        return "small_molecule_injectable"
    return "small_molecule_oral"


# Mapping from molecule_class to more detailed manufacturing complexity tags.
MOLECULE_CLASS_TAGS: dict[str, dict[str, Any]] = {
    "mab": {
        "modality": "monoclonal_antibody",
        "drug_form": "vial",
        "route_of_administration": "iv",
        "sterility_required": True,
        "potency_classification": "biologic",
        "cqas": [" aggregates", "glycosylation", "charge_variants", " potency", "sterility", "endotoxin"],
        "process_complexity": 9.5,
        "analytical_complexity": 9.5,
        "biologic_complexity": 9.5,
    },
    "peptide": {
        "modality": "peptide",
        "drug_form": "prefilled_pen",
        "route_of_administration": "subcutaneous",
        "sterility_required": True,
        "potency_classification": "high_potency",
        "cqas": ["peptide_identity", "aggregation", " potency", "particulate_matter", "sterility", "endotoxin"],
        "process_complexity": 8.5,
        "analytical_complexity": 8.5,
        "biologic_complexity": 6.0,
    },
    "small_molecule_injectable": {
        "modality": "small_molecule",
        "drug_form": "injection",
        "route_of_administration": "iv",
        "sterility_required": True,
        "potency_classification": "potent",
        "cqas": ["sterility", "endotoxin", "particulate_matter", "assay", "related_substances"],
        "process_complexity": 7.0,
        "analytical_complexity": 6.5,
        "biologic_complexity": 0.0,
    },
    "small_molecule_oral": {
        "modality": "small_molecule",
        "drug_form": "tablet",
        "route_of_administration": "oral",
        "sterility_required": False,
        "potency_classification": "standard",
        "cqas": ["dissolution", "assay", "content_uniformity", "related_substances", "physical_stability"],
        "process_complexity": 4.0,
        "analytical_complexity": 4.0,
        "biologic_complexity": 0.0,
    },
}


def derive_manufacturing_complexity(
    molecule_key: str,
    patent: Optional[PatentIntelligence],
    regulatory: Optional[RegulatoryPassport],
) -> "ManufacturingComplexity":
    """Infer manufacturing complexity from patent and regulatory data."""
    from intelligence_models import ManufacturingComplexity

    base = MOLECULE_CLASS_TAGS.get(_molecule_class(patent), MOLECULE_CLASS_TAGS["small_molecule_oral"]).copy()
    cqas = list(base.get("cqas", []))
    process = base["process_complexity"]
    analytical = base["analytical_complexity"]
    biologic = base["biologic_complexity"]

    # Refine drug form from regulatory dosage_form if available.
    if regulatory and regulatory.dosage_form:
        form = (regulatory.dosage_form or "").lower()
        if "delayed" in form or "enteric" in form or "mups" in form:
            base["drug_form"] = "enteric_tablet"
            process += 2.0
            analytical += 1.5
            cqas.extend(["acid_resistance", "enteric_coat_integrity"])
        elif "capsule" in form:
            base["drug_form"] = "capsule"
        elif "injection" in form or "vial" in form:
            base["drug_form"] = "vial"
            base["sterility_required"] = True
        elif "pen" in form or "syringe" in form:
            base["drug_form"] = "prefilled_pen" if "pen" in form else "prefilled_syringe"
            base["sterility_required"] = True
            process += 1.5

    # Potency / containment adjustments.
    if patent and "oncology" in (patent.therapeutic_area or "").lower():
        if base["modality"] == "small_molecule":
            base["potency_classification"] = "cytotoxic"
        process += 1.0
        cqas.append("containment_cross_contamination")

    # Analytical complexity bump for complex monographs / BE / biosimilarity.
    if regulatory:
        monograph_count = sum(bool(getattr(regulatory, k)) for k in ("ip_2026_monograph", "ph_eur_monograph", "usp_monograph"))
        analytical += monograph_count * 0.5
        if (regulatory.te_rating or "").upper() == "B":
            analytical += 1.0  # additional comparability work
        if base["modality"] in ("monoclonal_antibody", "peptide", "recombinant_protein"):
            biologic += 1.0
            analytical += 1.0

    process = max(1.0, min(10.0, process))
    analytical = max(1.0, min(10.0, analytical))
    biologic = max(0.0, min(10.0, biologic))

    return ManufacturingComplexity(
        molecule_key=molecule_key,
        modality=base["modality"],
        drug_form=base["drug_form"],
        route_of_administration=base["route_of_administration"],
        sterility_required=base["sterility_required"],
        potency_classification=base["potency_classification"],
        critical_quality_attributes=sorted(set(c.strip() for c in cqas)),
        process_complexity_score=round(process, 1),
        analytical_complexity_score=round(analytical, 1),
        biologic_complexity_score=round(biologic, 1),
        notes=f"Derived from patent/regulatory signals: class={_molecule_class(patent)}, dosage_form={regulatory.dosage_form if regulatory else 'unknown'}.",
    )


def _equipment_matches(train: dict[str, Any], required_caps: set[str]) -> bool:
    cap = (train.get("capability") or "").lower()
    return cap in required_caps


def score_customer_profile_fit(
    complexity: "ManufacturingComplexity",
    plant: Optional[PlantAsset],
) -> tuple[float, float, float, float, str, list[str]]:
    """Return infrastructure, talent, certification fit scores, overall customer fit score, tier, and gaps."""
    if plant is None:
        return 0.0, 0.0, 0.0, 0.0, "stretch", ["No plant asset selected."]

    # Required capabilities inferred from complexity.
    required_caps: set[str] = set()
    modality = complexity.modality
    drug_form = complexity.drug_form
    if modality in ("monoclonal_antibody", "recombinant_protein", "fusion_protein"):
        required_caps.update(["cell_culture", "protein_a", "aseptic_fill", "sterility_testing", "bioassay"])
    elif modality == "peptide":
        required_caps.update(["solid_phase_synthesis", "chromatography", "aseptic_fill", "sterility_testing"])
    elif drug_form in ("injection", "vial"):
        required_caps.update(["sterile_liquid", "aseptic_fill", "lyophilization", "sterility_testing"])
    else:
        required_caps.update(["granulation", "compression", "film_coating", "blister_packing"])
        if drug_form == "enteric_tablet":
            required_caps.add("enteric_coating")
        if complexity.potency_classification in ("potent", "cytotoxic", "high_potency"):
            required_caps.add("potent_containment")

    plant_caps = set((c or "").lower() for c in plant.capabilities)
    train_caps = set((t.get("capability") or "").lower() for t in plant.equipment_trains)
    available_caps = plant_caps | train_caps

    matched = required_caps & available_caps
    missing = required_caps - available_caps

    infrastructure_score = 100.0 * (len(matched) / len(required_caps)) if required_caps else 50.0

    # Talent relevance.
    talent_keys: list[str] = []
    if modality in ("monoclonal_antibody", "recombinant_protein", "fusion_protein", "peptide"):
        talent_keys = ["bioprocess", "analytical", "regulatory_affairs", "quality", "sterile_manufacturing"]
    elif drug_form in ("injection", "vial"):
        talent_keys = ["sterile_manufacturing", "analytical", "regulatory_affairs", "quality"]
    else:
        talent_keys = ["formulation", "analytical", "regulatory_affairs", "quality"]
        if complexity.potency_classification in ("potent", "cytotoxic", "high_potency"):
            talent_keys.append("cytotoxic_handling")

    talent_values = [plant.talent_depth.get(k, 0.0) for k in talent_keys]
    talent_score = sum(talent_values) / len(talent_values) if talent_values else 0.0

    # Certification relevance — assume at least WHO-GMP for any program; add EU/USFDA for export.
    required_certs = {"who_gmp"}
    if complexity.modality != "small_molecule":
        required_certs.add("biologic_gmp")
    if complexity.potency_classification == "cytotoxic":
        required_certs.add("cytotoxic_licensing")

    active_certs = set((c or "").lower().replace("-", "_") for c in plant.certifications_active)
    cert_matched = required_certs & active_certs
    cert_missing = required_certs - active_certs
    certification_score = 100.0 * (len(cert_matched) / len(required_certs)) if required_certs else 100.0

    # Commercial fit tier.
    overall = (infrastructure_score * 0.45 + talent_score * 0.30 + certification_score * 0.25)

    if overall >= 80:
        tier = "strategic"
    elif overall >= 60:
        tier = "core"
    elif overall >= 40:
        tier = "adjacent"
    else:
        tier = "stretch"

    gaps: list[str] = []
    if missing:
        gaps.append(f"Missing capabilities: {', '.join(sorted(missing))}")
    if cert_missing:
        gaps.append(f"Missing certifications: {', '.join(sorted(cert_missing))}")
    if talent_score < 50:
        gaps.append("Talent depth below threshold for the modality/form")

    return round(infrastructure_score, 1), round(talent_score, 1), round(certification_score, 1), round(overall, 1), tier, gaps


def build_manufacturing_roadmap(
    molecule_key: str,
    plant_asset_id: str,
    complexity: "ManufacturingComplexity",
    plant: Optional[PlantAsset],
) -> "ManufacturingRoadmap":
    """Generate a modality-specific manufacturing readiness roadmap."""
    from intelligence_models import ManufacturingRoadmap, RoadmapPhase

    infra, talent, cert, overall, tier, gaps = score_customer_profile_fit(complexity, plant)

    phases: list[RoadmapPhase] = []
    if complexity.modality in ("monoclonal_antibody", "recombinant_protein", "fusion_protein", "peptide"):
        phases = [
            RoadmapPhase(
                phase_id="bio-1",
                title="Reference product characterization",
                modality="biosimilar",
                activities=[
                    "Develop analytical/functional similarity package vs RLD",
                    "Establish physicochemical, biological, and immunogenicity assays",
                    "Map originator quality target product profile (QTPP)",
                ],
                deliverables=["Comparability protocol", "Reference characterization report"],
                estimated_duration_months=6,
                readiness_gates=["Analytical methods qualified", "RLD sourcing confirmed"],
                required_capabilities=["analytical_development", "bioassay"],
            ),
            RoadmapPhase(
                phase_id="bio-2",
                title="Cell-line / process development (biologics) or synthesis development (peptide)",
                modality="biosimilar",
                activities=[
                    "Clone/strain selection and upstream optimization" if complexity.modality == "monoclonal_antibody" else "Solid-phase / solution-phase peptide synthesis route",
                    "Downstream purification train design",
                    "Viral clearance / impurity clearance strategy",
                ],
                deliverables=["Development cell bank / synthesis route", "Purification process description"],
                estimated_duration_months=12,
                readiness_gates=["Process development report", "Viral clearance data plan"],
                required_capabilities=["cell_culture" if complexity.modality == "monoclonal_antibody" else "solid_phase_synthesis", "chromatography"],
            ),
            RoadmapPhase(
                phase_id="bio-3",
                title="Protocol design & method qualification",
                modality="biosimilar",
                activities=[
                    "Design biosimilarity exercise per FDA/EMA/WHO guidance",
                    "Qualify potency, binding, ADCC/CDC, glycan, and charge-variant methods",
                    "Draft forced-degradation and stability protocols",
                ],
                deliverables=["Biosimilarity protocol", "Method qualification package"],
                estimated_duration_months=6,
                readiness_gates=["Bioassay qualified", "Stability protocol approved"],
                required_capabilities=["bioassay", "analytical_development"],
            ),
            RoadmapPhase(
                phase_id="bio-4",
                title="Development, testing & comparability",
                modality="biosimilar",
                activities=[
                    "Manufacture representative lots at pilot scale",
                    "Execute side-by-side comparability with RLD",
                    "Run forced degradation and real-time stability",
                ],
                deliverables=["Comparability report", "Stability data package"],
                estimated_duration_months=18,
                readiness_gates=["Lot release criteria met", "No clinically meaningful differences"],
                required_capabilities=["aseptic_fill", "sterility_testing", "analytical_development"],
            ),
            RoadmapPhase(
                phase_id="bio-5",
                title="Clinical / PK-PD / immunogenicity",
                modality="biosimilar",
                activities=[
                    "Design totality-of-evidence clinical package",
                    "Run PK similarity study and, if needed, efficacy study",
                    "Establish immunogenicity monitoring approach",
                ],
                deliverables=["Clinical study report", "Immunogenicity risk assessment"],
                estimated_duration_months=24,
                readiness_gates=["PK equivalence demonstrated", "No unexpected immunogenicity"],
                required_capabilities=["regulatory_affairs", "clinical_operations"],
            ),
            RoadmapPhase(
                phase_id="bio-6",
                title="Scale-up, fill-finish & launch",
                modality="biosimilar",
                activities=[
                    "Tech transfer to commercial bioreactor train",
                    "Validate aseptic fill-finish and lyophilization if required",
                    "Prepare BLA/MAA submission and PPQ batches",
                ],
                deliverables=["PPQ batches", "Regulatory submission dossier"],
                estimated_duration_months=18,
                readiness_gates=["Commercial process validated", "Regulatory filing accepted"],
                required_capabilities=["bioreactor", "aseptic_fill", "lyophilization"],
            ),
        ]
    else:
        # Off-patent small molecule path.
        phases = [
            RoadmapPhase(
                phase_id="sm-1",
                title="API sourcing strategy — buy or build",
                modality="small_molecule",
                activities=[
                    "Assess API DMF availability and supplier audit status",
                    "Evaluate backward-integration opportunity (own synthesis / fermentation)",
                    "Map PLI/DENA/state incentive eligibility for domestic API manufacturing",
                ],
                deliverables=["Approved API supplier list", "Make-vs-buy recommendation"],
                estimated_duration_months=3,
                readiness_gates=["API supplier qualified", "Incentive eligibility confirmed"],
                required_capabilities=["api_sourcing_experience"],
            ),
            RoadmapPhase(
                phase_id="sm-2",
                title="Formulation development & QbD",
                modality="small_molecule",
                activities=[
                    "Define design space around CQAs (dissolution, impurities, stability)",
                    "Select excipients and process parameters based on BCS and NSQ history",
                    "Run DOE and pilot batches",
                ],
                deliverables=["Formulation development report", "Design-space rationale"],
                estimated_duration_months=6,
                readiness_gates=["Pilot batch meets release specs", "Critical parameters identified"],
                required_capabilities=["wet_granulation", "dry_granulation", "compression", "film_coating"],
            ),
            RoadmapPhase(
                phase_id="sm-3",
                title="Analytical method transfer & validation",
                modality="small_molecule",
                activities=[
                    "Transfer IP/Ph.Eur./USP methods (assay, dissolution, impurities)",
                    "Validate discriminatory dissolution profile",
                    "Set up stability-indicating methods",
                ],
                deliverables=["Method transfer/validation package", "Stability protocol"],
                estimated_duration_months=4,
                readiness_gates=["Methods validated", "Reference standard qualified"],
                required_capabilities=["analytical_qc", "stability_testing"],
            ),
            RoadmapPhase(
                phase_id="sm-4",
                title="Scale-up & tech transfer",
                modality="small_molecule",
                activities=[
                    "Define equipment-train mapping from pilot to commercial scale",
                    "Execute engineering/validation batches",
                    "Demonstrate batch-to-batch consistency",
                ],
                deliverables=["Tech-transfer report", "Validation batches"],
                estimated_duration_months=6,
                readiness_gates=["PPQ protocol approved", "Scale-up success criteria met"],
                required_capabilities=["fluid_bed_drying", "compression", "film_coating", "blister_packing"],
            ),
            RoadmapPhase(
                phase_id="sm-5",
                title="Regulatory filing & bioequivalence support",
                modality="small_molecule",
                activities=[
                    "Prepare ANDA/dossier with QbD and sameness justification",
                    "Manage BE study vendor and clinical protocol",
                    "Address RLD/exclusivity timing and Paragraph IV risk",
                ],
                deliverables=["ANDA/dossier submitted", "BE study report"],
                estimated_duration_months=8,
                readiness_gates=["BE study passed", "Regulatory filing accepted"],
                required_capabilities=["regulatory_affairs", "clinical_operations"],
            ),
            RoadmapPhase(
                phase_id="sm-6",
                title="Shop-floor AI / NSQ prevention",
                modality="small_molecule",
                activities=[
                    "Deploy predictive failure diagnostics from existing NSQ engine",
                    "Map ideal process parameters and critical material attributes",
                    "Set up PAT and real-time release testing where appropriate",
                ],
                deliverables=["NSQ risk mitigation plan", "PAT implementation plan"],
                estimated_duration_months=4,
                readiness_gates=["NSQ risk model validated", "Process parameters within design space"],
                required_capabilities=["analytical_development", "process_validation"],
            ),
        ]

    government_notes = ""
    if complexity.modality == "small_molecule":
        government_notes = (
            "India PLI Scheme for Bulk Drugs ( notified fermentation/chemical synthesis APIs) and DENA "
            "can subsidize domestic API manufacturing. Evaluate KSM/API backward integration if the molecule is on the "
            "scheme list. State-level incentives (Himachal Pradesh, Gujarat, Telangana) may further reduce capex."
        )

    return ManufacturingRoadmap(
        molecule_key=molecule_key,
        plant_asset_id=plant_asset_id,
        modality=complexity.modality,
        commercial_fit_tier=tier,
        customer_profile_fit_score=overall,
        infrastructure_fit_score=infra,
        talent_fit_score=talent,
        certification_fit_score=cert,
        phases=phases,
        gaps=gaps,
        government_support_notes=government_notes,
        nsq_risk_notes="NSQ/QbD risk overlay requires a match in the simulator PRODUCT_CATALOG for detailed diagnostics.",
    )


def score_plant_fit(
    molecule_class: str,
    patent: Optional[PatentIntelligence],
    plant: Optional[PlantAsset],
) -> tuple[float, dict[str, Any]]:
    """Return a 0–100 plant-fit score and explanation.

    Scoring:
    - Form/capability match: up to 50 points.
    - Containment/safety match: up to 20 points.
    - Experience match: up to 20 points.
    - Capacity bonus: up to 10 points.
    """
    if plant is None:
        return 0.0, {
            "summary": "No plant asset selected.",
            "capability_match": "none",
        }

    required_caps = set(MOLECULE_CAPABILITY_HINTS.get(molecule_class, MOLECULE_CAPABILITY_HINTS["small_molecule_oral"]))
    plant_caps = set((c or "").lower() for c in plant.capabilities)

    matched = required_caps & plant_caps
    missing = required_caps - plant_caps

    capability_score = 50.0 * (len(matched) / len(required_caps)) if required_caps else 50.0

    # Biologics require biologics_experience; cytotoxic/oncology may need potent/cytotoxic suite.
    containment_score = 20.0
    if molecule_class == "mab":
        containment_score = 20.0 if plant.biologics_experience else 0.0
    elif molecule_class in ("small_molecule_oral", "small_molecule_injectable"):
        # Standard or potent is fine for most small molecules; cytotoxic bonus only for oncology injectables
        if "oncology" in (patent.therapeutic_area or "").lower() and plant.containment_class in ("potent", "cytotoxic"):
            containment_score = 20.0
        elif plant.containment_class in ("standard", "potent"):
            containment_score = 18.0
        else:
            containment_score = 10.0

    experience_score = 20.0 if plant.small_molecule_experience else 0.0
    if molecule_class == "mab":
        experience_score = 20.0 if plant.biologics_experience else 0.0

    capacity_bonus = min(10.0, (plant.batch_capacity_kg or 0.0) / 100.0)

    score = capability_score + containment_score + experience_score + capacity_bonus
    score = max(0.0, min(100.0, score))

    explanation = {
        "summary": f"Plant fit {score:.0f}/100 for {molecule_class} on {plant.site_name}.",
        "capability_match": f"{len(matched)}/{len(required_caps)} required capabilities matched",
        "matched_capabilities": sorted(matched),
        "missing_capabilities": sorted(missing),
        "containment_class": plant.containment_class,
        "experience": "biologics" if molecule_class == "mab" else "small molecule",
        "capacity_bonus": f"{capacity_bonus:.1f} points",
    }
    return score, explanation


def score_candidate(
    molecule_key: str,
    patent: Optional[PatentIntelligence],
    plant: Optional[PlantAsset],
    weights: Optional[dict[str, float]] = None,
    regulatory: Optional[RegulatoryPassport] = None,
    demand: Optional[DemandProfile] = None,
) -> CandidateScore:
    """Compute the full four-pillar score for a molecule × plant line.

    If `regulatory` or `demand` are not provided they are loaded from Redis once;
    pass them in bulk-scoring loops to avoid repeated round-trips.
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        # Normalize provided weights to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            for k in w:
                if k in weights:
                    w[k] = weights[k] / total

    if regulatory is None:
        try:
            regulatory = load_regulatory(molecule_key)
        except Exception:
            regulatory = None

    if demand is None:
        try:
            demand = load_demand(molecule_key)
        except Exception:
            demand = None

    patent_score, patent_exp = score_patent(patent)
    regulatory_score, regulatory_exp = score_regulatory(regulatory, patent)
    demand_score, demand_exp = score_demand(demand, molecule_key)

    molecule_class = _molecule_class(patent)
    plant_score, plant_exp = score_plant_fit(molecule_class, patent, plant)

    total = (
        w["patent"] * patent_score
        + w["regulatory"] * regulatory_score
        + w["demand"] * demand_score
        + w["plant"] * plant_score
    )

    warnings: list[str] = []
    if plant is None:
        warnings.append("No plant asset selected; plant-fit score is zero.")
    if patent and patent.fto_risk == "high":
        warnings.append("High FTO risk — defensive patent thicket may delay launch.")
    if patent and patent.earliest_loe() and _days_until(patent.earliest_loe()) < 365:
        warnings.append("LOE window is less than 1 year; launch preparation is urgent.")
    if regulatory and _exclusivity_active(regulatory.exclusivity):
        warnings.append("Active regulatory exclusivity blocks immediate generic launch.")

    return CandidateScore(
        molecule_key=molecule_key,
        plant_asset_id=plant.asset_id if plant else None,
        patent_readiness_score=round(patent_score, 1),
        regulatory_clarity_score=round(regulatory_score, 1),
        demand_attractiveness_score=round(demand_score, 1),
        plant_fit_score=round(plant_score, 1),
        total_score=round(total, 1),
        weights={k: round(v, 3) for k, v in w.items()},
        explanation={
            "patent": patent_exp.get("summary", ""),
            "regulatory": regulatory_exp.get("summary", ""),
            "demand": demand_exp.get("summary", ""),
            "plant": plant_exp.get("summary", ""),
        },
        fto_risk=patent.fto_risk if patent else "unknown",
        earliest_loe=patent.earliest_loe() if patent else None,
        warnings=warnings,
    )


def evaluate_manufacturing_readiness(
    molecule_key: str,
    plant_asset_id: str,
    patent: Optional[PatentIntelligence] = None,
    regulatory: Optional[RegulatoryPassport] = None,
    plant: Optional[PlantAsset] = None,
) -> dict[str, Any]:
    """Full Phase 4 evaluation: complexity, customer profile fit, and roadmap.

    Pass `plant` in bulk loops to avoid a Redis round-trip per candidate.
    """
    if patent is None:
        patent = load_patent(molecule_key)
    if regulatory is None:
        regulatory = load_regulatory(molecule_key)
    if plant is None:
        plant = load_plant_asset(plant_asset_id)

    complexity = derive_manufacturing_complexity(molecule_key, patent, regulatory)
    roadmap = build_manufacturing_roadmap(molecule_key, plant_asset_id, complexity, plant)

    return {
        "molecule_key": molecule_key,
        "plant_asset_id": plant_asset_id,
        "manufacturing_complexity": complexity.model_dump(mode="json"),
        "customer_profile_fit": {
            "commercial_fit_tier": roadmap.commercial_fit_tier,
            "infrastructure_fit_score": roadmap.infrastructure_fit_score,
            "talent_fit_score": roadmap.talent_fit_score,
            "certification_fit_score": roadmap.certification_fit_score,
            "customer_profile_fit_score": roadmap.customer_profile_fit_score,
            "gaps": roadmap.gaps,
        },
        "roadmap": [p.model_dump() for p in roadmap.phases],
        "government_support_notes": roadmap.government_support_notes,
        "nsq_risk_notes": roadmap.nsq_risk_notes,
    }


def build_portfolio(
    scenario: "PortfolioScenario",
    patents: dict[str, PatentIntelligence],
    plants: dict[str, PlantAsset],
    regulatory_map: dict[str, RegulatoryPassport],
    demand_map: dict[str, DemandProfile],
) -> "PortfolioSnapshot":
    """Rank every molecule × plant combination under a configurable scenario.

    Returns a PortfolioSnapshot with entries sorted by total score descending.
    Applies scenario filters (cluster, LOE horizon, FTO risk, commercial tier,
    minimum score) before ranking.
    """
    from intelligence_models import PortfolioEntry, PortfolioSnapshot

    today = date.today()
    allowed_fto = set((r or "").lower() for r in scenario.fto_risks_allowed)
    target_plant_ids = set(scenario.plant_asset_ids) if scenario.plant_asset_ids else set(plants.keys())
    target_clusters = set((c or "").lower() for c in scenario.clusters) if scenario.clusters else set()

    entries: list[PortfolioEntry] = []
    for mol_key, patent in patents.items():
        regulatory = regulatory_map.get(mol_key)
        demand = demand_map.get(mol_key)
        cluster = (demand.cluster if demand else "").lower()

        if target_clusters and cluster not in target_clusters:
            continue
        if allowed_fto and patent.fto_risk.lower() not in allowed_fto:
            continue

        earliest = patent.earliest_loe()
        loe_years = None
        if earliest:
            loe_years = (earliest - today).days / 365.25
            if scenario.max_loe_years is not None and loe_years > scenario.max_loe_years:
                continue

        for plant_id in target_plant_ids:
            plant = plants.get(plant_id)
            if plant is None:
                continue

            candidate = score_candidate(
                mol_key, patent, plant, weights=scenario.weights, regulatory=regulatory, demand=demand
            )

            if scenario.min_total_score is not None and candidate.total_score < scenario.min_total_score:
                continue

            readiness = evaluate_manufacturing_readiness(
                mol_key, plant_id, patent=patent, regulatory=regulatory, plant=plant
            )
            customer_fit = readiness.get("customer_profile_fit", {})
            tier = customer_fit.get("commercial_fit_tier", "stretch")
            if tier == "stretch" and not scenario.include_stretch:
                continue

            complexity_data = readiness.get("manufacturing_complexity", {})
            roadmap = readiness.get("roadmap", [])

            entries.append(
                PortfolioEntry(
                    molecule_key=mol_key,
                    brand_name=patent.brand_name,
                    api_name=patent.api_name,
                    therapeutic_area=patent.therapeutic_area,
                    plant_asset_id=plant_id,
                    plant_site_name=plant.site_name,
                    cluster=demand.cluster if demand else "",
                    patent_readiness_score=candidate.patent_readiness_score,
                    regulatory_clarity_score=candidate.regulatory_clarity_score,
                    demand_attractiveness_score=candidate.demand_attractiveness_score,
                    plant_fit_score=candidate.plant_fit_score,
                    total_score=candidate.total_score,
                    commercial_fit_tier=tier,
                    infrastructure_fit_score=customer_fit.get("infrastructure_fit_score", 0.0),
                    talent_fit_score=customer_fit.get("talent_fit_score", 0.0),
                    certification_fit_score=customer_fit.get("certification_fit_score", 0.0),
                    fto_risk=candidate.fto_risk,
                    earliest_loe=candidate.earliest_loe,
                    loe_years=round(loe_years, 2) if loe_years is not None else None,
                    estimated_roadmap_months=sum(p.get("estimated_duration_months", 0) for p in roadmap),
                    modality=complexity_data.get("modality", ""),
                    drug_form=complexity_data.get("drug_form", ""),
                    sterility_required=complexity_data.get("sterility_required", False),
                    warnings=candidate.warnings,
                    gaps=customer_fit.get("gaps", []),
                )
            )

    entries.sort(key=lambda e: e.total_score, reverse=True)

    summary = {
        "total_candidates_evaluated": len(patents) * len(plants),
        "included_count": len(entries),
        "mean_total_score": round(sum(e.total_score for e in entries) / len(entries), 2) if entries else 0.0,
        "strategic_count": sum(1 for e in entries if e.commercial_fit_tier == "strategic"),
        "core_count": sum(1 for e in entries if e.commercial_fit_tier == "core"),
        "adjacent_count": sum(1 for e in entries if e.commercial_fit_tier == "adjacent"),
        "stretch_count": sum(1 for e in entries if e.commercial_fit_tier == "stretch"),
        "small_molecule_count": sum(1 for e in entries if e.modality == "small_molecule"),
        "biologics_count": sum(
            1 for e in entries if e.modality in ("monoclonal_antibody", "peptide", "recombinant_protein", "fusion_protein")
        ),
        "data_source": "representative_seed" if scenario.use_mock_data else "live_api",
        "weights_applied": {k: round(v, 3) for k, v in scenario.weights.items()},
    }

    return PortfolioSnapshot(
        scenario_id=scenario.scenario_id,
        scenario_name=scenario.name,
        entries=entries,
        count=len(entries),
        summary=summary,
    )
