"""Plant registry API (CDSCO WHO-GMP + SUGAM) and its link to the NSQ site directory."""

from __future__ import annotations

import uuid

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
    for cert in ("who_gmp", "eu_gmp", "eu_ncr", "us_fda", "fda_oai", "sugam", "schedule_c", "loan"):
        assert admin.get("/api/plants", params={"cert": cert}, headers=H).status_code == 200, cert


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

    original = data.cdmo()["plants"]["goa-osd-liquid"]
    request_cleanup = lambda: (store.save_plant_asset(original, data.redis_client()), data.invalidate())  # noqa: E731
    r = admin.post("/api/admin/orgs", json={"name": f"Org {uuid.uuid4().hex[:6]}", "ontology_keys": ["unicure"], "plant_ids": ["goa-osd-liquid"]}, headers=H)
    slug = r.json()["org"]["slug"]
    before = admin.get(f"/api/orgs/{slug}/infrastructure").json()["plants"][0]
    c = admin.get(f"/api/orgs/{slug}/plants/goa-osd-liquid/registry").json()
    assert c["candidates"] and all(x["name_score"] >= 85 for x in c["candidates"])
    c = admin.get(f"/api/orgs/{slug}/plants/goa-osd-liquid/registry", params={"q": "Affy Parenterals"}).json()
    target = c["candidates"][0]
    assert target["who_gmp"] and target["required"] > 10
    p = admin.post(f"/api/orgs/{slug}/plants/goa-osd-liquid/registry", json={"plant_id": target["id"]}, headers=H).json()
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


def test_summary_can_leave_out_api_only_plants(admin):
    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    a = admin.get("/api/plants/summary", headers=H).json()
    f = admin.get("/api/plants/summary", params={"exclude_api_only": "true"}, headers=H).json()
    assert f["exclude_api_only"] and a["api_only_plants"] > 0 and f["plants"] == a["plants"] - a["api_only_plants"]


def test_who_can_make_a_molecule(admin):
    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    r = admin.get("/api/plants/for-molecule/telmisartan", headers=H).json()
    assert r["molecule"]["forms"] == ["tablet"] and r["capable_total"] > 100
    assert r["made_total"] > 0 and r["made"][0]["alerts_for_molecule"] >= r["made"][-1]["alerts_for_molecule"]
    assert all("tablet" in p["dosage_forms"] for p in r["capable"])
    assert admin.get("/api/plants/for-molecule/not-a-molecule", headers=H).status_code == 404


def test_retired_plant_ids_are_renamed(admin):
    """Old demo ids (named after the wrong city) move to the new ids on startup."""
    import json as _json
    import redis as _redis
    from sqlalchemy import select as _select
    from app import main as app_main
    from app.config import settings as _settings
    from app.db import SessionLocal
    from app.models import Org as _Org, Plant as _Plant

    seed = _json.loads((_settings.data_dir / "plant_assets_seed.json").read_text())
    old, new = "ahmedabad-osd-liquid", seed["retired_ids"]["ahmedabad-osd-liquid"]
    assert new == "goa-osd-liquid" and new in {a["asset_id"] for a in seed["assets"]}
    r = _redis.from_url(_settings.redis_url)
    r.set(f"cdmo:plant:{old}", "{}")
    with SessionLocal() as db:
        org = _Org(name=f"Retired {uuid.uuid4().hex[:6]}", slug=f"retired-{uuid.uuid4().hex[:6]}", ontology_keys=[], plant_ids=[old, "baddi-osd-a"])
        db.add(org)
        db.merge(_Plant(asset_id=old, payload={**next(a for a in seed["assets"] if a["asset_id"] == new), "asset_id": old}))
        db.commit()
        oid = org.id
    app_main.rename_retired_plants()
    assert not r.exists(f"cdmo:plant:{old}") and r.exists(f"cdmo:plant:{new}")
    with SessionLocal() as db:
        assert db.get(_Org, oid).plant_ids == [new, "baddi-osd-a"]
        assert db.get(_Plant, old) is None and db.get(_Plant, new).payload["asset_id"] == new
        db.delete(db.get(_Plant, new)); db.commit()


