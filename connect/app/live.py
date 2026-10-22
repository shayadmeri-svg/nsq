"""Readings in, live state and alarms out.

Every reading names its machine, and the machine's batch and product tags say which batch of which product it belongs
to. That product's route gives, for this machine's step, each signal's ideal value and acceptable range
(params: {signal: {ideal, lo, hi, check}}):

    check = "continuous"  judged on every reading: outside [lo, hi] opens an alarm, back inside closes it
    check = "end"         judged once, on the batch's last reading at that step (LOD at the end of drying, weight
                          gain at the end of coating) — their values mid-step are meant to be out of range

The zone shown on the dashboard: alarm (outside the range), warn (inside, in its outer 20 %), ok.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import catalog
from .models import Agent, Alarm, Batch, Equipment, Product, Reading, iso, utcnow

IDLE_S = float(os.environ.get("CONNECT_IDLE_S", "45"))  # no reading for this long: the machine has finished its batch
RETAIN_H = float(os.environ.get("CONNECT_RETAIN_H", "24"))
HISTORY = 120

_lock = threading.Lock()
LATEST: dict[int, dict[str, Any]] = {}  # equipment id → {ts, batch, product_id, values}
HIST: dict[tuple[int, str], deque] = defaultdict(lambda: deque(maxlen=HISTORY))
CURRENT: dict[int, str] = {}  # equipment id → batch on it now


def _ts(v: Any) -> datetime:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return utcnow()


def match_product(products: list[Product], label: str) -> Optional[Product]:
    l = (label or "").strip().lower()
    if not l:
        return None
    for p in products:
        if l == p.name.lower() or l in [c.lower() for c in (p.codes or [])]:
            return p
    return None


def step_params(p: Optional[Product], equipment_id: int) -> dict[str, Any]:
    for st in (p.route if p else []) or []:
        if st.get("equipment_id") == equipment_id:
            return st.get("params") or {}
    return {}


def zone(v: float, par: dict[str, Any]) -> str:
    lo, hi = par.get("lo"), par.get("hi")
    if lo is None and hi is None:
        return "none"
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return "alarm"
    if lo is not None and hi is not None:
        band = 0.2 * (hi - lo)
        if v < lo + band or v > hi - band:
            return "warn"
    return "ok"


def _label(e: Equipment, sig: str) -> tuple[str, str]:
    t = catalog.TYPE_BY_ID.get(e.type, {})
    s = next((s for s in t.get("signals", []) if s["id"] == sig), None)
    return (s["label"], s["unit"]) if s else (sig.replace("_", " "), "")


def _alarm(db: Session, e: Equipment, batch: str, p: Optional[Product], sig: str, v: float, par: dict[str, Any], end: bool) -> None:
    open_ = db.scalar(select(Alarm).where(Alarm.equipment_id == e.id, Alarm.signal == sig, Alarm.batch == batch, Alarm.active.is_(True)))
    label, unit = _label(e, sig)
    lim = f"{par.get('lo')}–{par.get('hi')} {unit}".strip()
    msg = f"{label} {v:.4g} {unit} {'at the end of the step' if end else ''} outside {lim}".replace("  ", " ")
    if open_:
        open_.value, open_.last_at, open_.message = v, utcnow(), msg
    else:
        db.add(Alarm(plant_id=e.plant_id, equipment_id=e.id, batch=batch, product_id=p.id if p else None, signal=sig,
                     level="alarm", message=msg, value=v, active=True))


def _close(db: Session, e: Equipment, batch: str, sig: str) -> None:
    for a in db.scalars(select(Alarm).where(Alarm.equipment_id == e.id, Alarm.signal == sig, Alarm.batch == batch, Alarm.active.is_(True))):
        if not a.acked_by:  # an unacknowledged excursion stays visible after it clears, as cleared
            a.active = False


def finish_step(db: Session, e: Equipment, batch: str) -> None:
    """The batch has left this machine: judge its end-of-step signals on their last values."""
    b = db.scalar(select(Batch).where(Batch.plant_id == e.plant_id, Batch.batch_no == batch))
    if b is None:
        return
    st = dict((b.steps or {}).get(str(e.id)) or {})
    if st.get("done"):
        return
    p = db.get(Product, b.product_id) if b.product_id else None
    for sig, par in step_params(p, e.id).items():
        v = (st.get("end") or {}).get(sig)
        if par.get("check") == "end" and v is not None and zone(float(v), par) == "alarm":
            _alarm(db, e, batch, p, sig, float(v), par, end=True)
    st["done"] = True
    b.steps = {**(b.steps or {}), str(e.id): st}


def ingest(db: Session, agent: Agent, readings: list[dict[str, Any]]) -> dict[str, Any]:
    eqs = {e.name: e for e in db.scalars(select(Equipment).where(Equipment.plant_id == agent.plant_id))}
    products = list(db.scalars(select(Product).where(Product.plant_id == agent.plant_id)))
    rows, rejected, seen = [], 0, set()
    batches: dict[str, Batch] = {}
    for rd in readings:
        e = eqs.get(str(rd.get("machine") or ""))
        vals = {k: float(v) for k, v in (rd.get("values") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if e is None or not vals:
            rejected += 1
            continue
        ts, batch = _ts(rd.get("ts")), str(rd.get("batch_no") or "").strip()
        p = match_product(products, str(rd.get("product") or ""))
        prev = CURRENT.get(e.id)
        if prev and prev != batch:
            finish_step(db, e, prev)
        CURRENT[e.id] = batch
        with _lock:
            LATEST[e.id] = {"ts": ts.isoformat(), "batch": batch, "product_id": p.id if p else None, "product_label": rd.get("product") or "", "values": vals}
            for s, v in vals.items():
                HIST[(e.id, s)].append([ts.isoformat(), round(v, 4)])
        rows += [Reading(plant_id=e.plant_id, equipment_id=e.id, ts=ts, signal=s, value=v, batch=batch) for s, v in vals.items()]
        if batch:
            b = batches.get(batch) or db.scalar(select(Batch).where(Batch.plant_id == e.plant_id, Batch.batch_no == batch))
            if b is None:
                b = Batch(plant_id=e.plant_id, batch_no=batch, product_id=p.id if p else None, product_label=str(rd.get("product") or ""), started_at=ts)
                db.add(b)
            batches[batch] = b
            st = dict((b.steps or {}).get(str(e.id)) or {"first": ts.isoformat()})
            st["last"], st["end"] = ts.isoformat(), {**(st.get("end") or {}), **vals}
            b.steps, b.last_seen_at = {**(b.steps or {}), str(e.id): st}, ts
            if p and not b.product_id:
                b.product_id = p.id
            for sig, par in step_params(p, e.id).items():
                if par.get("check", "continuous") == "continuous" and sig in vals:
                    if zone(vals[sig], par) == "alarm":
                        _alarm(db, e, batch, p, sig, vals[sig], par, end=False)
                    else:
                        _close(db, e, batch, sig)
        seen.add(e.name)
    db.add_all(rows)
    agent.info = {**(agent.info or {}), "last_push": utcnow().isoformat(), "machines": sorted(seen)}
    db.commit()
    return {"accepted": len(readings) - rejected, "rejected": rejected, "machines": sorted(seen)}


def sweep(db: Session) -> None:
    """Background: finish the steps of machines that have gone quiet; drop readings past retention."""
    now = utcnow()
    for eid, batch in list(CURRENT.items()):
        last = LATEST.get(eid, {}).get("ts")
        if batch and last and (now - _ts(last)).total_seconds() > IDLE_S:
            e = db.get(Equipment, eid)
            if e:
                finish_step(db, e, batch)
            CURRENT[eid] = ""
    db.execute(delete(Reading).where(Reading.ts < now - timedelta(hours=RETAIN_H)))
    db.commit()


def history_from_db(db: Session, e: Equipment, minutes: int = 20) -> None:
    """Refill the sparkline buffers after a restart."""
    since = utcnow() - timedelta(minutes=minutes)
    rows = db.scalars(select(Reading).where(Reading.equipment_id == e.id, Reading.ts >= since).order_by(Reading.ts)).all()
    with _lock:
        for r in rows[-HISTORY * 8:]:
            HIST[(e.id, r.signal)].append([iso(r.ts), round(r.value, 4)])
        if rows:
            last = rows[-1]
            vals = {r.signal: r.value for r in rows if r.ts == last.ts}
            LATEST.setdefault(e.id, {"ts": iso(last.ts), "batch": last.batch, "product_id": None, "product_label": "", "values": vals})


def snapshot(db: Session, plant_id: int) -> dict[str, Any]:
    eqs = list(db.scalars(select(Equipment).where(Equipment.plant_id == plant_id).order_by(Equipment.position, Equipment.id)))
    products = list(db.scalars(select(Product).where(Product.plant_id == plant_id).order_by(Product.id)))
    pmap = {p.id: p for p in products}
    agents = list(db.scalars(select(Agent).where(Agent.plant_id == plant_id)))
    now = utcnow()
    active = list(db.scalars(select(Alarm).where(Alarm.plant_id == plant_id, Alarm.active.is_(True)).order_by(Alarm.started_at.desc())))
    recent = list(db.scalars(select(Alarm).where(Alarm.plant_id == plant_id).order_by(Alarm.started_at.desc()).limit(30)))
    out_eq = []
    for e in eqs:
        if e.id not in LATEST:
            history_from_db(db, e)
        lt = LATEST.get(e.id)
        age = (now - _ts(lt["ts"])).total_seconds() if lt else None
        running = bool(lt and lt.get("batch") and age is not None and age < IDLE_S)
        p = pmap.get(lt.get("product_id")) if lt and running else None
        params = step_params(p, e.id)
        t = catalog.TYPE_BY_ID.get(e.type, {})
        sigs = []
        for s in t.get("signals", []):
            v = (lt or {}).get("values", {}).get(s["id"])
            if v is None and s["id"] not in (e.tag_map or {}):
                continue
            par = params.get(s["id"], {})
            sigs.append({"id": s["id"], "label": s["label"], "unit": s["unit"], "key": s["key"], "value": v,
                         "ideal": par.get("ideal"), "lo": par.get("lo"), "hi": par.get("hi"), "check": par.get("check", "continuous"),
                         "zone": "end" if par.get("check") == "end" and v is not None and running else (zone(v, par) if v is not None and par else "none"),
                         "history": [h[1] for h in list(HIST.get((e.id, s["id"]), []))[-60:]]})
        out_eq.append({"id": e.id, "name": e.name, "type": e.type, "type_label": t.get("label", e.type), "stage": t.get("stage", ""),
                       "make": e.make, "model": e.model, "protocol": e.protocol,
                       "status": "not connected" if not e.tag_map else "running" if running else "idle" if lt else "no data",
                       "last_ts": lt["ts"] if lt else None, "batch": lt.get("batch") if running else "",
                       "product": {"id": p.id, "name": p.name, "color": p.color} if p else None, "signals": sigs,
                       "alarms": sum(1 for a in active if a.equipment_id == e.id)})
    bl = list(db.scalars(select(Batch).where(Batch.plant_id == plant_id).order_by(Batch.started_at.desc()).limit(12)))
    batches = []
    for b in bl:
        p = pmap.get(b.product_id)
        route = [st["equipment_id"] for st in (p.route if p else [])] or [int(k) for k in (b.steps or {})]
        steps = []
        for eid in route:
            st = (b.steps or {}).get(str(eid))
            on_it = CURRENT.get(eid) == b.batch_no and LATEST.get(eid, {}).get("batch") == b.batch_no
            steps.append({"equipment_id": eid, "status": "running" if on_it and not (st or {}).get("done") else "done" if st else "pending"})
        batches.append({"batch_no": b.batch_no, "product": {"id": p.id, "name": p.name, "color": p.color} if p else {"name": b.product_label or "unknown product", "color": "#94a3b8"},
                        "started_at": iso(b.started_at), "last_seen_at": iso(b.last_seen_at), "steps": steps,
                        "complete": bool(steps) and all(s["status"] == "done" for s in steps),
                        "alarms": sum(1 for a in recent if a.batch == b.batch_no)})
    names = {e.id: e.name for e in eqs}
    shared = defaultdict(list)
    for p in products:
        for st in p.route or []:
            shared[st["equipment_id"]].append(p.id)
    return {
        "plant_id": plant_id, "now": now.isoformat(),
        "agents": [{"id": a.id, "name": a.name, "online": bool(a.last_seen_at and (now - a.last_seen_at.replace(tzinfo=a.last_seen_at.tzinfo or timezone.utc)).total_seconds() < 90),
                    "last_seen_at": iso(a.last_seen_at), "machines": (a.info or {}).get("machines", [])} for a in agents],
        "equipment": out_eq,
        "products": [{"id": p.id, "name": p.name, "color": p.color, "dosage_form": p.dosage_form, "molecule_key": p.molecule_key,
                      "route": [{"equipment_id": st["equipment_id"], "name": names.get(st["equipment_id"], "?"),
                                 "shared": len(shared[st["equipment_id"]]) > 1} for st in p.route or []]} for p in products],
        "batches": batches,
        "alarms": [{"id": a.id, "equipment": names.get(a.equipment_id, "?"), "batch": a.batch, "signal": a.signal, "message": a.message,
                    "level": a.level, "active": a.active, "acked_by": a.acked_by, "started_at": iso(a.started_at), "last_at": iso(a.last_at),
                    "product": pmap[a.product_id].name if a.product_id in pmap else ""} for a in (active + [a for a in recent if not a.active])[:30]],
        "counts": {"machines": len(eqs), "running": sum(1 for e in out_eq if e["status"] == "running"), "active_alarms": len(active),
                   "batches_running": sum(1 for b in batches if not b["complete"] and any(s["status"] == "running" for s in b["steps"]))},
    }
