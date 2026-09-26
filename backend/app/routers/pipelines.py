"""Admin → Pipelines: public sources, schedules, the molecule universe,
the watchlist, and the site directory."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import data, insights, jobs, scheduler, sites
from ..audit import audit
from ..config import settings
from ..db import get_db
from ..models import JobRun, PipelineSchedule, User, WatchMolecule
from ..security import require_platform, require_super

if str(settings.loader_dir) not in sys.path:
    sys.path.insert(0, str(settings.loader_dir))

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])

SOURCE_JOBS = {
    "cdsco": "fetch-nsq", "orange_book": "src-orange-book", "purple_book": "src-purple-book", "ema": "src-ema",
    "clinical_trials": "src-clinical-trials", "fda_establishments": "src-fda-establishments",
    "fda_import_alerts": "src-fda-import-alerts", "fda_recalls": "src-fda-recalls",
}


def _read_json(path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _universe() -> dict[str, Any]:
    return _read_json(settings.data_dir / "generated" / "molecule_universe.json") or {"molecules": [], "skipped": [], "counts": {}}


def _age_days(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 1)


def _last_runs(db: Session, keys: list[str]) -> dict[str, dict[str, Any]]:
    out = {}
    for k in keys:
        r = db.scalars(select(JobRun).where(JobRun.job_key == k).order_by(JobRun.created_at.desc()).limit(1)).first()
        if r:
            out[k] = {"id": r.id, "status": r.status, "created_at": r.created_at.isoformat() if r.created_at else None,
                      "finished_at": r.finished_at.isoformat() if r.finished_at else None, "by": r.started_by_email}
    return out


@router.get("")
def overview(user: User = Depends(require_platform), db: Session = Depends(get_db)):
    from sources import public_meta
    from sources.common import read_manifest

    meta = public_meta()
    manifest = read_manifest()
    sched = {s.job_key: scheduler.describe(s) for s in db.scalars(select(PipelineSchedule))}
    keys = list(set(SOURCE_JOBS.values()) | set(sched) | {"sync-sources", "build-universe"})
    runs = _last_runs(db, keys)
    srcs = []
    for key, m in meta.items():
        man = manifest.get(key, {})
        job = SOURCE_JOBS.get(key)
        srcs.append({
            "key": key, **{k: m.get(k) for k in ("title", "publisher", "url", "page", "cadence", "feeds", "group")},
            "status": man.get("status") or "never", "records": man.get("records"), "last_success": man.get("last_success"),
            "last_attempt": man.get("last_attempt"), "error": man.get("error") or "", "age_days": _age_days(man.get("last_success")),
            "job": job, "schedule": sched.get(job) if job else None, "last_run": runs.get(job) if job else None,
            "running": bool(job and jobs.is_running(job)),
        })
    u = _universe()
    try:
        site_summary = sites.summary()
    except Exception as exc:  # frame not loaded yet
        site_summary = {"error": str(exc)}
    pipelines = []
    for k in ("fetch-nsq", "sync-sources", "build-universe"):
        j = jobs.REGISTRY[k]
        pipelines.append({"key": k, "title": j.title, "description": j.description, "role": j.role,
                          "schedule": sched.get(k), "last_run": runs.get(k), "running": bool(jobs.is_running(k)),
                          "params": [p.__dict__ for p in j.params]})
    return {
        "sources": srcs,
        "pipelines": pipelines,
        "schedules": sorted(sched.values(), key=lambda s: s["job_key"]),
        "schedulable": {k: jobs.REGISTRY[k].title for k in jobs.SCHEDULABLE if k in jobs.REGISTRY},
        "universe": {"built_at": u.get("built_at"), "counts": u.get("counts", {}), "sources": u.get("sources", {})},
        "sites": site_summary,
        "scheduler": {"enabled": scheduler.ENABLED, "tz": str(scheduler.TZ)},
        "is_super": user.role == "super_admin",
    }


class ScheduleBody(BaseModel):
    enabled: bool
    frequency: str = Field(pattern="^(daily|weekly|monthly)$")
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    weekday: int = Field(0, ge=0, le=6)
    day: int = Field(1, ge=1, le=28)
    params: dict[str, Any] = {}


@router.put("/schedules/{job_key}")
def set_schedule(job_key: str, body: ScheduleBody, request: Request, user: User = Depends(require_platform), db: Session = Depends(get_db)):
    job = jobs.REGISTRY.get(job_key)
    if job is None or job_key not in jobs.SCHEDULABLE:
        raise HTTPException(404, "This job cannot be scheduled.")
    params = {p.name: (bool(body.params.get(p.name, p.default)) if p.kind == "bool" else str(body.params.get(p.name, p.default) or ""))
              for p in job.params}
    if (job.role == "super_admin" or job.destructive(params)) and user.role != "super_admin":
        raise HTTPException(403, "Only a super admin can schedule this job.")
    s = db.get(PipelineSchedule, job_key) or PipelineSchedule(job_key=job_key)
    s.enabled, s.frequency, s.hour, s.minute, s.weekday, s.day = body.enabled, body.frequency, body.hour, body.minute, body.weekday, body.day
    s.params, s.updated_by = params, user.email
    s.next_run_at = scheduler.next_run(s)
    db.add(s)
    db.commit()
    audit(db, "schedule.updated", actor=user, target_type="job", target_id=job_key, detail=scheduler.describe(s), request=request)
    return scheduler.describe(s)


# --- molecule universe ----------------------------------------------------------------

@router.get("/molecules")
def molecules(q: str = "", origin: str = "", source: str = "", sort: str = "alerts", page: int = Query(1, ge=1),
              size: int = Query(25, le=100), user: User = Depends(require_platform)):
    u = _universe()
    rows = u.get("molecules", [])
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["key"] or ql in (r.get("name") or "").lower() or ql in (r.get("brand") or "").lower()]
    if origin:
        rows = [r for r in rows if r["origin"] == origin]
    if source:
        rows = [r for r in rows if source in r.get("sources", [])]
    keyf = {"alerts": lambda r: -r.get("alerts", 0), "loe": lambda r: r.get("loe_us") or "9999", "anda": lambda r: -(r.get("anda") or 0),
            "trials": lambda r: -(r.get("trials") or 0), "name": lambda r: r.get("name", "").lower()}.get(sort, lambda r: -r.get("alerts", 0))
    rows = sorted(rows, key=keyf)
    total = len(rows)
    pages = max(1, (total + size - 1) // size)
    page = min(page, pages)
    by_source: dict[str, int] = {}
    for r in u.get("molecules", []):
        for s in r.get("sources", []):
            by_source[s] = by_source.get(s, 0) + 1
    return {"items": rows[(page - 1) * size: page * size], "total": total, "page": page, "pages": pages,
            "counts": u.get("counts", {}), "by_source": by_source, "built_at": u.get("built_at"),
            "skipped": u.get("skipped", [])[:60]}


@router.get("/molecules/{key}")
def molecule(key: str, user: User = Depends(require_platform)):
    m = data.cdmo()
    p = m["patents"].get(key)
    if p is None:
        raise HTTPException(404, "Molecule not loaded — rebuild the universe.")
    reg = m["regulatory"].get(key)
    dem = m["demand"].get(key)
    return insights.json_safe({
        "patent": p.model_dump(mode="json"),
        "regulatory": reg.model_dump(mode="json") if reg else None,
        "demand": dem.model_dump(mode="json") if dem else None,
    })


class WatchBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    exclude: bool = False
    note: str = ""


@router.get("/watchlist")
def watchlist(user: User = Depends(require_platform), db: Session = Depends(get_db)):
    return {"items": [{"id": w.id, "name": w.name, "key": w.key, "exclude": w.exclude, "note": w.note, "added_by": w.added_by,
                       "created_at": w.created_at.isoformat() if w.created_at else None}
                      for w in db.scalars(select(WatchMolecule).order_by(WatchMolecule.created_at.desc()))]}


@router.post("/watchlist")
def add_watch(body: WatchBody, request: Request, user: User = Depends(require_super), db: Session = Depends(get_db)):
    import ingredients as ing

    name = re.sub(r"\s+", " ", body.name).strip()
    key = ing.molecule_key_for(ing.us_name(ing.ingredient_key(name))) or ing.molecule_key_for(name)
    if not key:
        raise HTTPException(400, "That name has no usable ingredient in it.")
    w = WatchMolecule(name=name, key=key, exclude=body.exclude, note=body.note, added_by=user.email)
    db.add(w)
    db.commit()
    audit(db, "watchlist.added", actor=user, target_type="molecule", target_id=key, detail={"exclude": body.exclude}, request=request)
    return {"id": w.id, "name": w.name, "key": w.key, "exclude": w.exclude,
            "hint": "Run 'Rebuild molecule universe' (or wait for the nightly sync) to apply."}


@router.delete("/watchlist/{wid}")
def del_watch(wid: int, request: Request, user: User = Depends(require_super), db: Session = Depends(get_db)):
    w = db.get(WatchMolecule, wid)
    if w is None:
        raise HTTPException(404, "Not found.")
    db.delete(w)
    db.commit()
    audit(db, "watchlist.removed", actor=user, target_type="molecule", target_id=w.key, request=request)
    return {"ok": True}


# --- site directory ------------------------------------------------------------------------

@router.get("/sites")
def site_list(q: str = "", state: str = "", fda: str = "", form: str = "", page: int = Query(1, ge=1),
              size: int = Query(25, le=100), user: User = Depends(require_platform)):
    return sites.search(q=q, state=state, fda=fda, form=form, page=page, size=size)


@router.get("/sites/summary")
def site_summary(user: User = Depends(require_platform)):
    return sites.summary()


@router.get("/sites/{site_id}")
def site_detail(site_id: str, user: User = Depends(require_platform), db: Session = Depends(get_db)):
    s = sites.get(site_id)
    if s is None:
        raise HTTPException(404, "Site not found.")
    from ..models import Org

    plants = data.cdmo()["plants"]
    orgs = [{"slug": o.slug, "name": o.name,
             "linked": any(pid in plants and (plants[pid].reference or {}).get("site_id") == site_id for pid in (o.plant_ids or []))}
            for o in db.scalars(select(Org)) if s["ontology_key"] in (o.ontology_keys or [])]
    return {**s, "orgs": orgs}