def test_eu_sites_split_by_plot_numbers():
    """One company, one PIN, different plots = different plants; a re-registration of one site folds in."""
    from app import plants as pl

    assert pl._same_site("Plant I L-14 Verna Industrial Estate, Goa, 403722", "(Plant I), L14, Verna Indl. Area, Goa 403 722", "403722")
    assert not pl._same_site("Plant II L 32 33 And 34 Verna Industrial Estate, 403722", "(Plant I), L14, Verna Goa 403 722", "403722")
    assert pl._same_site("Unit IV Plot S 20 To S 26 Pharma Sez, 509301", "Plot No's S-20 to S-26, Green Industrial Park, 509301", "509301")
    assert pl._same_site("Village Katha, Baddi", "HB 211, Village Katha", "173205")  # no plot number on one side
    assert pl._eu_pin({"postcode": "IN 173205"}) == "173205"

    def site(key, name, address, forms_code, last):
        return {"key": key, "name": name, "address": address, "city": "South Goa", "postcode": "403722", "status": "compliant",
                "last_gmp_inspection": last, "scope": [{"code": forms_code, "label": "", "details": []}]}

    reg = {"indoco--403722--l14": {"id": "indoco--403722--l14", "name": "Indoco Remedies Ltd", "pin": "403722", "state": "Goa",
                                   "district": "South Goa", "address": "(Plant I), L14, Verna Indl. Area, Verna Salcete Goa 403 722",
                                   "capabilities": {"dosage_forms": ["tablet"]}, "sources": ["cdsco_who_gmp"]}}
    eu = {"a": site("a", "Indoco Remedies Limited", "Plant I L-14 Verna Industrial Estate, 403722", "1.2.1.13", "2025-11-24"),
          "b": site("b", "Indoco Remedies Limited", "Plant II L 32 33 And 34 Verna Industrial Estate, 403722", "1.1.1.4", "2025-05-09"),
          "c": site("c", "Indoco Remedies Limited", "L - 32 33 And 34 IDC Verna Industrial Road, 403722", "1.1.1.4", "2023-04-25")}
    stats = pl._merge_eu(reg, eu)
    assert reg["indoco--403722--l14"]["eu_records"] == ["a"]
    assert "svp_liquid" not in reg["indoco--403722--l14"]["capabilities"]["dosage_forms"]  # Plant II's sterile line stays on Plant II
    plant2 = [p for pid, p in reg.items() if pid.startswith("eu-")]
    assert len(plant2) == 1 and plant2[0]["eu_records"] == ["b", "c"] and plant2[0]["eu"]["key"] == "b"
    assert stats["eu_matched"] == 1 and stats["eu_added"] == 1 and stats["eu_folded"] == 1


