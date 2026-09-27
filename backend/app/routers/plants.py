"""Plant registry API: CDSCO WHO-GMP / SUGAM plants, their capabilities, and the
NSQ alerts linked to them. Public records, so every signed-in user can read it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import plants
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api/plants", tags=["plants"])


@router.get("")
def plant_list(q: str = "", state: str = "", capability: str = "", segregated: str = "",
               cert: str = Query("", pattern="^(|who_gmp|eu_gmp|eu_ncr|sugam|schedule_c|loan)$"), nsq: str = Query("", pattern="^(|yes|no)$"),
               sort: str = Query("nsq", pattern="^(nsq|name|forms)$"), page: int = Query(1, ge=1), size: int = Query(25, ge=5, le=100),
               user: User = Depends(current_user)):
    return plants.search(q=q, state=state, capability=capability, segregated=segregated, cert=cert, nsq=nsq, sort=sort, page=page, size=size)


@router.get("/summary")
def plant_summary(exclude_api_only: bool = False, user: User = Depends(current_user)):
    return plants.summary(exclude_api_only=exclude_api_only)


@router.get("/facets")
def plant_facets(user: User = Depends(current_user)):
    return plants.facets()


@router.get("/for-molecule/{key}")
def plant_makers(key: str, user: User = Depends(current_user)):
    out = plants.makers(key)
    if out is None:
        raise HTTPException(404, "Molecule not tracked.")
    return out


@router.get("/{plant_id}")
def plant_detail(plant_id: str, user: User = Depends(current_user)):
    p = plants.get(plant_id)
    if p is None:
        raise HTTPException(404, "Plant not found in the registry.")
    return p
