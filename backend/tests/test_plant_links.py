"""Registry matching without postcodes, and plant profiles linked to their official records."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from app import plants as P  # noqa: E402


def _reg(*plants):
    reg = {p["id"]: p for p in plants}
    return reg, *P._indexes(reg)


def test_fda_site_without_pin_joins_the_same_site():
    # the registry address says "Life Sciences Centre": that must not strip "life" from the company name
    reg, by_pin, by_tok = _reg({"id": "eu-rls", "name": "Reliance Life Sciences Private Limited", "district": "Thane", "state": "Maharashtra", "pin": "400701",
                                "address": "Dhirubhai Ambani Life Sciences Centre, R 282 TTC Area Of M.I.D.C., Thane Belapur Road, Rabale Navi Mumbai, Thane, Maharashtra, 400701, India"})
    got = P._find_plants(reg, by_pin, by_tok, "Reliance Life Sciences Private Limited", "", "Ttc Area Of Midc, R - 282 Dhirubhai Ambani Life Sciences Centre; Thane Belapur Road", "Navi Mumbai")
    assert got == ["eu-rls"]


def test_same_district_is_not_the_same_town():
    reg, by_pin, by_tok = _reg({"id": "eu-morepen", "name": "Morepen Laboratories Limited", "district": "Baddi", "state": "Himachal Pradesh", "pin": "173205",
                                "address": "Village Morepen, Nalagarh Baddi Road, Solan District, Baddi, Himachal Pradesh, 173205, India"})
    assert P._find_plants(reg, by_pin, by_tok, "Morepen Laboratories Limited", "", "Village Masulkhana, P.O. Parwanoo", "Solan") == []  # Parwanoo plant
    assert P._find_plants(reg, by_pin, by_tok, "Morepen Laboratories Limited", "", "Malkumajra, Nalagarh Road", "Baddi, Solan") == ["eu-morepen"]


def _asset(**kw):
    from intelligence_models import PlantAsset
    return PlantAsset(asset_id="demo-1", site_name="Demo", **kw)


def test_official_records_replace_stated_certifications(monkeypatch):
    reg_plant = {"id": "eu-x", "name": "X Ltd", "address": "Plot 1", "sources": ["eudragmdp", "fda_inspections"], "who_gmp_certified": False,
                 "capabilities": {"dosage_forms": ["tablet", "lyophilised"]},
                 "eu": {"key": "LOC-1", "status": "compliant", "certified": True, "last_gmp_inspection": "2025-01-01"},
                 "fda": {"fei": "9", "last_inspection": "2020-02-25", "last_code": "OAI", "oai_count": 1, "acceptable": False, "oai_recent": True},
                 "fda_records": [{"fei": "9", "profile": "u", "inspections": [{"date": "2020-02-25", "code": "OAI"}]}], "eu_records": ["LOC-1"]}
    monkeypatch.setattr(P, "registry", lambda: {"plants": {"eu-x": reg_plant}})
    monkeypatch.setattr(P, "_seed_links", lambda: {})
    a = _asset(certifications_active=["USFDA", "EU_GMP", "ANVISA"], approved_forms=["tablet"], reference={"registry_plant": "eu-x"})
    o = P.apply_official(a)
    assert o.certifications_active == ["EU_GMP", "FDA_OAI", "ANVISA"]  # ANVISA cannot be checked: kept as stated
    assert o.certifications_claimed == ["USFDA"] and "OAI" in o.certification_basis["USFDA"]
    assert "lyophilised" in o.approved_forms and o.capability_basis["lyophilised"] == "official"
    assert o.inspections[0]["authority"] == "EU (EudraGMDP)" and o.reference["official"]["certs"] == ["EU_GMP", "FDA_OAI"]
    # an organisation's confirmed link works the same way; an unlinked profile is untouched
    assert P.apply_official(_asset(certifications_active=["USFDA"], reference={"registry": {"id": "eu-x"}})).certifications_claimed == ["USFDA"]
    plain = _asset(certifications_active=["USFDA"])
    assert P.apply_official(plain) is plain


def test_profile_with_no_official_record(monkeypatch):
    monkeypatch.setattr(P, "_seed_links", lambda: {"demo-1": {"registry_plant": None, "registry_note": "Plant II is not in the official records."}})
    o = P.apply_official(_asset(certifications_active=["UK_MHRA", "EU_GMP", "WHO_GMP"]))
    assert o.certifications_active == ["UK_MHRA"] and o.certifications_claimed == ["EU_GMP", "WHO_GMP"]
    assert "Plant II" in o.certification_basis["EU_GMP"]
