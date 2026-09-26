"""Parsers for the public-data fetchers, on small synthetic files in the
documented layouts (no network)."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "redis-loader"))
sys.path.insert(0, str(ROOT / "core"))

from sources import ema, fda_sites, orange_book, purple_book  # noqa: E402

PRODUCTS = """Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name
TAMOXIFEN CITRATE~TABLET;ORAL~NOLVADEX~ASTRAZENECA~EQ 10MG BASE~N~017970~001~~Approved Prior to Jan 1, 1982~Yes~No~DISCN~ASTRAZENECA PHARMACEUTICALS LP
TAMOXIFEN CITRATE~TABLET;ORAL~TAMOXIFEN CITRATE~MYLAN~EQ 20MG BASE~A~074360~002~AB~Feb 20, 2003~No~Yes~RX~MYLAN PHARMACEUTICALS INC
TAMOXIFEN CITRATE~TABLET;ORAL~TAMOXIFEN CITRATE~AUROBINDO PHARMA~EQ 20MG BASE~A~211111~001~AB~Mar 5, 2019~No~No~RX~AUROBINDO PHARMA LTD
PALBOCICLIB~CAPSULE;ORAL~IBRANCE~PFIZER INC~125MG~N~207103~003~~Feb 3, 2015~Yes~Yes~RX~PFIZER INC
AMOXICILLIN; CLAVULANATE POTASSIUM~TABLET;ORAL~AUGMENTIN~GLAXOSMITHKLINE~500MG;125MG~N~050564~001~AB~Aug 6, 1984~Yes~No~RX~GLAXOSMITHKLINE
"""
PATENTS = """Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~Submission_Date
N~207103~003~6936612~Mar 5, 2027~Y~Y~U-1680~~
N~207103~003~7781583~Mar 5, 2027~~~U-1680~~
N~207103~003~10723730~Feb 8, 2034~~Y~~~
"""
EXCL = """Appl_Type~Appl_No~Product_No~Exclusivity_Code~Exclusivity_Date
N~207103~003~ODE-123~Mar 31, 2026
"""


def _ob_zip(tmp_path: Path) -> Path:
    p = tmp_path / "ob.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("products.txt", PRODUCTS)
        zf.writestr("patent.txt", PATENTS)
        zf.writestr("exclusivity.txt", EXCL)
    return p


def test_orange_book(tmp_path):
    data = orange_book.parse_zip(_ob_zip(tmp_path))
    tam = data["tamoxifen"]
    assert tam["rld"]["trade_name"] == "NOLVADEX"
    assert tam["anda_active"] == 2
    assert tam["indian_anda_holders"] == ["AUROBINDO PHARMA LTD"]
    assert tam["first_generic_approval"] == "2003-02-20"
    assert tam["te_codes"] == {"AB": 2}
    pal = data["palbociclib"]
    assert pal["last_substance_patent_expiry"] == "2027-03-05"
    assert pal["last_patent_expiry"] == "2034-02-08"
    assert pal["exclusivity"][0]["code"] == "ODE-123"
    assert data["clavulanate"]["combination_only"] is True
    assert data["amoxicillin"]["combo_products"] == 1


def test_purple_book():
    csv_text = (
        "Purple Book Data Download,,,\n"
        "N/R/U,Applicant,BLA Number,Proprietary Name,Proper Name,BLA Type,Strength,Dosage Form,Route of Administration,Licensure,Date of First Licensure,Ref. Product Proper Name,Ref. Product Proprietary Name,Ref. Product Exclusivity Exp. Date\n"
        ",Genentech,103705,Rituxan,rituximab,351(a),100 mg/10 mL,Injection,Intravenous,Licensed,11/26/1997,,,\n"
        ",Amgen,761231,Riabni,rituximab-arrx,351(k) Biosimilar,100 mg/10 mL,Injection,Intravenous,Licensed,12/17/2020,rituximab,Rituxan,\n"
        ",Celltrion,761088,Truxima,rituximab-abbs,351(k) Interchangeable,100 mg/10 mL,Injection,Intravenous,Licensed,11/28/2018,rituximab,Rituxan,\n"
    )
    d = purple_book.parse_csv(csv_text)["rituximab"]
    assert d["reference"]["proprietary_name"] == "Rituxan"
    assert d["reference"]["approval"] == "1997-11-26"
    assert d["biosimilars"] == 2 and d["interchangeables"] == 1


def test_ema():
    payload = [
        {"Category": "Human", "Name of medicine": "Ibrance", "Medicine status": "Authorised",
         "International non-proprietary name (INN) / common name": "palbociclib",
         "international_non_proprietary_name_common_name": "palbociclib", "Generic": "No", "Biosimilar": "No",
         "Therapeutic area (MeSH)": "Breast Neoplasms", "therapeutic_area_mesh": "Breast Neoplasms",
         "Marketing authorisation developer / applicant / holder": "Pfizer Europe MA EEIG",
         "european_commission_decision_date": "09/11/2016", "orphan_medicine": "No"},
        {"category": "Human", "name_of_medicine": "Palbociclib Teva", "medicine_status": "Authorised",
         "international_non_proprietary_name_common_name": "palbociclib", "generic": "Yes",
         "european_commission_decision_date": "2026-03-01"},
        {"category": "Veterinary", "name_of_medicine": "X", "international_non_proprietary_name_common_name": "palbociclib"},
    ]
    d = ema.parse(payload)["palbociclib"]
    assert d["authorised"] == 2 and d["generics"] == 1
    assert d["originator"]["authorised"] == "2016-11-09"
    assert d["first_generic_authorised"] == "2026-03-01"
    assert d["therapeutic_areas"] == ["Breast Neoplasms"]


def test_decrs(tmp_path):
    p = tmp_path / "drls_reg.txt"
    p.write_text(
        "FIRM_NAME|FEI_NUMBER|DUNS_NUMBER|ADDRESS|CITY|STATE|ZIP_CODE|COUNTRY_CODE|BUSINESS_OPERATIONS|EXPIRATION_DATE\n"
        "Indoco Remedies Limited|3004567890|650000001|L-32 Verna Industrial Area|Verna|Goa|403722|IN|MANUFACTURE; ANALYSIS; PACK|12/31/2026\n"
        "Some US Firm|1000000000|1|1 Main St|Austin|TX|73301|US|MANUFACTURE|12/31/2026\n"
    )
    d = fda_sites.parse_decrs(p, log=lambda *_: None)
    assert list(d) == ["3004567890"]
    e = d["3004567890"]
    assert e["operations"] == ["analysis", "manufacture", "pack"]
    assert e["company_key"] == "indoco remedies"


def test_import_alert():
    html = """<h4>CHINA</h4><p><b>Some Chinese Co</b></p><p>Beijing CHINA</p>
    <h4>INDIA</h4>
    <p><b>Acme Pharma Pvt. Ltd.</b></p><p>Plot 5, MIDC</p><p>Tarapur, Maharashtra INDIA</p><p>FEI #: 3009876543</p>
    <p>Date Published: 03/15/2019</p>
    <p><b>Beta Labs Limited</b></p><p>Baddi, Himachal Pradesh INDIA</p><p>Date Published: 01/02/2024</p>
    <h4>ITALY</h4><p><b>Italian Co</b></p>"""
    d = fda_sites.parse_import_alert(html)
    names = sorted(v["name"] for v in d.values())
    assert names == ["Acme Pharma Pvt. Ltd.", "Beta Labs Limited"]
    acme = d["3009876543"]
    assert acme["dates"] == ["03/15/2019"] and "Tarapur" in acme["address"]


def test_recalls():
    results = [
        {"recalling_firm": "Acme Pharma Pvt. Ltd.", "classification": "Class II", "recall_initiation_date": "20240105",
         "product_description": "Metformin ER tablets", "reason_for_recall": "Failed dissolution", "status": "Ongoing"},
        {"recalling_firm": "ACME PHARMA PRIVATE LIMITED", "classification": "Class I", "recall_initiation_date": "20250310",
         "product_description": "X", "reason_for_recall": "CGMP deviations", "status": "Terminated"},
    ]
    d = fda_sites.parse_recalls(results)
    assert list(d) == ["acme pharma"]
    assert d["acme pharma"]["recalls"] == 2 and d["acme pharma"]["class_i"] == 1
    assert d["acme pharma"]["last"] == "20250310"
