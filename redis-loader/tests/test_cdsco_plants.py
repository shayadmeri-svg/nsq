"""CDSCO plant registry: SUGAM table parsing, WHO-GMP PDF parsing, capability vocabulary, merge.

Fixtures are rows copied from the live CDSCO pages (September 2026).
Run: python -m pytest redis-loader/tests -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from sources import cdsco_plants as cp  # noqa: E402

SUGAM_HTML = """
<form name="f1"><table>
<tr><td colspan=9>Search <input type="text" name="srch_pattrn" value=""></td></tr>
<tr><td>Sr.No</td><td>License No</td><td>Premise Name</td><td>Loan Premises Name</td><td>Premise Address</td>
<td>Site Type</td><td>Form No</td><td>Issue Date</td><td>Expiry Date</td></tr>
<tr><td>7</td><td>MB/05/203</td><td>Panacea Biotec Ltd</td><td>-</td>
<td>Village, MalpurBaddi,Solan(BBN),Himachal Pradesh,India,1795-304000,1795-246834</td><td>OWN</td><td>Form 28</td>
<td>11-Oct-2015</td><td>10-Oct-2020
<tr><td>911</td><td>43/UA/2008</td><td>Bal Pharma Limited</td><td>Acme Brands Pvt Ltd</td>
<td>M/s. Bal Pharma Ltd Sector ? 4, Plot No ? 1,2,3 &amp; 69,,  Integrated Industrial Estate, Pantnagar, Rudrapur ? 263145 (Uttarakhand) Rudrapur,Udham Singh Nagar,Uttarakhand,India,05944-250278,05944-250278</td>
<td>Loan</td><td>Form 25A</td><td>12-Aug-2023</td><td>11-Aug-2028
</table>
<input type="hidden" value="911" name="num_total_records"><input type="hidden" value="10" name="num_pages">
</form>"""


def test_sugam_page_and_address():
    rows, hidden = cp.parse_sugam_page(SUGAM_HTML)
    assert hidden["num_pages"] == "10" and len(rows) == 2
    a = cp.sugam_record(rows[0])
    assert a["state"] == "Himachal Pradesh" and a["district"] == "Solan"
    assert a["licence"]["kind"] == "schedule_c" and a["licence"]["issued"] == "2015-10-11"
    assert a["pin"] is None  # phone numbers are never mistaken for a PIN
    b = cp.sugam_record(rows[1])
    assert b["pin"] == "263145" and b["district"] == "Udham Singh Nagar"
    assert b["loan_licensee"] == "Acme Brands Pvt Ltd" and b["licence"]["kind"] == "loan_licence"


@pytest.mark.parametrize("text,forms,seg", [
    ("1. Oral & Soild Preparations (Tablets, Capsules, Liquids and Suppositories) 2. External Preparations (Ointments, Creams, Gels, Transdermal Patches)",
     {"tablet", "capsule_hard", "oral_liquid", "suppository", "topical", "transdermal"}, {}),
    ("Hormonal Preparations & External Preparations", {"topical"}, {"hormone": []}),
    ("Bulk Drugs (APIs)", {"api"}, {}),
    ("General - Tablets, Capsules, Dry Syrups, Oral Liquids, Oral Powders, External Preprations, Small Volume Parenteral Liquid, "
     "Opthalmic, Small Volume Parenteral (Dry) Beta lactam - Tablets, Capsules, Dry Syrups & Small Volume Parenteral (Dry)",
     {"tablet", "capsule_hard", "dry_syrup", "oral_liquid", "oral_powder", "topical", "svp_liquid", "ophthalmic", "svp_dry_powder"},
     {"beta_lactam": ["capsule_hard", "dry_syrup", "svp_dry_powder", "tablet"]}),
    ("Dry Powder Injection (Betalactam & Cephalosporin)", {"svp_dry_powder"},
     {"beta_lactam": ["svp_dry_powder"], "cephalosporin": ["svp_dry_powder"]}),
    ("Cytotoxic (Anti Cancer)Tablet, capsule, small volume paretenral(vial and ampoules) and small volume parenteral (lyophillized and dry)",
     {"tablet", "capsule_hard", "svp_liquid", "lyophilised"}, {"cytotoxic": ["capsule_hard", "lyophilised", "svp_liquid", "tablet"]}),
    ("Tablets, Capsules & Aerosoles", {"tablet", "capsule_hard", "inhalation"}, {}),
    ("Oral Liquid (Syrup Suspension)", {"oral_liquid"}, {}),
])
def test_capabilities(text, forms, seg):
    c = cp.parse_capabilities(text, source="t")
    assert forms <= set(c["dosage_forms"]), c["dosage_forms"]
    for k, v in seg.items():
        assert set(v) <= set(c["segregated"].get(k, [])), c["segregated"]
    assert set(seg) <= set(c["segregated"])


def test_certificate_dates_and_sterile():
    c = cp.parse_capabilities("1. Tablet Dosage, Date of Issue 02/02/2022, Valid upto 01/02/2025 "
                              "2. Small Volume Parenterals (Ampoules) and Capsule Dosage, Date of Issue 26/05/2023, Valid upto 25/05/2026",
                              source="t")
    assert c["sterile"] and [e["valid_until"] for e in c["evidence"]] == ["2025-02-01", "2026-05-25"]


def test_therapeutic_tags():
    c = cp.parse_capabilities("Anti-Viral,Anti-Coagulant,Anti-Diabetic,Antiretroviral,Antineoplastic agent & Antifungal", source="t")
    assert {"antiviral", "cardiovascular", "antidiabetic", "antifungal"} <= set(c["therapeutic"])
    assert "cytotoxic" in c["segregated"]


def test_names_pins_units():
    n, a = cp.split_name_address("M/S. HETERO HEALTHCARE LIMITED, UNIT-11, at Hudumpur Village, Kamrup Assam - 781128")
    assert n.upper().startswith("HETERO HEALTHCARE LIMITED") and cp.find_pin(a) == "781128"
    assert cp.find_pin("Kamrup Rural, Assam 781 125") == "781125"
    assert cp.find_pin("SANTEJ-VADSAR ROAD, KALOL,GANDHINAGAR - 380 060") == "380060"
    assert cp.name_key("M/s Cipla Limited (Unit-I)") != cp.name_key("M/s Cipla Limited (Unit-II)")
    assert cp.name_key("Cipla Ltd. Unit II") == cp.name_key("M/s Cipla Limited (Unit-II)")


def _w(text, x0, top):
    return {"text": text, "x0": x0, "x1": x0 + 5.5 * len(text), "top": top, "bottom": top + 9}


def _rules(*ys):
    return [{"x0": 55, "x1": 550, "top": y} for y in ys]


VEDGES = [{"x0": x, "top": 100, "bottom": 800} for x in (55, 90, 120, 370, 550)]


def test_layout_units_states_centred_serials_and_page_breaks():
    """Word-generated CDSCO layout: serial column x<90, sub-serial 90-120, name 120-370, category 370-550."""
    p1 = {"width": 595, "height": 842, "vedges": VEDGES, "hedges": _rules(120, 160, 180, 240, 330), "words": [
        _w("S.", 60, 127), _w("Name", 130, 127), _w("and", 160, 127), _w("address", 180, 127), _w("Category", 381, 127), _w("of", 430, 127), _w("Drugs", 445, 127),
        _w("Assam", 260, 166),
        # a tall row: the serial numbers sit in the middle, the name starts at the top
        _w("Phoenix", 178, 187), _w("Laboratories,", 220, 187), _w("Village", 290, 187),
        _w("1", 65, 205), _w("1", 100, 205),
        _w("Narayanpur,", 174, 200), _w("Kamrup", 240, 200), _w("Rural,", 280, 200), _w("Assam", 210, 213), _w("781", 245, 213), _w("125", 265, 213),
        _w("Hormonal", 381, 187), _w("Preparations", 431, 200),
        _w("M/S.", 172, 250), _w("HETERO", 200, 250), _w("HEALTHCARE", 243, 250), _w("LIMITED,", 141, 262), _w("Changsari,", 190, 262),
        _w("2", 65, 250), _w("2", 100, 250),
        _w("1.", 380, 250), _w("Oral", 392, 250), _w("&", 415, 250), _w("Soild", 425, 250), _w("Preparations", 450, 250),
        _w("Remarks", 72, 400)]}  # below the last rule: ignored
    p2 = {"width": 595, "height": 842, "vedges": VEDGES, "hedges": _rules(80, 110, 140, 200), "words": [
        _w("Assam", 200, 88), _w("781101", 240, 88), _w("2.", 380, 88), _w("External", 392, 88), _w("Preparations", 440, 88),  # continued row
        _w("Sikkim", 260, 120),
        _w("1294", 58, 150), _w("9", 100, 150), _w("M/s", 144, 150), _w("Cipla", 165, 150), _w("Limited", 195, 150), _w("(Unit-I)", 240, 150),
        _w("Kumrek,", 280, 150), _w("Rangpo", 320, 150), _w("Tablets,", 390, 150), _w("Capsules", 430, 150), _w("&", 480, 150), _w("Aerosoles", 490, 150)]}
    units = cp.units_from_layout([p1, p2])
    assert [(u["serial"], u["state"]) for u in units] == [("1", "Assam"), ("2", "Assam"), ("1294", "Sikkim")]
    assert units[0]["name_address"].startswith("Phoenix Laboratories, Village Narayanpur") and "781 125" in units[0]["name_address"]
    assert units[1]["name_address"].endswith("Assam 781101") and "External Preparations" in units[1]["category"]
    recs = [cp.who_record(u, "t.pdf") for u in units]
    assert recs[0]["pin"] == "781125" and "hormone" in recs[0]["capabilities"]["segregated"]
    assert recs[1]["pin"] == "781101" and "topical" in recs[1]["capabilities"]["dosage_forms"]
    assert recs[2]["name"] == "Cipla Limited (Unit-I)" and "inhalation" in recs[2]["capabilities"]["dosage_forms"]


def test_layout_skips_state_summary_table():
    p = {"width": 595, "height": 842, "vedges": [{"x0": x, "top": 100, "bottom": 400} for x in (100, 150, 350, 500)],
         "hedges": [{"x0": 100, "x1": 500, "top": y} for y in (120, 140, 160, 180)],
         "words": [_w("1", 110, 125), _w("Assam", 200, 125), _w("9", 400, 125),
                   _w("4", 110, 145), _w("Gujarat", 200, 145), _w("1077", 400, 145),
                   _w("9", 110, 165), _w("Meghalaya", 200, 165), _w("Nil", 400, 165)]}
    assert cp.units_from_layout([p]) == []


def test_registry_merges_sugam_into_who_unit():
    who = [cp.who_record({"serial": "7", "state_serial": "1", "state": "Himachal Pradesh",
                          "name_address": "Panacea Biotec Ltd., Village Malpur, Baddi, Distt. Solan, HP 173205",
                          "category": "Vaccines and Small Volume Parenterals"}, "t.pdf")]
    rows, _ = cp.parse_sugam_page(SUGAM_HTML)
    plants, stats = cp.build_registry([cp.sugam_record(r) for r in rows], who)
    assert stats["sugam_matched_to_who_gmp"] == 1 and stats["plants"] == 2
    p = next(p for p in plants.values() if p["name_key"].startswith("panacea"))
    assert p["who_gmp_certified"] and p["capabilities"]["schedule_c"] and "biological" in p["capabilities"]["dosage_forms"]
    assert {"who_gmp", "sterile", "schedule_c"} <= set(p["tags"]) and p["district"] == "Solan"
    bal = next(p for p in plants.values() if p["name_key"].startswith("bal"))
    assert bal["loan_licensees"] == ["Acme Brands Pvt Ltd"] and "loan_licence_host" in bal["tags"]


def test_pdf_end_to_end(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    data = [["S. No.", "Sub Sr. no.", "Name and address of the WHO-GMP certified manufacturers", "Category of Drugs permitted to manufacture under WHO-GMP Certificate"],
            ["Gujarat", "", "", ""]]
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph
    st = getSampleStyleSheet()["Normal"]
    data = [[Paragraph(c, st) for c in row] for row in data]
    for i in range(1, 70):
        data.append([str(i), str(i), Paragraph(f"Test Pharma {i} Pvt. Ltd., Plot {i}, GIDC, Vadodara - 390 0{i:02d}", st),
                     Paragraph("Tablets, Capsules" if i % 2 else "Bulk Drugs (APIs)", st)])
    t = Table(data, colWidths=[40, 40, 250, 180], repeatRows=0)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0)), ("SPAN", (0, 1), (-1, 1))]))
    pdf = tmp_path / "who.pdf"
    # a state heading printed as a paragraph between tables (not inside one)
    t2 = Table([[str(i), str(i), Paragraph(f"Hill Remedies {i} Ltd., Baddi, Solan 173 2{i:02d}", st), Paragraph("Beta lactam - Tablets", st)] for i in range(70, 73)],
               colWidths=[40, 40, 250, 180])
    t2.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    SimpleDocTemplate(str(pdf), pagesize=A4).build([t, Paragraph("Himachal Pradesh", st), t2])
    units = cp.extract_who_units(pdf, log=lambda *_: None)
    assert len(units) == 72 and all(u["state"] == "Gujarat" for u in units[:69])
    assert all(u["state"] == "Himachal Pradesh" for u in units[69:])
    recs = [cp.who_record(u, "who.pdf") for u in units]
    assert recs[0]["pin"] == "390001" and recs[1]["capabilities"]["api"]
    assert recs[-1]["capabilities"]["segregated"] == {"beta_lactam": ["tablet"]} and recs[-1]["pin"] == "173272"


def test_real_category_text_sample():
    """Category cells copied from the September 2025 WHO-GMP list (12 pages across states)."""
    import json
    sample = json.loads((Path(__file__).parent / "who_gmp_categories_sample.json").read_text())
    caps = {t: cp.parse_capabilities(t, source="t") for t in sample}
    assert all(c["dosage_forms"] for c in caps.values())  # every real cell yields at least one form
    by = lambda prefix: next(c for t, c in caps.items() if t.startswith(prefix))  # noqa: E731
    assert by("Tablets, Capsules (Non beta lactum)")["segregated"] == {}
    assert by("Injections (non beta Lactum)")["segregated"] == {}
    assert by("Tablets, Hard Gelatine Capsule")["dosage_forms"] == ["capsule_hard", "capsule_soft", "oral_powder", "tablet"]
    assert by("Tablets (General, Betalactam & Oncology)")["segregated"] == {"beta_lactam": ["tablet"], "cytotoxic": ["tablet"]}
    assert by("SVP ,Liquid(Ampoule")["segregated"] == {"hormone": ["tablet"]}
    assert by("Tablets, Dry Syrup & Dry injection")["segregated"] == {"cephalosporin": ["dry_syrup", "svp_dry_powder", "tablet"]}
    g = by("General - Tablets, Capsules, OralLiquids")["segregated"]["cephalosporin"]
    assert "oral_liquid" not in g and "topical" not in g and {"tablet", "capsule_hard", "dry_syrup"} <= set(g)
    t = by("Tablets, Capsules & Sterile Dry Powder Injections (Beta - lactam)")["segregated"]
    assert "svp_dry_powder" in t["beta_lactam"] and "svp_dry_powder" in t["cephalosporin"] and "svp_liquid" not in t["cephalosporin"]
    assert by("Small Volume Parenteral (Recombinant")["dosage_forms"] == ["biological", "svp_liquid"]
    assert by("Parenteral (SVP / LVP)")["sterile"] and by("Bulk Drug (API's)")["api"]


def test_row_rules_ignore_inset_text_boxes():
    # real borders run unbroken 51 -> 369; Word's inset text boxes (56-81, 92-130, 141-364) leave gaps
    border = [{"x0": a, "x1": b, "top": 326} for a, b in ((51, 86), (86, 136), (136, 369), (370, 547))]
    inset = [{"x0": a, "x1": b, "top": 339} for a, b in ((56, 81), (92, 130), (141, 364), (375, 542))]
    assert cp._row_rules(border + inset, name_left=141) == [326]


def test_names_with_divisions_districts_and_distinct_plants():
    n, a = cp.split_name_address("UNIQUE PHARMACEUTICAL LABORATORIES ( A DIV. OF J.B. CHEMICALS & PHARMACEUTICALS LTD ) PLOT NO. 128/1, GIDC")
    assert n.endswith("LTD )") and a.startswith("PLOT NO. 128/1")
    assert cp.district_of("Vill Thana Baddi Distt Solan HP") == "Solan"
    assert cp.district_of("Garru Bazar Dist:-Kamru Pin-781125.") == "Kamru"
    # same company, same state, no PIN: two different plants must stay two plants
    a1 = cp.plant_id("Alembic Pharmaceuticals Ltd", "Gujarat", None, None, "Panelav, Tal. Halol")
    a2 = cp.plant_id("Alembic Pharmaceuticals Ltd", "Gujarat", None, None, "Karakhadi, Tal. Padra")
    assert a1 != a2
    # Cipla's two Verna plants share a PIN but not a plot
    assert cp.plant_id("Cipla Ltd", "Goa", "403722", None, "Plot No. S-103 Verna") != cp.plant_id("Cipla Ltd", "Goa", "403722", None, "L-139 Verna")


def test_new_forms():
    f = lambda t: cp.parse_capabilities(t, source="t")["dosage_forms"]  # noqa: E731
    assert f("Mouth Dissolving Strip") == ["oral_film_gum"] and f("L.V.P") == ["lvp"] and f("Respiratory Solution") == ["inhalation"]
    assert f("Exteernal Preparation") == ["topical"]
    assert f("Tablet, Capsules (Soft Gelatin)") == ["capsule_soft", "tablet"]
