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
class Step:
    label: str
    cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)
    allow_fail: bool = False  # log and continue on a non-zero exit
    ok_codes: set[int] = field(default_factory=set)  # extra exit codes that count as success
    stop_on: dict[int, str] = field(default_factory=dict)  # exit code -> stop here, successfully


def _as_step(s) -> Step:
    if isinstance(s, Step):
        return s
    label, cmd, env = s
    return Step(label, cmd, env or {})


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
    before: Optional[Callable[[], str]] = None


def _local() -> str:
    return settings.redis_url


def _upstash() -> str:
    return settings.upstash_url


UPLOAD_TYPES = {".csv", ".zip", ".json", ".txt", ".html", ".htm", ".xlsx"}


def upload_path(name: str) -> Path:
    path = (UPLOAD_DIR / Path(name).name).resolve()
    if UPLOAD_DIR.resolve() not in path.parents:
        raise ValueError("Invalid upload name.")
    return path


def _csv_path(p: dict[str, Any]) -> Path:
    name = (p.get("csv") or "").strip()
    return upload_path(name) if name else DEFAULT_CSV


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


def _refresh_steps(p: dict[str, Any], fetch: bool = False):
    csv = str(_csv_path(p))
    target = _upstash() or _local()
    steps: list = []
    if fetch:
        month = (p.get("month") or "").strip()
        backfill = (p.get("backfill_from") or "").strip()
        cmd = [PY, "sync_cdsco.py", "--csv", csv, "--redis-url", _local(), "--exit-unchanged"]
        label = "Fetch the latest CDSCO month and append new alerts to the cumulative CSV"
        if month:
            cmd += ["--month", month]
            label = f"Fetch CDSCO month {month}"
        elif backfill:
            cmd += ["--backfill-from", backfill]
            label = f"Backfill empty CDSCO months since {backfill}"
        steps.append(Step(label, cmd, stop_on={3: "No new CDSCO alerts — Redis left as it is."}))
    else:
        # A fresh box / clone has no CSV (it is gitignored): rebuild it from
        # the records already in Redis instead of failing.
        steps.append(Step("Ensure the cumulative CSV exists (rebuild from Redis if missing)",
                          [PY, "sync_cdsco.py", "--csv", csv, "--redis-url", _local(), "--bootstrap-only"]))
    steps += [
        Step("Load CSV into " + ("Upstash" if _upstash() else "local Redis") + " (flush + ontology augment)",
             [PY, "load_csv_redis.py", "--input", csv, "--redis-url", target, "--flush", "--augment", "1"]),
        Step("Build product ontology", [PY, "build_product_ontology.py", "--input", csv, "--redis-url", target]),
        Step("Pre-compute enriched frame", [PY, "build_enriched_frame.py", "--redis-url", target]),
    ]
    if _upstash():
        steps.append(Step("Copy Upstash → local Redis", [PY, "pull_upstash.py", "--source", _upstash(), "--target", _local()]))
    steps.append(Step("Verify", [PY, "verify_nsq_redis.py"], {"REDIS_URL": _local()}))
    if fetch:
        steps += _universe_steps(p)
    return steps


def export_watchlist() -> str:
    """Write the admin watchlist (Postgres) where build_universe.py reads it."""
    import json as _json

    from .models import WatchMolecule

    with SessionLocal() as db:
        rows = [{"name": w.name, "key": w.key, "exclude": w.exclude} for w in db.scalars(select(WatchMolecule))]
    out = settings.data_dir / "generated" / "watchlist.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(rows, indent=1))
    return f"exported {len(rows)} watchlist entr{'y' if len(rows) == 1 else 'ies'}"


def _gen(name: str) -> str:
    return str(settings.data_dir / "generated" / name)


def _universe_steps(p: dict[str, Any]):
    """Build the molecule universe from seeds + sources + NSQ, then load it."""
    build = [PY, "build_universe.py", "--redis-url", _local()]
    if str(p.get("min_alerts") or "").strip().isdigit():
        build += ["--min-alerts", str(p["min_alerts"]).strip()]
    return [
        Step("Build molecule universe (curated seeds + public sources + NSQ ingredients)", build),
        Step("Load patents", [PY, "load_patents.py", "--input", _gen("patents.json"), "--redis-url", _local(), "--flush"]),
        Step("Load regulatory passports", [PY, "load_regulatory.py", "--input", _gen("regulatory.json"), "--redis-url", _local(), "--flush"]),
        Step("Load demand profiles", [PY, "load_demand.py", "--input", _gen("demand.json"), "--redis-url", _local(), "--flush"]),
    ]


