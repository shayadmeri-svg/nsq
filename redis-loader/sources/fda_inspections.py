"""FDA inspection classifications for Indian drug sites (FDA Data Dashboard).

One record per FDA Establishment Identifier (FEI): every drug / biologic inspection
FDA has classified, newest first, with the outcome —
  NAI  No Action Indicated        (clean)
  VAI  Voluntary Action Indicated (observations, firm fixes them)
  OAI  Official Action Indicated  (warning letter / import alert territory)

Two ways in:
* API  — set FDA_DD_USER (the approved e-mail) and FDA_DD_KEY (the key FDA sends).
         Request access on datadashboard.fda.gov → "API" (OII Unified Logon).
* File — Data Dashboard → Inspections → filter Country = India, Product Type = Drugs
         (and Biologics) → Export to Excel; run with --from-file <xlsx|csv>.
The inspection record has the firm's address and postcode, so plants are matched
on company + PIN + plot numbers, the same way as EU GMP sites.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .common import Ctx, Unreachable, read_normalized, write_json_atomic, write_normalized

API = "https://api-datadashboard.fda.gov/v1/inspections_classifications"
META = {
    "title": "FDA inspection classifications (India)",
    "publisher": "U.S. Food and Drug Administration — Data Dashboard",
    "url": API,
    "page": "https://datadashboard.fda.gov/oii/cd/inspections.htm",
    "cadence": "weekly (classifications are posted after each inspection closes)",
    "feeds": ["Plant registry (US FDA)", "OAI / VAI / NAI outcomes", "Who can make it"],
}
COLUMNS = ["FEINumber", "LegalName", "AddressLine1", "AddressLine2", "City", "State", "ZipCode", "CountryName",
           "InspectionID", "InspectionEndDate", "FiscalYear", "Classification", "ClassificationCode", "ProjectArea",
           "ProductType", "PostedCitations", "FirmProfile"]
PRODUCT_TYPES = ("Drugs", "Biologics")
RANK = {"OAI": 3, "VAI": 2, "NAI": 1}

# Excel export headers -> API field names (compared after lower-casing and dropping non-letters)
_HEADER = {
    "feinumber": "FEINumber", "fei": "FEINumber", "legalname": "LegalName", "firmname": "LegalName",
    "addressline": "AddressLine1", "addressline1": "AddressLine1", "address": "AddressLine1", "addressline2": "AddressLine2",
    "city": "City", "state": "State", "zipcode": "ZipCode", "zip": "ZipCode", "postalcode": "ZipCode",
    "countryname": "CountryName", "country": "CountryName", "countryarea": "CountryName",
    "inspectionid": "InspectionID", "inspectionenddate": "InspectionEndDate", "fiscalyear": "FiscalYear",
    "classification": "Classification", "classificationcode": "ClassificationCode", "projectarea": "ProjectArea",
    "producttype": "ProductType", "postedcitations": "PostedCitations", "firmprofile": "FirmProfile",
}


def _key(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def _code(row: dict[str, Any]) -> str:
    c = str(row.get("ClassificationCode") or "").strip().upper()
    if c in RANK:
        return c
    m = re.search(r"\b(NAI|VAI|OAI)\b", str(row.get("Classification") or "").upper())
    return m.group(1) if m else ""


def _date(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)  # the dashboard shows US dates
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return s[:10] or None


def _fei(v: Any) -> str:
    s = re.sub(r"\.0$", "", str(v or "").strip())
    return re.sub(r"\D", "", s).lstrip("0")


# --- input ------------------------------------------------------------------------

def read_file(path: Path) -> list[dict[str, Any]]:
    """Rows from a Data Dashboard export (.xlsx or .csv), keyed by API field names."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        rows_iter: Iterable = wb.worksheets[0].iter_rows(values_only=True)
    else:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        rows_iter = csv.reader(io.StringIO(text))
    header: Optional[list[str]] = None
    out: list[dict[str, Any]] = []
    for r in rows_iter:
        cells = list(r)
        if header is None:
            keys = [_HEADER.get(_key(str(c or ""))) for c in cells]
            if "FEINumber" in keys and ("Classification" in keys or "ClassificationCode" in keys):
                header = keys  # skip title / filter rows above the table
            continue
        row = {k: v for k, v in zip(header, cells) if k}
        if row.get("FEINumber"):
            out.append(row)
    if header is None:
        raise ValueError(f"{path.name}: no FEI Number / Classification header row found")
    return out


