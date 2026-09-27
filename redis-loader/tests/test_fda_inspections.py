"""FDA Data Dashboard inspection classifications: Excel/CSV export parsing and per-FEI grouping (synthetic rows)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import fda_inspections as fi  # noqa: E402

CSV = """FDA Data Dashboard - Inspections
Filters: Country/Area = India
FEI Number,Legal Name,Address Line 1,City,State,Zip Code,Country/Area,Fiscal Year,Inspection ID,Posted Citations,Inspection End Date,Classification,Project Area,Product Type
3002807456,Indoco Remedies Limited,L-14 Verna Industrial Area,Verna,Goa,403722,India,2025,1234567,Yes,11/24/2025,Voluntary Action Indicated (VAI),Drug Quality Assurance,Drugs
3002807456,Indoco Remedies Limited,L-14 Verna Industrial Area,Verna,Goa,403722,India,2025,1234567,Yes,11/24/2025,Voluntary Action Indicated (VAI),Pre-Approval Evaluation,Drugs
3002807456,Indoco Remedies Limited,L-14 Verna Industrial Area,Verna,Goa,403722,India,2019,1111111,Yes,03/02/2019,Official Action Indicated (OAI),Drug Quality Assurance,Drugs
0003005551234,Some Foods Pvt Ltd,Plot 9,Pune,Maharashtra,411001,India,2024,2222222,No,01/10/2024,No Action Indicated (NAI),Food Composition,Food/Cosmetics
3009999999,Acme Pharma Ltd,Plot 5,Houston,TX,77001,United States,2024,3333333,No,01/10/2024,No Action Indicated (NAI),Drug Quality Assurance,Drugs
"""


def test_export_parse_and_group(tmp_path):
    f = tmp_path / "inspections.csv"
    f.write_text(CSV)
    rows = fi.read_file(f)
    assert len(rows) == 5 and rows[0]["FEINumber"] == "3002807456" and rows[0]["ZipCode"] == "403722"
    sites = fi.build_sites(rows)
    assert list(sites) == ["3002807456"]  # food site and US site dropped
    s = sites["3002807456"]
    assert s["last_inspection"] == "2025-11-24" and s["last_code"] == "VAI" and s["oai_count"] == 1
    assert [i["id"] for i in s["inspections"]] == ["1234567", "1111111"]  # one row per inspection, newest first
    assert s["postcode"] == "403722" and s["address"] == "L-14 Verna Industrial Area"


def test_api_shape_and_codes():
    rows = [{"FEINumber": 3002807456, "LegalName": "X Ltd", "CountryName": "India", "ProductType": "Biologics",
             "InspectionID": 9, "InspectionEndDate": "2024-05-06", "ClassificationCode": "NAI", "ZipCode": "500 076"}]
    s = fi.build_sites(rows)["3002807456"]
    assert s["last_code"] == "NAI" and s["postcode"] == "500076" and s["inspections"][0]["product_type"] == "Biologics"
    assert fi._fei("0003005551234.0") == "3005551234"