def _source_steps(keys: list[str], p: dict[str, Any]):
    steps = []
    for k in keys:
        cmd = [PY, "fetch_source.py", k] + (["--force"] if p.get("force") else [])
        steps.append(Step(f"Fetch {SOURCE_TITLES.get(k, k)}", cmd, allow_fail=True, ok_codes={3}))
    return steps


def _sync_all_steps(p: dict[str, Any]):
    first = [k for k in SOURCE_TITLES if k != "clinical_trials"]
    steps = _source_steps(first, p)
    # candidates.json must exist before ClinicalTrials.gov is queried
    steps.append(Step("Build molecule universe (candidates for trial lookups)", [PY, "build_universe.py", "--redis-url", _local()]))
    steps += _source_steps(["clinical_trials"], p)
    steps += _universe_steps(p)
    if p.get("backup") and _upstash():
        steps.append(Step("Back up to Upstash", [PY, "pull_upstash.py", "--source", _local(), "--target", _upstash()]))
    return steps


def _seed_steps(p: dict[str, Any]):
    # Curated seeds go through the universe builder so public-source overlays
    # and auto-discovered molecules survive a seed reload.
    steps = _universe_steps(p)
    # Never --flush plants: that would delete user-created plant profiles.
    steps.append(Step("Load plant seed (upsert)", [PY, "load_plant_assets.py", "--input", str(settings.data_dir / "plant_assets_seed.json"), "--redis-url", _local()]))
    return steps


SOURCE_TITLES = {
    "orange_book": "FDA Orange Book",
    "purple_book": "FDA Purple Book",
    "ema": "EMA medicines (EPAR)",
    "fda_establishments": "FDA establishment registrations (India)",
    "fda_import_alerts": "FDA Import Alert 66-40 (India)",
    "fda_recalls": "openFDA recalls (India)",
    "clinical_trials": "ClinicalTrials.gov trial counts",
}
_SOURCE_JOB_DESC = {
    "orange_book": "US patents, exclusivity, RLD/TE codes and ANDA competitors per ingredient. Rebuilds the molecule universe after.",
    "purple_book": "Licensed biologics, reference-product exclusivity and biosimilar counts. Rebuilds the molecule universe after.",
    "ema": "EU central authorisations, generics/biosimilars and therapeutic areas. Rebuilds the molecule universe after.",
    "clinical_trials": "Trial totals, phase 3+, recent starts and India sites per molecule (60 molecules per run, oldest first; each is re-checked weekly).",
    "fda_establishments": "Every FDA-registered establishment in India (FEI, DUNS, operations) — feeds the site directory.",
    "fda_import_alerts": "Indian firms on the drug-GMP red list — feeds the site directory.",
    "fda_recalls": "US recalls of drugs made by Indian firms — feeds the site directory.",
}
_MOLECULE_SOURCES = {"orange_book", "purple_book", "ema", "clinical_trials"}


def _one_source(k: str):
    def steps(p: dict[str, Any]):
        s = _source_steps([k], p)
        s[0].allow_fail = False
        if (p.get("file") or "").strip():
            s[0].cmd += ["--from-file", str(upload_path(p["file"]))]
            s[0].label += " (from uploaded file)"
        if k == "clinical_trials":
            s.insert(0, Step("Refresh molecule candidates", [PY, "build_universe.py", "--redis-url", _local()]))
        if k in _MOLECULE_SOURCES:
            s += _universe_steps(p)
        return s
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
    Job("fetch-nsq", "Fetch latest CDSCO month", "Check the live CDSCO NSQ table; when it has new alerts, append them to the cumulative CSV, reload NSQ data and rebuild the molecule universe. Does nothing when there is nothing new.",
        "Pipelines", lambda p: _refresh_steps({**p, "csv": ""}, fetch=True), role="super_admin", destructive=lambda p: True,
        before=export_watchlist,
        params=[Param("month", "Only this reporting month (YYYY-MM, blank = current)", kind="text", default=""),
                Param("backfill_from", "Or backfill every empty month since (YYYY-MM)", kind="text", default="")]),
    Job("sync-sources", "Sync all public sources", "Fetch every public source (Orange Book, Purple Book, EMA, FDA site records, ClinicalTrials.gov), then rebuild and load the molecule universe. A source that is down is skipped; the rest still load.",
        "Pipelines", _sync_all_steps, before=export_watchlist,
        params=[Param("force", "Re-download even if unchanged", default=False),
                Param("backup", "Back up to Upstash afterwards", default=False)]),
    Job("build-universe", "Rebuild molecule universe", "Recombine curated seeds, the last fetched sources, NSQ ingredients and the watchlist, then load patents / regulatory / demand into Redis. No downloads.",
        "Pipelines", _universe_steps, before=export_watchlist,
        params=[Param("min_alerts", "Min NSQ alerts for an auto molecule (blank = 5)", kind="text", default="")]),
    *[Job(f"src-{k.replace('_', '-')}", SOURCE_TITLES[k], _SOURCE_JOB_DESC[k], "Sources", _one_source(k),
          before=export_watchlist if k in _MOLECULE_SOURCES else None, invalidates=k in _MOLECULE_SOURCES,
          params=[Param("force", "Re-download even if unchanged", default=False),
                  Param("file", "Or parse an uploaded file (for when the server cannot reach the source)", kind="file", default="")])
      for k in SOURCE_TITLES],
    Job("load-seeds", "Reload CDMO seeds", "Rebuild the molecule universe from data/*.json seeds (+ fetched sources) and reload seeded plants. User plants are kept.",
        "Data", _seed_steps, role="super_admin", destructive=lambda p: True, before=export_watchlist, after=sync_plants_to_redis),
    Job("sync-plants", "Re-publish user plants", "Write every user-created plant from Postgres back into Redis.",
        "Data", lambda p: [], after=sync_plants_to_redis),
]}

