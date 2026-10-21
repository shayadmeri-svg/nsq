"""Parsers for the new public sources, and the product-group naming that replaced first-seen brand names."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "redis-loader"))
sys.path.insert(0, str(ROOT / "core"))


def test_product_group_name_has_no_brand_and_no_strength():
    from company_ontology import product_display_name

    names = ["Paracetamol Tablets IP 650 mg (Febrex -650)", "Paracetamol Tablets IP", "Paracetamol Tablets IP 500 mg",
             "PARACETAMOL TABLETS IP 650 MG"]
    assert product_display_name(names) == "Paracetamol Tablets IP"


def test_label_pk_parser_quotes_its_sentence():
    from sources.fda_labels import parse_pk

    text = ("Following oral administration, peak concentrations (C max ) of telmisartan are reached in 0.5 to 1 hour after dosing. "
            "At 40 and 160 mg the bioavailability was 42% and 58%, respectively. Telmisartan shows bi-exponential decay kinetics "
            "with a terminal elimination half-life of approximately 24 hours. The volume of distribution for telmisartan is "
            "approximately 500 liters indicating additional tissue binding.")
    pk = parse_pk(text)
    assert pk["half_life_h"]["value"] == 24 and "half-life" in pk["half_life_h"]["text"]
    assert pk["vd_l"]["value"] == 500
    assert pk["f_pct"]["value"] in (42.0, 50.0)
    assert 0.5 <= pk["tmax_h"]["value"] <= 1


def test_label_inactive_ingredients():
    from sources.fda_labels import parse_inactive

    rec = {"description": ["Telmisartan is available as tablets. The tablets contain the following inactive ingredients: "
                           "magnesium stearate, mannitol, meglumine, povidone, sodium hydroxide and sorbitol. Telmisartan tablets are hygroscopic."]}
    assert parse_inactive(rec) == ["magnesium stearate", "mannitol", "meglumine", "povidone", "sodium hydroxide", "sorbitol"]


def test_fda_dissolution_table_parser():
    from sources.fda_dissolution import parse

    html = ("<table><tr><th>Drug Name</th><th>Dosage Form</th><th>USP Apparatus</th><th>Speed (RPMs)</th><th>Medium</th>"
            "<th>Volume (mL)</th><th>Recommended Sampling Times (minutes)</th><th>Date Updated</th></tr>"
            "<tr><td>Glimepiride</td><td>Tablet</td><td>II (Paddle)</td><td>75</td><td>Phosphate Buffer, pH 7.8</td><td>900</td>"
            "<td>5, 10, 15 and 30</td><td>01/15/2009</td></tr></table>")
    rows = parse(html)
    assert rows == [{"drug": "Glimepiride", "dosage_form": "Tablet", "apparatus": "II (Paddle)", "rpm": 75.0, "rpm_text": "75",
                     "medium": "Phosphate Buffer, pH 7.8", "volume_ml": 900.0, "volume_text": "900", "times_min": [5.0, 10.0, 15.0, 30.0],
                     "times_text": "5, 10, 15 and 30", "updated": "01/15/2009", "combination": False}]


def test_patent_number_conversion_keeps_reissues():
    from sources.patent_families import _LATER_FORM, _us_number

    assert _us_number("RE47739") == "USRE47739"
    assert _us_number("10723730") == "US10723730"
    assert _us_number("RE47739*PED") == ""
    assert _LATER_FORM.search("Solid forms of a selective CDK4/6 inhibitor")
    assert not _LATER_FORM.search("Acylated GLP-1 compounds")
