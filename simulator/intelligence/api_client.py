"""Thin client for the CDMO intelligence FastAPI engine.

Used by the Streamlit simulator pages. Falls back to direct in-process scoring
if the API is unreachable (so the UI still works in single-container dev).
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

# Import the shared scorer directly as a fallback.
from intelligence.intelligence_models import CandidateScore, PatentIntelligence, PlantAsset, PortfolioScenario
from intelligence.intelligence_scorer import build_portfolio, score_candidate
from intelligence.intelligence_store import (
    load_all_demand,
    load_all_patents,
    load_all_plant_assets,
    load_all_regulatory,
    load_patent,
    load_plant_asset,
)

API_BASE = os.environ.get("CDMO_ENGINE_URL", "http://localhost:8000")


def _safe_post(path: str, payload: dict) -> dict | None:
    try:
        resp = requests.post(f"{API_BASE}{path}", json=payload, timeout=10)
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None


def _safe_get(path: str) -> dict | None:
    try:
        resp = requests.get(f"{API_BASE}{path}", timeout=10)
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None


def health() -> dict:
    return _safe_get("/health") or {"status": "degraded", "redis_ready": False}


def list_molecules() -> list[dict[str, Any]]:
    data = _safe_get("/molecules")
    return data.get("molecules", []) if data else []


def get_molecule(molecule_key: str) -> dict | None:
    return _safe_get(f"/molecules/{molecule_key}")


def get_molecule_geo(molecule_key: str) -> dict | None:
    return _safe_get(f"/molecules/{molecule_key}/geo")


def get_molecule_regulatory(molecule_key: str) -> dict | None:
    return _safe_get(f"/molecules/{molecule_key}/regulatory")


def list_regulatory() -> list[dict[str, Any]]:
    data = _safe_get("/regulatory")
    return data.get("passports", []) if data else []


def list_demand() -> list[dict[str, Any]]:
    data = _safe_get("/demand")
    return data.get("profiles", []) if data else []


def get_molecule_demand(molecule_key: str) -> dict | None:
    return _safe_get(f"/molecules/{molecule_key}/demand")


def get_molecule_complexity(molecule_key: str) -> dict | None:
    return _safe_get(f"/molecules/{molecule_key}/complexity")


def get_molecule_roadmap(molecule_key: str, plant_asset_id: str) -> dict | None:
    return _safe_get(f"/molecules/{molecule_key}/roadmap?plant_asset_id={plant_asset_id}")


def get_plant_fit_summary(asset_id: str, molecule_key: str) -> dict | None:
    return _safe_get(f"/plants/{asset_id}/fit/{molecule_key}")


def list_plants() -> list[dict[str, Any]]:
    data = _safe_get("/plants")
    return data.get("plants", []) if data else []


def score(
    molecule_key: str,
    plant_asset_id: str | None = None,
    weights: dict[str, float] | None = None,
) -> CandidateScore:
    """Score a candidate. Uses the API if available, otherwise scores locally."""
    payload = {
        "molecule_key": molecule_key,
        "plant_asset_id": plant_asset_id,
        "weights": weights,
    }
    data = _safe_post("/score", payload)
    if data:
        return CandidateScore(**data)

    # Fallback: score in-process using Redis directly.
    patent = load_patent(molecule_key)
    plant = load_plant_asset(plant_asset_id) if plant_asset_id else None
    return score_candidate(molecule_key, patent, plant, weights=weights)


def score_portfolio(scenario: PortfolioScenario) -> dict | None:
    """Score a portfolio scenario. Uses the API if available, otherwise scores locally."""
    payload = {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "description": scenario.description,
        "weights": scenario.weights,
        "plant_asset_ids": scenario.plant_asset_ids,
        "clusters": scenario.clusters,
        "min_total_score": scenario.min_total_score,
        "max_loe_years": scenario.max_loe_years,
        "fto_risks_allowed": scenario.fto_risks_allowed,
        "include_stretch": scenario.include_stretch,
        "use_mock_data": scenario.use_mock_data,
    }
    data = _safe_post("/portfolio/score", payload)
    if data:
        return data

    # Fallback: build portfolio in-process using Redis directly.
    patents = load_all_patents()
    plants = load_all_plant_assets()
    regulatory_map = load_all_regulatory()
    demand_map = load_all_demand()
    if not patents:
        return None
    snapshot = build_portfolio(scenario, patents, plants, regulatory_map, demand_map)
    return snapshot.model_dump(mode="json")


def save_portfolio(portfolio_id: str, scenario: PortfolioScenario) -> dict | None:
    payload = {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "description": scenario.description,
        "weights": scenario.weights,
        "plant_asset_ids": scenario.plant_asset_ids,
        "clusters": scenario.clusters,
        "min_total_score": scenario.min_total_score,
        "max_loe_years": scenario.max_loe_years,
        "fto_risks_allowed": scenario.fto_risks_allowed,
        "include_stretch": scenario.include_stretch,
        "use_mock_data": scenario.use_mock_data,
    }
    return _safe_post(f"/portfolio/{portfolio_id}", payload)


def load_portfolio(portfolio_id: str) -> dict | None:
    return _safe_get(f"/portfolio/{portfolio_id}")


def export_portfolio(portfolio_id: str, format: str = "json") -> dict | None:
    return _safe_get(f"/portfolio/{portfolio_id}/export?format={format}")
