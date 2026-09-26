"""build_universe: curated overlay, auto-discovery gated by public sources,
provenance marks, watchlist, output in the seed structure."""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "redis-loader"))
sys.path.insert(0, str(ROOT / "core"))


def _nsq(alerts, mfrs, labels=None, forms=None):
    return {"alerts": alerts, "mfrs": {f"m{i}" for i in range(mfrs)}, "forms": Counter(forms or {"tablet": alerts}),
            "labels": Counter(labels or {}), "last": "2026-07", "products": Counter(), "variants": set()}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for f in ("patent_seed.json", "regulatory_seed.json", "demand_seed.json"):
        shutil.copy(ROOT / "data" / f, tmp_path / f)
    (tmp_path / "sources").mkdir()

    def src(name, data):
        (tmp_path / "sources" / f"{name}.json").write_text(json.dumps({"source": name, "retrieved_at": "2026-09-27T00:00:00+00:00", "records": len(data), "data": data}))

    src("orange_book", {
        "amoxicillin": {"names": ["AMOXICILLIN"], "rld": {"trade_name": "AMOXIL", "applicant": "US ANTIBIOTICS", "dosage_form": "capsule", "route": "oral", "strength": "500MG", "appl_no": "050542", "approval": "1982-01-01"},
                        "nda_count": 1, "nda_active": 1, "anda_count": 30, "anda_active": 24, "anda_holders": [], "indian_anda_holders": ["AUROBINDO PHARMA LTD"],
                        "te_codes": {"AB": 40}, "patents": [], "exclusivity": [], "first_generic_approval": "1983-05-01", "last_patent_expiry": "",
                        "last_substance_patent_expiry": "", "last_exclusivity_expiry": "", "combo_products": 12, "dosage_forms": ["capsule", "tablet"]},
        "palbociclib": {"names": ["PALBOCICLIB"], "rld": {"trade_name": "IBRANCE", "applicant": "PFIZER INC", "dosage_form": "capsule", "route": "oral", "strength": "125MG", "appl_no": "207103", "approval": "2015-02-03"},
                        "nda_count": 2, "nda_active": 2, "anda_count": 0, "anda_active": 0, "anda_holders": [], "indian_anda_holders": [], "te_codes": {},
                        "patents": [{"no": "6936612", "expires": "2027-03-05", "substance": True, "product": True, "use_codes": []}],
                        "exclusivity": [], "first_generic_approval": "", "last_patent_expiry": "2027-03-05", "last_substance_patent_expiry": "2027-03-05",
                        "last_exclusivity_expiry": "", "combo_products": 0, "dosage_forms": ["capsule"]},
        "clavulanate": {"names": ["CLAVULANATE POTASSIUM"], "combo_products": 20, "combination_only": True},
    })
    src("ema", {"amoxicillin": {"inn": "amoxicillin", "therapeutic_areas": ["Bacterial Infections"], "atc": [], "originator": None,
                                "authorised": 0, "generics": 0, "biosimilars": 0, "orphan": False, "withdrawn": 0, "first_generic_authorised": "", "holders": [], "medicines": []}})
    src("clinical_trials", {"amoxicillin": {"term": "amoxicillin OR amoxycillin", "total": 400, "phase3plus": 120, "recent": 40, "india": 12, "fetched_at": "2026-09-27T00:00:00+00:00"}})
    gen = tmp_path / "generated"
    gen.mkdir()
    (gen / "watchlist.json").write_text(json.dumps([{"name": "Vitamin D", "exclude": True}, {"name": "Semaglutide"}]))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import build_universe as bu
    monkeypatch.setattr(bu, "nsq_stats", lambda url: {
        "amoxycillin": _nsq(157, 70, {"ip": 120}), "clavulanate": _nsq(118, 50), "vitamin d": _nsq(201, 90),
        "aceclofenac": _nsq(106, 60), "palbociclib": _nsq(3, 2), "tamoxifen": _nsq(12, 5),
    })
    return bu, tmp_path


