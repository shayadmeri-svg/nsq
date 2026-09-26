"""FDA Purple Book (licensed biological products, incl. biosimilars).

Monthly CSV at accessdata.fda.gov/drugsatfda_docs/PurpleBook/<year>/
purplebook-search-<month>-data-download.csv. The file has a "changes this
month" block followed by the full database; both use the same header row,
so we parse every header block and de-duplicate by BLA + product number.

Normalised per proper name (suffix like "-xxxx" stripped, so biosimilars group
with their reference product):

  key -> {proper_name, reference{proprietary_name, applicant, bla, approval, dosage_form, route,
          exclusivity_expires}, biosimilars, interchangeables, biosimilar_holders, products}
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from .common import Ctx, NotModified, Unreachable, download, write_normalized

BASE = "https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/{year}/purplebook-search-{month}-data-download.csv"
META = {
    "title": "FDA Purple Book",
    "publisher": "U.S. Food and Drug Administration",
    "url": "https://purplebooksearch.fda.gov/downloads",
    "page": "https://purplebooksearch.fda.gov/downloads",
    "cadence": "monthly",
    "feeds": ["Biologic reference products", "Biosimilar / interchangeable counts", "Reference exclusivity"],
}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]
_SUFFIX = re.compile(r"-[a-z]{4}$")


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")


def _date(s: str) -> str:
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%d-%b-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def proper_key(name: str) -> str:
    n = (name or "").strip().lower()
    n = _SUFFIX.sub("", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    return n


def _get(row: dict[str, str], *cands: str) -> str:
    for c in cands:
        if c in row and row[c]:
            return row[c]
    for c in cands:  # prefix match (FDA occasionally renames "exp_date" etc.)
        for k, v in row.items():
            if k.startswith(c) and v:
                return v
    return ""


def parse_csv(text: str) -> dict[str, dict[str, Any]]:
    lines = list(csv.reader(io.StringIO(text)))
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in lines:
        normed = [_norm_header(c) for c in line]
        if "bla_number" in normed and ("proper_name" in normed or "proprietary_name" in normed):
            header = normed
            continue
        if header and len(line) >= 5 and any(line):
            rows.append({header[i]: (line[i] or "").strip() for i in range(min(len(header), len(line)))})
    seen: set[tuple[str, str]] = set()
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"reference": None, "biosimilars": set(), "interchangeables": set(),
                                                             "holders": set(), "products": 0, "names": set()})
    for r in rows:
        bla = _get(r, "bla_number")
        pno = _get(r, "product_number")
        if (bla, pno) in seen:
            continue
        seen.add((bla, pno))
        proper = _get(r, "proper_name")
        ref_proper = _get(r, "ref_product_proper_name", "reference_product_proper_name") or proper
        key = proper_key(ref_proper)
        if not key:
            continue
        g = groups[key]
        g["products"] += 1
        g["names"].add(proper)
        bla_type = _get(r, "bla_type").lower()
        licensure = _get(r, "licensure").lower()
        if "351(k)" in bla_type or "biosimilar" in bla_type or "interchangeable" in bla_type:
            g["biosimilars"].add(bla)
            g["holders"].add(_get(r, "applicant"))
            if "interchangeable" in bla_type:
                g["interchangeables"].add(bla)
        elif g["reference"] is None or "351(a)" in bla_type:
            if g["reference"] is None or (licensure != "disc" and not g["reference"].get("active")):
                g["reference"] = {
                    "proprietary_name": _get(r, "proprietary_name"),
                    "applicant": _get(r, "applicant"),
                    "bla": bla,
                    "approval": _date(_get(r, "date_of_first_licensure", "approval_date")),
                    "dosage_form": _get(r, "dosage_form").lower(),
                    "route": _get(r, "route_of_administration").lower(),
                    "strength": _get(r, "strength"),
                    "exclusivity_expires": _date(_get(r, "ref_product_exclusivity_exp_date", "exclusivity_expiration_date")),
                    "orphan_exclusivity_expires": _date(_get(r, "orphan_exclusivity_exp_date")),
                    "active": licensure != "disc",
                }
    out = {}
    for k, g in groups.items():
        out[k] = {
            "proper_name": k,
            "names": sorted(g["names"])[:6],
            "reference": g["reference"],
            "biosimilars": len(g["biosimilars"]),
            "interchangeables": len(g["interchangeables"]),
            "biosimilar_holders": sorted(h for h in g["holders"] if h)[:20],
            "products": g["products"],
        }
    return out


def run(ctx: Ctx) -> int:
    if ctx.from_file:
        text = ctx.from_file.read_text(encoding="utf-8-sig", errors="replace")
    else:
        # Latest available monthly file: this month, else walk back up to 4 months.
        today = date.today()
        text, last_exc = None, None
        for back in range(0, 5):
            y, m = today.year, today.month - back
            while m <= 0:
                m += 12
                y -= 1
            url = BASE.format(year=y, month=_MONTHS[m - 1])
            try:
                path = download(ctx, url, f"purplebook-{y}-{m:02d}.csv")
            except NotModified:
                raise
            except Unreachable as exc:
                last_exc = exc
                break
            except Exception as exc:  # 404 for months not yet published
                ctx.log(f"  {url}: {exc}")
                last_exc = exc
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            break
        if text is None:
            raise Unreachable(str(last_exc)) if isinstance(last_exc, Unreachable) else RuntimeError(f"No Purple Book file found: {last_exc}")
    data = parse_csv(text)
    if not data:
        raise RuntimeError("Purple Book file parsed to 0 products — the column layout may have changed.")
    write_normalized(ctx, META, data, len(data))
    return len(data)
