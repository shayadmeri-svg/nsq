from __future__ import annotations

from conftest import H


def test_pk_and_be_ratios():
    import app.lab  # noqa: F401  (core/ on sys.path)
    from chem import pk
    fast = pk.simulate([0, 5, 10, 30, 360], [0, 90, 100, 100, 100], 100, 10, 50, 1.5)
    slow = pk.simulate([0, 60, 180, 360], [0, 20, 40, 60], 100, 10, 50, 1.5, window_h=4)
    assert fast["absorbed_pct"] > 99 and slow["absorbed_pct"] < 50 and slow["cmax"] < fast["cmax"]
    c = pk.compare(slow, fast)
    assert c["risk"] == "high" and c["auc_ratio"] < 80
    assert pk.compare(fast, fast)["risk"] == "low"


def test_disproportionality_matches_hand_calculation():
    from app import safety
    # a=20 of drug 1000 reports; reaction 500 of 1,000,000 reports
    d = safety.disproportionality(20, 1000, 500, 1_000_000)
    # PRR = (20/1000) / (480/999000) = 41.6 ; ROR = (20/980)/(480/998520) = 42.45
    assert abs(d["prr"] - 41.63) < 0.05 and abs(d["ror"] - 42.45) < 0.05 and d["signal"]
    assert not safety.disproportionality(2, 1000, 500, 1_000_000)["signal"]  # n < 3


def test_faers_signals_parsing(monkeypatch):
    from app import safety
    safety._cache.clear()
    def fake(params):
        s, c = params.get("search"), params.get("count")
        if c == "patient.reaction.reactionmeddrapt.exact":
            return {"results": [{"term": "NAUSEA", "count": 40}, {"term": "HEPATOTOXICITY", "count": 30}]}
        if c == "patient.reaction.reactionoutcome":
            return {"results": [{"term": 5, "count": 7}]}
        if c:
            return {"results": [{"term": "SUN PHARMA", "count": 12}]}
        totals = {None: 20_000_000, 'patient.drug.openfda.generic_name:"TESTOL"': 2000,
                  'patient.reaction.reactionmeddrapt.exact:"NAUSEA"': 900_000, 'patient.reaction.reactionmeddrapt.exact:"HEPATOTOXICITY"': 20_000,
                  'patient.drug.openfda.generic_name:"TESTOL" AND serious:1': 800}
        return {"meta": {"results": {"total": totals.get(s, 0)}}}
    monkeypatch.setattr(safety, "_get", fake)
    r = safety.signals("Testol")
    assert r["found"] and r["reports"] == 2000 and r["serious_pct"] == 40.0 and r["fatal"] == 7
    hep = next(x for x in r["reactions"] if x["reaction"] == "Hepatotoxicity")
    assert hep["signal"] and r["reactions"][0]["reaction"] == "Hepatotoxicity"  # signals first
    assert r["manufacturers"][0]["name"] == "SUN PHARMA"


def test_survival_and_be_endpoints(root):
    s = root.get("/api/playground/survival?group=form&measure=months").json()
    assert len(s["curves"]) >= 2 and s["logrank"]["p"] < 1 and len(s["grid"]) == len(s["curves"][0]["sf"])
    assert root.get("/api/playground/survival?group=category&measure=shelf").json()["unit"] == "% of shelf life"
    assert root.get("/api/playground/survival?group=nope").status_code == 422
    b = root.post("/api/lab/molecule/paracetamol/bioequivalence", json={"d50_um": 150, "lag_min": 20, "window_h": 2}, headers=H).json()
    assert b["compare"]["risk"] in ("low", "moderate", "high") and b["test"]["pk"]["conc_mg_l"]
