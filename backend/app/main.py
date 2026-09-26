"""NSQ platform API — one FastAPI app replacing engine, manufacturer-api and
the process-model API, plus auth, admin and jobs."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from . import data
from .config import settings
from .db import Base, SessionLocal, engine
from .models import JobRun, Plant, User, utcnow
from .routers import admin, auth, jobs as jobs_router, orgs, platform
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
    restore_user_plants()
    yield


app = FastAPI(title="NSQ Platform API", version="2.0.0", lifespan=lifespan,
              dependencies=[Depends(csrf_guard)], docs_url="/api/docs", openapi_url="/api/openapi.json")

if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["content-type", "x-nsq-client"])

for r in (auth.router, orgs.router, admin.router, jobs_router.router, platform.router):
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
