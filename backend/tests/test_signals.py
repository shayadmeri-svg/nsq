"""Playground · Health & trade endpoints over small NFHS / IDSP / Comtrade files."""

import pytest

from conftest import H, login


@pytest.fixture()
def admin(client):  # noqa: D103
    login(client, "root@example.com", "root-password-1")
    return client


def _files(monkeypatch):
    from app import signals

    nfhs = {"retrieved_at": "2026-09-28", "records": 6, "rounds": ["NFHS-5", "NFHS-6"],
            "indicators": {"sugar_women": {"label": "Women 15+: high blood sugar or on medicine", "group": "Diabetes"}},
            "data": [{"level": "district", "state": "Kerala", "district": "Ernakulam", "round": "NFHS-5", "ind": "sugar_women", "value": 24.0},
                     {"level": "district", "state": "Kerala", "district": "Ernakulam", "round": "NFHS-6", "ind": "sugar_women", "value": 27.5},
                     {"level": "district", "state": "Kerala", "district": "Wayanad", "round": "NFHS-6", "ind": "sugar_women", "value": 19.0},
                     {"level": "district", "state": "Bihar", "district": "Patna", "round": "NFHS-6", "ind": "sugar_women", "value": 11.0},
                     {"level": "state", "state": "Bihar", "district": None, "round": "NFHS-6", "ind": "sugar_women", "value": 10.2},
                     {"level": "india", "state": "India", "district": None, "round": "NFHS-6", "ind": "sugar_women", "value": 14.1}]}
    idsp = {"retrieved_at": "2026-09-28", "records": 3, "diseases": {"Dengue": ["paracetamol"], "Cholera": ["azithromycin"]},
            "data": [{"state": "Kerala", "district": "Thrissur", "disease": "Dengue", "disease_key": "Dengue", "cases": 20, "deaths": 0, "week": "2026-W30", "reported": "2026-07-25"},
                     {"state": "Kerala", "district": "Thrissur", "disease": "Dengue", "disease_key": "Dengue", "cases": 12, "deaths": 1, "week": "2026-W31", "reported": "2026-08-01"},
                     {"state": "Bihar", "district": "Patna", "disease": "Cholera", "disease_key": "Cholera", "cases": 30, "deaths": 0, "week": "2026-W31", "reported": "2026-08-02"}]}
    ct = {"retrieved_at": "2026-09-28", "records": 4, "mode": "api", "hs": {"3004": {"label": "Medicaments, dosed", "group": "finished"}, "2941": {"label": "Antibiotics", "group": "api"}},
          "data": [{"year": 2024, "flow": "export", "hs": "3004", "partner_code": 0, "partner": "World", "value_usd": 2.0e10},
                   {"year": 2024, "flow": "export", "hs": "3004", "partner_code": 842, "partner": "USA", "partner_iso": "USA", "value_usd": 8.0e9},
                   {"year": 2024, "flow": "import", "hs": "2941", "partner_code": 156, "partner": "China", "partner_iso": "CHN", "value_usd": 9.0e8},
                   {"year": 2024, "flow": "import", "hs": "2941", "partner_code": 380, "partner": "Italy", "partner_iso": "ITA", "value_usd": 1.0e8}]}
    files = {"nfhs": nfhs, "idsp": idsp, "comtrade": ct}
    monkeypatch.setattr(signals, "_load", lambda name: files.get(name, {}))


def test_signals_endpoints(admin, monkeypatch):
    _files(monkeypatch)
    n = admin.get("/api/playground/signals/nfhs", headers=H).json()
    assert n["round"] == "NFHS-6" and n["previous_round"] == "NFHS-5" and n["india"] == 14.1
    assert n["districts"][0] == {"state": "Kerala", "district": "Ernakulam", "value": 27.5, "prev": 24.0, "change": 3.5}
    ker = next(s for s in n["states"] if s["name"] == "Kerala")
    assert ker["from_districts"] and ker["count"] == 23.2  # unweighted mean of its districts
    assert next(s for s in n["states"] if s["name"] == "Bihar")["count"] == 10.2
    o = admin.get("/api/playground/signals/outbreaks", headers=H).json()
    assert o["by_disease"][0]["disease"] == "Dengue" and o["by_disease"][0]["outbreaks"] == 2 and o["by_disease"][0]["deaths"] == 1
    assert o["series"]["months"] == ["2026-W30", "2026-W31"]
    assert admin.get("/api/playground/signals/outbreaks", params={"disease": "Cholera"}, headers=H).json()["states"] == [{"name": "Bihar", "count": 1}]
    t = admin.get("/api/playground/signals/trade", headers=H).json()
    assert next(c for c in t["codes"] if c["hs"] == "3004")["exports_musd"] == [20000.0]
    assert t["china_api_share"] == [{"year": 2024, "share_pct": 90.0, "imports_musd": 1000.0}]
    imp = admin.get("/api/playground/signals/trade", params={"flow": "import"}, headers=H).json()
    assert imp["partners"][0]["name"] == "China" and imp["partners"][0]["share_pct"] == 90.0
    assert admin.get("/api/playground/signals/meta", headers=H).json()["idsp"]["records"] == 3


def test_signals_missing(admin, monkeypatch):
    from app import signals

    monkeypatch.setattr(signals, "_load", lambda name: {})
    assert admin.get("/api/playground/signals/nfhs", headers=H).json() == {"available": False}
    assert admin.get("/api/playground/signals/trade", params={"flow": "sideways"}, headers=H).status_code == 422


def test_synthesis_endpoint(admin, monkeypatch):
    from app import signals

    ordj = {"retrieved_at": "2026-09-28", "records": 1, "licence": "CC BY-SA 4.0 — Open Reaction Database",
            "needs": {"hydrogenation": "Hydrogenation (H₂ under pressure, Pd/C, Raney Ni)"},
            "data": {"paracetamol": {"name": "Paracetamol", "reactions": 2, "sources": 1, "needs": {"hydrogenation": {"reactions": 1, "share_pct": 50.0}},
                                     "hazards": {}, "temp_c": {"min": 25, "median": 32.5, "max": 40, "n": 2}, "yield_median": 88,
                                     "solvents": {"Methanol": 1}, "catalysts": {}, "reagents": {}, "examples": [{"id": "r1", "needs": ["hydrogenation"]}]}}}
    monkeypatch.setattr(signals, "_load", lambda name: ordj if name == "ord" else {})
    s = admin.get("/api/playground/molecule/paracetamol/synthesis", headers=H).json()
    assert s["found"] and s["reactions"] == 2 and s["needs"][0]["key"] == "hydrogenation" and "H₂" in s["needs"][0]["equipment"]
    assert admin.get("/api/playground/molecule/nothing/synthesis", headers=H).json() == {"available": True, "found": False, "meta": signals._meta(ordj)}
