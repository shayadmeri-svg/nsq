"""Medicines added in the Playground: open-database lookup, composition, gaps."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import medicines as med
from ..audit import audit
from ..db import get_db
from ..models import Medicine, User
from ..security import current_user, require_super

from .. import features
from ..tenant import TenantRoute

router = APIRouter(route_class=TenantRoute, dependencies=[Depends(features.gate)], prefix="/api/medicines", tags=["medicines"])


class MedicineBody(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    brand: str = ""
    dosage_form: str = ""
    route: str = ""
    ingredients: list[dict[str, Any]] = []
    excipients: list[str] = []
    identifiers: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    notes: str = ""
    track: bool = True  # add actives that aren't in the molecule universe yet


@router.get("")
def list_medicines(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Medicine).order_by(Medicine.updated_at.desc())).all()
    return {"items": [med.to_dict(m) for m in rows]}


@router.get("/parse")
def parse(text: str, user: User = Depends(current_user)):
    return med.parse_composition(text)


@router.get("/lookup")
def lookup(text: str, user: User = Depends(current_user)):
    if len(text.strip()) < 3:
        raise HTTPException(400, "Type a medicine name, e.g. 'Telmisartan 40 mg Tablets'.")
    return med.lookup(text.strip())


@router.post("/ingredient")
def ingredient(body: dict[str, Any], user: User = Depends(current_user)):
    """Re-fetch chemistry for one ingredient (after the user edits its name)."""
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Give an ingredient name.")
    return med.enrich_ingredient({"name": name, "strength": body.get("strength"), "role": body.get("role", "active"), "source": "typed"})


def _clean(body: MedicineBody) -> dict[str, Any]:
    keep = ("name", "strength", "role", "source", "molecule_key", "smiles", "structure_source", "cid", "chembl_id", "mp_c", "xlogp",
            "logp_predicted", "pka_acid", "pka_base", "max_phase", "first_approval", "atc", "mechanisms", "molecule_type", "links",
            "us_strengths", "solubility_mg_ml")
    ings = []
    for a in body.ingredients:
        if not (a.get("name") or "").strip():
            continue
        x = {k: a.get(k) for k in keep if a.get(k) not in (None, "", [])}
        x["name"] = a["name"].strip()
        x.setdefault("role", "active")
        # Same key the molecule universe uses (salt forms, INN/USAN spellings resolved)
        from .molecules import key_for
        x["molecule_key"] = key_for(x["name"]) or x.get("molecule_key") or ""
        ings.append(x)
    if not any(a["role"] == "active" for a in ings):
        raise HTTPException(422, "Add at least one active ingredient.")
    return {"name": body.name.strip(), "brand": body.brand.strip(), "dosage_form": body.dosage_form.strip(), "route": body.route.strip(),
            "ingredients": ings, "excipients": [e.strip() for e in body.excipients if e.strip()][:60],
            "identifiers": body.identifiers, "sources": body.sources, "notes": body.notes[:4000]}


def _track(body: MedicineBody, clean: dict[str, Any], user: User, db: Session) -> dict[str, Any]:
    """Put every active ingredient into the molecule universe, like the Add molecule form does."""
    from .. import data
    from ..models import MoleculeEntry
    from .molecules import _rebuild, _seed
    if not body.track:
        return {"tracked": [], "run_id": None}
    universe = set(data.cdmo()["patents"]) | set(_seed("patent_seed", "molecules"))
    added = []
    for a in clean["ingredients"]:
        k = a.get("molecule_key")
        if a.get("role") != "active" or not k or k in universe or db.get(MoleculeEntry, k):
            continue
        values = {"api_name": a["name"]}
        if clean["dosage_form"]:
            values["dosage_form"] = clean["dosage_form"]
        s = a.get("strength") or {}
        if s.get("value"):
            values["strength"] = f"{s['value']:g} {s.get('unit') or 'mg'}" + (f"/{s['per']}" if s.get("per") else "")
        db.add(MoleculeEntry(key=k, name=a["name"], added=True, values=values, created_by=user.email, updated_by=user.email))
        added.append(k)
    db.commit()
    return {"tracked": added, "run_id": _rebuild(user) if added else None}


@router.post("")
def create(body: MedicineBody, request: Request, user: User = Depends(require_super), db: Session = Depends(get_db)):
    clean = _clean(body)
    m = Medicine(**clean, created_by=user.email, updated_by=user.email)
    db.add(m)
    audit(db, "medicine.added", actor=user, target_type="medicine", target_id=body.name, request=request)
    db.commit()
    db.refresh(m)
    med.VERSION["n"] += 1
    return {**med.to_dict(m), **_track(body, clean, user, db)}


@router.put("/{mid}")
def update(mid: int, body: MedicineBody, request: Request, user: User = Depends(require_super), db: Session = Depends(get_db)):
    m = db.get(Medicine, mid)
    if m is None:
        raise HTTPException(404, "Medicine not found.")
    clean = _clean(body)
    for k, v in clean.items():
        setattr(m, k, v)
    m.updated_by = user.email
    audit(db, "medicine.updated", actor=user, target_type="medicine", target_id=str(mid), request=request)
    db.commit()
    db.refresh(m)
    med.VERSION["n"] += 1
    return {**med.to_dict(m), **_track(body, clean, user, db)}


@router.delete("/{mid}")
def delete(mid: int, request: Request, user: User = Depends(require_super), db: Session = Depends(get_db)):
    m = db.get(Medicine, mid)
    if m is None:
        raise HTTPException(404, "Medicine not found.")
    db.delete(m)
    audit(db, "medicine.deleted", actor=user, target_type="medicine", target_id=str(mid), request=request)
    db.commit()
    med.VERSION["n"] += 1
    return {"ok": True}


@router.get("/{mid}/nsq")
def nsq(mid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Medicine, mid)
    if m is None:
        raise HTTPException(404, "Medicine not found.")
    return med.nsq_for([a.get("molecule_key") or a["name"].lower() for a in m.ingredients if a.get("role") == "active"])
