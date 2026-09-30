"""Feature entitlements (admin), persona visibility (org admin), and tenant isolation for org users."""

from __future__ import annotations

import json
import uuid

import pytest
from conftest import H, login


@pytest.fixture()
def user_client(app):
    """A second browser: the org user, while `root` stays signed in as the super admin."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def _org(root, keys=("unicure",), plants=("baddi-osd-a",)):
    r = root.post("/api/admin/orgs", json={"name": f"Org {uuid.uuid4().hex[:6]}", "ontology_keys": list(keys), "plant_ids": list(plants)}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["org"]


def _user(root, slug, role="member", persona="QA"):
    email = f"f{uuid.uuid4().hex[:8]}@example.com"
    r = root.post("/api/admin/users", json={"email": email, "role": role, "org_slug": slug, "password": "member-pass-1", "persona": persona}, headers=H)
    assert r.status_code == 200, r.text
    return email


def _as(user_client, email):
    user_client.post("/api/auth/logout", headers=H)
    return login(user_client, email, "member-pass-1")


def test_registry_and_base_package(user_client, root):
    m = root.get("/api/admin/features").json()
    ids = [f["id"] for f in m["registry"]]
    assert {"explore", "ledger", "forensics", "plants", "reactions"} <= set(ids)
    org = _org(root)
    me = _as(user_client, _user(root, org["slug"]))
    assert set(me["features"]) == set(m["base"])
    assert user_client.get("/api/playground/facets").status_code == 200  # explore is in the base package
    r = user_client.get("/api/lab/reactions/templates")
    assert r.status_code == 403 and "Reaction lab" in r.json()["detail"]


def test_entitlements_and_persona_visibility(user_client, root):
    org = _org(root)
    assert root.put(f"/api/admin/orgs/{org['slug']}/features", json={"features": ["explore", "reactions", "plants"]}, headers=H).status_code == 200
    assert root.put(f"/api/admin/orgs/{org['slug']}/features", json={"features": ["nope"]}, headers=H).status_code == 400
    admin_email = _user(root, org["slug"], role="org_admin")
    qa, execu = _user(root, org["slug"], persona="QA"), _user(root, org["slug"], persona="Executive")

    _as(user_client, admin_email)
    # org admin: cannot grant beyond what the organisation has
    assert user_client.put(f"/api/orgs/{org['slug']}/features/visibility", json={"visibility": {"QA": ["ledger"]}}, headers=H).status_code == 400
    r = user_client.put(f"/api/orgs/{org['slug']}/features/visibility", json={"visibility": {"Executive": ["explore"], "QA": None}}, headers=H)
    assert r.status_code == 200, r.text
    assert user_client.get("/api/lab/reactions/templates").status_code == 200  # admins see every entitled feature
    assert user_client.get("/api/admin/features").status_code == 403

    assert set(_as(user_client, qa)["features"]) == {"explore", "reactions", "plants"}
    assert user_client.get("/api/lab/reactions/templates").status_code == 200
    assert user_client.put(f"/api/orgs/{org['slug']}/features/visibility", json={"visibility": {}}, headers=H).status_code == 403

    assert _as(user_client, execu)["features"] == ["explore"]
    assert user_client.get("/api/lab/reactions/templates").status_code == 403
    assert user_client.get("/api/playground/cube").status_code == 200

    # removing a feature from the organisation removes it from every persona
    r = root.put(f"/api/admin/orgs/{org['slug']}/features", json={"features": ["reactions"]}, headers=H)
    assert r.status_code == 200, r.text
    assert _as(user_client, execu)["features"] == []


def test_no_cross_org_data(user_client, root):
    from app import data

    df = data.frame()
    counts = df["Mfg_Ontology_Key"].value_counts()
    mine, other = "unicure", next(k for k in counts.index if k != "unicure")
    org = _org(root, keys=(mine,))
    root.put(f"/api/admin/orgs/{org['slug']}/features", json={"features": ["explore", "ledger", "investigate", "plants", "forensics", "wc", "molecule"]}, headers=H)
    _as(user_client, _user(root, org["slug"], role="org_admin"))

    # addressed by id: someone else's manufacturer record is simply not there
    assert user_client.get(f"/api/playground/investigate/manufacturer/{other}").status_code == 404
    assert user_client.get(f"/api/playground/investigate/manufacturer/{other}/alerts").status_code == 404
    assert user_client.get(f"/api/playground/forensics/portfolio/maker", params={"key": other}).status_code == 404
    assert user_client.get(f"/api/playground/investigate/manufacturer/{mine}").status_code == 200

    # the ledger holds only our alerts
    led = user_client.get("/api/playground/ledger", params={"size": 250, "cols": ["company"]}).json()
    assert led["total"] == int(counts.get(mine, 0))

    # searching the national views by another company's name reveals nothing
    other_name = str(df.loc[df["Mfg_Ontology_Key"] == other, "Mfg_Company_Canonical"].dropna().iloc[0])
    body = user_client.get("/api/playground/cube").text
    from app.tenant import norm
    assert f'"{other_name}"' not in body
    top = user_client.get("/api/playground/cube").json()["top_manufacturers"]
    assert all(t["name"].startswith("Other manufacturer") or norm(t["name"]) in {norm(x) for x in df.loc[df["Mfg_Ontology_Key"] == mine, "Mfg_Company_Canonical"].dropna()}
               for t in top)
    srch = user_client.get("/api/playground/investigate/search", params={"q": other_name[:8]}).json()
    assert all(m["key"] == mine for m in srch["manufacturers"])

    # plants: only ours; another plant is not found
    pl = user_client.get("/api/plants", params={"size": 100}).json()
    root_pl = root.get("/api/plants", params={"size": 5}).json()
    assert pl["total"] < root_pl["total"]
    foreign = next(p["id"] for p in root_pl["items"] if p["id"] not in {x["id"] for x in pl["items"]})
    assert user_client.get(f"/api/plants/{foreign}").status_code == 404

    # platform staff still see everything
    assert root.get(f"/api/playground/investigate/manufacturer/{other}").status_code == 200
    assert not any(t["name"].startswith("Other manufacturer") for t in root.get("/api/playground/cube").json()["top_manufacturers"])


def test_scrub_unit():
    from app.tenant import Tenant, scrub

    t = Tenant(org_id=1, keys=frozenset({"acme"}), names=frozenset({"acme pharma"}), plants=frozenset(), profiles=frozenset(),
               peer_names=frozenset({"acme pharma", "beta labs ltd"}), all_plants=frozenset())
    out = scrub(t, {"top": [{"name": "Beta Labs Ltd", "count": 3}, {"name": "Acme Pharma", "count": 2}],
                    "manufacturer": "Gamma Remedies, Plot 4", "originator": "Beta Labs Ltd", "state": "Gujarat",
                    "Beta Labs Ltd": 5})
    assert out["top"][0]["name"].startswith("Other manufacturer") and out["top"][1]["name"] == "Acme Pharma"
    assert out["manufacturer"].startswith("Other manufacturer")  # name-like key: anything not ours
    assert out["originator"] == "Beta Labs Ltd" and out["state"] == "Gujarat"
    assert not any(k == "Beta Labs Ltd" for k in out)
    assert scrub(None, {"a": "Beta Labs Ltd"}) == {"a": "Beta Labs Ltd"}


def test_scrub_keeps_field_names_and_ordinary_words():
    from app.tenant import Tenant, scrub

    t = Tenant(org_id=1, keys=frozenset(), names=frozenset(), plants=frozenset(), profiles=frozenset(),
               peer_names=frozenset({"anchor", "product"}), all_plants=frozenset())
    out = scrub(t, {"anchor": True, "reactants": ["product", "citric acid"], "rows": ["Anchor"]})
    assert out["anchor"] is True and out["reactants"] == ["product", "citric acid"]
    assert out["rows"][0].startswith("Other manufacturer")  # a heatmap row label is a maker
