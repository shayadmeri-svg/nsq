"""FastAPI entry point for the CDMO off-patent intelligence engine.

Runs independently of the Streamlit apps. Reads patent and plant data from
Redis (cdmo:* keyspace) and exposes scoring endpoints.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))

from intelligence_models import CandidateScore, PortfolioScenario, PortfolioSnapshot
from intelligence_scorer import DEFAULT_WEIGHTS, build_portfolio, evaluate_manufacturing_readiness, score_candidate
from intelligence_store import (
    get_redis_client,
    load_all_demand,
    load_all_patents,
    load_all_plant_assets,
    load_all_regulatory,
    load_complexity,
    load_demand,
    load_patent,
    load_plant_asset,
    load_portfolio,
    load_regulatory,
    save_complexity,
    save_portfolio,
)


class ScoreRequest(BaseModel):
    molecule_key: str
    plant_asset_id: Optional[str] = None
    weights: Optional[dict[str, float]] = None


class PortfolioScoreRequest(BaseModel):
    scenario_id: str = "default"
    name: str = "Portfolio scenario"
    description: str = ""
    weights: Optional[dict[str, float]] = None
    plant_asset_ids: list[str] = []
    clusters: list[str] = []
    min_total_score: Optional[float] = None
    max_loe_years: Optional[float] = None
    fto_risks_allowed: list[str] = []
    include_stretch: bool = False
    use_mock_data: bool = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate Redis connectivity on startup.
    try:
        r = get_redis_client()
        r.ping()
        app.state.redis_ready = True
    except Exception:
        app.state.redis_ready = False
    yield


app = FastAPI(
    title="CDMO Off-Patent Drug Intelligence Engine",
    description="Four-pillar decision scoring for off-patent / LOE molecules.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "status": "ok" if app.state.redis_ready else "degraded",
        "redis_ready": app.state.redis_ready,
    }


@app.get("/molecules")
def list_molecules():
    try:
        patents = load_all_patents()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}")
    return {
        "count": len(patents),
        "molecules": [
            {
                "molecule_key": p.molecule_key,
                "brand_name": p.brand_name,
                "api_name": p.api_name,
                "therapeutic_area": p.therapeutic_area,
                "fto_risk": p.fto_risk,
                "earliest_loe": p.earliest_loe().isoformat() if p.earliest_loe() else None,
                "export_eligible_count": p.export_eligible_count(),
                "total_geo_count": len(p.geo_coverage),
            }
            for p in patents.values()
        ],
    }


@app.get("/molecules/{molecule_key}")
def get_molecule(molecule_key: str):
    patent = load_patent(molecule_key)
    if patent is None:
        raise HTTPException(status_code=404, detail=f"Molecule {molecule_key!r} not found")
    return patent.model_dump(mode="json")


@app.get("/plants")
def list_plants():
    try:
        plants = load_all_plant_assets()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}")
    return {
        "count": len(plants),
        "plants": [
            {
                "asset_id": a.asset_id,
                "site_name": a.site_name,
                "city": a.city,
                "state": a.state,
                "containment_class": a.containment_class,
                "small_molecule_experience": a.small_molecule_experience,
                "biologics_experience": a.biologics_experience,
            }
            for a in plants.values()
        ],
    }


@app.get("/plants/{asset_id}")
def get_plant(asset_id: str):
    plant = load_plant_asset(asset_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"Plant asset {asset_id!r} not found")
    return plant.model_dump(mode="json")


@app.get("/regulatory")
def list_regulatory():
    try:
        passports = load_all_regulatory()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}")
    return {
        "count": len(passports),
        "passports": [
            {
                "molecule_key": p.molecule_key,
                "rld": p.rld,
                "rld_applicant": p.rld_applicant,
                "te_code": p.te_code,
                "te_rating": p.te_rating,
                "bcs_class": p.bcs_class,
                "readiness": p.readiness,
            }
            for p in passports.values()
        ],
    }


@app.get("/demand")
def list_demand():
    try:
        profiles = load_all_demand()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}")
    return {
        "count": len(profiles),
        "profiles": [
            {
                "molecule_key": p.molecule_key,
                "disease_area": p.disease_area,
                "cluster": p.cluster,
                "growth_trend": p.growth_trend,
                "trial_count_phase_3_plus": p.trial_count_phase_3_plus,
                "buyer_activity_score": p.buyer_activity_score,
                "market_momentum_score": p.market_momentum_score,
            }
            for p in profiles.values()
        ],
    }


@app.get("/molecules/{molecule_key}/demand")
def get_molecule_demand(molecule_key: str):
    profile = load_demand(molecule_key)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Demand profile for {molecule_key!r} not found")
    return profile.model_dump(mode="json")


@app.get("/molecules/{molecule_key}/regulatory")
def get_molecule_regulatory(molecule_key: str):
    passport = load_regulatory(molecule_key)
    if passport is None:
        raise HTTPException(status_code=404, detail=f"Regulatory passport for {molecule_key!r} not found")
    return passport.model_dump(mode="json")


@app.get("/molecules/{molecule_key}/geo")
def get_molecule_geo(molecule_key: str):
    patent = load_patent(molecule_key)
    if patent is None:
        raise HTTPException(status_code=404, detail=f"Molecule {molecule_key!r} not found")
    eligible = [g.model_dump(mode="json") for g in patent.geo_coverage if g.export_eligible]
    return {
        "molecule_key": molecule_key,
        "total_countries": len(patent.geo_coverage),
        "export_eligible_countries": [g.country_code for g in patent.geo_coverage if g.export_eligible],
        "export_eligible": eligible,
        "all_geo": [g.model_dump(mode="json") for g in patent.geo_coverage],
    }


@app.get("/refresh-orange-book/{molecule_key}")
def refresh_orange_book(molecule_key: str):
    """Placeholder for future FDA Orange Book / EMA / India IPO refresh."""
    return {
        "molecule_key": molecule_key,
        "status": "not_implemented",
        "message": "Live Orange Book refresh is planned for a later phase.",
    }


@app.post("/score", response_model=CandidateScore)
def score_molecule(req: ScoreRequest):
    patent = load_patent(req.molecule_key)
    plant = load_plant_asset(req.plant_asset_id) if req.plant_asset_id else None
    if patent is None:
        raise HTTPException(status_code=404, detail=f"Molecule {req.molecule_key!r} not found")

    weights = req.weights or DEFAULT_WEIGHTS
    result = score_candidate(req.molecule_key, patent, plant, weights=weights)
    return result


@app.get("/molecules/{molecule_key}/complexity")
def get_molecule_complexity(molecule_key: str):
    patent = load_patent(molecule_key)
    if patent is None:
        raise HTTPException(status_code=404, detail=f"Molecule {molecule_key!r} not found")
    regulatory = load_regulatory(molecule_key)
    from intelligence_scorer import derive_manufacturing_complexity

    complexity = derive_manufacturing_complexity(molecule_key, patent, regulatory)
    try:
        save_complexity(complexity)
    except Exception:
        pass
    return complexity.model_dump(mode="json")


@app.get("/molecules/{molecule_key}/roadmap")
def get_molecule_roadmap(molecule_key: str, plant_asset_id: str):
    patent = load_patent(molecule_key)
    if patent is None:
        raise HTTPException(status_code=404, detail=f"Molecule {molecule_key!r} not found")
    plant = load_plant_asset(plant_asset_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"Plant asset {plant_asset_id!r} not found")
    return evaluate_manufacturing_readiness(molecule_key, plant_asset_id, patent=patent)


@app.get("/plants/{asset_id}/fit/{molecule_key}")
def get_plant_fit_summary(asset_id: str, molecule_key: str):
    plant = load_plant_asset(asset_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"Plant asset {asset_id!r} not found")
    patent = load_patent(molecule_key)
    if patent is None:
        raise HTTPException(status_code=404, detail=f"Molecule {molecule_key!r} not found")
    regulatory = load_regulatory(molecule_key)
    from intelligence_scorer import derive_manufacturing_complexity

    complexity = derive_manufacturing_complexity(molecule_key, patent, regulatory)
    return {
        "plant_asset_id": asset_id,
        "molecule_key": molecule_key,
        "manufacturing_complexity": complexity.model_dump(mode="json"),
        "customer_profile_fit": evaluate_manufacturing_readiness(molecule_key, asset_id, patent=patent)["customer_profile_fit"],
    }


@app.post("/portfolio/score", response_model=PortfolioSnapshot)
def score_portfolio(req: PortfolioScoreRequest):
    patents = load_all_patents()
    plants = load_all_plant_assets()
    regulatory_map = load_all_regulatory()
    demand_map = load_all_demand()
    if not patents:
        raise HTTPException(status_code=503, detail="No patent intelligence available in Redis")

    weights = req.weights or DEFAULT_WEIGHTS
    scenario = PortfolioScenario(
        scenario_id=req.scenario_id,
        name=req.name,
        description=req.description,
        weights=weights,
        plant_asset_ids=req.plant_asset_ids,
        clusters=req.clusters,
        min_total_score=req.min_total_score,
        max_loe_years=req.max_loe_years,
        fto_risks_allowed=req.fto_risks_allowed,
        include_stretch=req.include_stretch,
        use_mock_data=req.use_mock_data,
    )
    snapshot = build_portfolio(scenario, patents, plants, regulatory_map, demand_map)
    return snapshot


@app.post("/portfolio/{portfolio_id}")
def create_portfolio(portfolio_id: str, req: PortfolioScoreRequest):
    snapshot = score_portfolio(req)
    scenario = PortfolioScenario(
        scenario_id=req.scenario_id,
        name=req.name,
        description=req.description,
        weights=req.weights or DEFAULT_WEIGHTS,
        plant_asset_ids=req.plant_asset_ids,
        clusters=req.clusters,
        min_total_score=req.min_total_score,
        max_loe_years=req.max_loe_years,
        fto_risks_allowed=req.fto_risks_allowed,
        include_stretch=req.include_stretch,
        use_mock_data=req.use_mock_data,
    )
    save_portfolio(portfolio_id, scenario, snapshot)
    return {"portfolio_id": portfolio_id, "status": "saved", "count": snapshot.count}


@app.get("/portfolio/{portfolio_id}")
def get_portfolio(portfolio_id: str):
    record = load_portfolio(portfolio_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id!r} not found")
    return record


@app.get("/portfolio/{portfolio_id}/export")
def export_portfolio(portfolio_id: str, format: str = "json"):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    record = load_portfolio(portfolio_id)
    if record is None or not record.get("snapshot"):
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id!r} not found")

    snapshot = record["snapshot"]
    entries = snapshot.get("entries", [])

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "rank",
                "molecule_key",
                "brand_name",
                "api_name",
                "therapeutic_area",
                "plant_asset_id",
                "plant_site_name",
                "cluster",
                "commercial_fit_tier",
                "patent_readiness_score",
                "regulatory_clarity_score",
                "demand_attractiveness_score",
                "plant_fit_score",
                "infrastructure_fit_score",
                "talent_fit_score",
                "certification_fit_score",
                "total_score",
                "fto_risk",
                "earliest_loe",
                "loe_years",
                "estimated_roadmap_months",
                "modality",
                "drug_form",
                "sterility_required",
                "warnings",
                "gaps",
            ],
        )
        writer.writeheader()
        for idx, e in enumerate(entries, 1):
            row = dict(e)
            row["rank"] = idx
            row["warnings"] = " | ".join(row.get("warnings", []))
            row["gaps"] = " | ".join(row.get("gaps", []))
            writer.writerow(row)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={portfolio_id}.csv"},
        )

    return snapshot
