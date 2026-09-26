"""Redis-backed storage for the CDMO intelligence engine.

Mirrors the patterns in shared/nsq_redis.py but manages the separate
`cdmo:*` keyspace so the new engine does not collide with the existing
NSQ alert data.
"""

from __future__ import annotations

import json
import os
from typing import Any

import redis

from intelligence_models import (
    DemandProfile,
    ManufacturingComplexity,
    PatentIntelligence,
    PlantAsset,
    PortfolioScenario,
    PortfolioSnapshot,
    RegulatoryPassport,
)

PATENT_KEY_PREFIX = "cdmo:patent"
PLANT_KEY_PREFIX = "cdmo:plant"
REGULATORY_KEY_PREFIX = "cdmo:regulatory"
DEMAND_KEY_PREFIX = "cdmo:demand"
COMPLEXITY_KEY_PREFIX = "cdmo:complexity"
PORTFOLIO_KEY_PREFIX = "cdmo:portfolio"


def get_redis_client(url: str | None = None) -> redis.Redis:
    url = url or os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError(
            "REDIS_URL is not set. The intelligence engine needs a Redis "
            "connection string (see .env.example)."
        )
    return redis.from_url(url, decode_responses=True)


def patent_key(molecule_key: str) -> str:
    return f"{PATENT_KEY_PREFIX}:{molecule_key}"


def plant_key(asset_id: str) -> str:
    return f"{PLANT_KEY_PREFIX}:{asset_id}"


def regulatory_key(molecule_key: str) -> str:
    return f"{REGULATORY_KEY_PREFIX}:{molecule_key}"


def demand_key(molecule_key: str) -> str:
    return f"{DEMAND_KEY_PREFIX}:{molecule_key}"


def complexity_key(molecule_key: str) -> str:
    return f"{COMPLEXITY_KEY_PREFIX}:{molecule_key}"


def portfolio_key(portfolio_id: str) -> str:
    return f"{PORTFOLIO_KEY_PREFIX}:{portfolio_id}"


def save_patent(record: PatentIntelligence, client: redis.Redis | None = None) -> None:
    r = client or get_redis_client()
    r.hset(patent_key(record.molecule_key), mapping=record.to_redis())


def load_patent(molecule_key: str, client: redis.Redis | None = None) -> PatentIntelligence | None:
    r = client or get_redis_client()
    data = r.hgetall(patent_key(molecule_key))
    if not data:
        return None
    return PatentIntelligence.from_redis(data)


def list_patent_keys(client: redis.Redis | None = None) -> list[str]:
    r = client or get_redis_client()
    return sorted(r.scan_iter(f"{PATENT_KEY_PREFIX}:*"))


def load_all_patents(client: redis.Redis | None = None) -> dict[str, PatentIntelligence]:
    r = client or get_redis_client()
    out: dict[str, PatentIntelligence] = {}
    for key in list_patent_keys(r):
        data = r.hgetall(key)
        if data:
            rec = PatentIntelligence.from_redis(data)
            out[rec.molecule_key] = rec
    return out


def save_plant_asset(asset: PlantAsset, client: redis.Redis | None = None) -> None:
    r = client or get_redis_client()
    r.hset(plant_key(asset.asset_id), mapping=asset.to_redis())


def load_plant_asset(asset_id: str, client: redis.Redis | None = None) -> PlantAsset | None:
    r = client or get_redis_client()
    data = r.hgetall(plant_key(asset_id))
    if not data:
        return None
    return PlantAsset.from_redis(data)


def list_plant_keys(client: redis.Redis | None = None) -> list[str]:
    r = client or get_redis_client()
    return sorted(r.scan_iter(f"{PLANT_KEY_PREFIX}:*"))


def load_all_plant_assets(client: redis.Redis | None = None) -> dict[str, PlantAsset]:
    r = client or get_redis_client()
    out: dict[str, PlantAsset] = {}
    for key in list_plant_keys(r):
        data = r.hgetall(key)
        if data:
            asset = PlantAsset.from_redis(data)
            out[asset.asset_id] = asset
    return out


def save_regulatory(record: RegulatoryPassport, client: redis.Redis | None = None) -> None:
    r = client or get_redis_client()
    r.hset(regulatory_key(record.molecule_key), mapping=record.to_redis())


def load_regulatory(molecule_key: str, client: redis.Redis | None = None) -> RegulatoryPassport | None:
    r = client or get_redis_client()
    data = r.hgetall(regulatory_key(molecule_key))
    if not data:
        return None
    return RegulatoryPassport.from_redis(data)


