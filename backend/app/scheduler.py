"""Runs scheduled pipelines (Admin → Pipelines) inside the API process.

A daemon thread wakes every 30 s, and for each enabled schedule whose
next_run_at has passed starts the job (unless a run of it is already in
progress), then computes the next time. Times are wall-clock in SCHEDULE_TZ
(default Asia/Kolkata). A Postgres advisory lock makes sure only one API
process fires schedules even if more than one is started by mistake.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from . import jobs
from .db import SessionLocal, engine
from .models import PipelineSchedule, utcnow

log = logging.getLogger("nsq.scheduler")
TZ = ZoneInfo(os.environ.get("SCHEDULE_TZ", "Asia/Kolkata"))
ENABLED = os.environ.get("SCHEDULER", "on").lower() not in ("0", "off", "false", "no")
_LOCK_ID = 7_310_442
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def next_run(s: PipelineSchedule, after: Optional[datetime] = None) -> datetime:
    """Next fire time strictly after `after` (UTC), from the schedule's local wall-clock rule."""
    after = (after or utcnow()).astimezone(TZ)
    base = after.replace(hour=s.hour % 24, minute=s.minute % 60, second=0, microsecond=0)
    if s.frequency == "weekly":
        cand = base + timedelta(days=(s.weekday - base.weekday()) % 7)
        if cand <= after:
            cand += timedelta(days=7)
    elif s.frequency == "monthly":
        day = max(1, min(28, s.day or 1))
        cand = base.replace(day=day)
        if cand <= after:
            y, m = (cand.year + 1, 1) if cand.month == 12 else (cand.year, cand.month + 1)
            cand = cand.replace(year=y, month=m)
    else:
        cand = base if base > after else base + timedelta(days=1)
    return cand.astimezone(timezone.utc)


def ensure_defaults() -> None:
    with SessionLocal() as db:
        have = {s.job_key for s in db.scalars(select(PipelineSchedule))}
        for key, d in jobs.SCHEDULABLE.items():
            if key in have or key not in jobs.REGISTRY:
                continue
            s = PipelineSchedule(job_key=key, enabled=d.get("enabled", False), frequency=d.get("frequency", "daily"),
                                 hour=d.get("hour", 2), minute=d.get("minute", 0), weekday=d.get("weekday", 0),
                                 day=d.get("day", 1), params=d.get("params", {}), updated_by="default")
            s.next_run_at = next_run(s)
            db.add(s)
        db.commit()


def _default_params(job: jobs.Job, overrides: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for p in job.params:
        v = overrides.get(p.name, p.default)
        out[p.name] = bool(v) if p.kind == "bool" else str(v or "")
    return out


def tick(now: Optional[datetime] = None) -> list[str]:
    """Fire every due schedule once. Returns the job keys started."""
    now = now or utcnow()
    fired: list[str] = []
    with SessionLocal() as db:
        due = db.scalars(select(PipelineSchedule).where(PipelineSchedule.enabled.is_(True))).all()
        for s in due:
            if s.next_run_at is None:
                s.next_run_at = next_run(s, now)
                continue
            nra = s.next_run_at if s.next_run_at.tzinfo else s.next_run_at.replace(tzinfo=timezone.utc)
            if nra > now:
                continue
            job = jobs.REGISTRY.get(s.job_key)
            s.next_run_at = next_run(s, now)
            if job is None or (job.needs_upstash and not jobs.settings.upstash_url):
                continue
            if jobs.is_running(job.key):
                log.info("schedule %s skipped: already running", s.job_key)
                continue
            try:
                run = jobs.launch(job, _default_params(job, s.params or {}), None, "scheduler")
            except RuntimeError:
                continue
            s.last_fired_at, s.last_run_id = now, run.id
            fired.append(job.key)
            log.info("schedule fired %s (run %s)", job.key, run.id)
        db.commit()
    return fired


def _loop() -> None:
    conn = None
    held = False
    while not _stop.is_set():
        try:
            if engine.dialect.name == "postgresql":
                if conn is None:
                    conn, held = engine.connect(), False
                if held:
                    conn.execute(text("select 1"))  # keep the session (and its lock) alive
                else:
                    held = bool(conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": _LOCK_ID}).scalar())
                conn.commit()
                if held:
                    tick()
            else:
                tick()
        except Exception as exc:  # never let the thread die
            log.warning("scheduler tick failed: %s", exc)
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
        _stop.wait(30)


def start() -> None:
    global _thread
    if not ENABLED or (_thread and _thread.is_alive()):
        return
    try:
        ensure_defaults()
    except Exception as exc:
        log.warning("could not create default schedules: %s", exc)
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="scheduler")
    _thread.start()


def stop() -> None:
    _stop.set()


def describe(s: PipelineSchedule) -> dict[str, Any]:
    return {
        "job_key": s.job_key, "enabled": s.enabled, "frequency": s.frequency, "hour": s.hour, "minute": s.minute,
        "weekday": s.weekday, "day": s.day, "params": s.params or {},
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_fired_at": s.last_fired_at.isoformat() if s.last_fired_at else None,
        "last_run_id": s.last_run_id, "updated_by": s.updated_by, "tz": str(TZ),
    }
