"""Add / edit a tracked molecule.

The form starts from what the curated seed and the public sources already
say (the "baseline"), and stores only the fields someone types. When the
universe is rebuilt, typed values win and the baseline value is kept next
to them in provenance (`source_value`), so a disagreement stays visible.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import data, jobs
from ..audit import audit
from ..config import settings
from ..db import get_db
from ..models import MoleculeEntry, User
from ..security import require_platform, require_super

if str(settings.loader_dir) not in sys.path:
    sys.path.insert(0, str(settings.loader_dir))

import ingredients as ing  # noqa: E402  (core/)
import molecule_fields as mf  # noqa: E402  (core/)

router = APIRouter(prefix="/api/molecules", tags=["molecules"])

_lock = threading.Lock()
_nsq_cache: dict[str, Any] = {"at": 0.0, "stats": None}


def _bu():
    import build_universe  # redis-loader/

    return build_universe


def _nsq_stats() -> dict[str, Any]:
    with _lock:
        if _nsq_cache["stats"] is None or time.time() - _nsq_cache["at"] > 600:
            try:
                _nsq_cache["stats"] = _bu().nsq_stats(settings.redis_url)
            except Exception:
                _nsq_cache["stats"] = {}
            _nsq_cache["at"] = time.time()
        return _nsq_cache["stats"]


def _seed(name: str, list_key: str) -> dict[str, dict[str, Any]]:
    return {m["molecule_key"]: m for m in _bu().load_seed(name, list_key)}


def key_for(name: str) -> str:
    """An existing molecule's key when the name (or a known spelling) matches one,
    else a new key from the US name."""
    k = ing.ingredient_key(name)
    if k:
        loaded = data.cdmo()["patents"]
        hit = ing.match_tracked(k, ing.tracked_index(loaded)) or ing.match_tracked(ing.us_name(k), ing.tracked_index(loaded))
        if hit:
            return hit

        class _P:
            def __init__(self, api):
                self.api_name = api

        seeds = {mk: _P(m.get("api_name", "")) for mk, m in _seed("patent_seed", "molecules").items()}
        hit = ing.match_tracked(k, ing.tracked_index(seeds))
        if hit:
            return hit
    return ing.molecule_key_for(ing.us_name(k)) or ing.molecule_key_for(name)


def _jsonable(v: Any) -> Any:
    import json

    return json.loads(json.dumps(v, default=str))


def baseline(key: str, name: str) -> dict[str, Any]:
    """What the seed + sources + NSQ give for this molecule, before typed values."""
    bu = _bu()
    cur_p = _seed("patent_seed", "molecules").get(key)
    cur_r = _seed("regulatory_seed", "passports").get(key)
    cur_d = _seed("demand_seed", "profiles").get(key)
    loaded = data.cdmo()["patents"].get(key)
    names = [n for n in dict.fromkeys([name, ing.us_name(ing.ingredient_key(name)), *(loaded.aliases if loaded else [])]) if n]
    if cur_p:
        names = [cur_p.get("api_name", ""), *names]
    stats = _nsq_stats()
    nsq = bu.find_nsq(stats, names)
    origin = "curated" if cur_p else "manual"
    res = bu.build_molecule(key, names, origin, bu.Sources(), nsq, cur_p, cur_r, cur_d)
    p, r, d, row = res
    values, prov = {}, {}
    for f in mf.FIELDS:
        values[f["key"]] = _jsonable(mf.current_value(f["key"], p, r, d))
        rec = {"patent": p, "signals": p, "regulatory": r, "demand": d}[f["record"]]
        pv = (rec.get("provenance") or {}).get(f.get("prov") or f["key"])
        if pv:
            prov[f["key"]] = pv
        elif cur_p and values[f["key"]] not in (None, "", [], 0):
            prov[f["key"]] = {"status": "estimate", "source": "Curated seed"}
    return {
        "key": key, "values": values, "provenance": _jsonable(prov), "sources": row["sources"],
        "confirmed": bool(set(row["sources"]) & {"orange_book", "ema", "purple_book"}),
        "nsq": {"alerts": row["alerts"], "manufacturers": row["manufacturers"]},
        "curated": bool(cur_p), "tracked": loaded is not None,
        "origin": (loaded.origin if loaded else None),
    }


@router.get("/schema")
def schema(user: User = Depends(require_platform)):
    return mf.schema()


@router.get("/lookup")
def lookup(name: str = "", key: str = "", user: User = Depends(require_platform), db: Session = Depends(get_db)):
    """Pre-fill for the form: the baseline plus any values already typed."""
    name = (name or "").strip()
    if not name and not key:
        raise HTTPException(400, "Give a molecule name.")
    key = key or key_for(name)
    if not key:
        raise HTTPException(400, "That name has no usable ingredient in it.")
    loaded = data.cdmo()["patents"].get(key)
    if not name:
        name = loaded.api_name if loaded else key.replace("_", " ")
    base = baseline(key, name)
    entry = db.get(MoleculeEntry, key)
    return {**base, "name": name,
            "entered": (entry.values or {}) if entry else {},
            "entry": {"added": entry.added, "updated_by": entry.updated_by or entry.created_by,
                      "updated_at": entry.updated_at.isoformat() if entry.updated_at else None} if entry else None}


class SaveBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    key: str = ""
    # field -> typed value; null removes the typed value (back to the source/seed value)
    values: dict[str, Any] = {}
    rebuild: bool = True


def _rebuild(user: User) -> Optional[int]:
    job = jobs.REGISTRY["build-universe"]
    if jobs.is_running(job.key):
        return None
    try:
        run = jobs.launch(job, {"min_alerts": ""}, user.id, user.email)
    except RuntimeError:
        return None
    return run.id


@router.post("")
def save(body: SaveBody, request: Request, user: User = Depends(require_super), db: Session = Depends(get_db)):
    key = body.key or key_for(body.name)
    if not key:
        raise HTTPException(400, "That name has no usable ingredient in it.")
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}
    for k, v in body.values.items():
        if k not in mf.BY_KEY:
            errors[k] = "unknown field"
            continue
        try:
            cleaned[k] = mf.clean(k, v)
        except mf.FieldError as exc:
            errors[k] = str(exc)
    if errors:
        raise HTTPException(422, "; ".join(f"{mf.BY_KEY.get(k, {}).get('label', k)}: {m}" for k, m in errors.items()))

    entry = db.get(MoleculeEntry, key)
    in_universe = key in data.cdmo()["patents"] or key in _seed("patent_seed", "molecules")
    if entry is None:
        entry = MoleculeEntry(key=key, name=body.name.strip(), added=not in_universe, values={}, created_by=user.email)
        db.add(entry)
    values = dict(entry.values or {})
    for k, v in cleaned.items():
        if v is None or v == "" or v == []:
            values.pop(k, None)
        else:
            values[k] = v
    if entry.added:
        values.setdefault("api_name", body.name.strip())
    entry.values, entry.name, entry.updated_by = values, body.name.strip(), user.email
    removed = False
    if not values and not entry.added:
        db.delete(entry)
        removed = True
    db.commit()
    audit(db, "molecule.saved", actor=user, target_type="molecule", target_id=key,
          detail={"fields": sorted(cleaned), "added": entry.added if not removed else False}, request=request)
    run_id = _rebuild(user) if body.rebuild else None
    return {"key": key, "added": (not removed) and entry.added, "values": values, "run_id": run_id,
            "message": "Saved. Rebuilding the molecule universe…" if run_id else "Saved. It applies on the next universe build."}


@router.delete("/{key}")
def remove(key: str, request: Request, user: User = Depends(require_super), db: Session = Depends(get_db)):
    """Drop every typed value. A molecule that was added in the app stops being tracked."""
    entry = db.get(MoleculeEntry, key)
    if entry is None:
        raise HTTPException(404, "Nothing was entered for this molecule.")
    added = entry.added
    db.delete(entry)
    db.commit()
    audit(db, "molecule.removed", actor=user, target_type="molecule", target_id=key, detail={"added": added}, request=request)
    return {"key": key, "untracked": added, "run_id": _rebuild(user)}
