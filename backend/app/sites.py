"""Site directory: every Indian manufacturing site named in CDSCO NSQ alerts,
joined with FDA public records (establishment registration, Import Alert
66-40, openFDA recalls).

A "site" is one manufacturer at one PIN code (falling back to city) as
printed in the alert's "Manufactured By" field. What it makes is inferred
from the dosage forms of its alerted products, and every inferred capability
is marked 'inferred' when the site is turned into a plant profile.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from . import data
from .config import settings

_PIN = re.compile(r"(?<!\d)([1-8]\d{2})\s?(\d{3})(?!\d)")
_lock = threading.Lock()
_cache: Optional[tuple[tuple, list[dict[str, Any]]]] = None

# NSQ "Form type" -> (approved_forms, inferred capability tokens)
FORM_PROFILE: dict[str, tuple[list[str], list[str]]] = {
    "Tablet": (["solid_oral", "tablet"], ["compression", "wet_granulation", "film_coating", "blister_packing", "dissolution_testing"]),
    "Capsule": (["solid_oral", "capsule"], ["blister_packing", "bottle_packing", "dissolution_testing"]),
    "Injection": (["injection", "vial"], ["aseptic_fill", "vial_filling", "sterility_testing", "endotoxin_testing", "wfi_generation"]),
    "Syrup/Suspension": (["syrup", "suspension"], ["purified_water_generation", "bottle_packing"]),
    "Ointment/Cream": (["topical"], ["purified_water_generation"]),
    "Powder/Granules": (["powder"], ["dry_granulation"]),
    "Drops": (["drops"], ["purified_water_generation"]),
}


def norm_company(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"\bm/s\.?\s*", " ", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\b(private|pvt|limited|ltd|llp|inc|co|company|corporation|corp|the|india|industries|unit|plant|lab|labs|laboratories|laboratory)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _pincode(line: str) -> str:
    hits = _PIN.findall(line or "")
    return "".join(hits[-1]) if hits else ""


def _source(name: str) -> tuple[float, dict[str, Any]]:
    p = settings.data_dir / "sources" / f"{name}.json"
    try:
        mtime = p.stat().st_mtime
        return mtime, json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0, {}


def _mtimes() -> tuple:
    out = []
    for n in ("fda_establishments", "fda_import_alerts", "fda_recalls"):
        p = settings.data_dir / "sources" / f"{n}.json"
        out.append(p.stat().st_mtime if p.exists() else 0.0)
    return tuple(out)


def _index(rows: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    for r in rows.values():
        k = r.get("company_key") or norm_company(r.get("name", ""))
        if k:
            idx.setdefault(k, []).append(r)
    return idx


def build_directory(df: pd.DataFrame) -> list[dict[str, Any]]:
    import ingredients as ing  # core/

    est = _index((_source("fda_establishments")[1] or {}).get("data", {}))
    ia = _index((_source("fda_import_alerts")[1] or {}).get("data", {}))
    rec = _index((_source("fda_recalls")[1] or {}).get("data", {}))
    if df.empty:
        return []
    d = df[["Manufactured By", "Mfg_Company_Canonical", "Mfg_Ontology_Key", "Mfg_City", "Mfg_State", "Form type",
            "Name of Product", "Failure_Category_Primary", "Parsed_Date"]].copy()
    d["pin"] = d["Manufactured By"].astype(str).map(_pincode)
    d["company"] = d["Mfg_Company_Canonical"].fillna("").astype(str).str.replace(r"^M/s\.?\s*", "", regex=True).str.strip()
    d["okey"] = d["Mfg_Ontology_Key"].fillna("").astype(str)
    d["loc"] = d["pin"].where(d["pin"] != "", d["Mfg_City"].fillna("").astype(str).str.lower())
    out: list[dict[str, Any]] = []
    for (okey, loc), g in d.groupby(["okey", "loc"], sort=False):
        if not okey:
            continue
        company = g["company"].mode().iat[0] if not g["company"].mode().empty else okey
        addr = g["Manufactured By"].astype(str).mode().iat[0]
        ckey = norm_company(company)
        forms = Counter(g["Form type"].fillna("Other"))
        ingr = Counter(i for p in g["Name of Product"].astype(str) for i in ing.extract_ingredients(p))
        pin = g["pin"].iat[0] if loc and loc.isdigit() else ""
        regs = est.get(ckey, [])
        site_regs = [r for r in regs if pin and (r.get("postal") or "").replace(" ", "")[:6] == pin]
        last = g["Parsed_Date"].max()
        first = g["Parsed_Date"].min()
        approved, caps = [], []
        for f, _n in forms.most_common():
            prof = FORM_PROFILE.get(f)
            if prof:
                approved += [x for x in prof[0] if x not in approved]
                caps += [x for x in prof[1] if x not in caps]
        ia_hits = ia.get(ckey, [])
        rec_hit = (rec.get(ckey) or [None])[0]
        out.append({
            "id": f"{_slug(okey)}-{loc if pin else _slug(loc) or 'na'}",
            "company": company,
            "ontology_key": okey,
            "address": addr,
            "city": str(g["Mfg_City"].mode().iat[0]) if not g["Mfg_City"].mode().empty else "",
            "state": str(g["Mfg_State"].mode().iat[0]) if not g["Mfg_State"].mode().empty else "",
            "pincode": pin,
            "alerts": int(len(g)),
            "products": int(g["Name of Product"].nunique()),
            "first": first.strftime("%Y-%m") if pd.notna(first) else None,
            "last": last.strftime("%Y-%m") if pd.notna(last) else None,
            "forms": dict(forms.most_common()),
            "top_ingredients": [k for k, _ in ingr.most_common(8)],
            "categories": dict(Counter(g["Failure_Category_Primary"].fillna("")).most_common(4)),
            "approved_forms": approved,
            "capabilities": caps,
            "fda": {
                "registered": bool(site_regs or regs),
                "match": "site" if site_regs else ("company" if regs else ""),
                "establishments": [{k: r.get(k) for k in ("fei", "duns", "name", "address", "city", "state", "postal", "operations", "expiration")}
                                   for r in (site_regs or regs)[:4]],
                "import_alert": [{k: r.get(k) for k in ("name", "fei", "address", "dates")} for r in ia_hits[:3]],
                "recalls": ({k: rec_hit.get(k) for k in ("recalls", "class_i", "last", "items")} if rec_hit else None),
            },
        })
    out.sort(key=lambda s: (-s["alerts"], s["company"]))
    return out


def directory() -> list[dict[str, Any]]:
    global _cache
    df = data.frame()
    key = (id(df), len(df), _mtimes())
    c = _cache
    if c is not None and c[0] == key:
        return c[1]
    with _lock:
        if _cache is None or _cache[0] != key:
            t0 = time.time()
            rows = build_directory(df)
            _cache = (key, rows)
            print(f"[sites] built {len(rows)} sites in {time.time() - t0:.1f}s")
        return _cache[1]


def get(site_id: str) -> Optional[dict[str, Any]]:
    return next((s for s in directory() if s["id"] == site_id), None)


def search(q: str = "", state: str = "", fda: str = "", form: str = "", ontology_keys: Optional[list[str]] = None,
           page: int = 1, size: int = 25) -> dict[str, Any]:
    rows = directory()
    if ontology_keys is not None:
        ks = set(ontology_keys)
        rows = [r for r in rows if r["ontology_key"] in ks]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["company"].lower() or ql in r["address"].lower() or ql in r["ontology_key"] or ql == r["pincode"]]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if form:
        rows = [r for r in rows if form in r["forms"]]
    if fda == "registered":
        rows = [r for r in rows if r["fda"]["registered"]]
    elif fda == "import_alert":
        rows = [r for r in rows if r["fda"]["import_alert"]]
    elif fda == "recalls":
        rows = [r for r in rows if r["fda"]["recalls"]]
    total = len(rows)
    pages = max(1, (total + size - 1) // size)
    page = max(1, min(page, pages))
    return {"items": rows[(page - 1) * size: page * size], "total": total, "page": page, "pages": pages}


def summary() -> dict[str, Any]:
    rows = directory()
    states = Counter(r["state"] for r in rows if r["state"])
    return {
        "sites": len(rows),
        "companies": len({r["ontology_key"] for r in rows}),
        "fda_registered": sum(1 for r in rows if r["fda"]["registered"]),
        "fda_site_match": sum(1 for r in rows if r["fda"]["match"] == "site"),
        "import_alert": sum(1 for r in rows if r["fda"]["import_alert"]),
        "recalls": sum(1 for r in rows if r["fda"]["recalls"]),
        "with_pincode": sum(1 for r in rows if r["pincode"]),
        "states": [{"name": k, "count": v} for k, v in states.most_common(12)],
        "forms": [{"name": k, "count": v} for k, v in Counter(f for r in rows for f in r["forms"]).most_common(9)],
    }


def plant_from_site(site: dict[str, Any], asset_id: str) -> dict[str, Any]:
    """PlantAsset fields for a directory site. Every capability is 'inferred'."""
    fda = site["fda"]
    inspections = []
    for a in fda.get("import_alert") or []:
        inspections.append({"agency": "USFDA", "type": "Import Alert 66-40", "date": (a.get("dates") or [""])[-1],
                            "outcome": "Red list — detention without physical examination", "source": "https://www.accessdata.fda.gov/cms_ia/importalert_189.html"})
    if fda.get("recalls"):
        r = fda["recalls"]
        inspections.append({"agency": "USFDA", "type": "Recalls (openFDA)", "date": r.get("last", ""),
                            "outcome": f"{r.get('recalls', 0)} recall(s), {r.get('class_i', 0)} Class I", "source": "https://open.fda.gov/apis/drug/enforcement/"})
    sources = [{"label": "CDSCO NSQ alerts naming this site", "url": "https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug"}]
    if fda.get("establishments"):
        sources.append({"label": "FDA establishment registration (DECRS)", "url": "https://www.accessdata.fda.gov/scripts/cder/drls/"})
    forms_txt = ", ".join(f"{k} ({v})" for k, v in site["forms"].items())
    reg = fda.get("establishments") or []
    summary = f"{site['alerts']} CDSCO NSQ alerts ({site['first']}–{site['last']}) across {site['products']} products; forms: {forms_txt}."
    if reg:
        summary += f" FDA-registered ({fda['match']} match, FEI {reg[0].get('fei') or '—'}; operations: {', '.join(reg[0].get('operations') or []) or '—'})."
    containment = "cytotoxic" if any(k in " ".join(site["top_ingredients"]) for k in ("tamoxifen", "capecitabine", "methotrexate", "imatinib", "letrozole")) else "standard"
    return {
        "asset_id": asset_id,
        "site_name": f"{site['company']} — {site['city'] or site['state'] or site['pincode']}".strip(" —"),
        "city": site["city"], "state": site["state"], "country": "India",
        "capabilities": site["capabilities"],
        "approved_forms": site["approved_forms"],
        "containment_class": containment,
        "certifications": [], "certifications_active": [],
        "capability_basis": {t: "inferred" for t in site["capabilities"]},
        "certification_basis": {},
        "inspections": inspections,
        "notes": "Created from the site directory (public records). Capabilities are inferred from the dosage forms of alerted products — confirm with the organisation.",
        "reference": {
            "company": site["company"], "site": site["address"], "location": ", ".join(x for x in (site["city"], site["state"], site["pincode"]) if x),
            "summary": summary, "retrieved_at": time.strftime("%Y-%m-%d"), "sources": sources, "site_id": site["id"],
        },
    }
