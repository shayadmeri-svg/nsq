"""Plant registry API: CDSCO WHO-GMP / SUGAM plants, their capabilities, and the
NSQ alerts linked to them. Public records, so every signed-in user can read it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import plants
from ..models import User
from ..security import current_user
from ..tenant import keep_own_plants, own_plant, tenant_of

from .. import features
from ..tenant import TenantRoute

router = APIRouter(route_class=TenantRoute, dependencies=[Depends(features.gate)], prefix="/api/plants", tags=["plants"])


@router.get("")
def plant_list(q: str = "", state: str = "", capability: str = "", segregated: str = "",
               cert: str = Query("", pattern="^(|who_gmp|eu_gmp|eu_ncr|us_fda|fda_oai|sugam|schedule_c|loan)$"), nsq: str = Query("", pattern="^(|yes|no)$"),
               sort: str = Query("nsq", pattern="^(nsq|name|forms)$"), page: int = Query(1, ge=1), size: int = Query(25, ge=5, le=100),
               user: User = Depends(current_user), request: Request = None):
    t = tenant_of(request)  # an organisation's users: their own plants only
    return plants.search(q=q, state=state, capability=capability, segregated=segregated, cert=cert, nsq=nsq, sort=sort, page=page, size=size,
                         only=t.plants if t else None)


@router.get("/summary")
def plant_summary(exclude_api_only: bool = False, user: User = Depends(current_user)):
    return plants.summary(exclude_api_only=exclude_api_only)


@router.get("/facets")
def plant_facets(user: User = Depends(current_user)):
    return plants.facets()


@router.get("/for-molecule/{key}")
def plant_makers(key: str, request: Request, user: User = Depends(current_user)):
    out = plants.makers(key)
    if out is None:
        raise HTTPException(404, "Molecule not tracked.")
    return keep_own_plants(tenant_of(request), out)


@router.get("/{plant_id}")
def plant_detail(plant_id: str, request: Request, user: User = Depends(current_user)):
    own_plant(tenant_of(request), plant_id)
    p = plants.get(plant_id)
    if p is None:
        raise HTTPException(404, "Plant not found in the registry.")
    return p


@router.get("/{plant_id}/alerts")
def plant_alerts(plant_id: str, q: str = "", category: str = "", page: int = Query(1, ge=1), size: int = Query(20, ge=5, le=100),
                 user: User = Depends(current_user), request: Request = None):
    """Every NSQ alert linked to this plant, newest first; each opens its diagnosis in Playground · Investigate."""
    own_plant(tenant_of(request), plant_id)
    out = plants.alerts(plant_id, q, category, page, size)
    if out is None:
        raise HTTPException(404, "Plant not found in the registry.")
    return out
