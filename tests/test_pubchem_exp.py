"""PubChem PUG View experimental properties (solubility, pKa, log P) with citations,
parsed from hand-written fixtures in the documented PUG View JSON shape (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "redis-loader"))

from sources import pubchem as P  # noqa: E402


def _doc(heading: str, infos: list[tuple[int, dict]], refs: list[tuple[int, str, str]]) -> dict:
    """Record → Section[Chemical and Physical Properties] → Section[Experimental Properties] → Section[heading]."""
    return {"Record": {
        "RecordType": "CID", "RecordNumber": 1,
        "Section": [{"TOCHeading": "Chemical and Physical Properties", "Section": [
            {"TOCHeading": "Experimental Properties", "Section": [
                {"TOCHeading": heading, "Information": [{"ReferenceNumber": n, "Value": v} for n, v in infos]}]}]}],
        "Reference": [{"ReferenceNumber": n, "SourceName": s, "URL": u} for n, s, u in refs]}}


def _s(text: str) -> dict:
    return {"StringWithMarkup": [{"String": text}]}


@pytest.mark.parametrize("text,mg_ml,t_c", [
    ("In water, 21 mg/L at 25 °C", 0.021, 25.0),                     # ibuprofen (HSDB style)
    ("14,000 mg/L at 25 °C", 14.0, 25.0),                             # paracetamol
    ("In water, 1.4X10+4 mg/L at 25 °C", 14.0, 25.0),                 # HSDB exponent notation
    ("1 g dissolves in about 70 mL water", 1000 / 70, None),
    ("0.5 g/100 mL at 20 deg C", 5.0, 20.0),
    ("Water solubility: 3 µg/mL", 0.003, None),
    ("In water, 4.3 g/L at 20 °C; in ethanol, 200 g/L", 4.3, 20.0),
    ("In water 1.0E+03 mg/L (25 °C)", 1.0, 25.0),
])
def test_water_solubility_strings(text, mg_ml, t_c):
    got = P.parse_water_solubility(text)
    assert got is not None and got["value"] == pytest.approx(mg_ml, rel=1e-6) and got["t_c"] == t_c


@pytest.mark.parametrize("text", [
    "Practically insoluble in water",                 # qualitative only
    "Soluble in ethanol; practically insoluble in water",
    "Freely soluble in methanol, 10 mg/mL",           # other solvent
    "Solubility in pH 7.4 buffer 1.2 mg/mL",          # buffer, not water
])
def test_non_water_or_qualitative_is_skipped(text):
    assert P.parse_water_solubility(text) is None


def test_pka_strings():
    assert P.parse_pka("pKa = 4.91") == [{"value": 4.91, "kind": None}]
    assert [p["value"] for p in P.parse_pka("pKa1 = 6.09; pKa2 = 8.74")] == [6.09, 8.74]
    assert P.parse_pka("pKa 4.5 (carboxylic acid)") == [{"value": 4.5, "kind": "acid"}]
    assert P.parse_pka("pKa = 9.38 (amine)")[0]["kind"] == "base"
    assert P.parse_pka("9.5") == [{"value": 9.5, "kind": None}]


def test_logp_strings():
    assert P.parse_logp("log Kow = 3.97") == 3.97
    assert P.parse_logp("log P = 0.46") == 0.46
    assert P.parse_logp("0.51") == 0.51


def test_experimental_with_citations():
    refs = [(1, "Hazardous Substances Data Bank (HSDB)", "https://pubchem.ncbi.nlm.nih.gov/source/hsdb/3099"),
            (2, "DrugBank", "https://www.drugbank.ca/drugs/DB01050")]
    docs = {
        "Solubility": _doc("Solubility", [(2, _s("Practically insoluble in water")), (1, _s("In water, 21 mg/L at 25 °C"))], refs),
        "Dissociation Constants": _doc("Dissociation Constants", [(1, _s("pKa = 4.91"))], refs),
        "LogP": _doc("LogP", [(1, {"Number": [3.97]}), (2, _s("log Kow = 3.5"))], refs),
    }
    e = P.experimental(docs)
    s = e["solubility_water_mg_ml"]
    assert s["value"] == pytest.approx(0.021) and s["t_c"] == 25.0 and s["source"].startswith("Hazardous") and "hsdb" in s["url"]
    assert e["solubility_texts"][0]["text"] == "Practically insoluble in water" and e["solubility_texts"][0]["source"] == "DrugBank"
    assert e["pka"][0]["value"] == 4.91 and e["pka"][0]["url"].endswith("3099")
    assert e["logp"]["value"] == 3.97 and e["logp"]["source"].startswith("Hazardous")


def test_experimental_empty_is_backward_compatible():
    e = P.experimental({})
    assert e["solubility_water_mg_ml"] is None and e["pka"] == [] and e["logp"] is None
