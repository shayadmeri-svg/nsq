from __future__ import annotations

from conftest import H, login
from test_api import _org, _user


def test_playground_views(root):
    f = root.get("/api/playground/facets").json()
    assert f["form"] and f["months"]
    c = root.get("/api/playground/cube?focus=dissolution&form=Tablet").json()
    assert c["kpis"]["alerts"] > 0 and c["kpis"]["dissolution_share"] == 100.0
    assert c["heat_mfr_reason"]["rows"] and c["sankey_state"]["links"] and c["states"]
    led = root.get("/api/playground/ledger?cols=month&cols=product&cols=lab&sort=product&desc=false&size=10").json()
    assert [x["key"] for x in led["cols"]] == ["month", "product", "lab"] and len(led["rows"]) == 10
    assert led["rows"][0]["product"] <= led["rows"][-1]["product"]
    csv = root.get("/api/playground/ledger.csv?cols=month&cols=product&state=Gujarat")
    assert csv.status_code == 200 and csv.text.startswith("Month,Product")
    ins = root.get("/api/playground/insights").json()
    assert ins["shelf_life"]["rows"] and ins["repeat"]["concentration"] and "whitespace" in ins
    w = root.get("/api/playground/world?molecule=paracetamol").json()
    assert "IN" in w["markets"] and w["markets"]["IN"]["pics_member"] is False and w["molecule"]["key"] == "paracetamol"
    m = root.get("/api/playground/molecule/paracetamol?w_patent=1&w_regulatory=0&w_demand=0&w_plant=0").json()
    assert m["score"]["weights"]["patent"] == 1.0 and m["complexity"]["modality"]


def test_playground_open_to_members_but_plants_scoped(client, root):
    org = _org(root)
    assert root.put(f"/api/admin/orgs/{org['slug']}/features", json={"features": ["explore", "molecule"]}, headers=H).status_code == 200
    email, pw = _user(root, org["slug"])
    client.post("/api/auth/logout", headers=H)
    login(client, email, pw)
    assert client.get("/api/playground/cube").status_code == 200
    m = client.get("/api/playground/molecule/paracetamol").json()
    ids = {p["asset_id"] for p in m["plants"]}
    assert "baddi-osd-a" in ids  # the org's own plant (and unowned demo plants)


def test_spurious_kept_out_of_rankings(root):
    import pandas as pd
    from app import data, playground
    df = data.mark_spurious(pd.DataFrame({"NSQ Result": ["Assay fails", "Declared Spurious", "Batch not been manufactured by us"],
                                          "Manufactured By": ["A", "B", "C"]}))
    assert df["_spurious"].tolist() == [False, True, True]
    assert "science" not in playground.LEDGER_COLS and "regulation" not in playground.LEDGER_COLS
    sp = root.get("/api/playground/ledger?authenticity=spurious&cols=flag&size=10").json()
    assert all(r["flag"] for r in sp["rows"])
    c = root.get("/api/playground/cube").json()
    frame = data.frame()
    spur_makers = set(frame[frame["_spurious"]]["Mfg_Company_Canonical"]) - set(frame[~frame["_spurious"]]["Mfg_Company_Canonical"])
    assert not spur_makers & {m["name"] for m in c["top_manufacturers"]}
    assert all(s["intensity"] is None or s["intensity"] > 0 for s in c["states"]) and c["national_per_maker"] > 0
    ins = root.get("/api/playground/insights").json()
    assert ins["spurious"]["alerts"] == int(frame["_spurious"].sum())
    assert root.get("/api/playground/cube?authenticity=bogus").status_code == 422


def test_datamap(client, root):
    from app import datamap
    assert datamap.validate() == []
    g = root.get("/api/platform/datamap").json()
    assert {c["key"] for c in g["columns"]} >= {"origin", "stores", "pages"}
    assert g["stats"]["r_nsq"]["ok"] and "pg_audit" in g["stats"]
    stores = {m["store"] for m in g["mutations"]}
    assert {"pg_mol", "r_cdmo", "r_nsq", "pg_auth", "r_plant"} <= stores
    org = _org(root)
    email, pw = _user(root, org["slug"])
    client.post("/api/auth/logout", headers=H)
    login(client, email, pw)
    assert client.get("/api/platform/datamap").status_code == 403


