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
    email, pw = _user(root, org["slug"])
    client.post("/api/auth/logout", headers=H)
    login(client, email, pw)
    assert client.get("/api/playground/cube").status_code == 200
    m = client.get("/api/playground/molecule/paracetamol").json()
    ids = {p["asset_id"] for p in m["plants"]}
    assert "baddi-osd-a" in ids  # the org's own plant (and unowned demo plants)
