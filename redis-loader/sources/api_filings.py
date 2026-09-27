"""Who files for an active ingredient: two public registers of API makers.

* fda_dmf   FDA's list of Drug Master Files (quarterly spreadsheet). Type II DMFs are
            drug-substance files: holder + subject ("TELMISARTAN USP"). Active ones mean
            the holder supports US generics with that API.
* edqm_cep  EDQM's Certificates of Suitability to the Ph. Eur. (daily text file): holder,
            substance, monograph, status. A valid CEP means Europe accepts the holder's
            API against the Ph. Eur. monograph.

Neither names the manufacturing site or country, so the app links a holder to plants by
company name only ("company-level"), and says so.
Both accept --from-file (the .xls / .txt downloaded in a browser).
"""

from __future__ import annotations

import csv
import io
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

from .common import Ctx, NotFound, download_first, page_links, write_normalized

DMF_PAGE = "https://www.fda.gov/drugs/drug-master-files-dmfs/list-drug-master-files-dmfs"
DMF = {
    "title": "FDA Drug Master Files (Type II)",
    "publisher": "U.S. Food and Drug Administration",
    "url": "https://www.fda.gov/media/192069/download?attachment",
    "page": DMF_PAGE,
    "cadence": "quarterly",
    "feeds": ["API makers per molecule (US)", "Who can make it"],
}
CEP_PAGE = "https://extranet.edqm.eu/publications/recherches_CEP.shtml"
CEP = {
    "title": "EDQM Certificates of Suitability (CEP)",
    "publisher": "European Directorate for the Quality of Medicines & HealthCare",
    "url": CEP_PAGE,
    "page": CEP_PAGE,
    "cadence": "daily file; refreshed weekly here",
    "feeds": ["API makers per molecule (Europe)", "Who can make it"],
}


