"""EDQM Knowledge Database parsers and the change tracker (fragments of the real pages)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "redis-loader"))
sys.path.insert(0, str(ROOT / "core"))

from sources import edqm_kd as K  # noqa: E402

DETAIL = """<table><tr><td></td><td><b><span><font>Status</font></span></b></td><td><font>In use</font></td></tr>
<tr><td><b>Monograph Number</b></td><td>00049</td></tr>
<tr><td><b>Pharmeuropa</b></td><td>32.1</td></tr>
<tr><td><b>Last published in English</b></td><td>10.7</td></tr>
<tr><td><b><span><font>On-going</font></span></b></td><td><font>Revision</td></tr>
<tr><td><b><span><font>State of work</font></span></b></td><td><font>0</td></tr>
<tr><td><b><span><font>Description</font></span></b></td><td><font>Assay: optimisation of the analytical procedure.</td></tr>
<tr><td><b>Interchangeable (ICH_Q4B)</b></td><td>NO</td></tr></table>
<a href="http://crs.edqm.eu/db/4DCGI/View=P0300000">x</a><a href="http://crs.edqm.eu/db/4DCGI/View=Y0001945">y</a>"""

HISTORY = """<p><FONT><b>ISSUE 13.3</b></FONT><br><FONT SIZE=2><b>Assay</b>: liquid chromatography replaces titration.<br>
<b>Impurities</b>: section updated.</FONT></p><p><FONT><b>SUPPLEMENT 10.7</b></FONT><br><FONT SIZE=2><b>Related substances</b>: new LC.</FONT></p>
<p><FONT><b>EDITION 9.0</b></FONT><br><FONT SIZE=2><b>Heavy metals</b>: test deleted.</FONT></p>"""


def test_detail_page_fields():
    d = K.parse_detail(DETAIL)
    assert d["status"] == "In use" and d["last_published"] == "10.7" and d["pharmeuropa"] == "32.1"
    assert d["revision_in_progress"] and d["revision"].startswith("Assay") and d["reference_standards"] == 2


def test_history_and_schedule_dates():
    h = [K.dated(e, today="2026-10-21") for e in K.parse_history(HISTORY)]
    assert [e["issue"] for e in h] == ["13.3", "10.7", "9.0"]
    assert h[0]["state"] == "upcoming" and h[0]["implementation"] == "2027-07-01"
    assert h[0]["changes"][0] == {"section": "Assay", "text": "liquid chromatography replaces titration."}
    assert h[1]["state"] == "earlier" and h[1]["implementation"] is None  # no date is invented before 13.1
    assert K.dated({"issue": "13.1", "changes": []}, today="2027-02-01")["state"] == "in_force"


def test_salt_names_match_their_molecule():
    assert K._base("Amlodipine Besylate") == K._base("Amlodipine besilate") == "amlodipine"
    assert K._base("Metformin Hcl") == K._base("Metformin hydrochloride") == "metformin"
    assert K._base("Paracetamol (Acetaminophen)") == "paracetamol"
