"""Plant registry API (CDSCO WHO-GMP + SUGAM) and its link to the NSQ site directory."""

from __future__ import annotations

import pytest

from conftest import H, login


@pytest.fixture()
def admin(client):  # noqa: D103
    login(client, "root@example.com", "root-password-1")
    return client


def _have_registry() -> bool:
    from app import plants

    return bool(plants.registry()["plants"])


def test_registry_summary_list_detail(admin):
    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    s = admin.get("/api/plants/summary", headers=H).json()
    assert s["plants"] > 1000 and s["who_gmp"] > 1000
    assert s["nsq_sites_linked"] > 100 and 0 < s["nsq_alerts_linked_pct"] < 100
    caps = {c["key"]: c for c in s["capabilities"]}
    assert caps["tablet"]["plants"] > caps["lyophilised"]["plants"] > 0
    assert all(c["plants_with_nsq"] <= c["plants"] for c in s["capabilities"])

    r = admin.get("/api/plants", params={"capability": "svp_dry_powder", "segregated": "cephalosporin", "size": 10}, headers=H).json()
    assert r["total"] > 0
    assert all("svp_dry_powder" in p["dosage_forms"] and "cephalosporin" in p["segregated"] for p in r["items"])

    top = admin.get("/api/plants", params={"nsq": "yes", "size": 5}, headers=H).json()["items"]
    assert top and top[0]["nsq_alerts"] >= top[-1]["nsq_alerts"] > 0
    d = admin.get(f"/api/plants/{top[0]['id']}", headers=H).json()
    assert d["nsq"]["sites"] and d["capabilities"]["evidence"] is not None
    assert admin.get("/api/plants/nope", headers=H).status_code == 404


def test_site_detail_carries_registry_link(admin):
    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    from app import plants

    site_id, link = next((k, v) for k, v in plants.registry()["links"].items() if v["match"] == "site")
    d = admin.get(f"/api/pipelines/sites/{site_id}", headers=H).json()
    assert d["cdsco"]["match"] == "site" and d["cdsco"]["plants"][0]["id"] == link["plant_ids"][0]


def test_plant_from_site_adds_stated_capabilities():
    from app import plants, sites
    from intelligence_models import PlantAsset

    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    site_id = next(k for k, v in plants.registry()["links"].items() if v["match"] == "site" and plants.site_link(k)["plants"][0]["who_gmp"])
    pa = sites.plant_from_site(sites.get(site_id), "t-1", plants.site_link(site_id))
    PlantAsset(**pa)
    assert "required" in pa["capability_basis"].values() and pa["certifications"] == ["WHO_GMP"]


def test_org_plant_registry_match_and_apply(admin):
    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    import uuid

    from app import data
    import intelligence_store as store

    original = data.cdmo()["plants"]["ahmedabad-osd-liquid"]
    request_cleanup = lambda: (store.save_plant_asset(original, data.redis_client()), data.invalidate())  # noqa: E731
    r = admin.post("/api/admin/orgs", json={"name": f"Org {uuid.uuid4().hex[:6]}", "ontology_keys": ["unicure"], "plant_ids": ["ahmedabad-osd-liquid"]}, headers=H)
    slug = r.json()["org"]["slug"]
    before = admin.get(f"/api/orgs/{slug}/infrastructure").json()["plants"][0]
    c = admin.get(f"/api/orgs/{slug}/plants/ahmedabad-osd-liquid/registry").json()
    assert c["candidates"] and all(x["name_score"] >= 85 for x in c["candidates"])
    c = admin.get(f"/api/orgs/{slug}/plants/ahmedabad-osd-liquid/registry", params={"q": "Affy Parenterals"}).json()
    target = c["candidates"][0]
    assert target["who_gmp"] and target["required"] > 10
    p = admin.post(f"/api/orgs/{slug}/plants/ahmedabad-osd-liquid/registry", json={"plant_id": target["id"]}, headers=H).json()
    assert p["added"] and "WHO_GMP" in p["certifications_active"] and p["containment_class"] == "cytotoxic"
    basis = p["capability_basis"]
    assert basis["grade_a_cleanroom"] == "required" and basis["wfi_generation"] == "required"
    # nothing stated before is downgraded
    for t, b in (before["capability_basis"] or {}).items():
        if b == "stated":
            assert basis[t] == "stated"
    have = [h for s in p["sections"] for h in s["have"] if h["token"] == "grade_a_cleanroom"]
    assert have and "Grade A" in have[0]["why"]
    assert p["reference"]["registry"]["id"] == target["id"]
    request_cleanup()
