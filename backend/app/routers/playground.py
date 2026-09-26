"""Playground API — national exploratory views for every signed-in user
(CDSCO NSQ alerts and the public-source data are public records)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import data, playground
from ..db import get_db
from ..models import PLATFORM_ROLES, Org, User
from ..security import current_user

router = APIRouter(prefix="/api/playground", tags=["playground"])


def _filters(focus: str = "all", drug_type: list[str] = Query(default=[]), form: list[str] = Query(default=[]),
             category: list[str] = Query(default=[]), state: list[str] = Query(default=[]), source: list[str] = Query(default=[]),
             since: str = "", until: str = "", q: str = "", top_mfr: int = Query(15, ge=5, le=30)) -> dict[str, Any]:
    return {"focus": focus, "drug_type": drug_type, "form": form, "category": category, "state": state, "source": source,
            "since": since, "until": until, "q": q, "top_mfr": top_mfr}


@router.get("/facets")
def facets(user: User = Depends(current_user)):
    return playground.facets()


@router.get("/cube")
def cube(f: dict = Depends(_filters), user: User = Depends(current_user)):
    return playground.cube(f)


@router.get("/ledger")
def ledger(f: dict = Depends(_filters), cols: list[str] = Query(default=[]), sort: str = "month", desc: bool = True,
           page: int = Query(1, ge=1), size: int = Query(50, ge=10, le=250), user: User = Depends(current_user)):
    return playground.ledger(f, cols, sort, desc, page, size)


@router.get("/ledger.csv")
def ledger_csv(f: dict = Depends(_filters), cols: list[str] = Query(default=[]), sort: str = "month", desc: bool = True,
               user: User = Depends(current_user)):
    return Response(playground.ledger_csv(f, cols, sort, desc), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="nsq-alerts.csv"'})


@router.get("/geo/india")
def geo_india(user: User = Depends(current_user)):
    g = playground.india_geo()
    if g is None:
        raise HTTPException(404, "India state boundaries are not loaded (Redis key geo:india_states).")
    return Response(content=__import__("json").dumps(g, separators=(",", ":")), media_type="application/json",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/insights")
def insights_view(user: User = Depends(current_user)):
    return playground.insights_view()


@router.get("/world")
def world(molecule: str = "", user: User = Depends(current_user)):
    return playground.world(molecule)


def _visible_plants(user: User, db: Session) -> list[str]:
    """Seeded demo plants + the user's organisation's plants (all plants for platform staff)."""
    plants = data.cdmo()["plants"]
    if user.role in PLATFORM_ROLES:
        return list(plants)
    mine: list[str] = []
    if user.org_id:
        org = db.get(Org, user.org_id)
        mine = list(org.plant_ids or []) if org else []
    owned = {pid for o in db.scalars(select(Org)) for pid in (o.plant_ids or [])}
    seeded = [p for p in plants if p not in owned]
    return list(dict.fromkeys(mine + seeded))


@router.get("/molecule/{key}")
def molecule(key: str, plant_id: str = "", w_patent: Optional[float] = None, w_regulatory: Optional[float] = None,
             w_demand: Optional[float] = None, w_plant: Optional[float] = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    weights = None
    if None not in (w_patent, w_regulatory, w_demand, w_plant):
        tot = (w_patent or 0) + (w_regulatory or 0) + (w_demand or 0) + (w_plant or 0)
        if tot <= 0:
            raise HTTPException(422, "Weights must add up to more than 0.")
        weights = {"patent": w_patent / tot, "regulatory": w_regulatory / tot, "demand": w_demand / tot, "plant": w_plant / tot}
    out = playground.workbench(key, weights, _visible_plants(user, db), plant_id)
    if out is None:
        raise HTTPException(404, "Molecule not tracked.")
    return out
