"""Plant data (Playground): an organisation's own batch records — equipment / QC files uploaded, or machine readings
streamed by an edge agent over OPC UA / Modbus (edge-agent/) — each batch against its limits, why a batch failed,
the process twin calibrated to the plant, and a live forecast of the batches running now
(chem.batch_data, chem.process_twin).

Two routers: `router` (signed-in users, gated as the "plant-data" Playground feature) and `ingest_router` (the edge
agent, authenticated by its connector token)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from chem import batch_data as bd

from .. import features, insights, lab
from ..audit import audit
from ..db import get_db
from ..models import BatchDataset, PlantConnector, PlantSimConfig, User
from ..security import current_user, org_for_user

router = APIRouter(prefix="/api/plant-data/{slug}", tags=["plant-data"], dependencies=[Depends(features.gate)])
ingest_router = APIRouter(prefix="/api/ingest/plant-data", tags=["plant-data"])
LINE_ORDER = ["rmg", "fbd", "blender", "press"]  # where each machine sits on a tablet line
DEMO_ORG = "eurveda-demo"  # the plant simulator's organisation unless PLANT_SIM_ORG says otherwise (main.py)
LIVE = "live:"  # filename prefix of datasets fed by a connector: live:<connector id>:<machine>
MAX_LIVE_ROWS = 3_000  # raw tail kept per live stream; older batches keep their per-batch values
MAX_LIVE_BATCHES = 300
RETAIN_H = float(os.environ.get("PLANT_LIVE_RETAIN_H", "24"))  # live readings and batches older than this are dropped
_live_cache: dict[tuple, tuple[dict[str, Any], dict[str, Any]]] = {}
ONLINE_S = 90

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 50_000


async def _table(file: Optional[UploadFile], text: Optional[str]) -> tuple[pd.DataFrame, str]:
    if file is not None and file.filename:
        content = await file.read()
        name = file.filename
    elif text and text.strip():
        content, name = text.encode("utf-8"), "pasted.csv"
    else:
        raise HTTPException(400, "Choose a file or paste the table.")
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "The file is larger than 8 MB: split it by month or by batch.")
    try:
        df = bd.read_table(content, name)
    except Exception as exc:  # noqa: BLE001 — any parse failure is the user's file, reported back
        raise HTTPException(400, f"Couldn't read the table: {exc}") from exc
    if df.empty or not len(df.columns):
        raise HTTPException(400, "The table is empty: the first row must hold the column names.")
    if len(df) > MAX_ROWS:
        raise HTTPException(413, f"{len(df):,} rows: the limit is {MAX_ROWS:,} per upload.")
    return df, name


def _molecule_guess(df: pd.DataFrame, mapping: dict[str, str]) -> Optional[str]:
    col = mapping.get("product")
    if not col or col not in df:
        return None
    known = lab.structures()
    for name in df[col].dropna().astype(str).unique()[:20]:
        ings = insights.product_ingredients(name)
        if len(ings) == 1 and ings[0] in known:
            return ings[0]
    return None


def _dose(rows: list[BatchDataset]) -> Optional[float]:
    """The strength in the product name of the batch records ("Paracetamol Tablets IP 500 mg" → 500), if one."""
    from collections import Counter

    names = Counter(b.get("meta", {}).get("product", "") for d in rows for b in (d.batches or {}).values())
    for name, _ in names.most_common():
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", name or "", re.I)
        if m:
            return float(m.group(1))
    return None


def _summary(d: BatchDataset) -> dict[str, Any]:
    fm = bd.FORMAT_BY_ID.get(d.format, {})
    fields = sorted({k for b in (d.batches or {}).values() for k in b.get("values", {})})
    return {"id": d.id, "name": d.name, "format": d.format, "format_label": fm.get("label", d.format), "filename": d.filename,
            "rows": len(d.raw or []), "batches": len(d.batches or {}), "fields": fields, "mapping": d.mapping, "columns": d.columns,
            "molecule_key": d.molecule_key, "uploaded_by": d.uploaded_by, "created_at": d.created_at.isoformat() if d.created_at else None,
            "live": (d.filename or "").startswith(LIVE), "kind": fm.get("kind", "batch"),
            "timestamps": "timestamp" in (d.mapping or {}), "linked_by_time": "timestamp" in (d.mapping or {}) and "batch_no" not in (d.mapping or {}),
            "link": (d.mapping or {}).get("_link"), "machine": _machine_of(d)}


@router.get("/formats")
def formats(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org_for_user(db, slug, user)
    return {"formats": bd.format_guide(), "specs": bd.specs_for(),
            "note": "Sample files hold example batches (not real data) in each format's own column names: they upload as they are."}


@router.get("/formats/{fmt}/sample.csv")
def sample(slug: str, fmt: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org_for_user(db, slug, user)
    if fmt not in bd.FORMAT_BY_ID:
        raise HTTPException(404, "Unknown format.")
    return Response(bd.sample_csv(fmt), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="eurveda-sample-{fmt}.csv"'})


# --- reference windows: which batch was on which machine when ---------------------------------------------------

def _machine_of(d: BatchDataset) -> str:
    return d.name.removeprefix("Live · ") if (d.filename or "").startswith(LIVE) else str((d.mapping or {}).get("_machine") or "")


def _fields(mapping: dict[str, Any]) -> dict[str, str]:
    return {k: v for k, v in (mapping or {}).items() if k in bd.F and isinstance(v, str)}


def _windows(rows: list[BatchDataset]) -> list[dict[str, Any]]:
    """From batch schedules, and from data holding both a batch number and a timestamp on a known machine (a SCADA
    stream reads the machine's batch tag with every reading)."""
    out = []
    for d in rows:
        m = _fields(d.mapping)
        if not d.raw:
            continue
        if d.format == "batch_schedule":
            out += bd.schedule_windows(pd.DataFrame(d.raw).fillna("").astype(str), m)
        elif "batch_no" in m and "timestamp" in m and ("machine" in m or _machine_of(d)):
            out += bd.tagged_windows(pd.DataFrame(d.raw).fillna("").astype(str), m, _machine_of(d))
    return out


def _link_and_aggregate(df: pd.DataFrame, fmt: str, m: dict[str, str], wins: list[dict[str, Any]], machine: str) -> tuple[dict[str, Any], dict[str, Any]]:
    linked, mp, stats = bd.link(df, m, wins, machine)
    return bd.aggregate(linked, fmt, mp), stats


def _relink(db: Session, org_id: int) -> None:
    """Re-read every timestamp-only file against the current windows (after a schedule is added or removed)."""
    rows = _datasets(db, org_id)
    wins = _windows(rows)
    for d in rows:
        m = _fields(d.mapping)
        if "batch_no" in m or "timestamp" not in m or not d.raw:
            continue
        batches, stats = _link_and_aggregate(pd.DataFrame(d.raw).fillna("").astype(str), d.format, m, wins, _machine_of(d))
        d.batches = batches
        d.mapping = {**m, "_machine": _machine_of(d), "_link": stats}
    db.commit()


@router.post("/preview")
async def preview(slug: str, file: Optional[UploadFile] = File(None), text: Optional[str] = Form(None), format: Optional[str] = Form(None),
                  machine: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    df, name = await _table(file, text)
    headers = list(df.columns)
    if format and format in bd.FORMAT_BY_ID:
        fmt, mapping = format, bd.match_headers(headers, bd.FORMAT_BY_ID[format]["fields"])
    else:
        fmt, mapping = bd.detect_format(headers)
    extra = {k: h for k, h in bd.match_headers([h for h in headers if h not in mapping.values()]).items() if k not in mapping}
    full = {**mapping, **extra}
    wins = _windows(_datasets(db, org.id))
    link = None
    if "batch_no" not in full and "timestamp" in full and fmt != "batch_schedule":
        link = bd.link(df, full, wins, machine)[2] if wins else {"rows": len(df), "linked": 0, "windows": 0}
    return {"filename": name, "format": fmt, "headers": headers, "mapping": full, "rows": len(df),
            "preview": df.head(8).fillna("").to_dict(orient="records"), "unmapped": [h for h in headers if h not in full.values()],
            "molecule_guess": _molecule_guess(df, full), "batches": int(df[mapping["batch_no"]].nunique()) if "batch_no" in mapping else (link or {}).get("batches", 0),
            "link": link, "machines": sorted({w["machine"] for w in wins if w["machine"]}),
            "windows": len(wins)}


@router.post("/datasets")
async def create(slug: str, request: Request, file: Optional[UploadFile] = File(None), text: Optional[str] = Form(None),
                 format: str = Form(...), mapping: str = Form("{}"), name: str = Form(""), molecule_key: str = Form(""),
                 machine: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    if format not in bd.FORMAT_BY_ID:
        raise HTTPException(400, "Unknown format.")
    df, fname = await _table(file, text)
    try:
        m = {k: v for k, v in json.loads(mapping or "{}").items() if k in bd.F and v in df.columns}
    except ValueError as exc:
        raise HTTPException(400, "Bad column mapping.") from exc
    stored: dict[str, Any] = dict(m)
    if format == "batch_schedule":
        missing = [f for f in ("batch_no", "batch_start", "batch_end") if f not in m]
        if missing:
            raise HTTPException(400, f"A batch schedule needs {', '.join(bd.F[f]['label'] for f in missing)}.")
        if not bd.schedule_windows(df.fillna("").astype(str), m):
            raise HTTPException(400, "No row has a batch number with a readable start and end time.")
        batches = bd.schedule_batches(df.fillna("").astype(str), m)
    elif "batch_no" in m:
        try:
            batches = bd.aggregate(df, format, m)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not batches:
            raise HTTPException(400, "No rows with a batch number.")
    elif "timestamp" in m:
        wins = _windows(_datasets(db, org.id))
        if not wins:
            raise HTTPException(400, "This file has timestamps but no batch numbers. Add a batch schedule first (which batch ran on which "
                                     "machine, from when to when): the readings are assigned to batches by time.")
        batches, stats = _link_and_aggregate(df.fillna("").astype(str), format, m, wins, machine)
        if not stats["linked"]:
            raise HTTPException(400, f"None of the {stats['rows']} readings falls inside a batch window"
                                     f"{' on ' + machine if machine else ''}: check the machine and the time zone of the schedule.")
        stored.update(_machine=machine, _link=stats)
    else:
        raise HTTPException(400, "Map a column to 'Batch number', or to 'Timestamp' (with a batch schedule).")
    ds = BatchDataset(org_id=org.id, name=(name or re.sub(r"\.[a-z]+$", "", fname))[:200], format=format, filename=fname[:240],
                      columns=list(df.columns), mapping=stored, raw=df.fillna("").to_dict(orient="records"), batches=batches,
                      molecule_key=molecule_key[:160], uploaded_by=user.email)
    db.add(ds)
    db.commit()
    if format == "batch_schedule":
        _relink(db, org.id)
    audit(db, "batches.upload", user, "batch_dataset", ds.id, {"org": org.slug, "format": format, "rows": len(df), "batches": len(batches)}, request)
    return _summary(ds)


@router.get("/datasets")
def datasets(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    rows = db.scalars(select(BatchDataset).where(BatchDataset.org_id == org.id).order_by(BatchDataset.created_at.desc())).all()
    return {"datasets": [_summary(d) for d in rows]}


@router.delete("/datasets/{ds_id}")
def delete(slug: str, ds_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    ds = db.get(BatchDataset, ds_id)
    if ds is None or ds.org_id != org.id:
        raise HTTPException(404, "Dataset not found.")
    was_reference = ds.format == "batch_schedule" or "timestamp" in _fields(ds.mapping)
    db.delete(ds)
    db.commit()
    if was_reference:
        _relink(db, org.id)
    audit(db, "batches.delete", user, "batch_dataset", ds_id, {"org": org.slug, "name": ds.name}, request)
    return {"ok": True}


@router.get("/timeline/{ds_id}")
def timeline(slug: str, ds_id: int, field: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """How a time series became one row per batch: its readings over time, the batch windows they were assigned to,
    and each batch's resulting value."""
    org = org_for_user(db, slug, user)
    ds = db.get(BatchDataset, ds_id)
    if ds is None or ds.org_id != org.id:
        raise HTTPException(404, "Dataset not found.")
    m = _fields(ds.mapping)
    if "timestamp" not in m or not ds.raw:
        return {"mode": "none", "reason": "This file has no timestamps: each row already belongs to a batch."}
    df = pd.DataFrame(ds.raw).fillna("").astype(str)
    machine = _machine_of(ds)
    linked_by = "schedule" if "batch_no" not in m else "batch column"
    if "batch_no" not in m:
        df, mp, _ = bd.link(df, m, _windows(_datasets(db, org.id)), machine)
    else:
        mp = m
    numeric = [k for k in mp if bd.F.get(k, {}).get("kind") in ("param", "raw", "cqa")]
    field = field if field in numeric else next((k for k in ("inlet_c", "force_kn", "lod_pct") if k in numeric), numeric[0] if numeric else "")
    ts = [bd.to_date(x) for x in df[mp["timestamp"]]]
    val = pd.to_numeric(df[mp[field]].str.replace(",", "", regex=False), errors="coerce") if field else pd.Series(dtype=float)
    bat = df[mp["batch_no"]].map(bd._batch_key) if "batch_no" in mp else pd.Series("", index=df.index)
    mach = df[mp["machine"]].astype(str) if "machine" in mp else pd.Series(machine, index=df.index)
    pts = [{"t": t.isoformat(), "v": None if pd.isna(v) else round(float(v), 4), "batch": b, "machine": mc}
           for t, v, b, mc in zip(ts, val, bat, mach) if t is not None and not pd.isna(v)]
    step = max(1, len(pts) // 1500)
    pts = sorted(pts, key=lambda p: p["t"])[::step]
    wins: dict[tuple[str, str], dict[str, Any]] = {}
    for p in pts:
        if p["batch"]:
            w = wins.setdefault((p["batch"], p["machine"]), {"batch": p["batch"], "machine": p["machine"], "start": p["t"], "end": p["t"]})
            w["end"] = max(w["end"], p["t"])
    per_batch = [{"batch": b, "value": (ds.batches or {}).get(b, {}).get("values", {}).get(field), "how": (ds.batches or {}).get(b, {}).get("derived", {}).get(field)}
                 for b in dict.fromkeys(w["batch"] for w in wins.values())]
    return {"mode": "time", "dataset": _summary(ds), "field": field, "fields": [{"id": k, "label": bd.F[k]["label"], "unit": bd.F[k]["unit"]} for k in numeric],
            "unit": bd.F.get(field, {}).get("unit", ""), "points": pts, "windows": list(wins.values()), "per_batch": per_batch,
            "linked_by": linked_by, "link": (ds.mapping or {}).get("_link"), "machine": machine}


@router.post("/analysis")
def analysis(slug: str, body: dict[str, Any] = Body(default={}), user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    q = select(BatchDataset).where(BatchDataset.org_id == org.id).order_by(BatchDataset.created_at.desc())
    rows = [d for d in db.scalars(q).all() if not body.get("dataset_ids") or d.id in body["dataset_ids"]]
    if not rows:
        return {"empty": True}
    key = body.get("molecule_key") or next((d.molecule_key for d in rows if d.molecule_key), "") or None
    predict, molecule, withheld = None, None, {}
    if key:
        try:
            prof, mol, form, withheld, _ = lab.twin_molecule(key, _dose(rows))
            from chem import process_twin as twin

            def predict(values: dict[str, float]) -> dict[str, float]:  # noqa: F811 — the twin's view of one batch
                v = twin.evaluate(mol, values, form)["values"]
                return {k: round(float(x), 3) for k, x in v.items() if k not in (withheld or {})}

            molecule = {"key": key, "name": prof["name"], "dose_mg": mol.dose_mg, "withheld": withheld or {}}
        except KeyError:
            key = None
    out = bd.analyse(bd.merge([{"name": d.name, "format": d.format, "batches": _finished(d)} for d in rows]), body.get("specs"), predict)
    return {**out, "molecule": molecule, "datasets": [_summary(d) for d in rows]}


def _finished(d: BatchDataset) -> dict[str, Any]:
    """A dataset's batches, without the one a live stream is still running (its readings so far are not a result)."""
    if not (d.filename or "").startswith(LIVE) or not d.raw:
        return d.batches or {}
    running = bd._batch_key(d.raw[-1].get("batch_no"))
    return {b: v for b, v in (d.batches or {}).items() if b != running}


def _calibration(rows: list[BatchDataset]) -> dict[str, Any]:
    """Twin baseline and ranges from the uploaded files (stable); from the live streams only when there are no files."""
    files = [d for d in rows if not (d.filename or "").startswith(LIVE)] or rows
    return bd.analyse(bd.merge([{"name": d.name, "batches": _finished(d)} for d in files]))["calibration"] if files else {"baseline": {}, "nor": {}}


def _datasets(db: Session, org_id: int, ids: Optional[list[int]] = None) -> list[BatchDataset]:
    q = select(BatchDataset).where(BatchDataset.org_id == org_id).order_by(BatchDataset.created_at.desc())
    return [d for d in db.scalars(q).all() if not ids or d.id in ids]


@router.get("/molecules")
def molecules(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Molecules the twin can model (a structure on file), for the batch tab's picker."""
    org_for_user(db, slug, user)
    rows = [m for m in lab.molecules().get("molecules", []) if m.get("has_structure")]
    return {"molecules": [{"key": m["key"], "name": m["name"], "alerts": m.get("alerts", 0)} for m in rows]}


@router.post("/twin")
def calibrated_twin(slug: str, body: dict[str, Any] = Body(default={}), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The process twin calibrated to this organisation's batches: baseline = its medians, normal operating
    ranges = its mean ± 3 SD (computed here from its uploads, not taken from the request)."""
    org = org_for_user(db, slug, user)
    key = body.get("molecule_key")
    if not key:
        raise HTTPException(400, "Choose the molecule these batches are of.")
    rows = _datasets(db, org.id, body.get("dataset_ids"))
    cal = _calibration(rows)
    try:
        out = lab.process_twin(key, {"overrides": body.get("overrides") or {}, "baseline": cal["baseline"], "nor": cal["nor"], "dose_mg": _dose(rows)})
    except KeyError as exc:
        raise HTTPException(404, "No structure on file for this molecule.") from exc
    return {**out, "plant": {**cal, "batches": len({b for d in rows for b in (d.batches or {})})}}


# --- connectors: edge agents streaming machine readings -----------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _online(c: PlantConnector) -> bool:
    seen = c.last_seen_at
    if seen is None:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds() < ONLINE_S


def _conn(c: PlantConnector) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "token_hint": c.token_hint, "active": c.active, "online": _online(c),
            "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None, "machines": c.status or {}, "agent": c.agent or {},
            "created_by": c.created_by, "created_at": c.created_at.isoformat() if c.created_at else None}


AGENT_DIR = Path(__file__).resolve().parents[3] / "edge-agent"
AGENT_FILES = {"eurveda_agent.py": "text/x-python", "simulator.py": "text/x-python", "requirements.txt": "text/plain",
               "config.example.yaml": "text/yaml", "README.md": "text/markdown"}


@router.get("/agent/{name}")
def agent_file(slug: str, name: str, url: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The edge agent's files; config.yaml is the example with this Eurveda's address filled in."""
    org_for_user(db, slug, user)
    src = "config.example.yaml" if name == "config.yaml" else name
    if src not in AGENT_FILES or not (AGENT_DIR / src).is_file():
        raise HTTPException(404, "No such agent file.")
    text = (AGENT_DIR / src).read_text(encoding="utf-8")
    if name == "config.yaml" and re.match(r"^https?://[\w.:-]+$", url or ""):
        text = text.replace("https://YOUR-EURVEDA-HOST", url)
    return Response(text, media_type=AGENT_FILES[src], headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/connectors")
def connectors(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    rows = db.scalars(select(PlantConnector).where(PlantConnector.org_id == org.id).order_by(PlantConnector.created_at)).all()
    return {"connectors": [_conn(c) for c in rows], "ingest_path": ingest_router.prefix}


@router.post("/connectors")
def create_connector(slug: str, request: Request, body: dict[str, Any] = Body(default={}), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A new edge-agent connector; the token is returned once and only its hash is stored."""
    org = org_for_user(db, slug, user)
    name = (str(body.get("name") or "").strip() or "Plant agent")[:120]
    token = "evd_" + secrets.token_urlsafe(32)
    c = PlantConnector(org_id=org.id, name=name, token_hash=_hash(token), token_hint=token[:10], created_by=user.email, status={}, agent={})
    db.add(c)
    db.commit()
    audit(db, "plant_data.connector_create", user, "plant_connector", c.id, {"org": org.slug, "name": name}, request)
    return {**_conn(c), "token": token}


@router.delete("/connectors/{cid}")
def delete_connector(slug: str, cid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Revokes the token; the data it streamed stays (delete its live files separately)."""
    org = org_for_user(db, slug, user)
    c = db.get(PlantConnector, cid)
    if c is None or c.org_id != org.id:
        raise HTTPException(404, "Connector not found.")
    db.delete(c)
    db.commit()
    audit(db, "plant_data.connector_delete", user, "plant_connector", cid, {"org": org.slug}, request)
    return {"ok": True}


@router.get("/live")
def live(slug: str, molecule: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What the machines are doing now, and the twin's forecast for each batch they are running: each quality test
    predicted from the batch's live settings so far (the plant's medians for the rest). For a batch still drying,
    the forecast is what the tests would give if it stopped now."""
    org = org_for_user(db, slug, user)
    conns = db.scalars(select(PlantConnector).where(PlantConnector.org_id == org.id)).all()
    rows = _datasets(db, org.id)
    live_all = [d for d in rows if (d.filename or "").startswith(LIVE)]
    online = {c.id for c in conns if _online(c)}
    live_ds = [d for d in live_all if int(((d.filename or "").split(":") + ["0", "0"])[1] or 0) in online]  # machines running now
    machines = []
    for d in live_ds:
        raw = d.raw or []
        if not raw:
            continue
        last = raw[-1]
        b = bd._batch_key(last.get("batch_no"))
        fields = [k for k in last if k in bd.F and bd.F[k]["kind"] in ("param", "raw", "cqa")]
        tail = [r for r in raw[-240:] if bd._batch_key(r.get("batch_no")) == b][-120:]
        cur = [r for r in raw if bd._batch_key(r.get("batch_no")) == b]
        machines.append({"machine": d.name.removeprefix("Live · "), "dataset_id": d.id, "format": d.format,
                         "format_label": bd.FORMAT_BY_ID.get(d.format, {}).get("label", d.format), "batch_no": b,
                         "ts": last.get("timestamp"), "connector_id": int((d.filename or "live:0:").split(":")[1] or 0),
                         "latest": {k: _f(last.get(k)) for k in fields},
                         "series": {k: [_f(r.get(k)) for r in tail] for k in fields},
                         "fields": [{"id": k, "label": bd.F[k]["label"], "unit": bd.F[k]["unit"], "twin": k in bd.PARAM_IDS} for k in fields],
                         "batch_values": (d.batches or {}).get(b, {}).get("values", {}),
                         "batch_started": cur[0].get("timestamp") if cur else None, "batch_readings": len(cur),
                         "order": LINE_ORDER.index(d.format) if d.format in LINE_ORDER else 9})
    machines.sort(key=lambda m: (m["order"], m["machine"]))
    out: dict[str, Any] = {"connectors": [_conn(c) for c in conns], "machines": machines, "forecasts": [], "specs": bd.specs_for()}
    if not machines:
        return out
    if not molecule:
        out["recent"] = _feed(live_ds, machines, None)
        return out
    try:
        prof, mol, form, withheld, _ = lab.twin_molecule(molecule, _dose(rows))
    except KeyError:
        return out
    from chem import process_twin as twin

    merged = bd.merge([{"name": d.name, "batches": d.batches} for d in live_ds])

    def predict(values: dict[str, float]) -> dict[str, float]:
        return {k: float(v) for k, v in twin.evaluate(mol, values, form)["values"].items() if k not in (withheld or {})}

    # Calibration and the model's bias against this plant's measured results (uploaded files) change only when the
    # files do: computed once per file set, not on every 5-second refresh.
    files = [d for d in rows if not (d.filename or "").startswith(LIVE)]
    ck = (org.id, molecule, tuple((d.id, len(d.raw or [])) for d in (files or live_all)))
    hit = _live_cache.get(ck)
    if hit is None:
        cal = _calibration(rows)
        check = bd.analyse(bd.merge([{"name": d.name, "batches": d.batches} for d in files]), None, predict)["model_check"] if files else {}
        hit = (cal, {bd.F[f]["cqa"]: c for f, c in check.items() if c["n"] >= 3})
        if len(_live_cache) > 32:
            _live_cache.clear()
        _live_cache[ck] = hit
    cal, bias = hit
    sp = bd.specs_for()
    by_cqa = {cqa: f for f, cqa in bd.CQA_FIELDS.items()}
    for b in dict.fromkeys(m["batch_no"] for m in machines):
        vals = (merged.get(b) or {}).get("values", {})
        params = {k: v for k, v in vals.items() if k in bd.PARAM_IDS}
        ev = twin.evaluate(mol, {**cal["baseline"], **params}, form)
        pred = []
        for c in twin.CQAS:
            if c["id"] in (withheld or {}):
                continue
            fid = by_cqa.get(c["id"])
            lim = sp.get(fid, {})
            raw_v = float(ev["values"][c["id"]])
            b_ = bias.get(c["id"])
            v = raw_v - b_["bias"] if b_ else raw_v
            span = abs(lim.get("hi") if lim.get("hi") is not None else lim.get("lo") or 1) or 1
            room = min(x for x in [(lim["hi"] - v) if lim.get("hi") is not None else None,
                                   (v - lim["lo"]) if lim.get("lo") is not None else None] if x is not None) if lim else None
            fails = (lim.get("lo") is not None and v < lim["lo"]) or (lim.get("hi") is not None and v > lim["hi"]) if lim else bool(ev["fails"][c["id"]])
            pred.append({"test": c["id"], "label": c["label"], "value": round(v, 3), "fails": bool(fails), "model_value": round(raw_v, 3),
                         "corrected": {"bias": b_["bias"], "n": b_["n"]} if b_ else None,
                         "lo": lim.get("lo"), "hi": lim.get("hi"), "headroom_pct": round(100 * room / span, 1) if room is not None else None})
        out["forecasts"].append({"batch_no": b, "machines": [m["machine"] for m in machines if m["batch_no"] == b],
                                 "live_params": params, "predicted": pred,
                                 "drying_in_progress": any(m["batch_no"] == b and m["format"] == "fbd" for m in machines)})
    out["recent"] = _feed(live_ds, machines, lambda vals: _forecast(twin, mol, form, withheld, cal, bias, vals))
    out["molecule"] = {"key": molecule, "name": prof["name"], "dose_mg": mol.dose_mg}
    out["baseline"] = cal["baseline"]
    return out


def _retain(raw: list[dict[str, Any]], batches: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop live readings, and batches last seen, more than RETAIN_H hours ago."""
    cutoff = (datetime.now(timezone.utc) - pd.Timedelta(hours=RETAIN_H)).isoformat()
    keep_raw = [r for r in raw if not r.get("timestamp") or str(r["timestamp"]) >= cutoff[:19]]
    keep_b = {b: v for b, v in batches.items() if not v.get("meta", {}).get("last_ts") or str(v["meta"]["last_ts"]) >= cutoff[:19]}
    return keep_raw, keep_b


def prune_live(db: Session) -> int:
    """Apply the retention to every live stream (also when no agent is pushing); returns how many streams changed."""
    n = 0
    for d in db.scalars(select(BatchDataset).where(BatchDataset.filename.like(f"{LIVE}%"))).all():
        raw, batches = _retain(d.raw or [], d.batches or {})
        if len(raw) != len(d.raw or []) or len(batches) != len(d.batches or {}):
            d.raw, d.batches = raw, batches
            n += 1
    db.commit()
    return n


def _forecast(twin: Any, mol: Any, form: dict[str, Any], withheld: Any, cal: dict[str, Any], bias: dict[str, Any], vals: dict[str, float]) -> list[dict[str, Any]]:
    params = {k: v for k, v in vals.items() if k in bd.PARAM_IDS}
    ev = twin.evaluate(mol, {**cal["baseline"], **params}, form)
    sp = bd.specs_for()
    by_cqa = {cqa: f for f, cqa in bd.CQA_FIELDS.items()}
    out = []
    for c in twin.CQAS:
        if c["id"] in (withheld or {}):
            continue
        lim = sp.get(by_cqa.get(c["id"]), {})
        v = float(ev["values"][c["id"]]) - (bias.get(c["id"], {}).get("bias", 0.0))
        fails = (lim.get("lo") is not None and v < lim["lo"]) or (lim.get("hi") is not None and v > lim["hi"])
        out.append({"test": c["id"], "label": c["label"], "value": round(v, 3), "fails": bool(fails)})
    return out


def _feed(live_ds: list[BatchDataset], machines: list[dict[str, Any]], forecast: Any, n: int = 8) -> list[dict[str, Any]]:
    """The latest batches on the line, newest first: which machines each has been through (done), is on (running)
    or has still to reach (pending), and — once its settings are known — the forecast of its tests."""
    running = {m["machine"]: m["batch_no"] for m in machines}
    stations = [m["machine"] for m in machines]
    seen: dict[str, dict[str, Any]] = {}
    for d in live_ds:
        mach = d.name.removeprefix("Live · ")
        for b, v in (d.batches or {}).items():
            e = seen.setdefault(b, {"batch": b, "done": set(), "last": ""})
            e["done"].add(mach)
            e["last"] = max(e["last"], str(v.get("meta", {}).get("last_ts") or ""))
    merged = bd.merge([{"name": d.name, "batches": d.batches} for d in live_ds])
    out = []
    for e in sorted(seen.values(), key=lambda e: (e["last"], e["batch"]), reverse=True)[:n]:
        st = [{"machine": m, "status": "running" if running.get(m) == e["batch"] else "done" if m in e["done"] else "pending"} for m in stations]
        finished = all(x["status"] == "done" for x in st)
        vals = (merged.get(e["batch"]) or {}).get("values", {})
        out.append({"batch": e["batch"], "stations": st, "complete": finished, "last_ts": e["last"],
                    "settings": {k: v for k, v in vals.items() if k in bd.PARAM_IDS},
                    "forecast": forecast(vals) if forecast else None})
    return out


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


@ingest_router.post("")
def ingest(body: dict[str, Any] = Body(...), authorization: str = Header(""), db: Session = Depends(get_db)):
    """Readings from an edge agent: {"agent": {...}, "readings": [{"machine", "format", "ts", "batch_no", "product"?,
    "values": {field: number}}]}. Each machine's readings are appended to its live dataset and re-read per batch."""
    token = authorization.removeprefix("Bearer ").strip()
    c = db.scalar(select(PlantConnector).where(PlantConnector.token_hash == _hash(token))) if token else None
    if c is None or not c.active:
        raise HTTPException(401, "Unknown or revoked connector token.")
    readings = body.get("readings") or []
    if not isinstance(readings, list) or len(readings) > 5000:
        raise HTTPException(413, "Send at most 5,000 readings per request.")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rejected = 0
    for rd in readings:
        machine = str(rd.get("machine") or "")[:60]
        fmt = rd.get("format")
        b = str(rd.get("batch_no") or "").strip()
        vals = {k: _f(v) for k, v in (rd.get("values") or {}).items() if k in bd.F and bd.F[k]["kind"] != "meta"}
        vals = {k: v for k, v in vals.items() if v is not None}
        meta = {k: rd["values"][k] for k in ("elapsed_min", "time_min", "vessel", "sample_no") if k in (rd.get("values") or {})}
        if not machine or fmt not in bd.FORMAT_BY_ID or not b or not (vals or meta):
            rejected += 1
            continue
        groups[(machine, fmt)].append({"batch_no": b, "timestamp": str(rd.get("ts") or ""), "product": str(rd.get("product") or ""), **meta, **vals})
    status = dict(c.status or {})
    for (machine, fmt), new in groups.items():
        fname = f"{LIVE}{c.id}:{machine}"
        ds = db.scalar(select(BatchDataset).where(BatchDataset.org_id == c.org_id, BatchDataset.filename == fname))
        if ds is None:
            ds = BatchDataset(org_id=c.org_id, name=f"Live · {machine}", format=fmt, filename=fname, columns=[], mapping={}, raw=[],
                              batches={}, uploaded_by=f"connector:{c.name}")
            db.add(ds)
        raw = [*(ds.raw or []), *new][-MAX_LIVE_ROWS:]
        touched = {r["batch_no"] for r in new}
        df = pd.DataFrame([r for r in raw if r["batch_no"] in touched]).fillna("").astype(str)
        mapping = {k: k for k in df.columns if k in bd.F}
        batches = {**(ds.batches or {}), **bd.aggregate(df, fmt, mapping)}  # only the batches this push touched
        for r in new:  # when each batch was last seen, for retention
            b = bd._batch_key(r["batch_no"])
            if b in batches:
                batches[b].setdefault("meta", {})["last_ts"] = r["timestamp"]
        raw, batches = _retain(raw, batches)
        ds.raw, ds.format = raw, fmt
        ds.columns = list(dict.fromkeys([*(ds.columns or []), *df.columns]))
        ds.mapping = {k: k for k in ds.columns if k in bd.F}
        ds.batches = dict(list(batches.items())[-MAX_LIVE_BATCHES:])
        status[machine] = {"format": fmt, "ts": new[-1]["timestamp"], "batch_no": new[-1]["batch_no"], "readings": len(new),
                           "values": {k: v for k, v in new[-1].items() if k not in ("batch_no", "timestamp", "product")}}
    c.status = status
    c.agent = {k: str(v)[:120] for k, v in (body.get("agent") or {}).items()}
    c.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return {"accepted": sum(len(v) for v in groups.values()), "rejected": rejected, "machines": sorted(m for m, _ in groups)}


# --- the plant simulator's settings (Sim engine panel) ---------------------------------------------------------------

PATTERNS = ("steady", "drift", "sine", "step", "spikes", "ramp")
_NUM_KEYS = ("setpoint", "noise", "min", "max", "amplitude", "every", "period_min")


def sim_defaults() -> dict[str, Any]:
    return json.loads((AGENT_DIR / "sim_defaults.json").read_text(encoding="utf-8"))


def _merged(saved: Optional[dict[str, Any]]) -> dict[str, Any]:
    base = sim_defaults()

    def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        out = dict(a)
        for k, v in (b or {}).items():
            out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        return out
    return merge(base, saved or {})


def _clean(cfg: dict[str, Any]) -> dict[str, Any]:
    """Only known machines and signals, numbers as numbers, patterns from the list, min ≤ setpoint ≤ max."""
    base = sim_defaults()
    out: dict[str, Any] = {"running": bool(cfg.get("running", True)), "speed": max(1.0, min(240.0, float(cfg.get("speed", 30)))),
                           "handling_min": max(0.0, min(120.0, float(cfg.get("handling_min", 5)))), "apparatus": {}}
    for m, a in base["apparatus"].items():
        got = (cfg.get("apparatus") or {}).get(m) or {}
        am = {"label": a.get("label", m), "format": a.get("format"), "enabled": bool(got.get("enabled", a.get("enabled", True))),
              "duration_min": max(1.0, min(600.0, float(got.get("duration_min", a.get("duration_min", 30))))), "signals": {}}
        for f, sdef in a["signals"].items():
            g = (got.get("signals") or {}).get(f) or {}
            sv = {k: float(g.get(k, sdef.get(k, 0))) for k in _NUM_KEYS}
            sv["min"], sv["max"] = min(sv["min"], sv["max"]), max(sv["min"], sv["max"])
            sv["setpoint"] = min(sv["max"], max(sv["min"], sv["setpoint"]))
            sv["noise"], sv["every"], sv["period_min"] = abs(sv["noise"]), max(1, int(sv["every"])), max(1.0, sv["period_min"])
            sv["pattern"] = g.get("pattern") if g.get("pattern") in PATTERNS else sdef.get("pattern", "steady")
            sv.update(label=sdef.get("label", f), unit=sdef.get("unit", ""), per=sdef.get("per", "reading"))
            am["signals"][f] = sv
        out["apparatus"][m] = am
    return out


def _guidance(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each simulator signal the process twin uses, the twin's normal operating range expressed in that
    signal's own unit (chem.process_twin.PARAMS), so values can be fed knowingly."""
    from chem import process_twin as twin

    P = twin.P_BY_ID
    A = cfg["apparatus"]
    sp = lambda m, f: float(A[m]["signals"][f]["setpoint"])  # noqa: E731
    g: dict[str, dict[str, Any]] = {}

    def put(m: str, f: str, lo: float, hi: float, text: str) -> None:
        g[f"{m}.{f}"] = {"lo": round(lo, 3), "hi": round(hi, 3), "text": text}

    for f, pid in (("inlet_c", "inlet_c"), ("air_m3_h", "air_m3_h"), ("drying_min", "drying_min")):
        put("FBD-1", f, P[pid].lo, P[pid].hi, f"twin's normal range for {P[pid].label.lower()}")
    put("BLENDER-1", "blend_min", P["blend_min"].lo, P["blend_min"].hi, "twin's normal range for lubricated blend time")
    dry = sp("RMG-1", "dry_mix_kg")
    put("RMG-1", "binder_kg", P["granulation_liquid_pct"].lo * dry / 100, P["granulation_liquid_pct"].hi * dry / 100,
        f"granulation liquid {P['granulation_liquid_pct'].lo:g}–{P['granulation_liquid_pct'].hi:g}% w/w of a {dry:g} kg dry mix")
    T = sp("FBD-1", "inlet_c")
    rh = lambda td: 100 * math.exp(17.625 * td / (243.04 + td) - 17.625 * T / (243.04 + T))  # noqa: E731
    put("FBD-1", "inlet_rh_pct", rh(P["dew_point_c"].lo), rh(P["dew_point_c"].hi), f"inlet dew point {P['dew_point_c'].lo:g}–{P['dew_point_c'].hi:g} °C at {T:g} °C inlet (Magnus)")
    area = math.pi * sp("PRESS-1", "punch_diameter_mm") ** 2 / 4
    put("PRESS-1", "force_kn", P["pressure_mpa"].lo * area / 1000, P["pressure_mpa"].hi * area / 1000,
        f"compression pressure {P['pressure_mpa'].lo:g}–{P['pressure_mpa'].hi:g} MPa on a {sp('PRESS-1', 'punch_diameter_mm'):g} mm punch")
    w = sp("PRESS-1", "tablet_weight_mg")
    put("PRESS-1", "tablet_weight_mg", w * (1 - 3 * P["weight_rsd_pct"].hi / 100), w * (1 + 3 * P["weight_rsd_pct"].hi / 100),
        f"noise as weight RSD {P['weight_rsd_pct'].lo:g}–{P['weight_rsd_pct'].hi:g}% → SD {w * P['weight_rsd_pct'].lo / 100:.1f}–{w * P['weight_rsd_pct'].hi / 100:.1f} mg")
    return g


@router.get("/sim-config")
def get_sim_config(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    row = db.get(PlantSimConfig, org.id)
    cfg = _clean(_merged(row.config if row else None))
    sim = next((c for c in db.scalars(select(PlantConnector).where(PlantConnector.org_id == org.id)).all() if c.created_by == "PLANT_SIM_TOKEN"), None)
    return {"config": cfg, "defaults": _clean(sim_defaults()), "guidance": _guidance(cfg), "patterns": PATTERNS,
            "simulator": _conn(sim) if sim else None, "updated_by": row.updated_by if row else None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.put("/sim-config")
def put_sim_config(slug: str, request: Request, body: dict[str, Any] = Body(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    try:
        cfg = _clean(body.get("config") or {})
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Bad simulator settings: {exc}") from exc
    row = db.get(PlantSimConfig, org.id) or PlantSimConfig(org_id=org.id)
    row.config, row.updated_by = cfg, user.email
    db.add(row)
    db.commit()
    audit(db, "plant_data.sim_config", user, "org", org.id, {"running": cfg["running"], "speed": cfg["speed"]}, request)
    return {"config": cfg, "guidance": _guidance(cfg)}


@ingest_router.get("/sim-config")
def sim_config_for_agent(authorization: str = Header(""), db: Session = Depends(get_db)):
    """The simulator's settings, for the simulator itself (authenticated by its connector token)."""
    token = authorization.removeprefix("Bearer ").strip()
    c = db.scalar(select(PlantConnector).where(PlantConnector.token_hash == _hash(token))) if token else None
    if c is None or not c.active:
        raise HTTPException(401, "Unknown or revoked connector token.")
    row = db.get(PlantSimConfig, c.org_id)
    return {"config": _clean(_merged(row.config if row else None))}
