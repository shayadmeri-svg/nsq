"""Eurveda Connect: the demo plant, agent config and jobs, ingest → batches, alarms and the live snapshot."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DB = Path(tempfile.mkdtemp()) / "connect.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["PLANT_SIM_TOKEN"] = "evd_test_token"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, catalog, live  # noqa: E402
from app.main import app  # noqa: E402

H = {"x-nsq-client": "test"}
AGENT = {**H, "Authorization": "Bearer evd_test_token"}
ADMIN = {"email": "root@example.com", "is_platform": True, "features": [], "org": None}


@pytest.fixture(scope="module")
def c():
    app.dependency_overrides[auth.current_user] = lambda: ADMIN
    with TestClient(app) as client:
        yield client


def _plant(c):
    return c.get("/api/connect/plants", headers=H).json()["plants"][0]["id"]


def test_demo_plant_shares_machines_between_products(c):
    d = c.get(f"/api/connect/plants/{_plant(c)}", headers=H).json()
    names = [e["name"] for e in d["equipment"]]
    assert names == ["RMG-1", "FBD-1", "BLENDER-1", "PRESS-1", "COATER-1"]
    routes = {p["name"].split()[0]: [next(e["name"] for e in d["equipment"] if e["id"] == st["equipment_id"]) for st in p["route"]] for p in d["products"]}
    assert routes["Paracetamol"] == names[:4] and routes["Azithromycin"] == names  # azithromycin adds the coater


def test_agent_gets_its_machines_from_the_wizard_config(c):
    cfg = c.get("/api/connect/agent/config", headers=AGENT).json()
    assert [m["name"] for m in cfg["machines"]] == ["RMG-1", "FBD-1", "BLENDER-1", "PRESS-1", "COATER-1"]
    fbd = cfg["machines"][1]
    assert fbd["protocol"] == "opcua" and fbd["batch"] == {"node": "ns=2;s=FBD1.BatchNo"} and fbd["tags"]["lod_pct"] == "ns=2;s=FBD1.LOD"
    assert c.get("/api/connect/agent/config", headers={**H, "Authorization": "Bearer nope"}).status_code == 401


def test_browse_job_round_trip_suggests_a_mapping(c):
    pid = _plant(c)
    fbd = next(e for e in c.get(f"/api/connect/plants/{pid}", headers=H).json()["equipment"] if e["name"] == "FBD-1")
    job = c.post(f"/api/connect/equipment/{fbd['id']}/browse", headers=H).json()
    picked = c.get("/api/connect/agent/jobs", headers=AGENT).json()["jobs"]
    assert picked[0]["id"] == job["id"] and picked[0]["request"]["machine"]["endpoint"].startswith("opc.tcp://")
    tags = [{"node": "ns=2;s=FBD1.InletTemp", "name": "FBD1.InletTemp", "value": 60.1}, {"node": "ns=2;s=FBD1.ExhaustTemp", "name": "FBD1.ExhaustTemp", "value": 41.0},
            {"node": "ns=2;s=FBD1.LOD", "name": "FBD1.LOD", "value": 2.1}, {"node": "ns=2;s=FBD1.BatchNo", "name": "FBD1.BatchNo", "value": "B1"},
            {"node": "ns=2;s=FBD1.Product", "name": "FBD1.Product", "value": "PCM500"}]
    c.post(f"/api/connect/agent/jobs/{job['id']}", json={"status": "done", "result": {"tags": tags}}, headers=AGENT)
    r = c.get(f"/api/connect/jobs/{job['id']}", headers=H).json()["result"]
    assert r["suggestion"]["inlet_c"]["tag"] == "ns=2;s=FBD1.InletTemp" and r["suggestion"]["outlet_c"]["tag"] == "ns=2;s=FBD1.ExhaustTemp"
    assert r["suggestion"]["lod_pct"]["tag"] == "ns=2;s=FBD1.LOD"
    assert r["batch_tag"] == "ns=2;s=FBD1.BatchNo" and r["product_tag"] == "ns=2;s=FBD1.Product"


def _push(c, machine, batch, product, values, ts):
    return c.post("/api/connect/agent/ingest", headers=AGENT, json={"readings": [
        {"machine": machine, "format": "", "ts": ts.isoformat(), "batch_no": batch, "product": product, "values": values}]}).json()


def test_batches_move_through_the_line_and_alarms_follow_each_products_ranges(c):
    pid = _plant(c)
    t = datetime.now(timezone.utc)
    # paracetamol on the press: force inside 10–16, then outside → a live alarm that closes when it comes back
    _push(c, "PRESS-1", "PCM-1", "PCM500", {"force_kn": 13.0, "tablet_weight_mg": 650}, t)
    _push(c, "PRESS-1", "PCM-1", "PCM500", {"force_kn": 17.5, "tablet_weight_mg": 650}, t + timedelta(seconds=5))
    s = c.get(f"/api/connect/plants/{pid}/live", headers=H).json()
    a = [x for x in s["alarms"] if x["active"] and x["batch"] == "PCM-1"]
    assert len(a) == 1 and a[0]["signal"] == "force_kn" and "10–16 kN" in a[0]["message"]
    press = next(e for e in s["equipment"] if e["name"] == "PRESS-1")
    assert press["status"] == "running" and press["product"]["name"].startswith("Paracetamol")
    assert next(x for x in press["signals"] if x["id"] == "force_kn")["zone"] == "alarm"
    # the same force is normal for azithromycin (12–18): a different product's range applies on the same machine
    _push(c, "PRESS-1", "AZI-2", "AZI500", {"force_kn": 17.5, "tablet_weight_mg": 760}, t + timedelta(seconds=10))
    s = c.get(f"/api/connect/plants/{pid}/live", headers=H).json()
    assert not [x for x in s["alarms"] if x["active"] and x["batch"] == "AZI-2"]
    # end-of-step check: LOD high while drying is expected; judged once the batch leaves the dryer
    _push(c, "FBD-1", "PCM-3", "PCM500", {"lod_pct": 15.0, "inlet_c": 60}, t)
    assert not [x for x in c.get(f"/api/connect/plants/{pid}/live", headers=H).json()["alarms"] if x["batch"] == "PCM-3"]
    _push(c, "FBD-1", "PCM-3", "PCM500", {"lod_pct": 3.6, "inlet_c": 60}, t + timedelta(seconds=5))
    _push(c, "FBD-1", "AZI-4", "AZI500", {"lod_pct": 18.0, "inlet_c": 55}, t + timedelta(seconds=10))  # next batch arrives
    end = [x for x in c.get(f"/api/connect/plants/{pid}/live", headers=H).json()["alarms"] if x["batch"] == "PCM-3"]
    assert len(end) == 1 and end[0]["signal"] == "lod_pct" and "end of the step" in end[0]["message"]
    b = next(x for x in c.get(f"/api/connect/plants/{pid}/live", headers=H).json()["batches"] if x["batch_no"] == "PCM-3")
    assert [s_["status"] for s_ in b["steps"]][:2] == ["pending", "done"]  # route order: RMG not seen, FBD done


def test_other_organisations_cannot_see_the_plant(c):
    pid = _plant(c)
    app.dependency_overrides[auth.current_user] = lambda: {"email": "x@other.test", "is_platform": False, "features": ["monitor"], "org": {"slug": "other"}}
    try:
        assert c.get(f"/api/connect/plants/{pid}/live", headers=H).status_code == 404
        assert c.get("/api/connect/plants", headers=H).json()["plants"] == []
    finally:
        app.dependency_overrides[auth.current_user] = lambda: ADMIN


def test_mapping_suggestions_for_camel_case_tags():
    sug = catalog.suggest_mapping("press", [{"node": "a", "name": "PRESS1.MainCompressionForce", "value": 12.0},
                                            {"node": "b", "name": "PRESS1.TabletWeight", "value": 650.0},
                                            {"node": "c", "name": "PRESS1.Status", "value": "RUN"}])
    assert sug["force_kn"]["tag"] == "a" and sug["tablet_weight_mg"]["tag"] == "b"


def test_zones():
    par = {"lo": 10, "hi": 20}
    assert [live.zone(v, par) for v in (9, 11, 15, 19, 21)] == ["alarm", "warn", "ok", "warn", "alarm"]