def _post(body: dict[str, Any], user: str, key: str) -> dict[str, Any]:
    req = Request(API, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", "Authorization-User": user, "Authorization-Key": key})
    try:
        with urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as exc:
        raise Unreachable(f"FDA Data Dashboard API answered {exc.code}: {exc.read()[:300]!r}") from exc
    except URLError as exc:
        raise Unreachable(f"FDA Data Dashboard API: {exc.reason}") from exc


def fetch_api(ctx: Ctx, user: str, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ptype in PRODUCT_TYPES:
        start = 1
        while True:
            body = {"start": start, "rows": 5000, "sort": "InspectionEndDate", "sortorder": "DESC", "returntotalcount": True,
                    "filters": {"CountryName": ["India"], "ProductType": [ptype]}, "columns": COLUMNS}
            res = _post(body, user, key)
            got = res.get("result") or []
            if not isinstance(got, list):
                raise Unreachable(f"FDA Data Dashboard API: unexpected answer {str(res)[:300]}")
            rows += got
            ctx.log(f"  {ptype}: {start - 1 + len(got):,} of {res.get('totalrecordcount', '?')} inspections")
            if len(got) < 5000:
                break
            start += 5000
    return rows


# --- normalise --------------------------------------------------------------------

def build_sites(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_fei: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        country = str(r.get("CountryName") or "India")
        if "india" not in country.lower():
            continue
        if str(r.get("ProductType") or "Drugs") not in PRODUCT_TYPES:
            continue
        fei = _fei(r.get("FEINumber"))
        if fei:
            by_fei[fei].append(r)
    sites: dict[str, dict[str, Any]] = {}
    for fei, rs in by_fei.items():
        seen, insp = set(), []
        for r in sorted(rs, key=lambda r: _date(r.get("InspectionEndDate")) or "", reverse=True):
            iid = str(r.get("InspectionID") or "").replace(".0", "")
            k = iid or (_date(r.get("InspectionEndDate")), str(r.get("ProjectArea")))
            if k in seen:
                continue  # one inspection is listed once per project area / product type
            seen.add(k)
            insp.append({"id": iid or None, "date": _date(r.get("InspectionEndDate")), "code": _code(r),
                         "project_area": r.get("ProjectArea") or None, "product_type": r.get("ProductType") or None,
                         "citations": str(r.get("PostedCitations") or "").strip().lower() in ("yes", "true", "1")})
        last = insp[0] if insp else {}
        top = rs[0]
        addr = ", ".join(str(x) for x in (top.get("AddressLine1"), top.get("AddressLine2")) if x)
        sites[fei] = {
            "key": fei, "fei": fei, "name": str(top.get("LegalName") or "").strip(), "address": addr,
            "city": top.get("City") or None, "state": top.get("State") or None,
            "postcode": re.sub(r"\D", "", str(top.get("ZipCode") or ""))[:6] or None,
            "profile": top.get("FirmProfile") or f"https://datadashboard.fda.gov/oii/fd/firmprofile.htm?FEIi={fei}",
            "last_inspection": last.get("date"), "last_code": last.get("code") or None,
            "oai_count": sum(1 for i in insp if i["code"] == "OAI"),
            "inspections": insp,
        }
    return sites


def run(ctx: Ctx) -> int:
    prev = read_normalized(ctx.name) or {}
    if ctx.from_file:
        rows = read_file(ctx.from_file)
        mode = f"file {ctx.from_file.name}"
    else:
        user, key = os.environ.get("FDA_DD_USER", ""), os.environ.get("FDA_DD_KEY", "")
        if not (user and key):
            raise Unreachable("no FDA Data Dashboard API key — set FDA_DD_USER and FDA_DD_KEY, or export the Inspections "
                              "table (Country = India, Product Type = Drugs) to Excel and run with --from-file")
        rows = fetch_api(ctx, user, key)
        mode = "api"
    write_json_atomic(ctx.raw_dir / "inspections_rows.json", rows)
    sites = build_sites(rows)
    if not sites and prev.get("data"):
        raise Unreachable("no Indian drug inspections in the input — keeping the previous file")
    codes = defaultdict(int)
    for s in sites.values():
        codes[s["last_code"] or "?"] += 1
    ctx.log(f"  {len(rows):,} inspection rows → {len(sites):,} Indian sites · latest outcome {dict(codes)}")
    write_normalized(ctx, META, sites, len(sites), extra={"input": mode, "inspections": sum(len(s["inspections"]) for s in sites.values()),
                                                           "latest_outcome": dict(codes)})
    return len(sites)
