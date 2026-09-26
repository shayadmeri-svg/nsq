from __future__ import annotations

import uuid
from datetime import datetime, timezone

from conftest import H, login
from test_api import _org, _user


def test_pipelines_overview_and_schedule(root):
    d = root.get("/api/pipelines").json()
    keys = {s["key"] for s in d["sources"]}
    assert {"orange_book", "ema", "clinical_trials", "fda_establishments", "cdsco"} <= keys
    assert {p["key"] for p in d["pipelines"]} == {"fetch-nsq", "sync-sources", "build-universe"}
    r = root.put("/api/pipelines/schedules/src-ema", json={"enabled": True, "frequency": "weekly", "hour": 4, "minute": 5, "weekday": 2, "day": 1}, headers=H)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["enabled"] and s["frequency"] == "weekly" and s["next_run_at"]
    assert root.put("/api/pipelines/schedules/ping", json={"enabled": True, "frequency": "daily", "hour": 1, "minute": 0}, headers=H).status_code == 404


def test_admin_cannot_schedule_destructive(client, root):
    email = f"a{uuid.uuid4().hex[:6]}@example.com"
    assert root.post("/api/admin/users", json={"email": email, "role": "admin", "password": "admin-pass-1"}, headers=H).status_code == 200
    client.post("/api/auth/logout", headers=H)
    login(client, email, "admin-pass-1")
    r = client.put("/api/pipelines/schedules/fetch-nsq", json={"enabled": True, "frequency": "daily", "hour": 6, "minute": 0}, headers=H)
    assert r.status_code == 403
    assert client.put("/api/pipelines/schedules/src-ema", json={"enabled": False, "frequency": "daily", "hour": 6, "minute": 0}, headers=H).status_code == 200


def test_member_cannot_see_pipelines(client, root):
    org = _org(root)
    email, pw = _user(root, org["slug"])
    client.post("/api/auth/logout", headers=H)
    login(client, email, pw)
    assert client.get("/api/pipelines").status_code == 403
    assert client.get("/api/pipelines/sites").status_code == 403


def test_watchlist_roundtrip(root):
    r = root.post("/api/pipelines/watchlist", json={"name": "Salbutamol Sulphate"}, headers=H)
    assert r.status_code == 200 and r.json()["key"] == "albuterol"
    items = root.get("/api/pipelines/watchlist").json()["items"]
    wid = next(w["id"] for w in items if w["key"] == "albuterol")
    assert root.delete(f"/api/pipelines/watchlist/{wid}", headers=H).status_code == 200


def test_sites_and_plant_from_site(root):
    res = root.get("/api/pipelines/sites?q=unicure").json()
    assert res["total"] >= 1
    site = res["items"][0]
    assert site["ontology_key"] == "unicure" and site["alerts"] > 0 and site["capabilities"]
    org = _org(root)  # ontology_keys=["unicure"]
    sug = root.get(f"/api/orgs/{org['slug']}/site-suggestions").json()
    assert any(s["id"] == site["id"] for s in sug["items"])
    r = root.post(f"/api/orgs/{org['slug']}/plants/from-site", json={"site_id": site["id"]}, headers=H)
    assert r.status_code == 200, r.text
    p = r.json()
    assert set(p["capability_basis"].values()) == {"inferred"} and p["reference"]["site_id"] == site["id"]
    assert root.post(f"/api/orgs/{org['slug']}/plants/from-site", json={"site_id": site["id"]}, headers=H).status_code == 409
    infra = root.get(f"/api/orgs/{org['slug']}/infrastructure").json()
    assert any(x["asset_id"] == p["asset_id"] for x in infra["plants"])
    detail = root.get(f"/api/pipelines/sites/{site['id']}").json()
    assert any(o["slug"] == org["slug"] and o["linked"] for o in detail["orgs"])


def test_scheduler_next_run_and_tick(root, monkeypatch):
    from app import jobs, scheduler
    from app.models import PipelineSchedule

    s = PipelineSchedule(job_key="x", frequency="daily", hour=6, minute=30, weekday=0, day=1)
    after = datetime(2026, 9, 26, 2, 0, tzinfo=timezone.utc)  # 07:30 IST
    assert scheduler.next_run(s, after).isoformat() == "2026-09-27T01:00:00+00:00"
    s.frequency, s.weekday = "weekly", 0
    assert scheduler.next_run(s, after).isoformat() == "2026-09-28T01:00:00+00:00"
    s.frequency, s.day = "monthly", 5
    assert scheduler.next_run(s, after).isoformat() == "2026-10-05T01:00:00+00:00"

    started = []
    monkeypatch.setattr(jobs, "launch", lambda job, params, by, email: started.append((job.key, params)) or type("R", (), {"id": 1})())
    root.put("/api/pipelines/schedules/build-universe", json={"enabled": True, "frequency": "daily", "hour": 3, "minute": 45}, headers=H)
    from app.db import SessionLocal
    with SessionLocal() as db:
        row = db.get(PipelineSchedule, "build-universe")
        row.next_run_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
    fired = scheduler.tick()
    assert "build-universe" in fired and started[-1][0] == "build-universe"
    assert scheduler.tick() == [] or "build-universe" not in scheduler.tick()
