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
    assert "stated" in pa["capability_basis"].values() and pa["certifications"] == ["WHO-GMP (CDSCO COPP)"]