def test_investigate_product_to_manufacturer_to_diagnosis(root):
    """Playground · Investigate (the retired Streamlit dashboard's investigation tab)."""
    s = root.get("/api/playground/investigate/search", params={"q": "paracetamol"}).json()
    assert s["products"] and all("paracetamol" in p["name"].lower() for p in s["products"])
    p = root.get("/api/playground/investigate/product", params={"name": s["products"][0]["name"]}).json()
    assert p["alerts"] == s["products"][0]["alerts"] and p["manufacturers"] and p["categories"]
    key = next(m["key"] for m in p["manufacturers"] if m["key"])
    m = root.get(f"/api/playground/investigate/manufacturer/{key}").json()
    assert m["kpis"]["alerts"] >= 1 and m["manufacturer"]["key"] == key
    alerts = root.get(f"/api/playground/investigate/manufacturer/{key}/alerts", params={"product": p["product"]}).json()
    assert alerts["total"] >= 1 and all(a["product"] == p["product"] for a in alerts["items"])
    d = root.get(f"/api/playground/investigate/manufacturer/{key}/alerts/{alerts['items'][0]['id']}").json()
    assert d["issue"]["id"] == alerts["items"][0]["id"] and "mitigations" in d["diagnosis"]
    assert root.get("/api/playground/investigate/product", params={"name": "no such product"}).status_code == 404


def test_failure_forensics(root):
    from app import forensics as F
    assert F.failed_tests("The sample does not conform to IP with respect to test for Dissolution and Assay") == ["Dissolution", "Assay / content"]
    o = root.get("/api/playground/forensics").json()
    assert o["available"] and o["groups"] > 0 and {a["id"] for a in o["archetypes"]} >= {"born", "ages", "plant"}
    lst = root.get("/api/playground/forensics/products", params={"size": 5}).json()
    g = lst["items"][0]
    d = root.get("/api/playground/forensics/product", params={"key": g["key"]}).json()
    assert d["signals"]["n"] == g["n"] and d["hypotheses"] and len(d["timing"]["product"]) == len(d["timing"]["bins"])
    assert root.get("/api/playground/forensics/product", params={"key": "nothing|Tablet"}).status_code == 404


def test_portfolio_and_needed(root):
    p = root.post("/api/playground/forensics/portfolio", json={"lines": ["Telmisartan 40 mg tablets", "", "telmisartan 40 mg tablets", "zzqx brand"]}, headers=H).json()
    assert p.get("available"), p
    assert len(p["rows"]) == 2  # blank and duplicate lines dropped
    tel = next(r for r in p["rows"] if r["input"].startswith("Telmisartan"))
    assert tel["form"] == "Tablet" and tel["alerts"] > 0 and tel["risk"] in ("high", "watch", "low")
    assert next(r for r in p["rows"] if r["input"] == "zzqx brand")["risk"] == "unknown"
    n = root.get("/api/playground/forensics/needed").json()
    assert n["available"] and {c["key"] for c in n["conditions"]} >= {"diabetes", "hypertension", "anaemia"}
    assert all(r["conditions"] for r in n["ranked"])


def test_portfolio_compare(root):
    from app import forensics as F
    d = F._frame()
    key = d[d["_group"] == d["_group"].value_counts().index[0]]["Mfg_Ontology_Key"].dropna().iloc[0]
    label = F._label(d["_group"].value_counts().index[0]).replace(" · ", " ")
    p = root.post("/api/playground/forensics/portfolio", json={"lines": [label], "compare_keys": [key], "compare_name": "X"}, headers=H).json()
    assert p["compare"]["name"] == "X" and p["rows"][0]["own"]["alerts"] >= 1


def test_reaction_lab(root):
    t = root.get("/api/lab/reactions/templates").json()
    assert {x["id"] for x in t["templates"]} >= {"first", "second", "consecutive", "parallel", "comp_consec", "reversible"}
    out = root.post("/api/lab/reactions/run", json={"template": "consecutive", "temp_c": 90, "hours": 6, "bp_c": 118,
                                                    "anchor": {"temp_c": 90, "hours": 6, "yield_pct": 80}}, headers=H).json()
    assert out["calibration"]["ok"] and abs(out["result"]["summary"]["yield_pct"] - 80) < 0.05
    assert out["map"]["best"]["yield_pct"] >= 80 and out["ea_band"]["mid"] and out["result"]["summary"]["criticality"] in (1, 3)
    v = root.get("/api/lab/reactions/validation").json()
    assert v["passed"] == v["total"]
