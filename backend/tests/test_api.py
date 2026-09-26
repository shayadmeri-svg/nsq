from __future__ import annotations

import time
import uuid

from conftest import H, login


def _org(root, **kw):
    name = kw.pop("name", f"Org {uuid.uuid4().hex[:6]}")
    body = {"name": name, "ontology_keys": ["unicure"], "plant_ids": ["baddi-osd-a"], **kw}
    r = root.post("/api/admin/orgs", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["org"]


def _user(root, org_slug, role="member", password="member-pass-1"):
    email = f"u{uuid.uuid4().hex[:8]}@example.com"
    r = root.post("/api/admin/users", json={"email": email, "role": role, "org_slug": org_slug, "password": password}, headers=H)
    assert r.status_code == 200, r.text
    return email, password


def test_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/orgs").status_code == 401


def test_bad_password_and_csrf(client):
    assert client.post("/api/auth/login", json={"email": "root@example.com", "password": "nope-nope"}, headers=H).status_code == 401
    # No client header → rejected before auth.
    assert client.post("/api/auth/login", json={"email": "root@example.com", "password": "root-password-1"}).status_code == 403


def test_superadmin_seeded(root):
    me = root.get("/api/auth/me").json()["user"]
    assert me["role"] == "super_admin" and me["permissions"]["run_destructive_jobs"]


def test_org_dashboards(root):
    org = _org(root)
    for part in ("overview", "quality", "infrastructure", "opportunities", "eu-export"):
        r = root.get(f"/api/orgs/{org['slug']}/{part}")
        assert r.status_code == 200, (part, r.text)
    q = root.get(f"/api/orgs/{org['slug']}/quality").json()
    assert q["kpis"]["alerts"] > 0
    issues = root.get(f"/api/orgs/{org['slug']}/quality/issues?size=3").json()
    assert issues["total"] == q["kpis"]["alerts"] and len(issues["items"]) == 3
    detail = root.get(f"/api/orgs/{org['slug']}/quality/issues/{issues['items'][0]['id']}").json()
    assert "diagnosis" in detail and detail["diagnosis"]["product"]
    opp = root.get(f"/api/orgs/{org['slug']}/opportunities").json()
    assert opp["molecules"] and opp["has_plants"]
    eu = root.get(f"/api/orgs/{org['slug']}/eu-export").json()
    assert all(0 <= a["readiness_pct"] <= 100 for a in eu["assessments"])


def test_member_isolated_to_own_org(client, root):
    a, b = _org(root), _org(root, ontology_keys=["zee"])
    email, pw = _user(root, a["slug"])
    client.post("/api/auth/logout", headers=H)
    login(client, email, pw)
    assert client.get(f"/api/orgs/{a['slug']}/quality").status_code == 200
    assert client.get(f"/api/orgs/{b['slug']}/quality").status_code == 404
    assert [o["slug"] for o in client.get("/api/orgs").json()["orgs"]] == [a["slug"]]
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/nsq/summary").status_code == 403
    assert client.get("/api/jobs").status_code == 403


def test_org_admin_scope(client, root):
    a, b = _org(root), _org(root)
    email, pw = _user(root, a["slug"], role="org_admin")
    client.post("/api/auth/logout", headers=H)
    login(client, email, pw)
    ok = client.post("/api/admin/users", json={"email": f"x{uuid.uuid4().hex[:6]}@example.com", "role": "member", "password": "abcdefgh1"}, headers=H)
    assert ok.status_code == 200 and ok.json()["user"]["org"]["slug"] == a["slug"]
    other = client.post("/api/admin/users", json={"email": f"y{uuid.uuid4().hex[:6]}@example.com", "role": "member", "org_slug": b["slug"], "password": "abcdefgh1"}, headers=H)
    assert other.status_code == 403
    esc = client.post("/api/admin/users", json={"email": f"z{uuid.uuid4().hex[:6]}@example.com", "role": "admin", "password": "abcdefgh1"}, headers=H)
    assert esc.status_code == 403
    # org admin can add a plant to their own org
    r = client.post(f"/api/orgs/{a['slug']}/plants", json={"name": "Test Line", "capabilities": ["wet_granulation", "compression", "film_coating", "blister_packing", "serialization"], "certifications": ["WHO_GMP", "EU_GMP"]}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["asset_id"] in client.get(f"/api/orgs/{a['slug']}").json()["org"]["plant_ids"]


def test_invite_flow(client, root):
    org = _org(root)
    email = f"inv{uuid.uuid4().hex[:6]}@example.com"
    r = root.post("/api/admin/users", json={"email": email, "role": "member", "org_slug": org["slug"]}, headers=H)
    link = r.json()["invite"]["link"]
    token = link.rsplit("/", 1)[1]
    client.post("/api/auth/logout", headers=H)
    assert client.get(f"/api/auth/invite/{token}").json()["email"] == email
    r = client.post("/api/auth/accept-invite", json={"token": token, "name": "New Person", "password": "new-pass-123"}, headers=H)
    assert r.status_code == 200 and r.json()["user"]["org"]["slug"] == org["slug"]
    # single use
    assert client.get(f"/api/auth/invite/{token}").status_code == 404


def test_deactivated_user_cannot_login(client, root):
    org = _org(root)
    email, pw = _user(root, org["slug"])
    uid = next(u["id"] for u in root.get("/api/admin/users").json()["users"] if u["email"] == email)
    assert root.patch(f"/api/admin/users/{uid}", json={"is_active": False}, headers=H).status_code == 200
    client.post("/api/auth/logout", headers=H)
    assert client.post("/api/auth/login", json={"email": email, "password": pw}, headers=H).status_code == 401


def test_job_run_and_destructive_guard(root):
    jobs = {j["key"]: j for j in root.get("/api/jobs").json()["jobs"]}
    assert {"ping", "refresh-nsq", "restore-snapshot"} <= set(jobs)
    r = root.post("/api/jobs/refresh-nsq/run", json={"params": {}}, headers=H)
    assert r.status_code == 400 and "confirm" in r.json()["detail"]
    run = root.post("/api/jobs/ping/run", json={}, headers=H).json()["run"]
    for _ in range(50):
        got = root.get(f"/api/jobs/runs/{run['id']}").json()["run"]
        if got["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert got["status"] == "succeeded", got["log"]
    audit = root.get("/api/admin/audit?action=job").json()
    assert audit["total"] >= 1
