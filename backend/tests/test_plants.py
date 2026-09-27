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


def _eu_fixture():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "redis-loader"))
    from sources import eudragmdp as e

    fx = root / "redis-loader" / "tests" / "fixtures" / "eudragmdp"
    docs = {}
    for i, (f, pc, city) in enumerate([("gmpc_fdf_emcure", "382865", "Vijapur"), ("gmpc_api_pharmazell", "600045", "Chennai"),
                                       ("ncr_aculife", "382150", "Ahmedabad"), ("gmpc_bio_serum", "411028", "Pune")]):
        d = e.parse_certificate((fx / f"{f}.html").read_text())
        docs[str(i)] = {**d, "id": str(i), "site_name": d["manufacturer"], "postcode": pc, "city": city}
    # a site on no CDSCO list
    docs["9"] = {**docs["0"], "id": "9", "oms_loc": "LOC-999", "site_name": "Zzyzx Remedies Private Limited", "manufacturer": "Zzyzx Remedies",
                 "postcode": "500090", "city": "Hyderabad", "address": "Plot 1, Hyderabad, 500090"}
    return {"data": e.build_sites(docs), "retrieved_at": "2026-09-27", "total_listed": 5}


def test_eu_gmp_merged_into_registry(monkeypatch):
    from app import plants

    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    eu = _eu_fixture()
    real = plants._load
    monkeypatch.setattr(plants, "_load", lambda name="cdsco_plants": (123.0, eu) if name == "eudragmdp" else real(name))
    monkeypatch.setattr(plants, "_cache", None)
    reg = plants.registry()
    ps = reg["plants"].values()
    emcure = next(p for p in ps if p.get("pin") == "382865" and "emcure" in p["name"].lower())
    assert emcure["eu"]["status"] == "compliant" and "eudragmdp" in emcure["sources"]
    prof = plants.catalog_profile(emcure)
    comp = [h for s in prof["sections"] for h in s["have"] if h["token"] == "compression"][0]
    assert comp["basis"] == "stated" and "1.2.1.13 Tablets" in comp["why"][0]
    aculife = [p for p in ps if p.get("pin") == "382150" and "aculife" in p["name"].lower()]
    assert aculife and all(p["eu"]["status"] == "non_compliant" for p in aculife)
    assert "critical deficiency" in aculife[0]["eu"]["documents"][0]["ncr"]["nature"]
    pz = next(p for p in ps if p.get("pin") == "600045" and "pharmazell" in p["name"].lower())
    assert pz["eu"]["substances"] and "api" in pz["capabilities"]["dosage_forms"]
    new = next(p for p in ps if p["id"].startswith("eu-zzyzx"))
    assert new["sources"] == ["eudragmdp"] and new["state"] == "Telangana" and "tablet" in new["capabilities"]["dosage_forms"]
    assert reg["meta"]["eudragmdp"]["eu_added"] >= 1
    s = plants.summary()
    assert s["eu_ncr"] >= 1 and any(t["key"] == "EU non-compliance statement" for t in s["tiers"])
    assert plants.search(cert="eu_ncr")["total"] >= 1
    b = plants.brief(emcure)
    assert b["eu_stated"]["compression"]
    monkeypatch.setattr(plants, "_cache", None)
