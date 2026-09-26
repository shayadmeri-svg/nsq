"""Platform-wide views (staff only): all-India NSQ analytics, alert ledger,
CDMO catalogue, process simulator, and data freshness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import capability_catalog
import field_provenance
from process_models import ROUTES, route_metadata

from .. import data, insights
from ..models import User
from ..security import current_user, require_platform

router = APIRouter(prefix="/api", tags=["platform"])


@router.get("/nsq/summary")
def nsq_summary(user: User = Depends(require_platform)):
    return insights.platform_summary()


@router.get("/nsq/alerts")
def nsq_alerts(q: str = "", category: str = "", form: str = "", manufacturer: str = "",
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
               user: User = Depends(require_platform)):
    df = data.frame()
    if manufacturer:
        df = df[df["Mfg_Ontology_Key"] == manufacturer]
    df = insights.filter_issues(df, q, category, form)
    return insights.paginate(df, page, size)


@router.get("/nsq/facets")
def nsq_facets(user: User = Depends(current_user)):
    df = data.frame()
    return {
        "categories": sorted(df["Failure_Category_Primary"].dropna().unique().tolist()),
        "forms": sorted(df["Form type"].dropna().unique().tolist()),
    }


@router.get("/cdmo/molecules")
def molecules(user: User = Depends(current_user)):
    m = data.cdmo()
    out = []
    for key, p in m["patents"].items():
        d = m["demand"].get(key)
        out.append({
            "molecule_key": key, "api_name": p.api_name, "brand_name": p.brand_name, "originator": p.originator,
            "therapeutic_area": p.therapeutic_area, "fto_risk": p.fto_risk, "market_size_usd_bn": p.market_size_usd_bn,
            "loe": {"in": p.estimated_loe_in, "eu": p.estimated_loe_eu, "us": p.estimated_loe_us},
            "cluster": d.cluster if d else "",
        })
    return {"molecules": insights.json_safe(sorted(out, key=lambda r: r["api_name"]))}


@router.get("/cdmo/capability-taxonomy")
def taxonomy(user: User = Depends(current_user)):
    return {"sections": [
        {"id": s.section_id, "title": s.title, "icon": s.icon, "description": s.description,
         "capabilities": [{"token": c.token, "label": c.label} for c in s.capabilities]}
        for s in capability_catalog.SECTIONS
    ]}


# --- process simulator (was the host-only :8010 API) ----------------------------

@router.get("/process/routes")
def process_routes(user: User = Depends(current_user)):
    return route_metadata()


@router.post("/process/{route_id}")
def process_simulate(route_id: str, payload: dict[str, Any] = Body(default_factory=dict), user: User = Depends(current_user)):
    mod = ROUTES.get(route_id)
    if mod is None:
        raise HTTPException(404, f"Unknown route {route_id!r}.")
    clean: dict[str, float] = {}
    for stage in mod.STAGES:
        for cpp in stage["cpps"]:
            name = cpp["name"]
            try:
                val = float(payload.get(name, cpp["default"]))
            except (TypeError, ValueError):
                raise HTTPException(422, f"CPP {name!r} must be numeric.")
            if not float(cpp["min"]) <= val <= float(cpp["max"]):
                raise HTTPException(422, f"CPP {name!r}={val} out of range [{cpp['min']}, {cpp['max']}].")
            clean[name] = val
    return insights.json_safe(mod.simulate(clean))


# --- data freshness ---------------------------------------------------------------

@router.get("/data/status")
def data_status(user: User = Depends(current_user)):
    s = data.data_status()
    if user.role not in ("super_admin", "admin"):
        # Org users see freshness, not infrastructure detail.
        r = s.get("redis") or {}
        return {"records": r.get("records"), "loaded_at": (r.get("meta") or {}).get("loaded_at"),
                "frame_built_at": (r.get("frame") or {}).get("built_at"), "ok": r.get("ok", False)}
    return s


@router.get("/meta/provenance")
def meta_provenance(user: User = Depends(current_user)):
    """Where each displayed number comes from and what is missing (for the UI's disclaimer icons)."""
    return {"fields": field_provenance.provenance()}
