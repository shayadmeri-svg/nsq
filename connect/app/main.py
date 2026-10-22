"""Eurveda Connect: the integration service. Plants are described once — equipment from a catalog of types, how each
machine is reached and which of its tags is which signal, the products and their routes through the equipment — and
edge agents at the plant read the machines (OPC UA, Modbus, …) and stream here. It keeps the live state, tracks
batches as they move machine to machine, raises alarms against each product's ranges, and serves the plant monitor.

The cloud never connects into a plant: what the setup wizard needs from the plant floor (browse a machine's tags,
test-read them) is queued as a job the plant's agent picks up.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import catalog, live
from .auth import csrf, current_agent, current_user, plant_for, token_hash, visible_plants
from .db import Base, SessionLocal, engine, get_db
from .models import Agent, Alarm, Equipment, Job, Plant, Product, iso, utcnow
from .seed import seed_demo

log = logging.getLogger("connect")


async def _sweeper() -> None:
    while True:
        await asyncio.sleep(10)
        try:
            def sweep() -> None:
                with SessionLocal() as db:
                    live.sweep(db)
            await run_in_threadpool(sweep)
        except Exception as exc:  # noqa: BLE001 — never stop the sweeper
            log.warning("sweep failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_demo(db)
    live.BUS.bind(asyncio.get_running_loop())
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()


app = FastAPI(title="Eurveda Connect", lifespan=lifespan, dependencies=[Depends(csrf)], docs_url="/api/connect/docs", openapi_url="/api/connect/openapi.json")
P = "/api/connect"


@app.get(f"{P}/health")
def health():
    return {"ok": True}


# --- catalog & plant configuration (people) ------------------------------------------------------------------------

@app.get(f"{P}/catalog")
def get_catalog(user: dict = Depends(current_user)):
    return {"protocols": catalog.PROTOCOLS, "equipment_types": catalog.EQUIPMENT_TYPES, "profiles": catalog.PROFILES, "dosage_forms": catalog.DOSAGE_FORMS}


def _get(db: Session, model: Any, id_: int, missing: str) -> Any:
    row = db.get(model, id_)
    if row is None:
        raise HTTPException(404, missing)
    return row


def _eq(e: Equipment) -> dict[str, Any]:
    return {"id": e.id, "name": e.name, "type": e.type, "line": e.line, "position": e.position, "make": e.make, "model": e.model,
            "protocol": e.protocol, "connection": e.connection, "tag_map": e.tag_map, "batch_tag": e.batch_tag, "product_tag": e.product_tag,
            "agent_id": e.agent_id, "profile_id": e.profile_id}


def _prod(p: Product) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "molecule_key": p.molecule_key, "dosage_form": p.dosage_form, "codes": p.codes, "color": p.color, "route": p.route}


def _agent(a: Agent) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "token_hint": a.token_hint, "last_seen_at": iso(a.last_seen_at), "info": a.info}


@app.get(f"{P}/plants")
def plants(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    org = visible_plants(user)
    q = select(Plant).order_by(Plant.id) if org is None else select(Plant).where(Plant.org_slug == org)
    return {"plants": [{"id": p.id, "name": p.name, "org_slug": p.org_slug, "location": p.location} for p in db.scalars(q)]}


@app.post(f"{P}/plants")
def create_plant(body: dict = Body(...), user: dict = Depends(current_user), db: Session = Depends(get_db)):
    org = body.get("org_slug") if user.get("is_platform") else (user.get("org") or {}).get("slug")
    if not org:
        raise HTTPException(400, "Which organisation is the plant for?")
    p = Plant(org_slug=org, name=str(body.get("name") or "New plant")[:160], location=str(body.get("location") or "")[:160],
              timezone=str(body.get("timezone") or "Asia/Kolkata")[:60])
    db.add(p)
    db.commit()
    return {"id": p.id}


@app.get(f"{P}/plants/{{plant_id}}")
def plant(plant_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    p = plant_for(db, plant_id, user)
    return {"plant": {"id": p.id, "name": p.name, "location": p.location, "timezone": p.timezone, "org_slug": p.org_slug},
            "equipment": [_eq(e) for e in db.scalars(select(Equipment).where(Equipment.plant_id == p.id).order_by(Equipment.position, Equipment.id))],
            "products": [_prod(x) for x in db.scalars(select(Product).where(Product.plant_id == p.id).order_by(Product.id))],
            "agents": [_agent(a) for a in db.scalars(select(Agent).where(Agent.plant_id == p.id))]}


@app.put(f"{P}/plants/{{plant_id}}")
def update_plant(plant_id: int, body: dict = Body(...), user: dict = Depends(current_user), db: Session = Depends(get_db)):
    p = plant_for(db, plant_id, user)
    for k in ("name", "location", "timezone"):
        if k in body:
            setattr(p, k, str(body[k])[:160])
    db.commit()
    return {"ok": True}


_EQ_FIELDS = ("name", "type", "line", "position", "make", "model", "protocol", "connection", "tag_map", "batch_tag", "product_tag", "agent_id", "profile_id")


def _apply_eq(e: Equipment, body: dict[str, Any]) -> None:
    for k in _EQ_FIELDS:
        if k in body:
            setattr(e, k, body[k])
    if e.type not in catalog.TYPE_BY_ID:
        raise HTTPException(400, f"Unknown equipment type {e.type!r}.")
    if e.protocol not in catalog.PROTOCOL_BY_ID:
        raise HTTPException(400, f"Unknown protocol {e.protocol!r}.")
    if body.get("profile_id") and body["profile_id"] in catalog.PROFILE_BY_ID:  # a verified machine-model profile fills the mapping
        pr = catalog.PROFILE_BY_ID[body["profile_id"]]
        e.tag_map, e.batch_tag, e.product_tag, e.protocol = dict(pr["tags"]), pr["batch_tag"], pr.get("product_tag", ""), pr["protocol"]


@app.post(f"{P}/plants/{{plant_id}}/equipment")
def add_equipment(plant_id: int, body: dict = Body(...), user: dict = Depends(current_user), db: Session = Depends(get_db)):
    p = plant_for(db, plant_id, user)
    e = Equipment(plant_id=p.id, name="", type="rmg", connection={}, tag_map={})
    _apply_eq(e, {"position": len(list(db.scalars(select(Equipment.id).where(Equipment.plant_id == p.id)))), **body})
    if not e.name:
        raise HTTPException(400, "Give the machine a name (as the plant calls it, e.g. FBD-2).")
    db.add(e)
    db.commit()
    return _eq(e)


@app.put(f"{P}/equipment/{{eid}}")
def update_equipment(eid: int, body: dict = Body(...), user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = _get(db, Equipment, eid, "Machine not found.")
    plant_for(db, e.plant_id, user)
    _apply_eq(e, body)
    db.commit()
    return _eq(e)


@app.delete(f"{P}/equipment/{{eid}}")
def delete_equipment(eid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = _get(db, Equipment, eid, "Machine not found.")
    plant_for(db, e.plant_id, user)
    for p in db.scalars(select(Product).where(Product.plant_id == e.plant_id)):
        if any(st.get("equipment_id") == eid for st in p.route or []):
            raise HTTPException(409, f"{e.name} is on the route of {p.name}: take it off the route first.")
    db.delete(e)
    db.commit()
    return {"ok": True}


def _clean_route(db: Session, plant_id: int, route: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {e.id for e in db.scalars(select(Equipment).where(Equipment.plant_id == plant_id))}
    out = []
    for st in route or []:
        if st.get("equipment_id") not in ids:
            raise HTTPException(400, "A route step names a machine that is not on this plant.")
        params = {}
        for sig, par in (st.get("params") or {}).items():
            q = {k: (float(par[k]) if par.get(k) not in (None, "") else None) for k in ("ideal", "lo", "hi")}
            if q["lo"] is not None and q["hi"] is not None and q["lo"] > q["hi"]:
                raise HTTPException(400, f"{sig}: the low limit is above the high limit.")
            params[sig] = {**q, "check": "end" if par.get("check") == "end" else "continuous", "source": str(par.get("source") or "")[:240]}
        out.append({"equipment_id": st["equipment_id"], "params": params})
    return out


@app.post(f"{P}/plants/{{plant_id}}/products")
def add_product(plant_id: int, body: dict = Body(...), user: dict = Depends(current_user), db: Session = Depends(get_db)):
    p = plant_for(db, plant_id, user)
    pr = Product(plant_id=p.id, name=str(body.get("name") or "New product")[:160], molecule_key=str(body.get("molecule_key") or ""),
                 dosage_form=str(body.get("dosage_form") or "tablet"), codes=[str(c) for c in body.get("codes") or []],
                 color=str(body.get("color") or "#06a7c4"), route=_clean_route(db, p.id, body.get("route") or []))
    db.add(pr)
    db.commit()
    return _prod(pr)


@app.put(f"{P}/products/{{pid}}")
def update_product(pid: int, body: dict = Body(...), user: dict = Depends(current_user), db: Session = Depends(get_db)):
    pr = _get(db, Product, pid, "Product not found.")
    plant_for(db, pr.plant_id, user)
    for k in ("name", "molecule_key", "dosage_form", "color"):
        if k in body:
            setattr(pr, k, str(body[k]))
    if "codes" in body:
        pr.codes = [str(c) for c in body["codes"] or []]
    if "route" in body:
        pr.route = _clean_route(db, pr.plant_id, body["route"])
    db.commit()
    return _prod(pr)


@app.delete(f"{P}/products/{{pid}}")
def delete_product(pid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    pr = _get(db, Product, pid, "Product not found.")
    plant_for(db, pr.plant_id, user)
    db.delete(pr)
    db.commit()
    return {"ok": True}


@app.post(f"{P}/plants/{{plant_id}}/agents")
def add_agent(plant_id: int, body: dict = Body(default={}), user: dict = Depends(current_user), db: Session = Depends(get_db)):
    p = plant_for(db, plant_id, user)
    tok = "evd_" + secrets.token_urlsafe(32)
    a = Agent(plant_id=p.id, name=str(body.get("name") or "Plant agent")[:120], token_hash=token_hash(tok), token_hint=tok[:10], info={})
    db.add(a)
    db.commit()
    return {**_agent(a), "token": tok}


@app.delete(f"{P}/agents/{{aid}}")
def delete_agent(aid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    a = _get(db, Agent, aid, "Agent not found.")
    plant_for(db, a.plant_id, user)
    db.delete(a)
    db.commit()
    return {"ok": True}


# --- jobs the wizard asks an agent to run ------------------------------------------------------------------------------

def _machine_cfg(e: Equipment) -> dict[str, Any]:
    """The agent's machine entry (edge-agent/eurveda_agent.py config format)."""
    c = dict(e.connection or {})
    m = {"name": e.name, "format": e.type, "protocol": "modbus" if e.protocol == "modbus_tcp" else e.protocol,
         "poll_s": float(c.pop("poll_s", 5) or 5), "tags": e.tag_map or {}, **{k: v for k, v in c.items() if v not in (None, "")}}
    if e.batch_tag:
        m["batch"] = {"node": e.batch_tag} if e.protocol == "opcua" else {"fixed": e.batch_tag}
    if e.product_tag:
        m["product"] = {"node": e.product_tag} if e.protocol == "opcua" else {"fixed": e.product_tag}
    return m