def test_fda_inspections_attach_by_pin_and_plot():
    """FDA sites join registry plants like EU sites; unmatched inspected sites become plants; import alert blocks 'acceptable'."""
    from app import plants as pl

    reg = {"indoco--403722--l14": {"id": "indoco--403722--l14", "name": "Indoco Remedies Ltd", "pin": "403722", "state": "Goa",
                                   "district": "South Goa", "address": "(Plant I), L14, Verna Indl. Area, Verna Salcete Goa 403 722",
                                   "capabilities": {"dosage_forms": ["tablet"]}, "sources": ["cdsco_who_gmp"]}}
    recent = "2025-11-24"
    fda = {"3002807456": {"fei": "3002807456", "key": "3002807456", "name": "INDOCO REMEDIES LIMITED", "address": "L-14 Verna Industrial Area",
                          "city": "Verna", "postcode": "403722", "last_inspection": recent, "last_code": "VAI", "oai_count": 0,
                          "inspections": [{"date": recent, "code": "VAI"}]},
           "3005550001": {"fei": "3005550001", "key": "3005550001", "name": "Indoco Remedies Limited", "address": "L-32, 33 & 34 Verna",
                          "city": "Verna", "postcode": "403722", "last_inspection": recent, "last_code": "NAI", "oai_count": 0, "inspections": []},
           "3005550002": {"fei": "3005550002", "key": "3005550002", "name": "Redlist Labs Pvt Ltd", "address": "Plot 7", "city": "Hyderabad",
                          "postcode": "500076", "last_inspection": "2024-01-01", "last_code": "NAI", "oai_count": 0, "inspections": []}}
    stats = pl._merge_fda(reg, fda, {"3005550002"})
    p1 = reg["indoco--403722--l14"]
    assert p1["fda"]["fei"] == "3002807456" and p1["fda"]["acceptable"] and "fda_inspections" in p1["sources"]
    assert stats == {"fda_sites": 3, "fda_matched": 1, "fda_added": 2, "fda_folded": 0}  # Plant II (L-32) is a separate plant
    red = next(p for pid, p in reg.items() if pid.startswith("fda-redlist"))
    assert red["fda"]["import_alert"] and not red["fda"]["acceptable"] and red["state"] == "Telangana"
    b = pl.brief(p1)
    assert b["fda_ok"] and b["fda_code"] == "VAI" and not b["fda_oai"]
    assert pl._matches(p1, "", "", "", "", "us_fda", "") and not pl._matches(red, "", "", "", "", "us_fda", "")
    assert pl._matches(red, "", "", "", "", "fda_oai", "")


def test_who_can_make_it_lists_dmf_and_cep_holders(admin, monkeypatch):
    """Active Type II DMFs and valid CEPs for the API, linked to registry plants by company name."""
    if not _have_registry():
        pytest.skip("data/sources/cdsco_plants.json not present")
    from app import plants

    dmf = {"data": {"18990": {"number": "18990", "status": "active", "type": "II", "date": "2005-11-28",
                              "holder": "GLENMARK LIFE SCIENCES LTD", "subject": "TELMISARTAN USP"},
                    "20001": {"number": "20001", "status": "inactive", "type": "II", "date": "2007-01-05",
                              "holder": "OLD CHEM LTD", "subject": "TELMISARTAN"},
                    "20002": {"number": "20002", "status": "active", "type": "II", "date": "2010-01-05",
                              "holder": "ZHEJIANG SOMEWHERE CO LTD", "subject": "TELMISARTAN"}},
           "retrieved_at": "2026-09-27"}
    cep = {"data": {"R1-CEP 2010-123-Rev 03": {"number": "R1-CEP 2010-123-Rev 03", "holder": "GLENMARK LIFE SCIENCES LIMITED IN",
                                               "substance": "Telmisartan", "valid": True, "date": "2024-03-15"}}}
    real = plants._load
    monkeypatch.setattr(plants, "_load", lambda name="cdsco_plants": (777.0, dmf) if name == "fda_dmf" else (778.0, cep) if name == "edqm_cep" else real(name))
    plants._filings_cache = None
    plants._makers_cache.clear()
    r = admin.get("/api/plants/for-molecule/telmisartan", headers=H).json()
    assert r["dmf_total"] == 2 and r["cep_total"] == 1  # inactive DMF dropped
    glen = next(x for x in r["dmf"] if x["number"] == "18990")
    assert glen["plants"] and all("glenmark" in p["name"].lower() for p in glen["plants"])
    assert r["dmf"][0]["number"] == "18990" and not next(x for x in r["dmf"] if x["number"] == "20002")["plants"]
    assert r["cep"][0]["plants"] and r["dmf_in_registry"] == 1 and r["cep_in_registry"] == 1
    plants._filings_cache = None
    plants._makers_cache.clear()
