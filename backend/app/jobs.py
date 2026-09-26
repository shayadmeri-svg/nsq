"""Admin job runner: a fixed registry of data operations (the justfile's
data recipes), run as subprocesses with logs persisted to Postgres.

Nothing outside REGISTRY can run — there is no free-text command path.
Each job declares the role it needs and whether it is destructive; the API
enforces both and requires a typed confirmation for destructive runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import select

from . import data
from .config import settings
from .db import SessionLocal
from .models import JobRun, Plant, utcnow

PY = sys.executable
UPLOAD_DIR = settings.data_dir / "uploads"
DEFAULT_CSV = settings.data_dir / "CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv"


@dataclass
class Param:
    name: str
    label: str
    kind: str = "bool"  # bool | csv
    default: Any = False
    help: str = ""


@dataclass
class Job:
    key: str
    title: str
    description: str
    group: str
    steps: Callable[[dict[str, Any]], list[tuple[str, list[str], dict[str, str]]]]
    role: str = "admin"  # admin | super_admin
    destructive: Callable[[dict[str, Any]], bool] = lambda p: False
    needs_upstash: bool = False
    params: list[Param] = field(default_factory=list)
    invalidates: bool = True
    after: Optional[Callable[[], str]] = None


def _local() -> str:
    return settings.redis_url


def _upstash() -> str:
    return settings.upstash_url


def _csv_path(p: dict[str, Any]) -> Path:
    name = (p.get("csv") or "").strip()
    if not name:
        return DEFAULT_CSV
    path = (UPLOAD_DIR / Path(name).name).resolve()
    if UPLOAD_DIR.resolve() not in path.parents:
        raise ValueError("Invalid CSV name.")
    return path


def sync_plants_to_redis() -> str:
    """Re-publish every user-created plant from Postgres into Redis."""
    import intelligence_store as store
    from intelligence_models import PlantAsset

    n = 0
    with SessionLocal() as db:
        for row in db.scalars(select(Plant)):
            try:
                store.save_plant_asset(PlantAsset(**row.payload), data.redis_client())
                n += 1
            except Exception as exc:  # keep going; report
                return f"plant {row.asset_id} failed: {exc}"
    return f"re-published {n} user-created plant(s) from Postgres"


def _refresh_steps(p: dict[str, Any]):
    csv = str(_csv_path(p))
    target = _upstash() or _local()
    steps = [
        ("Load CSV into " + ("Upstash" if _upstash() else "local Redis") + " (flush + ontology augment)",
         [PY, "load_csv_redis.py", "--input", csv, "--redis-url", target, "--flush", "--augment", "1"], {}),
        ("Build product ontology", [PY, "build_product_ontology.py", "--input", csv, "--redis-url", target], {}),
        ("Pre-compute enriched frame", [PY, "build_enriched_frame.py", "--redis-url", target], {}),
    ]
    if _upstash():
        steps.append(("Copy Upstash → local Redis", [PY, "pull_upstash.py", "--source", _upstash(), "--target", _local()], {}))
    steps.append(("Verify", [PY, "verify_nsq_redis.py"], {"REDIS_URL": _local()}))
    return steps


def _seed_steps(p: dict[str, Any]):
    steps = []
    for fam, f in (("patents", "patent_seed"), ("regulatory", "regulatory_seed"), ("demand", "demand_seed")):
        steps.append((f"Load {fam} seed", [PY, f"load_{fam}.py", "--input", str(settings.data_dir / f"{f}.json"), "--redis-url", _local(), "--flush"], {}))
    # Never --flush plants: that would delete user-created plant profiles.
    steps.append(("Load plant seed (upsert)", [PY, "load_plant_assets.py", "--input", str(settings.data_dir / "plant_assets_seed.json"), "--redis-url", _local()], {}))
    return steps


REGISTRY: dict[str, Job] = {j.key: j for j in [
    Job("ping", "Check Redis", "Ping the in-server Redis and report the key count.", "Health",
        lambda p: [("Ping", [PY, "ping_redis.py"], {"REDIS_URL": _local()})], invalidates=False),
    Job("verify", "Verify NSQ data", "Count loaded NSQ records and print a sample.", "Health",
        lambda p: [("Verify", [PY, "verify_nsq_redis.py"], {"REDIS_URL": _local()})], invalidates=False),
    Job("pull-upstash", "Pull from Upstash", "Copy the NSQ dataset and CDMO seeds from Upstash into the in-server Redis.",
        "Sync", lambda p: [("Pull", [PY, "pull_upstash.py", "--source", _upstash(), "--target", _local()] + (["--dry-run"] if p.get("dry_run") else []), {})],
        destructive=lambda p: not p.get("dry_run"), needs_upstash=True,
        params=[Param("dry_run", "Dry run (show what would change)", default=True)]),
    Job("backup-to-upstash", "Back up to Upstash", "Copy the in-server Redis (NSQ data + CDMO incl. user plants) up to Upstash.",
        "Sync", lambda p: [("Push", [PY, "pull_upstash.py", "--source", _local(), "--target", _upstash()] + (["--dry-run"] if p.get("dry_run") else []), {})],
        destructive=lambda p: not p.get("dry_run"), needs_upstash=True, invalidates=False,
        params=[Param("dry_run", "Dry run (show what would change)", default=True)]),
    Job("restore-snapshot", "Restore from snapshot", "Load the bundled snapshot file into the in-server Redis (use when Upstash is unavailable).",
        "Sync", lambda p: [("Restore", [PY, "restore_snapshot.py", "--input", str(settings.snapshot_path), "--redis-url", _local()] + (["--flush"] if p.get("flush") else []), {}),
                           ("Pre-compute enriched frame", [PY, "build_enriched_frame.py", "--redis-url", _local()], {})],
        destructive=lambda p: bool(p.get("flush")),
        params=[Param("flush", "Delete existing nsq:* / geo:* keys first", default=False)]),
    Job("build-frame", "Rebuild enriched frame", "Recompute the precomputed dashboard frame from the records in Redis.",
        "Data", lambda p: [("Build", [PY, "build_enriched_frame.py", "--redis-url", _local()], {})]),
    Job("snapshot", "Write snapshot", "Dump the in-server Redis to the snapshot file (the fallback tier).",
        "Data", lambda p: [("Dump", [PY, "dump_snapshot.py", "--redis-url", _local(), "--output", str(settings.snapshot_path), "--source-label", "server"], {})],
        invalidates=False),
    Job("refresh-nsq", "Monthly NSQ refresh", "Rebuild the whole NSQ dataset from a CSV: load, ontologies, frame, then copy to the in-server Redis.",
        "Data", _refresh_steps, role="super_admin", destructive=lambda p: True,
        params=[Param("csv", "CSV file (blank = bundled cumulative CSV)", kind="csv", default="")]),
    Job("load-seeds", "Reload CDMO seeds", "Reload patents, regulatory passports, demand and seeded plants from data/*.json. User plants are kept.",
        "Data", _seed_steps, role="super_admin", destructive=lambda p: True, after=sync_plants_to_redis),
    Job("sync-plants", "Re-publish user plants", "Write every user-created plant from Postgres back into Redis.",
        "Data", lambda p: [], after=sync_plants_to_redis),
]}


def describe(job: Job) -> dict[str, Any]:
    return {
        "key": job.key, "title": job.title, "description": job.description, "group": job.group,
        "role": job.role, "needs_upstash": job.needs_upstash,
        "available": (not job.needs_upstash) or bool(_upstash()),
        "params": [p.__dict__ for p in job.params],
        "destructive_by_default": job.destructive({p.name: p.default for p in job.params}),
    }


# --- runner --------------------------------------------------------------------

_running: dict[str, int] = {}  # job_key -> run id
_running_lock = threading.Lock()
_live_logs: dict[int, list[str]] = {}


def is_running(key: str) -> Optional[int]:
    with _running_lock:
        return _running.get(key)


def live_log(run_id: int) -> Optional[str]:
    buf = _live_logs.get(run_id)
    return "".join(buf) if buf is not None else None


def _redact(line: str) -> str:
    for secret in filter(None, [settings.upstash_url]):
        line = line.replace(secret, "rediss://***")
    return line


def start(job: Job, params: dict[str, Any], run: JobRun) -> None:
    with _running_lock:
        if job.key in _running:
            raise RuntimeError("already running")
        _running[job.key] = run.id
    _live_logs[run.id] = []
    threading.Thread(target=_execute, args=(job, params, run.id), daemon=True, name=f"job-{job.key}-{run.id}").start()


def _execute(job: Job, params: dict[str, Any], run_id: int) -> None:
    buf = _live_logs[run_id]

    def emit(s: str) -> None:
        buf.append(_redact(s))

    status, code = "succeeded", 0
    with SessionLocal() as db:
        run = db.get(JobRun, run_id)
        run.status, run.started_at = "running", utcnow()
        db.commit()
    try:
        steps = job.steps(params)
        base_env = {**os.environ, "PYTHONUNBUFFERED": "1", "REDIS_URL": _local()}
        for i, (label, cmd, extra_env) in enumerate(steps, 1):
            emit(f"\n▶ [{i}/{len(steps)}] {label}\n")
            t0 = time.time()
            proc = subprocess.Popen(cmd, cwd=str(settings.loader_dir), env={**base_env, **extra_env},
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            assert proc.stdout is not None
            for line in proc.stdout:
                emit(line)
            code = proc.wait()
            emit(f"  exit {code} · {time.time() - t0:.1f}s\n")
            if code != 0:
                # pull_upstash exits 10 for "already seeded" — not a failure.
                if not (job.key == "pull-upstash" and code == 10):
                    status = "failed"
                    break
                code = 0
        if status == "succeeded" and job.after:
            emit(f"\n▶ {job.after()}\n")
    except Exception as exc:
        status, code = "failed", code or 1
        emit(f"\nERROR: {exc}\n")
    finally:
        if job.invalidates:
            data.invalidate()
        with SessionLocal() as db:
            run = db.get(JobRun, run_id)
            run.status, run.exit_code, run.finished_at = status, code, utcnow()
            run.log = "".join(buf)[-200_000:]
            db.commit()
        with _running_lock:
            _running.pop(job.key, None)
        # keep the buffer briefly for late SSE readers
        threading.Timer(120, lambda: _live_logs.pop(run_id, None)).start()
