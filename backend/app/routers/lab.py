"""The lab: structure-based molecule profiles and process / product models."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import lab
from ..models import User
from ..security import current_user

from .. import features
from ..tenant import TenantRoute

router = APIRouter(route_class=TenantRoute, dependencies=[Depends(features.gate)], prefix="/api/lab", tags=["lab"])


def _run(fn, *args):
    try:
        return fn(*args)
    except KeyError:
        raise HTTPException(404, "No structure for this molecule yet.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/molecules")
def molecules(user: User = Depends(current_user)):
    return lab.molecules()


@router.get("/molecule/{key}")
def molecule(key: str, user: User = Depends(current_user)):
    p = lab.profile(key)
    if p is None:
        raise HTTPException(404, "No structure for this molecule yet.")
    return p


@router.get("/engines")
def engines(user: User = Depends(current_user)):
    return lab.engines()


@router.post("/molecule/{key}/dissolution")
def dissolution(key: str, body: dict[str, Any] = Body(default={}), user: User = Depends(current_user)):
    return _run(lab.dissolution, key, body)


@router.post("/molecule/{key}/crystallization")
def crystallization(key: str, body: dict[str, Any] = Body(default={}), user: User = Depends(current_user)):
    return _run(lab.crystallize, key, body)


@router.post("/compaction")
def compaction(body: dict[str, Any] = Body(default={}), user: User = Depends(current_user)):
    return _run(lab.compaction, body)


@router.post("/fluid-bed")
def fluid_bed(body: dict[str, Any] = Body(default={}), user: User = Depends(current_user)):
    return _run(lab.fluid_bed, body)


@router.post("/structure")
def structure(body: dict[str, Any] = Body(default={}), user: User = Depends(current_user)):
    """Render any SMILES with RDKit and return its descriptors."""
    from chem import molecule
    smiles = (body.get("smiles") or "").strip()
    mol = molecule.parse(smiles)
    if mol is None:
        raise HTTPException(422, "Not a valid SMILES.")
    return {"smiles": smiles, "svg": molecule.svg(mol, int(body.get("width", 260)), int(body.get("height", 180))),
            "descriptors": molecule.descriptors(mol)}


@router.post("/molecule/{key}/fetch-structure")
def fetch_structure(key: str, user: User = Depends(current_user)):
    """Fetch this molecule's structure from PubChem / ChEMBL now (no need to wait for the nightly job)."""
    return _run(lab.fetch_structure, key)


@router.post("/molecule/{key}/bioequivalence")
def bioequivalence(key: str, body: dict[str, Any] = Body(default={}), user: User = Depends(current_user)):
    return _run(lab.bioequivalence, key, body)


@router.get("/molecule/{key}/safety")
def safety(key: str, user: User = Depends(current_user)):
    return _run(lab.safety, key)


# --- reaction lab -----------------------------------------------------------------------------

@router.get("/reactions/templates")
def reaction_templates(user: User = Depends(current_user)):
    from .. import reactions
    return reactions.templates()


@router.get("/reactions/routes/{key}")
def reaction_routes(key: str, user: User = Depends(current_user)):
    from .. import reactions
    return reactions.routes(key)


@router.get("/reactions/molecules")
def reaction_molecules(user: User = Depends(current_user)):
    from .. import reactions
    return {"molecules": reactions.molecules_with_routes()}


@router.get("/reactions/solvent")
def reaction_solvent(name: str, user: User = Depends(current_user)):
    from .. import reactions
    got = reactions.solvent_props(name)
    if not got:
        raise HTTPException(404, "Solvent not recognised.")
    return got


@router.post("/reactions/run")
def reaction_run(body: dict[str, Any] = Body(default={}), user: User = Depends(current_user)):
    from .. import reactions
    try:
        return reactions.run(body)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc))


@router.get("/reactions/validation")
def reaction_validation(user: User = Depends(current_user)):
    from .. import reactions
    return reactions.validation()