def list_regulatory_keys(client: redis.Redis | None = None) -> list[str]:
    r = client or get_redis_client()
    return sorted(r.scan_iter(f"{REGULATORY_KEY_PREFIX}:*"))


def load_all_regulatory(client: redis.Redis | None = None) -> dict[str, RegulatoryPassport]:
    r = client or get_redis_client()
    out: dict[str, RegulatoryPassport] = {}
    for key in list_regulatory_keys(r):
        data = r.hgetall(key)
        if data:
            rec = RegulatoryPassport.from_redis(data)
            out[rec.molecule_key] = rec
    return out


def save_demand(record: DemandProfile, client: redis.Redis | None = None) -> None:
    r = client or get_redis_client()
    r.hset(demand_key(record.molecule_key), mapping=record.to_redis())


def load_demand(molecule_key: str, client: redis.Redis | None = None) -> DemandProfile | None:
    r = client or get_redis_client()
    data = r.hgetall(demand_key(molecule_key))
    if not data:
        return None
    return DemandProfile.from_redis(data)


def list_demand_keys(client: redis.Redis | None = None) -> list[str]:
    r = client or get_redis_client()
    return sorted(r.scan_iter(f"{DEMAND_KEY_PREFIX}:*"))


def load_all_demand(client: redis.Redis | None = None) -> dict[str, DemandProfile]:
    r = client or get_redis_client()
    out: dict[str, DemandProfile] = {}
    for key in list_demand_keys(r):
        data = r.hgetall(key)
        if data:
            rec = DemandProfile.from_redis(data)
            out[rec.molecule_key] = rec
    return out


def save_complexity(record: ManufacturingComplexity, client: redis.Redis | None = None) -> None:
    r = client or get_redis_client()
    r.hset(complexity_key(record.molecule_key), mapping=record.to_redis())


def load_complexity(molecule_key: str, client: redis.Redis | None = None) -> ManufacturingComplexity | None:
    r = client or get_redis_client()
    data = r.hgetall(complexity_key(molecule_key))
    if not data:
        return None
    return ManufacturingComplexity.from_redis(data)


def list_complexity_keys(client: redis.Redis | None = None) -> list[str]:
    r = client or get_redis_client()
    return sorted(r.scan_iter(f"{COMPLEXITY_KEY_PREFIX}:*"))


def load_all_complexity(client: redis.Redis | None = None) -> dict[str, ManufacturingComplexity]:
    r = client or get_redis_client()
    out: dict[str, ManufacturingComplexity] = {}
    for key in list_complexity_keys(r):
        data = r.hgetall(key)
        if data:
            rec = ManufacturingComplexity.from_redis(data)
            out[rec.molecule_key] = rec
    return out


def save_portfolio(
    portfolio_id: str,
    scenario: PortfolioScenario,
    snapshot: PortfolioSnapshot,
    client: redis.Redis | None = None,
) -> None:
    """Persist a portfolio scenario + ranked snapshot to Redis."""
    r = client or get_redis_client()
    r.hset(
        portfolio_key(portfolio_id),
        mapping={
            "portfolio_id": portfolio_id,
            "scenario": json.dumps(scenario.model_dump(mode="json"), ensure_ascii=False),
            "snapshot": json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False),
            "updated_at": json.dumps({"iso": __import__("datetime").datetime.utcnow().isoformat()}),
        },
    )


def load_portfolio(portfolio_id: str, client: redis.Redis | None = None) -> dict[str, Any] | None:
    """Load a persisted portfolio scenario + snapshot from Redis."""
    r = client or get_redis_client()
    data = r.hgetall(portfolio_key(portfolio_id))
    if not data:
        return None
    try:
        return {
            "portfolio_id": data.get("portfolio_id", portfolio_id),
            "scenario": json.loads(data["scenario"]) if "scenario" in data else None,
            "snapshot": json.loads(data["snapshot"]) if "snapshot" in data else None,
            "updated_at": json.loads(data["updated_at"]) if "updated_at" in data else None,
        }
    except (json.JSONDecodeError, KeyError):
        return None


def list_portfolio_keys(client: redis.Redis | None = None) -> list[str]:
    r = client or get_redis_client()
    return sorted(r.scan_iter(f"{PORTFOLIO_KEY_PREFIX}:*"))
