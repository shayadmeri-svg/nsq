"""CDSCO International Cell page parsing (layout copied from the live page, Sept 2026)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import cdsco_wc as wc  # noqa: E402
from sources.common import Ctx  # noqa: E402

PANES = """<div class="tab-v1"> <ul class="nav nav-tabs">
<li class= " btn btn-default "><a href="#79be-tab-1" data-toggle="tab"><i class="fa"></i><p>Functions</p></a></li>
<li class= " btn btn-default "><a href="#79be-tab-3" data-toggle="tab"><i class="fa"></i><p>SOP</p></a></li>
<li class= " btn btn-default "><a href="#79be-tab-4" data-toggle="tab"><i class="fa"></i><p>Organogram</p></a></li> </ul>
<div class="well"> <div class="tab-content">
<div id="79be-tab-1" class="tab-pane active"> <div ><div class="none"><div ><div ><ol> <li> <p>Handling of quality failure of drugs exported from India</p> </li>
<li> <p>Grant of written Confirmation for Export of Active Pharmaceutical Ingredients (API) as per EU directives.</p> </li> </ol></div></div></div></div></div>
<div id="79be-tab-3" class="tab-pane "> <div ></div></div>
<div id="79be-tab-4" class="tab-pane "> <div ><div class="none"><div ><div ><h3><a href="/opencms/export/sites/CDSCO_WEB/Pdf-documents/International-Cell/Organogram_InternationalCell.pdf">Organogram</a></h3></div></div></div></div></div>
</div><!--/tab-content--> </div></div>
"""

TABLE = """<div class="col-md-12 col-sm-12 table-responsive">
<table class="table table-bordered bg-head table-striped example" data-page-size="10" id="example">
<thead ><tr ><th>S.no</th><th>WC Number</th><th>Comapany Name </th><th>Products</th><th>Release Date</th><th>Download Pdf</th><th>Pdf Size</th></tr></thead>
<tbody>
<tr>
<td>1</td>
<td>WC-0537</td>
<td>M/s. Reine Lifescience</td>
<td>Pregabalin BP/EP and 5 items</td>
<td>2026-09-01 00:00:00.0</td>
<td><a href='/opencms/opencms/system/modules/CDSCO.WEB/elements/download_file_division.jsp?num_id=MTQ2Njc='><i class="fa fa-file-pdf-o"></i></a></td>
<td>2844 KB</td>
</tr>
<tr>
<td>2</td>
<td>WC -0537n</td>
<td>M/s Reine Lifescience,</td>
<td>Pregabalin BP/EP</td>
<td>2023-02-11 00:00:00.0</td>
<td><a href='/opencms/opencms/system/modules/CDSCO.WEB/elements/download_file_division.jsp?num_id=MjE4MA=='><i class="fa"></i></a></td>
<td>1,368KB</td>
</tr>
<tr>
<td>709</td>
<td>Office Memorandum- Regarding grant of NOC for manufacture of Unapproved/Approved New Drug/Band Bulk Drug</td>
<td></td>
<td></td>
<td>2014-01-20 00:00:00.0</td>
<td><a href='/opencms/opencms/system/modules/CDSCO.WEB/elements/download_file_division.jsp?num_id=MTUw'><i class="fa"></i></a></td>
<td>443kb</td>
</tr>
</tbody></table></div>"""

PAGE = "<html><body>" + PANES + TABLE + "</body></html>"


def test_norm_wc():
    assert wc.norm_wc("WC -0104") == "WC-0104"
    assert wc.norm_wc("WC/0037") == "WC-0037"
    assert wc.norm_wc("WC-340n") == "WC-0340"
    assert wc.norm_wc("WC-0491A3") == "WC-0491"
    assert wc.norm_wc("Office Memorandum- Regarding grant of NOC") is None


def test_parse_table():
    rows = wc.parse_table(PAGE)
    assert [r["id"] for r in rows] == ["14667", "2180", "150"]  # base64 num_id decoded
    a, b, memo = rows
    assert a["wc"] == "WC-0537" and a["company"] == "Reine Lifescience" and a["items"] == 6 and a["date"] == "2026-09-01"
    assert a["size_kb"] == 2844 and b["size_kb"] == 1368
    assert a["latest"] is True and b["latest"] is False  # same WC number, older letter
    assert b["company"] == "Reine Lifescience" and b["items"] == 1
    assert memo["kind"] == "notice" and memo["wc"] is None and memo["company"] is None
    assert a["download"].startswith("https://cdsco.gov.in/opencms/opencms/system/modules/CDSCO.WEB/elements/download_file_division.jsp?num_id=")


def test_parse_about():
    about = {a["title"]: a for a in wc.parse_about(PAGE)}
    assert set(about) == {"Functions", "SOP", "Organogram"}
    assert len(about["Functions"]["paragraphs"]) == 2
    assert about["SOP"]["paragraphs"] == [] and about["SOP"]["links"] == []
    assert about["Organogram"]["links"][0]["url"].endswith("/International-Cell/Organogram_InternationalCell.pdf")


def test_valid_until():
    assert wc.valid_until("This written confirmation is valid up to 31.08.2029 unless") == "2029-08-31"
    assert wc.valid_until("Valid till: 5/3/27") == "2027-03-05"
    assert wc.valid_until("no date here") is None


def test_run_from_saved_page(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    page = tmp_path / "page.html"
    page.write_text(PAGE)
    (tmp_path / "docs" / "cdsco_wc").mkdir(parents=True)
    (tmp_path / "docs" / "cdsco_wc" / "14667.pdf").write_bytes(b"%PDF-1.4 not really")
    assert wc.run(Ctx(name="cdsco_wc", from_file=page)) == 0
    out = json.loads((tmp_path / "sources" / "cdsco_wc.json").read_text())
    assert out["records"] == 3 and out["pdfs"] == 1
    assert [r["id"] for r in out["data"]] == ["14667", "2180", "150"]  # newest first
    assert out["data"][0]["has_pdf"] and not out["data"][1]["has_pdf"]
    assert {a["title"] for a in out["about"]} == {"Functions", "SOP", "Organogram"}
