"""NSQ platform API — one FastAPI app replacing engine, manufacturer-api and
the process-model API, plus auth, admin and jobs."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import select, text

from . import data, scheduler
from .config import settings
from .db import Base, SessionLocal, engine
from .models import JobRun, Org, Plant, User, utcnow
from .routers import admin, auth, jobs as jobs_router, lab as lab_router, medicines as medicines_router, molecules, orgs, pipelines, platform, playground, plants as plants_router
from .security import csrf_guard, hash_password

log = logging.getLogger("nsq")


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        # Runs interrupted by a restart can never finish.
        for r in db.scalars(select(JobRun).where(JobRun.status.in_(("queued", "running")))):
            r.status, r.finished_at = "failed", utcnow()
            r.log = (r.log or "") + "\n[interrupted: server restarted]\n"
        email, pw = settings.superadmin_email, settings.superadmin_password
        if email and pw:
            u = db.scalar(select(User).where(User.email == email))
            if u is None:
                db.add(User(email=email, name="Super admin", role="super_admin", password_hash=hash_password(pw)))
                log.warning("seeded super admin %s", email)
            elif u.role != "super_admin" or not u.is_active:
                u.role, u.is_active = "super_admin", True
        db.commit()


def rename_retired_plants() -> None:
    """Move references off plant ids the seed has retired (renamed) and drop their Redis keys."""
    try:
        import json

        seed = json.loads((settings.data_dir / "plant_assets_seed.json").read_text())
    except Exception as exc:
        log.warning("could not read plant seed: %s", exc)
        return
    renames = {k: v for k, v in (seed.get("retired_ids") or {}).items() if not k.startswith("_")}
    if not renames:
        return
    assets = {a["asset_id"]: a for a in seed.get("assets", [])}
    with SessionLocal() as db:
        for org in db.scalars(select(Org)):
            ids = org.plant_ids or []
            if any(i in renames for i in ids):
                org.plant_ids = list(dict.fromkeys(renames.get(i, i) for i in ids))
        for old, new in renames.items():
            row = db.get(Plant, old)
            if row is not None:
                if db.get(Plant, new) is None:
                    db.add(Plant(asset_id=new, org_id=row.org_id, created_by=row.created_by, created_at=row.created_at,
                                 payload={**(row.payload or {}), "asset_id": new}))
                db.delete(row)
        db.commit()
        saved = {p.asset_id: p.payload for p in db.scalars(select(Plant).where(Plant.asset_id.in_(list(renames.values()))))}
    try:
        import intelligence_store as store
        from intelligence_models import PlantAsset

        r = data.redis_client()
        for old, new in renames.items():
            if r.delete(f"cdmo:plant:{old}"):
                log.warning("retired plant id %s -> %s", old, new)
            if not r.exists(f"cdmo:plant:{new}"):
                src = saved.get(new) or assets.get(new)
                if src:
                    store.save_plant_asset(PlantAsset(**src), r)
        data.invalidate()
    except Exception as exc:  # Redis down at boot must not stop the API
        log.warning("could not rename retired plants in Redis: %s", exc)


def restore_user_plants() -> None:
    """User plants live in Postgres too; put back any Redis lost (rebuild, flush)."""
    try:
        import intelligence_store as store
        from intelligence_models import PlantAsset

        r = data.redis_client()
        with SessionLocal() as db:
            for row in db.scalars(select(Plant)):
                if not r.exists(f"cdmo:plant:{row.asset_id}"):
                    store.save_plant_asset(PlantAsset(**row.payload), r)
    except Exception as exc:  # Redis down at boot must not stop the API
        log.warning("could not restore user plants: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    rename_retired_plants()
    restore_user_plants()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="NSQ Platform API", version="2.0.0", lifespan=lifespan,
              dependencies=[Depends(csrf_guard)], docs_url="/api/docs", openapi_url="/api/openapi.json")

class _GZipExceptStreams:
    """GZip every response except server-sent event streams: Starlette's GZipMiddleware (0.38) buffers a streaming
    response until its compressor flushes, so a job's live log would arrive only when the job ends."""

    def __init__(self, app, minimum_size: int = 2048):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").endswith("/stream"):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


app.add_middleware(_GZipExceptStreams, minimum_size=2048)

if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["content-type", "x-nsq-client"])

for r in (auth.router, orgs.router, admin.router, jobs_router.router, pipelines.router, molecules.router, playground.router, lab_router.router, medicines_router.router, plants_router.router, platform.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    out = {"status": "ok"}
    try:
        data.redis_client().ping()
        out["redis"] = "ok"
    except Exception:
        out["redis"], out["status"] = "down", "degraded"
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
        out["db"] = "ok"
    except Exception:
        out["db"], out["status"] = "down", "degraded"
    return out