# Jobs a schedule may run, with their default schedule (IST).
SCHEDULABLE: dict[str, dict[str, Any]] = {
    "fetch-nsq": {"enabled": True, "frequency": "daily", "hour": 6, "minute": 30},
    "sync-sources": {"enabled": True, "frequency": "daily", "hour": 2, "minute": 30},
    "build-universe": {"enabled": False, "frequency": "daily", "hour": 3, "minute": 45},
    "src-orange-book": {"enabled": False, "frequency": "weekly", "hour": 3, "minute": 0, "weekday": 0},
    "src-ema": {"enabled": False, "frequency": "daily", "hour": 3, "minute": 15},
    "src-purple-book": {"enabled": False, "frequency": "monthly", "hour": 3, "minute": 30, "day": 5},
    "src-clinical-trials": {"enabled": False, "frequency": "daily", "hour": 4, "minute": 0},
    "src-fda-establishments": {"enabled": False, "frequency": "weekly", "hour": 4, "minute": 30, "weekday": 6},
    "src-fda-import-alerts": {"enabled": False, "frequency": "daily", "hour": 4, "minute": 45},
    "src-fda-recalls": {"enabled": False, "frequency": "weekly", "hour": 5, "minute": 0, "weekday": 6},
    "build-frame": {"enabled": False, "frequency": "daily", "hour": 5, "minute": 30},
    "snapshot": {"enabled": False, "frequency": "weekly", "hour": 5, "minute": 45, "weekday": 6},
    "backup-to-upstash": {"enabled": False, "frequency": "daily", "hour": 7, "minute": 0, "params": {"dry_run": False}},
}


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


def launch(job: Job, params: dict[str, Any], started_by: Optional[int], email: str) -> JobRun:
    """Create a JobRun row and start it (used by the API and the scheduler)."""
    with SessionLocal() as db:
        run = JobRun(job_key=job.key, params=params, status="queued", started_by=started_by, started_by_email=email)
        db.add(run)
        db.commit()
        db.refresh(run)
        db.expunge(run)
    try:
        start(job, params, run)
    except RuntimeError:
        with SessionLocal() as db:
            r = db.get(JobRun, run.id)
            r.status, r.log = "failed", "Another run of this job is in progress."
            db.commit()
        raise
    return run


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
        if job.before:
            emit(f"▶ {job.before()}\n")
        steps = [_as_step(x) for x in job.steps(params)]
        base_env = {**os.environ, "PYTHONUNBUFFERED": "1", "REDIS_URL": _local(), "DATA_DIR": str(settings.data_dir)}
        warnings: list[str] = []
        for i, st in enumerate(steps, 1):
            emit(f"\n▶ [{i}/{len(steps)}] {st.label}\n")
            t0 = time.time()
            proc = subprocess.Popen(st.cmd, cwd=str(settings.loader_dir), env={**base_env, **st.env},
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            assert proc.stdout is not None
            for line in proc.stdout:
                emit(line)
            code = proc.wait()
            emit(f"  exit {code} · {time.time() - t0:.1f}s\n")
            if code in st.stop_on:
                emit(f"\n■ {st.stop_on[code]}\n")
                code = 0
                break
            if code == 0 or code in st.ok_codes:
                code = 0
                continue
            # pull_upstash exits 10 for "already seeded" — not a failure.
            if job.key == "pull-upstash" and code == 10:
                code = 0
                continue
            if st.allow_fail:
                warnings.append(f"{st.label} (exit {code})")
                emit("  ↳ continuing without it\n")
                code = 0
                continue
            status = "failed"
            break
        if status == "succeeded" and warnings:
            status = "partial"
            emit("\n⚠ Finished with skipped steps:\n" + "".join(f"  - {w}\n" for w in warnings))
        if status in ("succeeded", "partial") and job.after:
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
