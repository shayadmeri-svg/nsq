from __future__ import annotations

from conftest import H

NDC = {"results": [
    {"product_ndc": "0597-0039", "brand_name": "Micardis HCT", "labeler_name": "Boehringer", "dosage_form": "TABLET", "route": ["ORAL"],
     "active_ingredients": [{"name": "TELMISARTAN", "strength": "40 mg/1"}, {"name": "HYDROCHLOROTHIAZIDE", "strength": "12.5 mg/1"}],
     "pharm_class": ["Angiotensin 2 Receptor Blocker [EPC]"], "openfda": {"unii": ["U5SYW473RQ"]}},
    {"product_ndc": "1", "brand_name": "Other", "dosage_form": "TABLET", "route": ["ORAL"],
     "active_ingredients": [{"name": "TELMISARTAN", "strength": "80 mg/1"}]},
]}
LABEL = {"results": [{"set_id": "abc", "inactive_ingredient": ["INACTIVE INGREDIENTS: magnesium stearate, meglumine, povidone (K-25), sodium hydroxide, sorbitol and lactose monohydrate."]}]}
RX = {"drugGroup": {"conceptGroup": [{"tty": "SCD", "conceptProperties": [{"name": "hydrochlorothiazide 12.5 MG / telmisartan 40 MG Oral Tablet"}]}]}}
RXCUI = {"idGroup": {"rxnormId": ["301620"]}}
CHEMBL = {"molecules": [{"molecule_chembl_id": "CHEMBL1017", "pref_name": "TELMISARTAN", "max_phase": "4.0", "first_approval": 1998,
                         "atc_classifications": ["C09CA07"], "molecule_type": "Small molecule",
                         "molecule_structures": {"canonical_smiles": "CCCc1nc2c(C)cc(-c3nc4ccccc4n3C)cc2n1Cc1ccc(-c2ccccc2C(=O)O)cc1"},
                         "molecule_properties": {"cx_most_apka": "3.65", "cx_most_bpka": "5.62", "cx_logp": "7.25", "full_mwt": "514.63"}}]}


def _fake_get(url, params=None):
    if "ndc.json" in url:
        return NDC
    if "label.json" in url:
        return LABEL
    if "drugs.json" in url:
        return RX
    if "rxcui.json" in url:
        return RXCUI
    if "molecule/search" in url:
        q = (params or {}).get("q", "").lower()
        return CHEMBL if "telmisartan" in q else {"molecules": []}
    if "mechanism" in url:
        return {"mechanisms": [{"mechanism_of_action": "Type-1 angiotensin II receptor antagonist"}]}
    return None


def test_lookup_merges_sources_and_lists_gaps(monkeypatch):
    from app import medicines as M
    monkeypatch.setattr(M, "_get", _fake_get)
    monkeypatch.setattr(M, "pubchem", lambda name: None)
    r = M.lookup("Telmisartan 40 mg + Hydrochlorothiazide 12.5 mg Tablets IP")
    names = [a["name"] for a in r["ingredients"]]
    assert names == ["Telmisartan", "Hydrochlorothiazide"] and r["dosage_form"] == "Tablet" and r["route"] == "Oral"
    t = r["ingredients"][0]
    assert t["smiles"] and t["structure_source"] == "ChEMBL" and t["pka_acid"] == 3.65 and t["max_phase"] == 4.0
    assert t["mechanisms"] == ["Type-1 angiotensin II receptor antagonist"]
    assert "meglumine" in r["excipients"] and "povidone" in r["excipients"]
    assert r["us_market"]["products"] == 1 and r["identifiers"]["rxcui"] == "301620"
    gaps = {g["item"]: g["status"] for g in r["gaps"]}
    assert gaps["Telmisartan: structure"] == "ok" and gaps["Hydrochlorothiazide: structure"] == "missing"
    assert gaps["India approval (CDSCO)"] == "info"


def test_lookup_survives_unreachable_sources(monkeypatch):
    import requests
    from app import medicines as M
    def boom(url, params=None):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(M, "_get", boom)
    monkeypatch.setattr(M, "pubchem", lambda name: None)
    r = M.lookup("Amoxycillin & Potassium Clavulanate Tablets I.P. 625 mg")
    assert [a["name"] for a in r["ingredients"]] == ["Amoxycillin", "Potassium Clavulanate"]
    assert r["sources"]["openfda_ndc"]["status"] == "unreachable" and r["sources"]["product_strength"] == "625 mg"


def test_save_list_and_lab_structures(root):
    body = {"name": "Telmisartan 40 mg Tablets", "dosage_form": "Tablet", "route": "Oral", "excipients": ["meglumine"],
            "ingredients": [{"name": "Zzmedicinib", "role": "active", "strength": {"value": 40, "unit": "mg"},
                             "smiles": "CC(=O)Nc1ccc(OC)cc1", "structure_source": "typed", "pka_base": 5.1}]}
    r = root.post("/api/medicines", json={**body, "track": False}, headers=H)
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert r.json()["gap_score"]["total"] > 5
    assert any(x["id"] == mid for x in root.get("/api/medicines").json()["items"])
    from app import lab
    s = lab.structures()
    key = r.json()["ingredients"][0]["molecule_key"]
    assert s[key]["smiles"] and s[key]["pka_base"] == 5.1
    assert root.post("/api/lab/structure", json={"smiles": "CCO"}, headers=H).json()["svg"].startswith("<svg")
    assert root.post("/api/lab/structure", json={"smiles": "nonsense("}, headers=H).status_code == 422
    assert root.post("/api/medicines", json={**body, "ingredients": []}, headers=H).status_code == 422
    assert root.delete(f"/api/medicines/{mid}", headers=H).json()["ok"]


def test_salt_forms_share_parent_structure_and_medicines_align(root):
    from app import lab
    lab._cache.clear()
    mols = {m["key"]: m for m in root.get("/api/lab/molecules").json()["molecules"]}
    assert mols["amlodipine_besylate"]["has_structure"] and "amlodipine" not in mols  # folded, no duplicate
    assert root.get("/api/lab/molecule/amlodipine").json()["key"] == "amlodipine_besylate"
    body = {"name": "Amlodipine 5 mg Tablets", "dosage_form": "Tablet", "track": True,
            "ingredients": [{"name": "Amlodipine", "role": "active", "strength": {"value": 5, "unit": "mg"}}]}
    r = root.post("/api/medicines", json=body, headers=H).json()
    assert r["ingredients"][0]["molecule_key"] == "amlodipine_besylate" and r["tracked"] == []
    root.delete(f"/api/medicines/{r['id']}", headers=H)


def test_medicine_tracks_new_active(root, monkeypatch):
    from app.routers import molecules
    monkeypatch.setattr(molecules, "_rebuild", lambda user: 77)
    body = {"name": "Zzqtrackinib 10 mg Tablets", "dosage_form": "Tablet",
            "ingredients": [{"name": "Zzqtrackinib", "role": "active", "strength": {"value": 10, "unit": "mg"}}]}
    r = root.post("/api/medicines", json=body, headers=H).json()
    assert r["tracked"] == ["zzqtrackinib"] and r["run_id"] == 77
    e = root.get("/api/molecules/lookup?key=zzqtrackinib").json()
    assert e["entered"]["strength"] == "10 mg" and e["entry"]["added"]
    root.delete(f"/api/medicines/{r['id']}", headers=H)
    root.delete("/api/molecules/zzqtrackinib", headers=H)
