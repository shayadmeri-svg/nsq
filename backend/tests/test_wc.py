"""Playground · Written confirmations: listing, search in the letter text, and the PDF itself."""

import json

import pytest

from conftest import H, login


@pytest.fixture()
def admin(client):  # noqa: D103
    login(client, "root@example.com", "root-password-1")
    return client


def _setup(tmp_path, monkeypatch):
    from app import wc
    monkeypatch.setattr(wc, "_root", lambda: tmp_path)
    wc._cache.update(mtime=None, data={})
    (tmp_path / "sources").mkdir()
    (tmp_path / "docs" / "cdsco_wc").mkdir(parents=True)
    (tmp_path / "docs" / "cdsco_wc" / "14667.pdf").write_bytes(b"%PDF-1.4 test")
    data = [
        {"id": "14667", "kind": "wc", "wc": "WC-0537", "wc_raw": "WC-0537", "company": "Reine Lifescience", "products": "Pregabalin BP/EP and 5 items",
         "items": 6, "date": "2026-09-01", "size_kb": 2844, "latest": True, "text": "Site: Plot 12, GIDC Ankleshwar. Products: Pregabalin, Gabapentin, Lacosamide"},
        {"id": "2180", "kind": "wc", "wc": "WC-0537", "wc_raw": "WC-0537n", "company": "Reine Lifescience", "products": "Pregabalin BP/EP",
         "items": 1, "date": "2023-02-11", "latest": False, "download": "https://cdsco.gov.in/x.jsp?num_id=MjE4MA=="},
        {"id": "150", "kind": "notice", "wc": None, "wc_raw": "Office Memorandum", "company": None, "products": None, "date": "2014-01-20"},
    ]
    (tmp_path / "sources" / "cdsco_wc.json").write_text(json.dumps({"title": "CDSCO WC", "retrieved_at": "2026-09-28T00:00:00Z", "records": 3, "data": data,
                                                                     "about": [{"title": "Functions", "paragraphs": ["Grant of written confirmation"], "links": []}]}))


def test_wc_listing_and_search(admin, tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = admin.get("/api/playground/wc", headers=H).json()
    assert r["available"] and r["total"] == 2 and r["stats"]["letters"] == 2 and r["stats"]["numbers"] == 1 and r["stats"]["pdfs"] == 1
    assert r["stats"]["last_12m"] == 1 and r["years"] == {"2023": 1, "2026": 1}
    assert r["items"][0]["has_pdf"] and not r["items"][1]["has_pdf"] and r["items"][1]["source_url"].startswith("https://cdsco.gov.in/")
    assert r["about"][0]["title"] == "Functions"
    hit = admin.get("/api/playground/wc", params={"q": "lacosamide"}, headers=H).json()  # only in the letter text
    assert hit["total"] == 1 and "Lacosamide" in hit["items"][0]["hit"]
    assert admin.get("/api/playground/wc", params={"latest": True}, headers=H).json()["total"] == 1
    assert admin.get("/api/playground/wc", params={"kind": "notice"}, headers=H).json()["items"][0]["id"] == "150"
    assert admin.get("/api/playground/wc", params={"year": "2023"}, headers=H).json()["items"][0]["id"] == "2180"


def test_wc_pdf(admin, tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = admin.get("/api/playground/wc/14667.pdf", headers=H)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert r.headers["content-disposition"].startswith('inline; filename="WC-0537_Reine_Lifescience')
    assert admin.get("/api/playground/wc/2180.pdf", headers=H).status_code == 404
    assert admin.get("/api/playground/wc/..%2Fsources%2Fcdsco_wc.pdf", headers=H).status_code == 404


def test_wc_missing(admin, tmp_path, monkeypatch):
    from app import wc
    monkeypatch.setattr(wc, "_root", lambda: tmp_path)
    wc._cache.update(mtime=None, data={})
    assert admin.get("/api/playground/wc", headers=H).json() == {"available": False}
