"""Playground API — national exploratory views for every signed-in user
(CDSCO NSQ alerts and the public-source data are public records)."""

from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import data, playground
from ..db import get_db
from ..models import PLATFORM_ROLES, Org, User
from ..security import current_user

router = APIRouter(prefix="/api/playground", tags=["playground"])


def _filters(focus: str = "all", drug_type: list[str] = Query(default=[]), form: list[str] = Query(default=[]),
             category: list[str] = Query(default=[]), state: list[str] = Query(default=[]), source: list[str] = Query(default=[]),
             since: str = "", until: str = "", q: str = "", top_mfr: int = Query(15, ge=5, le=30),
             authenticity: str = Query("", pattern="^(|genuine|spurious)$")) -> dict[str, Any]:
    return {"focus": focus, "drug_type": drug_type, "form": form, "category": category, "state": state, "source": source,
            "since": since, "until": until, "q": q, "top_mfr": top_mfr, "authenticity": authenticity}


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
    """Plant profiles a user can score against: their organisation's plants (every organisation's for platform staff).
    The demo profiles in plant_assets_seed.json are left out (unless they are the user's own organisation's plants)."""
    from .. import plants as registry_plants

    plants = data.cdmo()["plants"]
    demo = {k for k, v in registry_plants._seed_links().items() if v.get("demo")}
    mine: list[str] = []
    if user.org_id:
        org = db.get(Org, user.org_id)
        mine = list(org.plant_ids or []) if org else []
    if user.role in PLATFORM_ROLES:
        return list(dict.fromkeys([*mine, *(p for p in plants if p not in demo)]))
    return [p for p in dict.fromkeys(mine) if p in plants]


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


@router.get("/molecule/{key}/plant-fit")
def molecule_plant_fit(key: str, limit: int = Query(25, ge=1, le=100), state: str = "", q: str = "",
                       cert: str = Query("", pattern="^(|who_gmp|eu_gmp|us_fda|sugam|schedule_c|loan)$"),
                       user: User = Depends(current_user)):
    """Plant fit of every plant in the registry for this molecule, best first."""
    from .. import plants as registry_plants

    out = registry_plants.fit_ranking(key, limit=limit, state=state, cert=cert, q=q)
    if out is None:
        raise HTTPException(404, "Molecule not tracked.")
    return out


@router.get("/survival")
def survival(group: str = Query("form", pattern="^(form|category|drug_type|source|state)$"), measure: str = Query("months", pattern="^(months|shelf)$"),
             f: dict = Depends(_filters), user: User = Depends(current_user)):
    return playground.survival(group, measure, f)


# --- Health & trade signals (NFHS, IDSP, UN Comtrade) -------------------------------------------

@router.get("/signals/meta")
def signals_meta(user: User = Depends(current_user)):
    from .. import signals

    return signals.meta()


@router.get("/signals/nfhs")
def signals_nfhs(ind: str = "sugar_women", round: str = "", state: str = "", user: User = Depends(current_user)):  # noqa: A002
    from .. import signals

    return signals.nfhs(ind, round, state)


@router.get("/signals/outbreaks")
def signals_outbreaks(weeks: int = Query(26, ge=1, le=260), disease: str = "", state: str = "", user: User = Depends(current_user)):
    from .. import signals

    return signals.outbreaks(weeks, disease, state)


@router.get("/signals/trade")
def signals_trade(hs: str = Query("", pattern=r"^(|\d{4})$"), flow: str = Query("export", pattern="^(export|import)$"),
                  user: User = Depends(current_user)):
    from .. import signals

    return signals.trade(hs, flow)


@router.get("/molecule/{key}/synthesis")
def molecule_synthesis(key: str, user: User = Depends(current_user)):
    """How the molecule is made: reactions from the Open Reaction Database."""
    from .. import signals

    return signals.synthesis(key)


# --- CDSCO Written Confirmations (API exports to the EU) --------------------------------------

@router.get("/wc")
def wc_list(q: str = Query("", max_length=120), kind: str = Query("wc", pattern="^(wc|notice|all)$"), year: str = Query("", pattern=r"^(|\d{4})$"),
            latest: bool = False, page: int = Query(1, ge=1), size: int = Query(25, ge=5, le=100), user: User = Depends(current_user)):
    from .. import wc
    return wc.listing(q, kind, year, latest, page, size)


@router.get("/wc/{rid}.pdf")
def wc_pdf(rid: str, user: User = Depends(current_user)):
    """The letter itself, shown inline (the page embeds it; CDSCO's own site refuses to be framed)."""
    from fastapi.responses import FileResponse

    from .. import wc
    p = wc.pdf_path(rid)
    if p is None:
        raise HTTPException(404, "This PDF is not on the server yet — run just fetch-cdsco-wc and just push-wc.")
    r = wc.record(rid.removesuffix(".pdf")) or {}
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{r.get('wc') or 'CDSCO'}_{r.get('company') or rid}")[:80] + ".pdf"
    return FileResponse(p, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"',
                                                                   "Cache-Control": "private, max-age=86400"})


# --- Investigate: any product or manufacturer, nationally (replaces the Streamlit investigation tab) ----------

@router.get("/investigate/search")
def investigate_search(q: str = Query("", max_length=120), user: User = Depends(current_user)):
    from .. import insights
    return {"products": insights.product_search(q, 10), "manufacturers": insights.manufacturer_search(q, 10)}


@router.get("/investigate/product")
def investigate_product(name: str = Query(..., min_length=1, max_length=300), user: User = Depends(current_user)):
    from .. import insights
    out = insights.product_detail(name)
    if out is None:
        raise HTTPException(404, "No NSQ alert for this product.")
    return out


@router.get("/investigate/manufacturer/{key}")
def investigate_manufacturer(key: str, user: User = Depends(current_user)):
    from .. import insights
    out = insights.org_quality([key])
    if out.get("empty"):
        raise HTTPException(404, "No NSQ alert for this manufacturer.")
    hit = next((x for x in insights.manufacturer_search(key, 50) if x["key"] == key), None)
    return {**out, "manufacturer": hit or {"key": key, "name": key.title()}}


@router.get("/investigate/manufacturer/{key}/alerts")
def investigate_manufacturer_alerts(key: str, q: str = "", category: str = "", form: str = "", product: str = "",
                                    page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200), user: User = Depends(current_user)):
    from .. import insights
    df = data.org_frame([key])
    if product:
        df = df[df["Product_Name_Canonical"].fillna(df["Name of Product"]).astype(str) == product]
    return insights.paginate(insights.filter_issues(df, q, category, form), page, size)


@router.get("/investigate/manufacturer/{key}/alerts/{issue_id}")
def investigate_alert(key: str, issue_id: str, user: User = Depends(current_user)):
    """One alert with its diagnosis: GMP & testing standards, probable causes, mitigation plan."""
    from .. import insights
    detail = insights.org_issue_detail([key], issue_id)
    if detail is None:
        raise HTTPException(404, "Alert not found for this manufacturer.")
    detail["persona"] = user.persona
    return detail
