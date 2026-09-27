"""EudraGMDP certificate / non-compliance parsing. Fixtures are real EudraGMDP pages (September 2026), trimmed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import eudragmdp as e  # noqa: E402

FX = Path(__file__).parent / "fixtures" / "eudragmdp"


def cert(name):
    return e.parse_certificate((FX / f"{name}.html").read_text())


def test_list_page():
    rows, total = e.parse_list((FX / "list_page.html").read_text())
    assert total == 1052 and [r["id"] for r in rows] == ["187081", "187173"]
    assert rows[1]["type"] == "NCR" and rows[1]["postcode"] == "382150" and rows[0]["oms_loc"] == "LOC-100032422" and rows[0]["mia"] is None


def test_finished_dose_certificate():
    d = cert("gmpc_fdf_emcure")
    assert (d["type"], d["number"], d["authority"]) == ("GMPC", "MT/047HM/2026", "Malta Medicines Authority")
    assert d["manufacturer"] == "Emcure Pharmaceuticals Limited" and d["oms_loc"] == "LOC-100080357" and d["duns"] == "85-451-6776"
    assert d["inspection_date"] == "2026-03-24" and d["issued"] == "2026-06-10" and d["role"] == "third_country_ma"
    codes = {s["code"]: s["label"] for s in d["scope"]}
    assert codes["1.2.1.13"] == "Tablets" and codes["1.2.1.1"] == "Capsules, hard shell"
    assert codes["1.6.2"] == "Microbiological: non-sterility" and "1" not in codes
    assert d["remarks"].startswith("The certificate is limited in scope")


def test_biological_sterile_certificate():
    codes = {s["code"] for s in cert("gmpc_bio_serum")["scope"]}
    assert {"1.1.1.4", "1.3.1.5", "1.6.4"} <= codes


def test_api_certificate():
    d = cert("gmpc_api_pharmazell")
    assert d["role"] == "active_substance" and d["substances"] == ["L-Cysteine Hydrochloride Monohydrate", "Propafenone Hydrochloride"]
    s = {(x["code"], x["substance"]): x for x in d["scope"]}
    assert s[("3.5.1", "L-Cysteine Hydrochloride Monohydrate")]["detail"] == "Drying, Blending, Sieving, Milling, Micronisation"
    assert ("3.1.1", "Propafenone Hydrochloride") in s and not any(x["code"] == "3" for x in d["scope"])


def test_non_compliance_statement():
    d = cert("ncr_aculife")
    assert d["type"] == "NCR" and d["number"] == "MT/003NCR/2026" and d["inspection_date"] == "2026-07-14"
    assert "critical deficiency on inadequate cleaning validation" in d["ncr"]["nature"]
    assert d["ncr"]["action"].startswith("Prohibition of supply")
    assert {"1.1.1.4", "1.1.2.1"} <= {s["code"] for s in d["scope"]}


def test_sites_status():
    g = {**cert("ncr_aculife"), "id": "2", "inspection_date": "2026-07-14"}
    old = {**cert("gmpc_fdf_emcure"), "id": "1", "oms_loc": g["oms_loc"], "inspection_date": "2024-01-10"}
    sites = e.build_sites({"1": old, "2": g})
    s = sites[g["oms_loc"]]
    assert s["status"] == "non_compliant" and s["last_ncr"] == "2026-07-14" and s["last_gmp_inspection"] == "2024-01-10"
    assert any(c["code"] == "1.2.1.13" for c in s["scope"])  # scope comes from certificates only
    assert all(not c["code"].startswith("1.1.1") for c in s["scope"])  # the NCR's (non-compliant) operations are not capabilities


def test_crawl_goes_back_to_the_list_before_paging(monkeypatch, tmp_path):
    """EudraGMDP returns an empty page unless 'Back To Search' follows an opened certificate."""
    import json

    from sources.common import Ctx

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    html = (FX / "gmpc_fdf_emcure.html").read_text()
    log: list[str] = []

    class Fake:
        def __init__(self, ctx, sleep):
            self.open = False

        def _rows(self, n):
            return [{"id": f"{n}{i}", "number": f"N{n}{i}", "doc_ref": "", "type": "GMPC", "mia": None, "oms_org": None,
                     "oms_loc": f"LOC-{n}{i}", "site_name": f"Site {n}{i}", "address": "a", "city": "c", "postcode": "382865",
                     "country": "India", "inspection_date": "2026-01-01"} for i in range(10)]

        def search(self):
            log.append("search")
            self.open = False
            return self._rows(0), 25

        def detail(self, _id):
            self.open = True
            return html

        def back_to_list(self):
            log.append("back")
            self.open = False

        def page(self, n):
            log.append(f"page{n}")
            return [] if self.open else self._rows(n)[: 5 if n == 2 else 10]

    monkeypatch.setattr(e, "Session", Fake)
    ctx = Ctx(name="eudragmdp")
    e.run(ctx)
    out = json.loads((tmp_path / "sources" / "eudragmdp.json").read_text())
    assert len(out["documents"]) == 25 and out["complete"] and log == ["search", "back", "page1", "back", "page2"]
