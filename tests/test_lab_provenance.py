"""Lab profile provenance: measured (cited) values win over estimates, and verdicts are withheld
when they would rest on unknowns. Structures and NSQ counts are stubbed (no Redis/Postgres)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import lab  # noqa: E402

IBU = "CC(C)Cc1ccc(cc1)C(C)C(=O)O"
HSDB = {"source": "Hazardous Substances Data Bank (HSDB)", "url": "https://pubchem.ncbi.nlm.nih.gov/source/hsdb/3099"}


@pytest.fixture
def stub(monkeypatch):
    recs = {
        "ibu_measured": {"key": "ibu_measured", "name": "Ibuprofen", "smiles": IBU, "source": "PubChem", "cid": 3672,
                         "url": "https://pubchem.ncbi.nlm.nih.gov/compound/3672", "xlogp": 3.5, "mp_c": 76.0, "aliases": [],
                         "exp": {"solubility_water_mg_ml": {"value": 0.021, "t_c": 25.0, "text": "In water, 21 mg/L at 25 °C", **HSDB},
                                 "pka": [{"value": 4.91, "kind": None, "text": "pKa = 4.91", **HSDB}],
                                 "logp": {"value": 3.97, "text": "log Kow = 3.97", **HSDB}}},
        "ibu_bare": {"key": "ibu_bare", "name": "Ibuprofen", "smiles": IBU, "source": "PubChem", "cid": 3672, "url": None,
                     "xlogp": 3.5, "mp_c": 76.0, "aliases": []},
    }
    nsq = {"alerts": 3, "dissolution": 1, "dissolution_pct": 33.3, "categories": [], "forms": [], "strengths_mg": [400.0],
           "max_strength_mg": 400.0, "other_strengths": False}
    monkeypatch.setattr(lab, "structures", lambda: recs)
    monkeypatch.setattr(lab, "_nsq_for", lambda rec: dict(nsq))
    return recs


def test_measured_values_are_used_and_cited(stub):
    p = lab.profile("ibu_measured")
    s = p["solubility"]
    assert s["kind"] == "source" and s["mg_per_ml"] == pytest.approx(0.021) and "HSDB" in s["model"]
    assert p["provenance"]["aqueous_solubility"]["url"] == HSDB["url"]
    assert p["solubility"]["logp"] == 3.97 and p["provenance"]["log_p"]["kind"] == "source"
    # pKa kind not stated, but the only GI-ionisable group is a carboxylic acid
    assert p["derived"]["pka_acid"] == 4.91 and p["provenance"]["pka"]["kind"] == "source"
    assert "measured solubility" in p["bcs"]["reason"]
    d = lab.dissolution("ibu_measured", {})
    assert d["verdict"] in ("pass", "fail") and d["inputs"]["pka"]["kind"] == "source" and d["inputs"]["pka"]["value"] == 4.91


def test_estimate_only_withholds_dissolution_verdict(stub):
    p = lab.profile("ibu_bare")
    assert p["solubility"]["kind"] == "estimate" and p["solubility"]["uncertainty"].startswith("±1")
    assert p["derived"]["pka_acid"] is None
    d = lab.dissolution("ibu_bare", {})
    assert d["verdict"] == "withheld" and any("pKa" in w for w in d["why"])
    # user picks "weak acid" but gives no pKa: still withheld (no invented pKa)
    assert lab.dissolution("ibu_bare", {"ionization": "acid"})["verdict"] == "withheld"
    assert lab.dissolution("ibu_bare", {"ionization": "acid", "pka": 4.9})["verdict"] in ("pass", "fail")


def test_be_marks_assumed_pk(stub):
    b = lab.bioequivalence("ibu_measured", {})
    assert set(b["pk_assumed"]) == {"cl_l_h", "v_l", "ka_h", "f_abs"}
    assert b["compare"]["risk"] in ("inside", "outside", "not_assessable")
    assert "near" not in b["compare"]["message"].lower()