def _key(h: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


# --- generic table reading (xlsx / xls / html-as-xls / csv / txt) -------------------------------

class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def read_rows(path: Path) -> list[list[Any]]:
    raw = path.read_bytes()
    if raw[:2] == b"PK":
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    if raw[:4] == b"\xd0\xcf\x11\xe0":
        import xlrd  # legacy .xls (FDA still publishes the DMF list this way)

        sh = xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
        return [sh.row_values(i) for i in range(sh.nrows)]
    text = raw.decode("utf-8-sig", errors="replace")
    if "<tr" in text[:20000].lower():
        t = _Table()
        t.feed(text)
        return t.rows
    sample = text[:5000]
    delim = max(("\t", ";", "|", ","), key=sample.count)
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _table(rows: list[list[Any]], want: dict[str, tuple[str, ...]], need: tuple[str, ...]) -> list[dict[str, Any]]:
    """Find the header row (it may sit below a title) and return dict rows keyed by our field names."""
    for i, r in enumerate(rows[:30]):
        keys = [_key(c) for c in r]
        cols = {}
        for field, names in want.items():
            for n in names:
                if n in keys:
                    cols[field] = keys.index(n)
                    break
        if all(f in cols for f in need):
            out = []
            for row in rows[i + 1:]:
                d = {f: (row[j] if j < len(row) else None) for f, j in cols.items()}
                if any(str(v or "").strip() for v in d.values()):
                    out.append(d)
            return out
    raise ValueError(f"header not found; first rows: {[list(map(str, r))[:8] for r in rows[:3]]}")


def _s(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _date(v: Any, dayfirst: bool = False) -> Optional[str]:
    if v in (None, ""):
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):  # Excel serial date (xlrd)
        from datetime import date, timedelta

        return (date(1899, 12, 30) + timedelta(days=int(v))).isoformat()
    s = _s(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 50 else y + 1900 if y < 100 else y
        mo, d = (int(m.group(2)), int(m.group(1))) if dayfirst else (int(m.group(1)), int(m.group(2)))
        return f"{y}-{mo:02d}-{d:02d}"
    m = re.match(r"(\d{1,2})[./-](\w{3})[./-](\d{4})", s)  # 05-Jan-2024
    if m:
        from datetime import datetime

        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


# --- FDA DMF list -----------------------------------------------------------------------------

DMF_COLS = {"number": ("dmf", "dmfno", "dmfnumber"), "status": ("status", "activitystatus"), "type": ("type", "dmftype"),
            "date": ("submitdate", "submissiondate", "submitteddate"), "holder": ("holder", "holdername"),
            "subject": ("subject", "subjecttitle", "title")}


def parse_dmf(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in _table(read_rows(path), DMF_COLS, ("number", "holder", "subject")):
        typ = _s(r.get("type")).upper().replace("TYPE", "").strip()
        if typ and typ not in ("II", "2"):
            continue  # III packaging, IV excipients, V other
        num = _s(r.get("number"))
        if not num:
            continue
        out[num] = {"number": num, "status": "active" if _s(r.get("status")).upper().startswith("A") else "inactive",
                    "type": "II", "date": _date(r.get("date")), "holder": _s(r.get("holder")), "subject": _s(r.get("subject"))}
    return out


def run_dmf(ctx: Ctx) -> int:
    if ctx.from_file:
        path = ctx.from_file
    else:
        # The media id changes every quarter: take the spreadsheet link from the list page, fall back to the last known.
        links = page_links(DMF_PAGE, r"/media/\d+/download")
        path = download_first(ctx, [*links, DMF["url"]], "dmf_list.xls")
    rows = parse_dmf(path)
    if not rows:
        raise NotFound(f"no Type II DMFs parsed from {path.name}")
    active = sum(1 for r in rows.values() if r["status"] == "active")
    ctx.log(f"  {len(rows):,} Type II DMFs ({active:,} active)")
    write_normalized(ctx, DMF, rows, len(rows), extra={"active": active})
    return len(rows)


# --- EDQM CEP ---------------------------------------------------------------------------------

# EDQM's EXPORT_WEB_CEP.txt header (Sep 2026): Monograph Number | Substance | Type CEP | Certificate (CEP) Holder |
# Holder SPOR ORG-ID / SPOR LOC-ID | Certificate (CEP) Number | Issue Date CEP | Status CEP
CEP_COLS = {"number": ("certificatecepnumber", "certificatenumber", "cepnumber", "certificateno", "numero", "number", "cep"),
            "holder": ("certificatecepholder", "holder", "certificateholder", "holdername", "titulaire"),
            "substance": ("substance", "substancename", "nameofsubstance", "substancenameen"),
            "monograph": ("monographnumber", "monograph", "monographno"),
            "status": ("statuscep", "status", "statut"),
            "date": ("issuedatecep", "issuedate", "dateofissue", "lastissuedate", "issuingdate", "date"),
            "type": ("typecep", "type", "certificatetype"), "spor": ("holderspororgidsporlocid", "sporlocid", "spor")}


def parse_cep(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in _table(read_rows(path), CEP_COLS, ("number", "holder", "substance")):
        num = _s(r.get("number"))
        if not num:
            continue
        status = _s(r.get("status")).lower()
        holder = _s(r.get("holder"))
        m = re.search(r"\s([A-Z]{2})$", holder)  # the holder ends with its city and ISO country code: "... Hyderabad IN"
        spor = _s(r.get("spor"))
        out[num] = {"number": num, "holder": holder, "country": m.group(1) if m else None, "substance": _s(r.get("substance")),
                    "monograph": _s(r.get("monograph")) or None, "type": _s(r.get("type")) or None,
                    "status": status or None, "valid": (not status) or status.startswith("valid"), "date": _date(r.get("date"), dayfirst=True),
                    "spor_org": (re.search(r"ORG-\d+", spor) or [None])[0], "spor_loc": (re.search(r"LOC-\d+", spor) or [None])[0]}
    return out


def run_cep(ctx: Ctx) -> int:
    if ctx.from_file:
        path = ctx.from_file
    else:
        links = [u for u in page_links(CEP_PAGE, r"download|\.txt") if "cep" in u.lower() or u.lower().endswith(".txt")]
        if not links:
            raise NotFound("could not find the 'Download CEP data file' link on the EDQM CEP database page — download it "
                           "in a browser and run with --from-file")
        path = download_first(ctx, links, "cep_data.txt")
    rows = parse_cep(path)
    if not rows:
        raise NotFound(f"no CEPs parsed from {path.name}")
    valid = sum(1 for r in rows.values() if r["valid"])
    india = sum(1 for r in rows.values() if r["valid"] and r["country"] == "IN")
    ctx.log(f"  {len(rows):,} CEPs ({valid:,} valid, {india:,} of them held from India)")
    write_normalized(ctx, CEP, rows, len(rows), extra={"valid": valid, "valid_india": india})
    return len(rows)
