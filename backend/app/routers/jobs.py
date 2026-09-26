"""Admin → Jobs: list the registry, start runs, stream logs, upload CSVs."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import jobs
from ..audit import audit
from ..db import SessionLocal, get_db
from ..models import JobRun, User
from ..security import require_platform

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class RunBody(BaseModel):
    params: dict[str, Any] = {}
    confirm: str = ""


def _run_row(r: JobRun, with_log: bool = False) -> dict[str, Any]:
    d = {
        "id": r.id, "job_key": r.job_key, "params": r.params, "status": r.status, "by": r.started_by_email,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "exit_code": r.exit_code,
    }
    if with_log:
        d["log"] = jobs.live_log(r.id) if r.status in ("queued", "running") and jobs.live_log(r.id) is not None else r.log
    return d


@router.get("")
def list_jobs(user: User = Depends(require_platform), db: Session = Depends(get_db)):
    out = []
    for j in jobs.REGISTRY.values():
        d = jobs.describe(j)
        d["allowed"] = user.role == "super_admin" or j.role == "admin"
        last = db.scalars(select(JobRun).where(JobRun.job_key == j.key).order_by(JobRun.created_at.desc()).limit(1)).first()
        d["last_run"] = _run_row(last) if last else None
        d["running"] = jobs.is_running(j.key)
        out.append(d)
    return {"jobs": out, "is_super": user.role == "super_admin"}


@router.post("/{key}/run")
def run_job(key: str, body: RunBody, request: Request, user: User = Depends(require_platform), db: Session = Depends(get_db)):
    job = jobs.REGISTRY.get(key)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    if job.role == "super_admin" and user.role != "super_admin":
        raise HTTPException(403, "Only a super admin can run this job.")
    if job.needs_upstash and not jobs.settings.upstash_url:
        raise HTTPException(400, "UPSTASH_URL is not configured on the server.")
    allowed = {p.name: p for p in job.params}
    params: dict[str, Any] = {}
    for name, p in allowed.items():
        v = body.params.get(name, p.default)
        params[name] = bool(v) if p.kind == "bool" else str(v or "")
    if job.destructive(params):
        if user.role != "super_admin":
            raise HTTPException(403, "Only a super admin can run this job in destructive mode.")
        if body.confirm != job.key:
            raise HTTPException(400, f"Type {job.key!r} to confirm this destructive job.")
    for pname in ("csv", "file"):
        if params.get(pname):
            try:
                if not jobs.upload_path(params[pname]).exists():
                    raise HTTPException(400, "That upload does not exist.")
            except ValueError as exc:
                raise HTTPException(400, str(exc))
    if jobs.is_running(key):
        raise HTTPException(409, "This job is already running.")
    run = JobRun(job_key=key, params=params, status="queued", started_by=user.id, started_by_email=user.email)
    db.add(run)
    db.commit()
    db.refresh(run)
    audit(db, "job.started", actor=user, target_type="job", target_id=f"{key}#{run.id}", detail=params, request=request)
    try:
        jobs.start(job, params, run)
    except RuntimeError:
        run.status = "failed"
        run.log = "Another run of this job is in progress."
        db.commit()
        raise HTTPException(409, "This job is already running.")
    return {"run": _run_row(run)}


@router.get("/runs")
def list_runs(page: int = Query(1, ge=1), size: int = Query(25, le=100), key: str = "",
              user: User = Depends(require_platform), db: Session = Depends(get_db)):
    stmt = select(JobRun)
    if key:
        stmt = stmt.where(JobRun.job_key == key)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(JobRun.created_at.desc()).offset((page - 1) * size).limit(size))
    return {"total": total, "items": [_run_row(r) for r in rows]}


@router.get("/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(require_platform), db: Session = Depends(get_db)):
    r = db.get(JobRun, run_id)
    if r is None:
        raise HTTPException(404, "Run not found.")
    return {"run": _run_row(r, with_log=True)}


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int, request: Request, user: User = Depends(require_platform)):
    """Server-sent events: `log` chunks as they arrive, then one `done`."""

    async def gen():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            with SessionLocal() as db:
                r = db.get(JobRun, run_id)
                status = r.status if r else "missing"
                stored = r.log if r else ""
            text = jobs.live_log(run_id)
            if text is None:
                text = stored
            if len(text) > sent:
                yield f"event: log\ndata: {json.dumps(text[sent:])}\n\n"
                sent = len(text)
            if status in ("succeeded", "partial", "failed", "missing"):
                yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
                return
            await asyncio.sleep(0.7)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- CSV uploads for the monthly refresh ---------------------------------------------

@router.get("/uploads")
def list_uploads(user: User = Depends(require_platform)):
    jobs.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted((p for p in jobs.UPLOAD_DIR.iterdir() if p.is_file() and p.suffix.lower() in jobs.UPLOAD_TYPES),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return {"uploads": [
        {"name": p.name, "bytes": p.stat().st_size,
         "modified_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()} for p in files
    ], "default_csv": jobs.DEFAULT_CSV.name if jobs.DEFAULT_CSV.exists() else None}


@router.post("/uploads")
async def upload_csv(request: Request, file: UploadFile = File(...), user: User = Depends(require_platform), db: Session = Depends(get_db)):
    if user.role != "super_admin":
        raise HTTPException(403, "Only a super admin can upload data files.")
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", file.filename or "upload.csv").strip() or "upload.csv"
    if not any(name.lower().endswith(ext) for ext in jobs.UPLOAD_TYPES):
        raise HTTPException(400, f"Upload one of: {', '.join(sorted(jobs.UPLOAD_TYPES))}.")
    jobs.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = jobs.UPLOAD_DIR / name
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > 300 * (1 << 20):
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "File larger than 300 MB.")
            fh.write(chunk)
    audit(db, "data.csv_uploaded", actor=user, target_type="file", target_id=name, detail={"bytes": size}, request=request)
    return {"name": name, "bytes": size}
