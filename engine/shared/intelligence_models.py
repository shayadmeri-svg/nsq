"""Shared data models for the off-patent drug intelligence engine.

These models are used by both the FastAPI scoring engine and the
Streamlit simulator UI. They are deliberately plain Pydantic models so
they serialize cleanly to/from Redis hashes and JSON.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PatentEntry(BaseModel):
    """A single patent: description, expiry, jurisdiction, risk level."""

    description: str
    expiry_date: Optional[date] = None
    jurisdiction: str = "global"  # e.g. US, EU, IN, global
    risk_level: str = "medium"  # low | medium | high


class GeoCoverage(BaseModel):
    """Per-country patent coverage, LOE date, and export eligibility."""

    country_code: str  # ISO 3166-1 alpha-2, e.g. "US"
    country_name: str
    market_status: str = "patented"  # patented | loe_pending | off_patent | export_eligible
    loe_date: Optional[date] = None
    export_eligible: bool = False
    patent_barrier: str = "none"  # none | composition | formulation | process | device | secondary
    notes: str = ""


class PatentIntelligence(BaseModel):
    """Patent Intelligence pillar for one molecule."""

    molecule_key: str
    brand_name: str
    api_name: str
    therapeutic_area: str
    originator: str
    estimated_loe_us: Optional[date] = None
    estimated_loe_eu: Optional[date] = None
    estimated_loe_in: Optional[date] = None
    market_size_usd_bn: Optional[float] = None
    formulation_patents: list[PatentEntry] = Field(default_factory=list)
    process_patents: list[PatentEntry] = Field(default_factory=list)
    secondary_patents: list[PatentEntry] = Field(default_factory=list)
    geo_coverage: list[GeoCoverage] = Field(default_factory=list)
    fto_risk: str = "medium"  # low | medium | high
    notes: str = ""
    source_url: str = ""
    updated_at: str = Field(default_factory=_utc_now)

    def export_eligible_count(self) -> int:
        return sum(1 for g in self.geo_coverage if g.export_eligible)

    def earliest_loe(self) -> Optional[date]:
        dates = [d for d in (self.estimated_loe_us, self.estimated_loe_eu, self.estimated_loe_in) if d]
        return min(dates) if dates else None

    def patent_count(self) -> int:
        return len(self.formulation_patents) + len(self.process_patents) + len(self.secondary_patents)

    def to_redis(self) -> dict[str, str]:
        """Flatten to strings for a Redis HASH."""
        return {
            "molecule_key": self.molecule_key,
            "brand_name": self.brand_name,
            "api_name": self.api_name,
            "therapeutic_area": self.therapeutic_area,
            "originator": self.originator,
            "estimated_loe_us": self.estimated_loe_us.isoformat() if self.estimated_loe_us else "",
            "estimated_loe_eu": self.estimated_loe_eu.isoformat() if self.estimated_loe_eu else "",
            "estimated_loe_in": self.estimated_loe_in.isoformat() if self.estimated_loe_in else "",
            "market_size_usd_bn": str(self.market_size_usd_bn) if self.market_size_usd_bn is not None else "",
            "formulation_patents": _json_encode(self.formulation_patents),
            "process_patents": _json_encode(self.process_patents),
            "secondary_patents": _json_encode(self.secondary_patents),
            "geo_coverage": _json_encode(self.geo_coverage),
            "fto_risk": self.fto_risk,
            "notes": self.notes,
            "source_url": self.source_url,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_redis(cls, data: dict[str, str]) -> "PatentIntelligence":
        def _date_or_none(v: str) -> date | None:
            return date.fromisoformat(v) if v else None

        return cls(
            molecule_key=data.get("molecule_key", ""),
            brand_name=data.get("brand_name", ""),
            api_name=data.get("api_name", ""),
            therapeutic_area=data.get("therapeutic_area", ""),
            originator=data.get("originator", ""),
            estimated_loe_us=_date_or_none(data.get("estimated_loe_us", "")),
            estimated_loe_eu=_date_or_none(data.get("estimated_loe_eu", "")),
            estimated_loe_in=_date_or_none(data.get("estimated_loe_in", "")),
            market_size_usd_bn=float(data["market_size_usd_bn"]) if data.get("market_size_usd_bn") else None,
            formulation_patents=_parse_entries(data.get("formulation_patents", "")),
            process_patents=_parse_entries(data.get("process_patents", "")),
            secondary_patents=_parse_entries(data.get("secondary_patents", "")),
            geo_coverage=_parse_geo_coverage(data.get("geo_coverage", "")),
            fto_risk=data.get("fto_risk", "medium"),
            notes=data.get("notes", ""),
            source_url=data.get("source_url", ""),
            updated_at=data.get("updated_at", _utc_now()),
        )


class PlantAsset(BaseModel):
    """A manufacturing line / site / asset in the CDMO network."""

    asset_id: str
    site_name: str
    city: str = ""
    state: str = ""
    country: str = "India"
    capabilities: list[str] = Field(default_factory=list)
    approved_forms: list[str] = Field(default_factory=list)
    containment_class: str = "standard"  # standard | potent | cytotoxic | biologic_GMP
    batch_capacity_kg: Optional[float] = None
    certifications: list[str] = Field(default_factory=list)
    certifications_active: list[str] = Field(default_factory=list)
    small_molecule_experience: bool = True
    biologics_experience: bool = False
    small_molecule_experience_years: int = 0
    biologics_experience_years: int = 0
    api_sourcing_experience: bool = False
    talent_profile: list[str] = Field(default_factory=list)
    talent_depth: dict[str, float] = Field(default_factory=dict)
    equipment_highlights: list[str] = Field(default_factory=list)
    equipment_trains: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""

    def to_redis(self) -> dict[str, str]:
        return {
            "asset_id": self.asset_id,
            "site_name": self.site_name,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "capabilities": _json_encode(self.capabilities),
            "approved_forms": _json_encode(self.approved_forms),
            "containment_class": self.containment_class,
            "batch_capacity_kg": str(self.batch_capacity_kg) if self.batch_capacity_kg is not None else "",
            "certifications": _json_encode(self.certifications),
            "certifications_active": _json_encode(self.certifications_active),
            "small_molecule_experience": "1" if self.small_molecule_experience else "0",
            "biologics_experience": "1" if self.biologics_experience else "0",
            "small_molecule_experience_years": str(self.small_molecule_experience_years),
            "biologics_experience_years": str(self.biologics_experience_years),
            "api_sourcing_experience": "1" if self.api_sourcing_experience else "0",
            "talent_profile": _json_encode(self.talent_profile),
            "talent_depth": _json_encode(self.talent_depth),
            "equipment_highlights": _json_encode(self.equipment_highlights),
            "equipment_trains": _json_encode(self.equipment_trains),
            "notes": self.notes,
        }

    @classmethod
    def from_redis(cls, data: dict[str, str]) -> "PlantAsset":
        return cls(
            asset_id=data.get("asset_id", ""),
            site_name=data.get("site_name", ""),
            city=data.get("city", ""),
            state=data.get("state", ""),
            country=data.get("country", "India"),
            capabilities=_parse_list(data.get("capabilities", "")),
            approved_forms=_parse_list(data.get("approved_forms", "")),
            containment_class=data.get("containment_class", "standard"),
            batch_capacity_kg=float(data["batch_capacity_kg"]) if data.get("batch_capacity_kg") else None,
            certifications=_parse_list(data.get("certifications", "")),
            certifications_active=_parse_list(data.get("certifications_active", "")),
            small_molecule_experience=data.get("small_molecule_experience", "1") == "1",
            biologics_experience=data.get("biologics_experience", "0") == "1",
            small_molecule_experience_years=int(data.get("small_molecule_experience_years", "0") or "0"),
            biologics_experience_years=int(data.get("biologics_experience_years", "0") or "0"),
            api_sourcing_experience=data.get("api_sourcing_experience", "0") == "1",
            talent_profile=_parse_list(data.get("talent_profile", "")),
            talent_depth=_parse_dict_float(data.get("talent_depth", "")),
            equipment_highlights=_parse_list(data.get("equipment_highlights", "")),
            equipment_trains=_parse_equipment_trains(data.get("equipment_trains", "")),
            notes=data.get("notes", ""),
        )


class RegulatoryPassport(BaseModel):
    """Regulatory Rules pillar for one molecule.

    Captures pharmacopeia monographs, Orange Book reference information
    (RLD, TE code), FDA/regulatory exclusivity, and development context.
    """

    molecule_key: str
    ip_2026_monograph: str = ""
    ph_eur_monograph: str = ""
    usp_monograph: str = ""
    analytical_specs: list[str] = Field(default_factory=list)
    stability_conditions: str = ""
    bcs_class: str = ""  # BCS I / II / III / IV
    rld: str = ""  # Reference Listed Drug brand name
    rld_applicant: str = ""
    te_code: str = ""  # e.g. AB1, AB2, BX
    te_rating: str = ""  # A | B | ""
    dosage_form: str = ""
    strength: str = ""
    exclusivity: list[dict[str, Any]] = Field(default_factory=list)
    bioequivalence_notes: str = ""
    readiness: str = "placeholder"  # placeholder | partial | ready
    source_url: str = ""
    notes: str = ""

    def to_redis(self) -> dict[str, str]:
        return {
            "molecule_key": self.molecule_key,
            "ip_2026_monograph": self.ip_2026_monograph,
            "ph_eur_monograph": self.ph_eur_monograph,
            "usp_monograph": self.usp_monograph,
            "analytical_specs": _json_encode(self.analytical_specs),
            "stability_conditions": self.stability_conditions,
            "bcs_class": self.bcs_class,
            "rld": self.rld,
            "rld_applicant": self.rld_applicant,
            "te_code": self.te_code,
            "te_rating": self.te_rating,
            "dosage_form": self.dosage_form,
            "strength": self.strength,
            "exclusivity": _json_encode(self.exclusivity),
            "bioequivalence_notes": self.bioequivalence_notes,
            "readiness": self.readiness,
            "source_url": self.source_url,
            "notes": self.notes,
        }

    @classmethod
    def from_redis(cls, data: dict[str, str]) -> "RegulatoryPassport":
        return cls(
            molecule_key=data.get("molecule_key", ""),
            ip_2026_monograph=data.get("ip_2026_monograph", ""),
            ph_eur_monograph=data.get("ph_eur_monograph", ""),
            usp_monograph=data.get("usp_monograph", ""),
            analytical_specs=_parse_list(data.get("analytical_specs", "")),
            stability_conditions=data.get("stability_conditions", ""),
            bcs_class=data.get("bcs_class", ""),
            rld=data.get("rld", ""),
            rld_applicant=data.get("rld_applicant", ""),
            te_code=data.get("te_code", ""),
            te_rating=data.get("te_rating", ""),
            dosage_form=data.get("dosage_form", ""),
            strength=data.get("strength", ""),
            exclusivity=_parse_exclusivity(data.get("exclusivity", "")),
            bioequivalence_notes=data.get("bioequivalence_notes", ""),
            readiness=data.get("readiness", "placeholder"),
            source_url=data.get("source_url", ""),
            notes=data.get("notes", ""),
        )


class ManufacturingComplexity(BaseModel):
    """Biochemistry-derived manufacturing complexity profile for a molecule.

    Inferred from patent, regulatory, and demand signals. Used to match
    molecule requirements against plant capability and to generate roadmaps.
    """

    molecule_key: str
    modality: str = "small_molecule"  # small_molecule | monoclonal_antibody | peptide | recombinant_protein | fusion_protein
    drug_form: str = "tablet"  # tablet | capsule | enteric_tablet | injection | vial | prefilled_pen | prefilled_syringe | lyophilized_vial
    route_of_administration: str = "oral"  # oral | subcutaneous | iv | intramuscular | ophthalmic
    sterility_required: bool = False
    potency_classification: str = "standard"  # standard | potent | cytotoxic | high_potency | biologic
    critical_quality_attributes: list[str] = Field(default_factory=list)
    process_complexity_score: float = 0.0  # 1–10
    analytical_complexity_score: float = 0.0  # 1–10
    biologic_complexity_score: float = 0.0  # 1–10
    notes: str = ""

    def to_redis(self) -> dict[str, str]:
        return {
            "molecule_key": self.molecule_key,
            "modality": self.modality,
            "drug_form": self.drug_form,
            "route_of_administration": self.route_of_administration,
            "sterility_required": "1" if self.sterility_required else "0",
            "potency_classification": self.potency_classification,
            "critical_quality_attributes": _json_encode(self.critical_quality_attributes),
            "process_complexity_score": str(self.process_complexity_score),
            "analytical_complexity_score": str(self.analytical_complexity_score),
            "biologic_complexity_score": str(self.biologic_complexity_score),
            "notes": self.notes,
        }

    @classmethod
    def from_redis(cls, data: dict[str, str]) -> "ManufacturingComplexity":
        return cls(
            molecule_key=data.get("molecule_key", ""),
            modality=data.get("modality", "small_molecule"),
            drug_form=data.get("drug_form", "tablet"),
            route_of_administration=data.get("route_of_administration", "oral"),
            sterility_required=data.get("sterility_required", "0") == "1",
            potency_classification=data.get("potency_classification", "standard"),
            critical_quality_attributes=_parse_list(data.get("critical_quality_attributes", "")),
            process_complexity_score=float(data.get("process_complexity_score", "0") or "0"),
            analytical_complexity_score=float(data.get("analytical_complexity_score", "0") or "0"),
            biologic_complexity_score=float(data.get("biologic_complexity_score", "0") or "0"),
            notes=data.get("notes", ""),
        )


class RoadmapPhase(BaseModel):
    """A single phase inside a manufacturing readiness roadmap."""

    phase_id: str
    title: str
    modality: str  # small_molecule | biosimilar
    activities: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    estimated_duration_months: int = 0
    readiness_gates: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


class ManufacturingRoadmap(BaseModel):
    """Generated manufacturing readiness roadmap for a molecule × plant line."""

    molecule_key: str
    plant_asset_id: str
    modality: str
    commercial_fit_tier: str = "stretch"  # strategic | core | adjacent | stretch
    customer_profile_fit_score: float = 0.0
    infrastructure_fit_score: float = 0.0
    talent_fit_score: float = 0.0
    certification_fit_score: float = 0.0
    phases: list[RoadmapPhase] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    government_support_notes: str = ""
    nsq_risk_notes: str = ""

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["phases"] = [p.model_dump(**kwargs) for p in self.phases]
        return data


class DemandProfile(BaseModel):
    """Demand Trends pillar for one molecule.

    Combines disease burden, clinical trial pipeline, therapeutic cluster,
    buyer/institution activity proxies, and market momentum into a single
    demand attractiveness signal for CDMO portfolio decisions.
    """

    molecule_key: str
    disease_area: str = ""
    disease_prevalence_global_millions: float = 0.0
    disease_prevalence_india_millions: float = 0.0
    growth_trend: str = "stable"  # growing | stable | declining
    trial_count_total: int = 0
    trial_count_phase_3_plus: int = 0
    cluster: str = ""  # oncology | specialty injectable | immunology | lifestyle / chronic | commodity
    buyer_activity_score: float = 0.0  # 0–100 proxy
    competitor_anda_count: int = 0
    market_momentum_score: float = 0.0  # 0–100
    notes: str = ""
    source_url: str = ""

    def to_redis(self) -> dict[str, str]:
        return {
            "molecule_key": self.molecule_key,
            "disease_area": self.disease_area,
            "disease_prevalence_global_millions": str(self.disease_prevalence_global_millions),
            "disease_prevalence_india_millions": str(self.disease_prevalence_india_millions),
            "growth_trend": self.growth_trend,
            "trial_count_total": str(self.trial_count_total),
            "trial_count_phase_3_plus": str(self.trial_count_phase_3_plus),
            "cluster": self.cluster,
            "buyer_activity_score": str(self.buyer_activity_score),
            "competitor_anda_count": str(self.competitor_anda_count),
            "market_momentum_score": str(self.market_momentum_score),
            "notes": self.notes,
            "source_url": self.source_url,
        }

    @classmethod
    def from_redis(cls, data: dict[str, str]) -> "DemandProfile":
        def _float(key: str) -> float:
            try:
                return float(data.get(key, "0") or "0")
            except ValueError:
                return 0.0

        def _int(key: str) -> int:
            try:
                return int(data.get(key, "0") or "0")
            except ValueError:
                return 0

        return cls(
            molecule_key=data.get("molecule_key", ""),
            disease_area=data.get("disease_area", ""),
            disease_prevalence_global_millions=_float("disease_prevalence_global_millions"),
            disease_prevalence_india_millions=_float("disease_prevalence_india_millions"),
            growth_trend=data.get("growth_trend", "stable"),
            trial_count_total=_int("trial_count_total"),
            trial_count_phase_3_plus=_int("trial_count_phase_3_plus"),
            cluster=data.get("cluster", ""),
            buyer_activity_score=_float("buyer_activity_score"),
            competitor_anda_count=_int("competitor_anda_count"),
            market_momentum_score=_float("market_momentum_score"),
            notes=data.get("notes", ""),
            source_url=data.get("source_url", ""),
        )


class CandidateScore(BaseModel):
    """Final four-pillar decision score for one molecule × plant line."""

    molecule_key: str
    plant_asset_id: Optional[str] = None
    patent_readiness_score: float = 0.0  # 0–100
    regulatory_clarity_score: float = 0.0  # 0–100
    demand_attractiveness_score: float = 0.0  # 0–100
    plant_fit_score: float = 0.0  # 0–100
    total_score: float = 0.0
    weights: dict[str, float] = Field(default_factory=dict)
    explanation: dict[str, str] = Field(default_factory=dict)
    fto_risk: str = ""
    earliest_loe: Optional[date] = None
    warnings: list[str] = Field(default_factory=list)


class PortfolioScenario(BaseModel):
    """User-configurable scenario for ranking a portfolio of candidates."""

    scenario_id: str = "default"
    name: str = "Default scenario"
    description: str = ""
    weights: dict[str, float] = Field(default_factory=lambda: {
        "patent": 0.25,
        "regulatory": 0.20,
        "demand": 0.25,
        "plant": 0.30,
    })
    # Optional filters
    plant_asset_ids: list[str] = Field(default_factory=list)
    clusters: list[str] = Field(default_factory=list)
    min_total_score: Optional[float] = None
    max_loe_years: Optional[float] = None  # only include molecules with LOE within N years
    fto_risks_allowed: list[str] = Field(default_factory=list)  # low, medium, high
    include_stretch: bool = False  # whether to include "stretch" commercial-fit tier
    use_mock_data: bool = True  # flag surfaced in UI as data-source indicator

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["weights"] = {k: round(v, 4) for k, v in data.get("weights", {}).items()}
        return data


class PortfolioEntry(BaseModel):
    """One molecule × plant candidate inside a portfolio snapshot."""

    molecule_key: str
    brand_name: str = ""
    api_name: str = ""
    therapeutic_area: str = ""
    plant_asset_id: Optional[str] = None
    plant_site_name: str = ""
    cluster: str = ""
    patent_readiness_score: float = 0.0
    regulatory_clarity_score: float = 0.0
    demand_attractiveness_score: float = 0.0
    plant_fit_score: float = 0.0
    total_score: float = 0.0
    commercial_fit_tier: str = "stretch"  # strategic | core | adjacent | stretch
    infrastructure_fit_score: float = 0.0
    talent_fit_score: float = 0.0
    certification_fit_score: float = 0.0
    fto_risk: str = ""
    earliest_loe: Optional[date] = None
    loe_years: Optional[float] = None
    estimated_roadmap_months: int = 0
    modality: str = ""
    drug_form: str = ""
    sterility_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class PortfolioSnapshot(BaseModel):
    """Full ranked portfolio result for a scenario."""

    scenario_id: str
    scenario_name: str = ""
    generated_at: str = Field(default_factory=_utc_now)
    count: int = 0
    entries: list[PortfolioEntry] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["entries"] = [e.model_dump(**kwargs) for e in self.entries]
        return data


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def _json_encode(value: Any) -> str:
    import json
    from pydantic import BaseModel

    def _default(obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    return json.dumps(value, default=_default, ensure_ascii=False)


def _parse_list(raw: str) -> list[str]:
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _parse_entries(raw: str) -> list[PatentEntry]:
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [PatentEntry(**item) for item in parsed if isinstance(item, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_geo_coverage(raw: str) -> list[GeoCoverage]:
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [GeoCoverage(**item) for item in parsed if isinstance(item, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_exclusivity(raw: str) -> list[dict[str, Any]]:
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [item for item in parsed if isinstance(item, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_dict_float(raw: str) -> dict[str, float]:
    import json

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return {str(k): float(v) for k, v in parsed.items() if isinstance(v, (int, float, str))}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _parse_equipment_trains(raw: str) -> list[dict[str, Any]]:
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [item for item in parsed if isinstance(item, dict)]
    except (json.JSONDecodeError, TypeError):
        return []
