"""FDA DMF list and EDQM CEP file parsing (synthetic files in the published layouts)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import api_filings as af  # noqa: E402


def test_dmf_xlsx_type_ii_only(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["List of Drug Master Files current through DMF 044443"])
    ws.append(["DMF#", "STATUS", "TYPE", "SUBMIT DATE", "HOLDER", "SUBJECT"])
    ws.append([18990, "A", "II", "11/28/2005", "GLENMARK LIFE SCIENCES LTD", "TELMISARTAN USP"])
    ws.append([20001, "I", "TYPE II", "01/05/2007", "OLD CHEM LTD", "TELMISARTAN"])
    ws.append([30000, "A", "III", "01/05/2015", "PACK CO", "PVC FILM"])
    f = tmp_path / "dmf.xlsx"
    wb.save(f)
    rows = af.parse_dmf(f)
    assert set(rows) == {"18990", "20001"}
    assert rows["18990"] == {"number": "18990", "status": "active", "type": "II", "date": "2005-11-28",
                             "holder": "GLENMARK LIFE SCIENCES LTD", "subject": "TELMISARTAN USP"}
    assert rows["20001"]["status"] == "inactive"


def test_dmf_html_as_xls(tmp_path):
    f = tmp_path / "dmf.xls"
    f.write_text("<table><tr><th>DMF#</th><th>STATUS</th><th>TYPE</th><th>SUBMIT DATE</th><th>HOLDER</th><th>SUBJECT</th></tr>"
                 "<tr><td>18990</td><td>A</td><td>II</td><td>2005-11-28</td><td>GLENMARK</td><td>TELMISARTAN USP</td></tr></table>")
    assert af.parse_dmf(f)["18990"]["date"] == "2005-11-28"


def test_cep_tab_text(tmp_path):
    f = tmp_path / "cep.txt"
    f.write_text("Certificate Number\tHolder\tSubstance\tMonograph Number\tStatus\tIssue Date\n"
                 "R1-CEP 2010-123-Rev 03\tAUROBINDO PHARMA LIMITED IN\tTelmisartan\t2154\tValid\t15/03/2024\n"
                 "R0-CEP 2012-001-Rev 00\tSOME CHEM\tTelmisartan\t2154\tWithdrawn by holder\t01/02/2013\n")
    rows = af.parse_cep(f)
    assert rows["R1-CEP 2010-123-Rev 03"]["valid"] and not rows["R0-CEP 2012-001-Rev 00"]["valid"]
    assert rows["R1-CEP 2010-123-Rev 03"]["monograph"] == "2154" and rows["R1-CEP 2010-123-Rev 03"]["date"] == "2024-03-15"


def test_cep_real_export_header(tmp_path):
    f = tmp_path / "EXPORT_WEB_CEP.txt"
    f.write_text("Monograph Number\tSubstance\tType CEP\tCertificate (CEP) Holder\tHolder SPOR ORG-ID / SPOR LOC-ID\t"
                 "Certificate (CEP) Number\tIssue Date CEP\tStatus CEP\n"
                 "0\t1,2-dihydrotriamcinolone\tTSE\tPharmacia & Upjohn Company Kalamazoo US\t\tR0-CEP 2001-231 - Rev 00\t09/04/2002\tExpired\n"
                 "2154\tTelmisartan\tChemistry\tGlenmark Life Sciences Limited Mumbai IN\tORG-100001234 / LOC-100028900\t"
                 "R1-CEP 2010-123 - Rev 03\t15/03/2024\tValid\n")
    rows = af.parse_cep(f)
    t = rows["R1-CEP 2010-123 - Rev 03"]
    assert t["valid"] and t["country"] == "IN" and t["spor_loc"] == "LOC-100028900" and t["spor_org"] == "ORG-100001234"
    assert t["date"] == "2024-03-15" and t["monograph"] == "2154"
    assert not rows["R0-CEP 2001-231 - Rev 00"]["valid"] and rows["R0-CEP 2001-231 - Rev 00"]["country"] == "US"
