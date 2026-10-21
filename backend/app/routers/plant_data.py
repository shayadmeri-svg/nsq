"""Plant data (Playground): an organisation's own batch records — equipment / QC files uploaded, or machine readings
streamed by an edge agent over OPC UA / Modbus (edge-agent/) — each batch against its limits, why a batch failed,
the process twin calibrated to the plant, and a live forecast of the batches running now
(chem.batch_data, chem.process_twin).

Two routers: `router` (signed-in users, gated as the "plant-data" Playground feature) and `ingest_router` (the edge
agent, authenticated by its connector token)."""

from __future__ import annotations

import hashlib
import json
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
from ..models import BatchDataset, PlantConnector, User
from ..security import current_user, org_for_user

router = APIRouter(prefix="/api/plant-data/{slug}", tags=["plant-data"], dependencies=[Depends(features.gate)])
ingest_router = APIRouter(prefix="/api/ingest/plant-data", tags=["plant-data"])
DEMO_ORG = "eurveda-demo"  # the plant simulator's organisation unless PLANT_SIM_ORG says otherwise (main.py)
LIVE = "live:"  # filename prefix of datasets fed by a connector: live:<connector id>:<machine>
MAX_LIVE_ROWS = 3_000  # raw tail kept per live stream; older batches keep their per-batch values
MAX_LIVE_BATCHES = 300
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
            "live": (d.filename or "").startswith(LIVE)}


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


@router.post("/preview")
async def preview(slug: str, file: Optional[UploadFile] = File(None), text: Optional[str] = Form(None), format: Optional[str] = Form(None),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    org_for_user(db, slug, user)
    df, name = await _table(file, text)
    headers = list(df.columns)
    if format and format in bd.FORMAT_BY_ID:
        fmt, mapping = format, bd.match_headers(headers, bd.FORMAT_BY_ID[format]["fields"])
    else:
        fmt, mapping = bd.detect_format(headers)
    extra = {k: h for k, h in bd.match_headers([h for h in headers if h not in mapping.values()]).items() if k not in mapping}
    return {"filename": name, "format": fmt, "headers": headers, "mapping": {**mapping, **extra}, "rows": len(df),
            "preview": df.head(8).fillna("").to_dict(orient="records"), "unmapped": [h for h in headers if h not in {**mapping, **extra}.values()],
            "molecule_guess": _molecule_guess(df, {**mapping, **extra}), "batches": int(df[mapping["batch_no"]].nunique()) if "batch_no" in mapping else 0}


@router.post("/datasets")
async def create(slug: str, request: Request, file: Optional[UploadFile] = File(None), text: Optional[str] = Form(None),
                 format: str = Form(...), mapping: str = Form("{}"), name: str = Form(""), molecule_key: str = Form(""),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = org_for_user(db, slug, user)
    if format not in bd.FORMAT_BY_ID:
        raise HTTPException(400, "Unknown format.")
    df, fname = await _table(file, text)
    try:
        m = {k: v for k, v in json.loads(mapping or "{}").items() if k in bd.F and v in df.columns}
    except ValueError as exc:
        raise HTTPException(400, "Bad column mapping.") from exc
    if "batch_no" not in m:
        raise HTTPException(400, "Map a column to 'Batch number': batches are joined on it.")
    try:
        batches = bd.aggregate(df, format, m)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not batches:
        raise HTTPException(400, "No rows with a batch number.")
    ds = BatchDataset(org_id=org.id, name=(name or re.sub(r"\.[a-z]+$", "", fname))[:200], format=format, filename=fname[:240],
                      columns=list(df.columns), mapping=m, raw=df.fillna("").to_dict(orient="records"), batches=batches,
                      molecule_key=molecule_key[:160], uploaded_by=user.email)
    db.add(ds)
    db.commit()
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
    db.delete(ds)
    db.commit()
    audit(db, "batches.delete", user, "batch_dataset", ds_id, {"org": org.slug, "name": ds.name}, request)
    return {"ok": True}


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
    out = bd.analyse(bd.merge([{"name": d.name, "format": d.format, "batches": d.batches} for d in rows]), body.get("specs"), predict)
    return {**out, "molecule": molecule, "datasets": [_summary(d) for d in rows]}


def _calibration(rows: list[BatchDataset]) -> dict[str, Any]:
    """Twin baseline and ranges from the uploaded files (stable); from the live streams only when there are no files."""
    files = [d for d in rows if not (d.filename or "").startswith(LIVE)] or rows
    return bd.analyse(bd.merge([{"name": d.name, "batches": d.batches} for d in files]))["calibration"] if files else {"baseline": {}, "nor": {}}


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
        machines.append({"machine": d.name.removeprefix("Live · "), "dataset_id": d.id, "format": d.format,
                         "format_label": bd.FORMAT_BY_ID.get(d.format, {}).get("label", d.format), "batch_no": b,
                         "ts": last.get("timestamp"), "connector_id": int((d.filename or "live:0:").split(":")[1] or 0),
                         "latest": {k: _f(last.get(k)) for k in fields},
                         "series": {k: [_f(r.get(k)) for r in tail] for k in fields},
                         "fields": [{"id": k, "label": bd.F[k]["label"], "unit": bd.F[k]["unit"], "twin": k in bd.PARAM_IDS} for k in fields],
                         "batch_values": (d.batches or {}).get(b, {}).get("values", {})})
    out: dict[str, Any] = {"connectors": [_conn(c) for c in conns], "machines": machines, "forecasts": [], "specs": bd.specs_for()}
    if not molecule or not machines:
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
    out["molecule"] = {"key": molecule, "name": prof["name"], "dose_mg": mol.dose_mg}
    out["baseline"] = cal["baseline"]
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
