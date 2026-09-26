"""EMA — centrally authorised human medicines (EPAR JSON report).

Normalised per active substance / INN:

  key -> {inn, therapeutic_areas, atc, originator{name, holder, authorised, status},
          authorised, generics, biosimilars, orphan, withdrawn, first_generic_authorised,
          holders, medicines[name...]}

Only the centralised procedure is covered: many old small molecules were
authorised nationally and do not appear here (that gap is reported as such).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from .common import Ctx, download, write_normalized

META = {
    "title": "EMA medicines (EPAR)",
    "publisher": "European Medicines Agency",
    "url": "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json",
    "page": "https://www.ema.europa.eu/en/medicines/download-medicine-data",
    "cadence": "daily (EMA regenerates the report daily)",
    "feeds": ["EU authorisation status", "EU generics / biosimilars", "EU LOE estimate", "Therapeutic area"],
}


def _norm(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (k or "").strip().lower()).strip("_")


def _date(s: Any) -> str:
    s = str(s or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    s = s.split(" ")[0]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _yes(v: Any) -> bool:
    return str(v or "").strip().lower() in {"yes", "true", "1", "y"}


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "medicines", "items", "results"):
            if isinstance(payload.get(k), list):
                return payload[k]
    raise ValueError("Unrecognised EMA JSON layout")


def parse(payload: Any) -> dict[str, dict[str, Any]]:
    import ingredients as ing  # core/

    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "inn": "", "areas": set(), "atc": set(), "holders": set(), "medicines": [], "authorised": 0,
        "generics": 0, "biosimilars": 0, "orphan": False, "withdrawn": 0, "originator": None, "first_generic": "",
    })
    for raw in _records(payload):
        r = {_norm(k): v for k, v in raw.items()}
        if "human" not in str(r.get("category", "human")).lower():
            continue
        inn = str(r.get("international_non_proprietary_name_common_name") or r.get("international_non_proprietary_name_inn_common_name")
                  or r.get("inn_common_name") or r.get("active_substance") or "").strip()
        if not inn:
            continue
        parts = [p for p in re.split(r"\s*[/,;]\s*|\s+and\s+", inn) if p]
        if len(parts) > 1:
            continue  # fixed combinations: skip for the per-molecule view
        key = ing.ingredient_key(inn)
        if not key:
            continue
        g = groups[key]
        g["inn"] = g["inn"] or inn
        status = str(r.get("medicine_status") or r.get("authorisation_status") or "").lower()
        authorised = "authorised" in status and "not" not in status and "withdrawn" not in status
        generic = _yes(r.get("generic")) or _yes(r.get("generic_or_hybrid"))
        biosimilar = _yes(r.get("biosimilar"))
        decided = _date(r.get("european_commission_decision_date") or r.get("marketing_authorisation_date"))
        holder = str(r.get("marketing_authorisation_developer_applicant_holder") or r.get("marketing_authorisation_holder_company_name") or "").strip()
        name = str(r.get("name_of_medicine") or r.get("medicine_name") or "").strip()
        area = str(r.get("therapeutic_area_mesh") or r.get("therapeutic_area") or "").strip()
        if area:
            for a in re.split(r"\s*[;\n]\s*", area):
                if a:
                    g["areas"].add(a)
        atc = str(r.get("atc_code_human") or r.get("atc_code") or "").strip()
        if atc:
            g["atc"].add(atc)
        if "withdrawn" in status:
            g["withdrawn"] += 1
        if not authorised:
            continue
        g["authorised"] += 1
        g["medicines"].append(name)
        if holder:
            g["holders"].add(holder)
        g["orphan"] |= _yes(r.get("orphan_medicine") or r.get("orphan"))
        if generic:
            g["generics"] += 1
            if decided and (not g["first_generic"] or decided < g["first_generic"]):
                g["first_generic"] = decided
        elif biosimilar:
            g["biosimilars"] += 1
            if decided and (not g["first_generic"] or decided < g["first_generic"]):
                g["first_generic"] = decided
        else:
            cur = g["originator"]
            if cur is None or (decided and decided < (cur.get("authorised") or "9999")):
                g["originator"] = {"name": name, "holder": holder, "authorised": decided, "status": status,
                                   "url": str(r.get("medicine_url") or "")}
    out = {}
    for k, g in groups.items():
        out[k] = {
            "inn": g["inn"],
            "therapeutic_areas": sorted(g["areas"])[:5],
            "atc": sorted(g["atc"])[:3],
            "originator": g["originator"],
            "authorised": g["authorised"],
            "generics": g["generics"],
            "biosimilars": g["biosimilars"],
            "orphan": g["orphan"],
            "withdrawn": g["withdrawn"],
            "first_generic_authorised": g["first_generic"],
            "holders": sorted(g["holders"])[:20],
            "medicines": sorted(set(g["medicines"]))[:10],
        }
    return out


def run(ctx: Ctx) -> int:
    path = ctx.from_file or download(ctx, META["url"], "ema_medicines.json")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    data = parse(payload)
    if not data:
        raise RuntimeError("EMA report parsed to 0 substances — the JSON layout may have changed.")
    write_normalized(ctx, META, data, len(data))
    return len(data)