def _job(db: Session, e: Equipment, kind: str, user: dict) -> dict[str, Any]:
    plant_for(db, e.plant_id, user)
    if not e.agent_id:
        raise HTTPException(400, "Choose which plant agent reaches this machine first.")
    if e.protocol not in ("opcua", "modbus_tcp"):
        raise HTTPException(400, f"{catalog.PROTOCOL_BY_ID[e.protocol]['label']}: browsing and test reads are for OPC UA and Modbus machines.")
    if kind == "browse" and e.protocol != "opcua":
        raise HTTPException(400, "Modbus has no tag names to browse: enter the register addresses from the machine's manual.")
    j = Job(agent_id=e.agent_id, equipment_id=e.id, kind=kind, request={"machine": _machine_cfg(e)})
    db.add(j)
    db.commit()
    return {"id": j.id, "status": j.status}


@app.post(f"{P}/equipment/{{eid}}/browse")
def browse(eid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = _get(db, Equipment, eid, "Machine not found.")
    return _job(db, e, "browse", user)


@app.post(f"{P}/equipment/{{eid}}/test")
def test_read(eid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    e = _get(db, Equipment, eid, "Machine not found.")
    return _job(db, e, "test", user)


@app.get(f"{P}/jobs/{{jid}}")
def job(jid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    j = _get(db, Job, jid, "Job not found.")
    e = db.get(Equipment, j.equipment_id) if j.equipment_id else None
    if e:
        plant_for(db, e.plant_id, user)
    return {"id": j.id, "kind": j.kind, "status": j.status, "result": j.result}


# --- live --------------------------------------------------------------------------------------------------------------

@app.get(f"{P}/plants/{{plant_id}}/live")
def live_snapshot(plant_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    plant_for(db, plant_id, user)
    return live.snapshot(db, plant_id)


STREAM_HEARTBEAT_S = 15.0  # at most this long between frames, so proxies keep the connection and idle machines show as idle
STREAM_MIN_GAP_S = 0.25    # readings arriving within this are sent together


@app.get(f"{P}/plants/{{plant_id}}/stream")
async def stream(plant_id: int, request: Request, user: dict = Depends(current_user)):
    """Server-sent events. On connect, `snapshot`: the whole live state with each signal's recent history. Then, when a
    machine reports (or a step finishes, or an alarm is acknowledged), `tick`: each machine without history, each
    signal's new readings as `append`, and only the other sections that changed. A tick also goes out every 15 s,
    so time-based states (a machine going idle) reach the screen; `retry` tells the browser to reconnect in 3 s."""
    with SessionLocal() as db:
        plant_for(db, plant_id, user)

    def frame(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"

    async def gen():
        marks: dict = {}
        sent: dict[str, str] = {}
        seen = live.BUS.version[plant_id]

        def snap(since):
            with SessionLocal() as db:
                return live.snapshot(db, plant_id, since=since, track=marks)

        full = await run_in_threadpool(snap, None)
        sent = {k: json.dumps(v, default=str) for k, v in full.items() if k not in ("equipment", "now")}
        yield "retry: 3000\n\n" + frame("snapshot", full)
        while not await request.is_disconnected():
            seen = await live.BUS.wait(plant_id, seen, STREAM_HEARTBEAT_S)
            await asyncio.sleep(STREAM_MIN_GAP_S)  # let a burst of readings settle into one frame
            seen = live.BUS.version[plant_id]
            d = await run_in_threadpool(snap, dict(marks))
            tick = {"now": d["now"], "equipment": d["equipment"]}
            for k, v in d.items():
                if k in ("equipment", "now"):
                    continue
                enc = json.dumps(v, default=str)
                if sent.get(k) != enc:
                    tick[k], sent[k] = v, enc
            yield frame("tick", tick)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.post(f"{P}/alarms/{{aid}}/ack")
def ack(aid: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    a = _get(db, Alarm, aid, "Alarm not found.")
    plant_for(db, a.plant_id, user)
    a.acked_by, a.active = user.get("email", "?"), False
    db.commit()
    live.BUS.notify(a.plant_id)
    return {"ok": True}


# --- edge agents -------------------------------------------------------------------------------------------------------

@app.get(f"{P}/agent/config")
def agent_config(agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    """What this agent reads: its machines as configured in the setup wizard (the agent re-reads this every minute)."""
    eqs = db.scalars(select(Equipment).where(Equipment.agent_id == agent.id).order_by(Equipment.position))
    return {"ingest_path": f"{P}/agent/ingest", "jobs_path": f"{P}/agent/jobs",
            "machines": [_machine_cfg(e) for e in eqs if e.tag_map and e.protocol in ("opcua", "modbus_tcp")]}


@app.post(f"{P}/agent/ingest")
def agent_ingest(body: dict = Body(...), agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    readings = body.get("readings") or []
    if not isinstance(readings, list) or len(readings) > 5000:
        raise HTTPException(413, "Send at most 5,000 readings per request.")
    if body.get("agent"):
        agent.info = {**(agent.info or {}), **{k: str(v)[:120] for k, v in body["agent"].items()}}
    return live.ingest(db, agent, readings)


@app.get(f"{P}/agent/jobs")
def agent_jobs(agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job).where(Job.agent_id == agent.id, Job.status == "queued").order_by(Job.id).limit(5)))
    for j in jobs:
        j.status = "running"
    db.commit()
    return {"jobs": [{"id": j.id, "kind": j.kind, "request": j.request} for j in jobs]}


@app.post(f"{P}/agent/jobs/{{jid}}")
def agent_job_result(jid: int, body: dict = Body(...), agent: Agent = Depends(current_agent), db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if j is None or j.agent_id != agent.id:
        raise HTTPException(404, "Job not found.")
    result = body.get("result") or {}
    if j.kind == "browse" and body.get("status") == "done":
        e = db.get(Equipment, j.equipment_id)
        tags = result.get("tags") or []
        result = {**result, "suggestion": catalog.suggest_mapping(e.type, tags) if e else {},
                  "batch_tag": catalog.suggest_batch_tag(tags), "product_tag": catalog.suggest_product_tag(tags)}
    j.status, j.result, j.finished_at = ("done" if body.get("status") == "done" else "failed"), result, utcnow()
    db.commit()
    return {"ok": True}
