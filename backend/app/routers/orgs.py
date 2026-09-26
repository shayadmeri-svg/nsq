"""Organisation dashboards: overview, quality (NSQ), infrastructure,
opportunities (patents × infra) and EU export readiness."""

from __future__ import annotations

import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import capability_catalog
import intelligence_store as store
from intelligence_models import PlantAsset
from intelligence_scorer import evaluate_manufacturing_readiness

from .. import data, insights, sites
from ..audit import audit
from ..db import get_db
from ..models import Org, PLATFORM_ROLES, Plant, User
from ..security import can_manage_org, current_user, org_for_user

router = APIRouter(prefix="/api/orgs", tags=["orgs"])


def org_payload(org: Org) -> dict:
    return {
        "id": org.id, "slug": org.slug, "name": org.name, "city": org.city, "country": org.country,
        "ontology_keys": org.ontology_keys or [], "plant_ids": org.plant_ids or [],
        "notes": org.notes, "is_active": org.is_active,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.get("")
def list_my_orgs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role in PLATFORM_ROLES:
        orgs = db.scalars(select(Org).order_by(Org.name)).all()
    else:
        orgs = [user.org] if user.org else []
    return {"orgs": [org_payload(o) for o in orgs]}


@router.get("/{slug}")
def get_org(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    return {"org": org_payload(org), "can_manage": can_manage_org(user, org)}


@router.get("/{slug}/overview")
def overview(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    return insights.org_overview(org)


@router.get("/{slug}/quality")
def quality(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    return insights.org_quality(org.ontology_keys or [])


@router.get("/{slug}/quality/issues")
def quality_issues(
    slug: str,
    q: str = "",
    category: str = "",
    form: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    org = org_for_user(db, slug, user)
    df = insights.filter_issues(data.org_frame(org.ontology_keys or []), q, category, form)
    return insights.paginate(df, page, size)


@router.get("/{slug}/quality/issues/{issue_id}")
def quality_issue(slug: str, issue_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    detail = insights.org_issue_detail(org.ontology_keys or [], issue_id)
    if detail is None:
        raise HTTPException(404, "Issue not found for this organisation.")
    detail["persona"] = user.persona
    return detail


@router.get("/{slug}/infrastructure")
def infrastructure(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    out = insights.org_infrastructure(org.plant_ids or [])
    owned = {p.asset_id for p in db.scalars(select(Plant).where(Plant.org_id == org.id))}
    for p in out["plants"]:
        p["editable"] = can_manage_org(user, org) and (p["asset_id"] in owned or user.role in PLATFORM_ROLES)
    out["can_manage"] = can_manage_org(user, org)
    return out


@router.get("/{slug}/opportunities")
def opportunities(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    return insights.org_opportunities(org.plant_ids or [], org.ontology_keys or [])


@router.get("/{slug}/opportunities/{molecule_key}")
def opportunity_detail(slug: str, molecule_key: str, plant_id: Optional[str] = None,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    m = data.cdmo()
    patent = m["patents"].get(molecule_key)
    if patent is None:
        raise HTTPException(404, "Molecule not found.")
    plant_ids = org.plant_ids or []
    if plant_id and plant_id not in plant_ids:
        raise HTTPException(404, "Plant not linked to this organisation.")
    pid = plant_id or (plant_ids[0] if plant_ids else None)
    plant = m["plants"].get(pid) if pid else None
    result = {
        "patent": patent.model_dump(mode="json"),
        "regulatory": m["regulatory"][molecule_key].model_dump(mode="json") if molecule_key in m["regulatory"] else None,
        "demand": m["demand"][molecule_key].model_dump(mode="json") if molecule_key in m["demand"] else None,
    }
    if plant is not None:
        result["readiness"] = evaluate_manufacturing_readiness(
            molecule_key, plant.asset_id, patent=patent, regulatory=m["regulatory"].get(molecule_key), plant=plant)
        result["plant"] = {"asset_id": plant.asset_id, "name": plant.site_name}
    eu = insights.org_eu_export(org.ontology_keys or [], plant_ids, [molecule_key])
    result["eu"] = eu["assessments"][0] if eu["assessments"] else None
    return result


@router.get("/{slug}/eu-export")
def eu_export(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    return insights.org_eu_export(org.ontology_keys or [], org.plant_ids or [])


# --- plants owned by the org ------------------------------------------------------

class PlantBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    city: str = ""
    state: str = ""
    capabilities: list[str] = []
    certifications: list[str] = []
    approved_forms: list[str] = []
    containment_class: Optional[str] = None
    batch_capacity_kg: Optional[float] = None
    notes: str = ""


_CERTS = {"WHO_GMP", "EU_GMP", "USFDA", "PICS", "UK_MHRA", "TGA", "HEALTH_CANADA", "PMDA", "ANVISA", "BIOLOGIC_GMP", "CYTOTOXIC_LICENSING", "EU_GMP_ANNEX_1", "COFEPRIS", "DIGEMID"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "plant"


def _build_plant(asset_id: str, body: PlantBody, base: Optional[PlantAsset] = None) -> PlantAsset:
    valid, invalid = capability_catalog.validate_capabilities(body.capabilities)
    # Seeded plants carry legacy tokens outside the catalog; keep those.
    legacy = set(base.capabilities) if base else set()
    valid += [t for t in invalid if t in legacy]
    invalid = [t for t in invalid if t not in legacy]
    if invalid:
        raise HTTPException(400, f"Unknown capabilities: {', '.join(invalid)}")
    certs = sorted({c.strip().upper() for c in body.certifications if c.strip()})
    bad = [c for c in certs if c not in _CERTS]
    if bad:
        raise HTTPException(400, f"Unknown certifications: {', '.join(bad)}")
    defaults = capability_catalog.infer_plant_defaults(valid) if valid else {}
    fields = dict(base.model_dump() if base else {})
    fields.update(defaults)
    fields.update({
        "asset_id": asset_id, "site_name": body.name.strip(), "city": body.city, "state": body.state,
        "capabilities": valid, "certifications": certs, "certifications_active": certs, "notes": body.notes,
    })
    if body.approved_forms:
        fields["approved_forms"] = body.approved_forms
    basis = dict((base.capability_basis if base else {}) or {})
    for t in valid:
        basis.setdefault(t, "user")
    fields["capability_basis"] = {t: basis[t] for t in valid}
    cert_basis = dict((base.certification_basis if base else {}) or {})
    fields["certification_basis"] = {c: cert_basis.get(c, "Entered in the app") for c in certs}
    if body.containment_class:
        fields["containment_class"] = body.containment_class
    if body.batch_capacity_kg is not None:
        fields["batch_capacity_kg"] = body.batch_capacity_kg
    return PlantAsset(**fields)


@router.post("/{slug}/plants")
def create_plant(slug: str, body: PlantBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    if not can_manage_org(user, org):
        raise HTTPException(403, "Only organisation admins can add plants.")
    asset_id = f"{org.slug}-{_slug(body.name)}-{uuid.uuid4().hex[:6]}"
    plant = _build_plant(asset_id, body)
    store.save_plant_asset(plant, data.redis_client())
    db.add(Plant(asset_id=asset_id, org_id=org.id, created_by=user.id, payload=plant.model_dump(mode="json")))
    org.plant_ids = list(org.plant_ids or []) + [asset_id]
    db.commit()
    data.invalidate()
    audit(db, "plant.created", actor=user, target_type="plant", target_id=asset_id, detail={"org": org.slug}, request=request)
    return insights.plant_profile(plant)


def _linked_sites(org) -> dict[str, str]:
    plants = data.cdmo()["plants"]
    out = {}
    for pid in org.plant_ids or []:
        p = plants.get(pid)
        sid = (p.reference or {}).get("site_id") if p else None
        if sid:
            out[sid] = pid
    return out


@router.get("/{slug}/site-suggestions")
def site_suggestions(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Sites in the public-record directory that belong to this organisation's
    NSQ manufacturer identities, with whether each is already a plant."""
    org = org_for_user(db, slug, user)
    res = sites.search(ontology_keys=list(org.ontology_keys or []), size=100)
    linked = _linked_sites(org)
    return {"items": [{**s, "plant_id": linked.get(s["id"])} for s in res["items"]], "total": res["total"],
            "can_add": can_manage_org(user, org)}


class FromSiteBody(BaseModel):
    site_id: str


@router.post("/{slug}/plants/from-site")
def plant_from_site(slug: str, body: FromSiteBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    if not can_manage_org(user, org):
        raise HTTPException(403, "Only organisation admins can add plants.")
    site = sites.get(body.site_id)
    if site is None:
        raise HTTPException(404, "Site not found in the directory.")
    if site["ontology_key"] not in (org.ontology_keys or []) and user.role not in PLATFORM_ROLES:
        raise HTTPException(403, "That site belongs to a manufacturer this organisation is not linked to.")
    if body.site_id in _linked_sites(org):
        raise HTTPException(409, "This site is already one of the organisation's plants.")
    asset_id = f"{org.slug}-{_slug(site['company'])[:40]}-{site['pincode'] or uuid.uuid4().hex[:6]}"
    plant = PlantAsset(**sites.plant_from_site(site, asset_id))
    store.save_plant_asset(plant, data.redis_client())
    db.merge(Plant(asset_id=asset_id, org_id=org.id, created_by=user.id, payload=plant.model_dump(mode="json")))
    if asset_id not in (org.plant_ids or []):
        org.plant_ids = list(org.plant_ids or []) + [asset_id]
    db.commit()
    data.invalidate()
    audit(db, "plant.created_from_site", actor=user, target_type="plant", target_id=asset_id, detail={"org": org.slug, "site": body.site_id}, request=request)
    return insights.plant_profile(plant)


@router.put("/{slug}/plants/{asset_id}")
def update_plant(slug: str, asset_id: str, body: PlantBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    if not can_manage_org(user, org) or asset_id not in (org.plant_ids or []):
        raise HTTPException(403, "You cannot edit this plant.")
    row = db.get(Plant, asset_id)
    if row is None and user.role not in PLATFORM_ROLES:
        raise HTTPException(403, "Seeded plants can only be edited by platform admins.")
    base = data.cdmo()["plants"].get(asset_id)
    plant = _build_plant(asset_id, body, base)
    store.save_plant_asset(plant, data.redis_client())
    if row is None:
        db.add(Plant(asset_id=asset_id, org_id=org.id, created_by=user.id, payload=plant.model_dump(mode="json")))
    else:
        row.payload = plant.model_dump(mode="json")
    db.commit()
    data.invalidate()
    audit(db, "plant.updated", actor=user, target_type="plant", target_id=asset_id, detail={"org": org.slug}, request=request)
    return insights.plant_profile(plant)
