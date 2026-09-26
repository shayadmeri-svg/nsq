from __future__ import annotations

from conftest import H


def test_schema_and_lookup(root):
    s = root.get("/api/molecules/schema").json()
    keys = {f["key"] for f in s["fields"]}
    assert {"api_name", "estimated_loe_us", "dosage_form", "competitor_anda_count", "patents"} <= keys
    d = root.get("/api/molecules/lookup?name=Paracetamol").json()
    assert d["key"] == "paracetamol" and d["curated"] and d["tracked"]
    assert d["values"]["api_name"] and d["entered"] == {}
    new = root.get("/api/molecules/lookup?name=Zzzmadeupinib").json()
    assert not new["tracked"] and not new["confirmed"] and new["entry"] is None


def test_add_edit_revert_untrack(root, monkeypatch):
    from app import jobs
    started = []
    monkeypatch.setattr(jobs, "launch", lambda job, params, by, email: started.append(job.key) or type("R", (), {"id": 99})())

    bad = root.post("/api/molecules", json={"name": "Zzzmadeupinib", "values": {"fto_risk": "extreme"}}, headers=H)
    assert bad.status_code == 422 and "Freedom-to-operate" in bad.json()["detail"]

    r = root.post("/api/molecules", json={"name": "Zzzmadeupinib", "values": {
        "brand_name": "Madeup", "dosage_form": "Tablet", "estimated_loe_us": "2030-06", "aliases": "zmi\nzzz-inib",
        "patents": [{"kind": "formulation", "description": "Salt form", "jurisdiction": "IN", "expiry_date": "2031-01-01", "risk_level": "high"}]}}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] and body["run_id"] == 99 and started == ["build-universe"]
    assert body["values"]["estimated_loe_us"] == "2030-06-01" and body["values"]["aliases"] == ["zmi", "zzz-inib"]
    key = body["key"]

    look = root.get(f"/api/molecules/lookup?key={key}").json()
    assert look["entered"]["brand_name"] == "Madeup" and look["entry"]["added"]

    # null = back to the source value
    r = root.post("/api/molecules", json={"name": "Zzzmadeupinib", "key": key, "values": {"brand_name": None}, "rebuild": False}, headers=H)
    assert "brand_name" not in r.json()["values"]

    # editing a curated molecule stores only the typed fields and does not make it "added"
    r = root.post("/api/molecules", json={"name": "Paracetamol", "values": {"market_size_usd_bn": 1.1}, "rebuild": False}, headers=H)
    assert r.status_code == 200 and not r.json()["added"]
    r = root.post("/api/molecules", json={"name": "Paracetamol", "values": {"market_size_usd_bn": None}, "rebuild": False}, headers=H)
    assert root.delete("/api/molecules/paracetamol", headers=H).status_code == 404  # entry dropped when emptied

    d = root.delete(f"/api/molecules/{key}", headers=H)
    assert d.status_code == 200 and d.json()["untracked"]


def test_export_includes_entries(root, tmp_path, monkeypatch):
    import json
    from app import jobs
    monkeypatch.setattr(jobs.settings.__class__, "data_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(jobs, "launch", lambda *a, **k: type("R", (), {"id": 1})())
    root.post("/api/molecules", json={"name": "Qqqexportamab", "values": {"modality": "biologic"}}, headers=H)
    msg = jobs.export_watchlist()
    rows = json.loads((tmp_path / "generated" / "molecules.json").read_text())
    assert any(r["name"] == "Qqqexportamab" and r["added"] and r["values"]["modality"] == "biologic" for r in rows)
    assert "entered in the app" in msg


def test_only_super_admin_edits_molecules(client, root):
    import uuid
    from conftest import login
    email = f"a{uuid.uuid4().hex[:6]}@example.com"
    assert root.post("/api/admin/users", json={"email": email, "role": "admin", "password": "admin-pass-1"}, headers=H).status_code == 200
    client.post("/api/auth/logout", headers=H)
    login(client, email, "admin-pass-1")
    assert client.get("/api/auth/me").json()["user"]["permissions"]["edit_molecules"] is False
    assert client.get("/api/molecules/lookup?name=Paracetamol").status_code == 200
    assert client.post("/api/molecules", json={"name": "Zzzmadeupinib", "values": {}}, headers=H).status_code == 403
    assert client.delete("/api/molecules/paracetamol", headers=H).status_code == 403
    assert client.post("/api/pipelines/watchlist", json={"name": "Menthol", "exclude": True}, headers=H).status_code == 403
