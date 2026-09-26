from __future__ import annotations

from conftest import H


def test_chem_core():
    import app.lab  # noqa: F401  (puts core/ on sys.path)
    from chem import molecule, product, thermo_props, crystallization
    p = molecule.profile("CC(=O)Nc1ccc(O)cc1", 169.8, 500.0, 0.46, "measured")
    assert p["descriptors"]["formula"] == "C8H9NO2" and p["solubility"]["mg_per_ml"] > 1
    d = product.dissolution(500, 14.0, 1.2e-5, d50_um=40)
    assert d["verdict"] == "pass" and d["pct"][-1] > 95
    assert product.dissolution(500, 0.05, 1.2e-5)["verdict"] == "fail"
    assert product.compaction(80, 12, 7)["p_for_target"]
    assert product.fluid_bed(60, 10, 300, 400)["regime"] == "overwetting"
    cu = thermo_props.curve(151.16, 169.8, 30500, "ethanol")
    r = crystallization.builtin({"curve": cu, "program": {"t0_c": 50, "t1_c": 5, "cool_min": 60, "hold_min": 10}})
    assert 0 < r["summary"]["yield_pct"] <= r["summary"]["max_yield_pct"] + 0.5


def test_lab_api(root):
    m = root.get("/api/lab/molecules").json()
    assert any(x["key"] == "paracetamol" and x["has_structure"] for x in m["molecules"])
    p = root.get("/api/lab/molecule/paracetamol").json()
    assert p["nsq"]["alerts"] > 0 and "<svg" in p["svg"]
    d = root.post("/api/lab/molecule/paracetamol/dissolution", json={"d50_um": 10}, headers=H).json()
    assert d["pct"] and d["verdict"] in ("pass", "fail")
    c = root.post("/api/lab/molecule/paracetamol/crystallization", json={"engine": "builtin"}, headers=H).json()
    assert c["engine"] == "builtin" and c["summary"]["yield_pct"] > 0
    assert root.post("/api/lab/fluid-bed", json={"dew_point_c": 70, "inlet_c": 60}, headers=H).status_code == 422
    assert root.get("/api/lab/molecule/nope").status_code == 404


def test_fetch_structure_on_demand(root, monkeypatch, tmp_path):
    from app import lab, medicines
    from app.config import settings
    live = settings.data_dir / "generated" / "structures_live.json"
    before = live.read_text() if live.exists() else None
    monkeypatch.setattr(medicines, "enrich_ingredient", lambda a: {**a, "smiles": "CC(=O)Oc1ccccc1C(=O)O", "structure_source": "PubChem", "pka_acid": 3.5, "links": {}})
    try:
        r = root.post("/api/lab/molecule/zzfetchtest/fetch-structure", headers=H)
        assert r.status_code == 200 and r.json()["smiles"]
        assert lab.structures()["zzfetchtest"]["pka_acid"] == 3.5
        monkeypatch.setattr(medicines, "enrich_ingredient", lambda a: {**a, "smiles": None, "sources": {"pubchem": {"status": "not found"}}})
        assert root.post("/api/lab/molecule/zznothing/fetch-structure", headers=H).status_code == 422
    finally:
        if before is None:
            live.unlink(missing_ok=True)
        else:
            live.write_text(before)
        lab._cache.clear()