def test_universe(env):
    bu, tmp = env
    u = bu.build(None, min_alerts=5, max_auto=50)
    rows = {r["key"]: r for r in u["molecules"]}
    # auto molecule confirmed by the Orange Book, keyed by the US name
    assert "amoxicillin" in rows and rows["amoxicillin"]["origin"] == "auto"
    assert set(rows["amoxicillin"]["sources"]) >= {"orange_book", "ema", "clinical_trials", "cdsco"}
    # combination-only and unconfirmed ingredients are skipped with a reason
    skipped = {s["name"]: s["reason"] for s in u["skipped"]}
    assert "no public source" in skipped["clavulanate"]
    assert "no public source" in skipped["aceclofenac"]
    assert skipped["vitamin d"] == "excluded by an admin"
    # watchlist addition included even without sources
    assert rows["semaglutide"]["origin"] in ("manual", "curated")
    # curated molecule overlaid with Orange Book data
    pats = {m["molecule_key"]: m for m in json.loads((tmp / "generated" / "patents.json").read_text())["molecules"]}
    pal = pats["palbociclib"]
    assert pal["origin"] == "curated"
    assert pal["estimated_loe_us"] == "2027-03-05"
    assert pal["provenance"]["loe_us"]["status"] == "sourced"
    assert pal["fto_risk"] == "high"
    assert any("6936612" in x["description"] for x in pal["formulation_patents"])
    amx = pats["amoxicillin"]
    assert amx["estimated_loe_us"] == "1983-05-01" and amx["fto_risk"] == "low"
    assert amx["estimated_loe_in"] and amx["provenance"]["loe_in"]["status"] == "derived"
    assert "amoxycillin" in amx["aliases"]
    regs = {m["molecule_key"]: m for m in json.loads((tmp / "generated" / "regulatory.json").read_text())["passports"]}
    assert regs["amoxicillin"]["te_code"] == "AB" and regs["amoxicillin"]["ip_2026_monograph"].startswith("IP")
    dem = {m["molecule_key"]: m for m in json.loads((tmp / "generated" / "demand.json").read_text())["profiles"]}
    assert dem["amoxicillin"]["competitor_anda_count"] == 24
    assert dem["amoxicillin"]["trial_count_total"] == 400
    assert dem["amoxicillin"]["cluster"] == "commodity"
    assert dem["amoxicillin"]["provenance"]["buyer_activity_score"]["status"] == "derived"
    cands = json.loads((tmp / "generated" / "candidates.json").read_text())
    assert any(c["key"] == "amoxicillin" for c in cands)


def test_loaders_accept_generated(env, monkeypatch):
    """The generated files parse with the models the loaders build."""
    bu, tmp = env
    bu.build(None, 5, 50)
    from intelligence_models import PatentIntelligence, RegulatoryPassport, DemandProfile  # noqa: F401
    import load_patents
    for raw in json.loads((tmp / "generated" / "patents.json").read_text())["molecules"]:
        e = PatentIntelligence(
            molecule_key=raw["molecule_key"], brand_name=raw.get("brand_name") or "", api_name=raw["api_name"],
            therapeutic_area=raw.get("therapeutic_area") or "", originator=raw.get("originator") or "",
            estimated_loe_us=load_patents._parse_month(raw.get("estimated_loe_us")),
            geo_coverage=[load_patents._parse_geo_coverage(g) for g in raw.get("geo_coverage", [])],
            provenance=raw.get("provenance") or {}, aliases=raw.get("aliases") or [], signals=raw.get("signals") or {},
        )
        back = PatentIntelligence.from_redis(e.to_redis())
        assert back.provenance == e.provenance and back.signals == json.loads(json.dumps(e.signals))


def test_typed_values_win_and_keep_source_value(env):
    bu, tmp = env
    (tmp / "generated" / "molecules.json").write_text(json.dumps([
        {"key": "amoxicillin", "name": "Amoxicillin", "by": "qa@example.com", "at": "2026-09-27",
         "values": {"estimated_loe_us": "2031-01-01", "market_size_usd_bn": 2.5, "aliases": ["amoxil"]}},
        {"key": "empagliflozin", "name": "Empagliflozin", "added": True, "by": "qa@example.com", "at": "2026-09-27",
         "values": {"api_name": "Empagliflozin", "brand_name": "Jardiance", "dosage_form": "Tablet", "te_code": "AB",
                    "patents": [{"kind": "formulation", "description": "Crystalline form", "jurisdiction": "IN",
                                 "expiry_date": "2029-05-01", "risk_level": "high"}]}},
    ]))
    u = bu.build(None, 5, 50)
    rows = {r["key"]: r for r in u["molecules"]}
    assert rows["empagliflozin"]["origin"] == "manual" and "brand_name" in rows["empagliflozin"]["entered"]
    assert rows["amoxicillin"]["origin"] == "auto"
    pats = {m["molecule_key"]: m for m in json.loads((tmp / "generated" / "patents.json").read_text())["molecules"]}
    amx = pats["amoxicillin"]
    assert amx["estimated_loe_us"] == "2031-01-01"
    prov = amx["provenance"]["loe_us"]
    assert prov["status"] == "entered" and prov["source_value"] == "1983-05-01" and "Orange Book" in prov["note"]
    assert amx["market_size_usd_bn"] == 2.5 and "amoxil" in amx["aliases"] and "amoxycillin" in amx["aliases"]
    emp = pats["empagliflozin"]
    assert emp["formulation_patents"][0]["jurisdiction"] == "IN"
    regs = {m["molecule_key"]: m for m in json.loads((tmp / "generated" / "regulatory.json").read_text())["passports"]}
    assert regs["empagliflozin"]["te_rating"] == "A"


def test_field_validation():
    import molecule_fields as mf
    assert mf.clean("estimated_loe_us", "2030-04") == "2030-04-01"
    assert mf.clean("aliases", "a, b\nc") == ["a", "b", "c"]
    with pytest.raises(mf.FieldError):
        mf.clean("fto_risk", "extreme")
    with pytest.raises(mf.FieldError):
        mf.clean("buyer_activity_score", 150)
    with pytest.raises(mf.FieldError):
        mf.clean("api_name", " ")
