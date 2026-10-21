"""Plant data: upload an apparatus file or stream readings from an edge agent, analyse, and keep it private to the organisation."""

from __future__ import annotations

import json
import uuid

import pytest
from conftest import H, login


@pytest.fixture()
def user_client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def _org(root):
    r = root.post("/api/admin/orgs", json={"name": f"Org {uuid.uuid4().hex[:6]}", "ontology_keys": [], "plant_ids": []}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["org"]["slug"]


def _upload(c, slug, fmt):
    csv = c.get(f"/api/plant-data/{slug}/formats/{fmt}/sample.csv").text
    p = c.post(f"/api/plant-data/{slug}/preview", files={"file": (f"{fmt}.csv", csv, "text/csv")}, headers=H)
    assert p.status_code == 200, p.text
    r = c.post(f"/api/plant-data/{slug}/datasets", files={"file": (f"{fmt}.csv", csv, "text/csv")},
               data={"format": p.json()["format"], "mapping": json.dumps(p.json()["mapping"]), "name": fmt}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_analyse_and_isolation(root, user_client):
    slug, other = _org(root), _org(root)
    assert _upload(root, slug, "batch_summary")["batches"] == 10
    _upload(root, slug, "press")
    a = root.post(f"/api/plant-data/{slug}/analysis", json={}, headers=H).json()
    assert a["counts"]["batches"] == 10 and {d["batch"] for d in a["diagnoses"]} == {"EX007", "EX009"}
    assert "pressure_mpa" in a["calibration"]["nor"]

    email = f"b{uuid.uuid4().hex[:8]}@example.com"
    assert root.post("/api/admin/users", json={"email": email, "role": "member", "org_slug": other, "password": "member-pass-1"}, headers=H).status_code == 200
    login(user_client, email, "member-pass-1")
    assert user_client.get(f"/api/plant-data/{slug}/datasets").status_code == 404  # another organisation's files
    assert user_client.get(f"/api/plant-data/{other}/datasets").json()["datasets"] == []


def test_upload_needs_a_batch_column(root):
    slug = _org(root)
    r = root.post(f"/api/plant-data/{slug}/datasets", files={"file": ("x.csv", "Assay\n99\n", "text/csv")},
                  data={"format": "qc_release", "mapping": json.dumps({"assay_pct": "Assay"})}, headers=H)
    assert r.status_code == 400 and "Batch number" in r.text


def test_edge_agent_ingest(root, client):
    slug = _org(root)
    c = root.post(f"/api/plant-data/{slug}/connectors", json={"name": "test agent"}, headers=H).json()
    tok = c["token"]
    bad = client.post("/api/ingest/plant-data", json={"readings": []}, headers={**H, "Authorization": "Bearer nope"})
    assert bad.status_code == 401
    rows = [{"machine": "FBD-1", "format": "fbd", "ts": f"2026-10-22T10:{m:02d}:00+00:00", "batch_no": "L1",
             "values": {"inlet_c": 60, "inlet_rh_pct": 8, "air_m3_h": 3000, "lod_pct": 20 - m / 4, "elapsed_min": m}} for m in range(0, 61, 5)]
    r = client.post("/api/ingest/plant-data", json={"agent": {"version": "test"}, "readings": rows}, headers={**H, "Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["accepted"] == len(rows)
    live = root.get(f"/api/plant-data/{slug}/live", headers=H).json()
    assert live["connectors"][0]["online"] and live["machines"][0]["batch_no"] == "L1"
    ds = root.get(f"/api/plant-data/{slug}/datasets", headers=H).json()["datasets"][0]
    assert ds["live"] and "drying_min" in ds["fields"]
    root.delete(f"/api/plant-data/{slug}/connectors/{c['id']}", headers=H)
    assert client.post("/api/ingest/plant-data", json={"readings": rows}, headers={**H, "Authorization": f"Bearer {tok}"}).status_code == 401
