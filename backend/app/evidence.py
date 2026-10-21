"""Evidence for one NSQ alert's molecule: only what a public source says, each block with its source and link.

Replaces the hand-written drug profiles (core/gmp_knowledge.PRODUCT_CATALOG: "probable root causes", "VigiBase
risks", "ideal" process corridors and excipient percentages, patent titles) that had no citation. What is shown
instead, per molecule:

  nsq          every CDSCO alert naming this molecule across India: failure categories, the share of this alert's
               category, and the result text of similar alerts quoted as CDSCO published it
  dissolution  FDA Dissolution Methods Database: the method FDA recommends for each dosage form
  label        the US reference label (openFDA / DailyMed): inactive ingredients and PK values, quoted
  recalls      FDA enforcement reports naming the molecule (openFDA, live, cached a day), the ones whose reason
               matches this alert's failure category first
  patents      Orange Book patents with titles from Google Patents, and the per-market status with its basis
  guidance     the ICH / EU GMP documents that govern the failed test (links checked to resolve)

Nothing is inferred about the cause of this particular failure: a public record can show patterns, not root causes.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

import pandas as pd
import requests

from . import data, signals

_ICH = "https://database.ich.org/sites/default/files/"
GUIDES = {
    "q6a": {"title": "ICH Q6A — Specifications: test procedures and acceptance criteria (incl. dissolution decision trees)", "issuer": "ICH",
            "url": _ICH + "Q6A%20Guideline.pdf"},
    "q2": {"title": "ICH Q2(R2) — Validation of analytical procedures", "issuer": "ICH", "url": _ICH + "ICH_Q2%28R2%29_Guideline_2023_1130.pdf"},
    "q3b": {"title": "ICH Q3B(R2) — Impurities in new drug products", "issuer": "ICH", "url": _ICH + "Q3B%28R2%29%20Guideline.pdf"},
    "q1a": {"title": "ICH Q1A(R2) — Stability testing", "issuer": "ICH", "url": _ICH + "Q1A%28R2%29%20Guideline.pdf"},
    "q9": {"title": "ICH Q9(R1) — Quality risk management", "issuer": "ICH", "url": _ICH + "ICH_Q9%28R1%29_Guideline_Step4_2022_1219.pdf"},
    "q10": {"title": "ICH Q10 — Pharmaceutical quality system (CAPA)", "issuer": "ICH", "url": _ICH + "Q10%20Guideline.pdf"},
    "annex1": {"title": "EU GMP Annex 1 (2022) — Manufacture of sterile medicinal products", "issuer": "European Commission",
               "url": "https://health.ec.europa.eu/system/files/2022-08/20220825_gmp-an1_en_0.pdf"},
    "fda_diss": {"title": "FDA Dissolution Methods Database", "issuer": "US FDA",
                 "url": "https://www.accessdata.fda.gov/scripts/cder/dissolution/index.cfm"},
}
# Which documents govern a failed test (by CDSCO failure category). Each line of advice in the mitigation bank is
# general practice; these are the documents it comes from.
CATEGORY_GUIDES = {
    "Dissolution": ["fda_diss", "q6a", "q1a"],
    "Disintegration": ["q6a"],
    "Assay / Content": ["q2", "q6a", "q1a"],
    "Uniformity": ["q6a"],
    "Uniformity of Weight": ["q6a"],
    "Related Substances": ["q3b", "q1a", "q2"],
    "Description / Appearance": ["q1a", "q6a"],
    "Sterility / Microbial": ["annex1"],
    "Bacterial Endotoxin": ["annex1"],
    "Particulate Matter": ["annex1"],
    "pH": ["q6a"],
}
# Words in an FDA recall reason that correspond to a CDSCO failure category.
_RECALL_WORDS = {
    "Dissolution": r"dissolution",
    "Disintegration": r"disintegrat",
    "Assay / Content": r"subpotent|superpotent|assay|potency|content uniformity",
    "Related Substances": r"impurit|degradat|nitrosamine|related substance",
    "Description / Appearance": r"discolor|spot|foreign|appearance|odor|particulate",
    "Sterility / Microbial": r"steril|microbial|contaminat",
    "Bacterial Endotoxin": r"endotoxin",
    "pH": r"\bph\b",
}
_recall_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _src(name: str) -> dict[str, Any]:
    d = signals._load(name)
    return {"label": d.get("title") or name, "publisher": d.get("publisher"), "url": d.get("page") or d.get("url"),
            "retrieved_at": d.get("retrieved_at")} if d else {"label": name}


def _molecule(product: str) -> Optional[str]:
    from .insights import tracked_for

    keys = tracked_for(product)
    return keys[0] if len(keys) == 1 else None  # combinations: no single molecule to attribute


def _names(key: str) -> list[str]:
    p = data.cdmo()["patents"].get(key)
    names = [key.replace("_", " ")]
    if p:
        names = [p.api_name, *p.aliases, *names]
    return [n for n in dict.fromkeys(names) if n]


def nsq_block(key: str, product: str, category: str) -> dict[str, Any]:
    from .insights import tracked_for

    df = data.frame()
    if df.empty:
        return {}
    names = df["Name of Product"].astype(str)
    uniq = {n: tracked_for(n) for n in names.unique()}
    hit = df[names.map(lambda n: uniq.get(n) == [key])]
    if hit.empty:
        return {}
    cats = hit["Failure_Category_Primary"].value_counts()
    same = hit[hit["Failure_Category_Primary"] == category].sort_values("Parsed_Date", ascending=False)
    quotes = [{"month": r["Parsed_Date"].strftime("%Y-%m") if pd.notna(r["Parsed_Date"]) else None, "product": str(r["Name of Product"]),
               "result": str(r.get("NSQ Result") or r.get("Reason") or ""), "lab": str(r.get("Reporting by Lab/State") or "")}
              for _, r in same.head(6).iterrows()]
    return {"alerts": int(len(hit)), "manufacturers": int(hit["Mfg_Ontology_Key"].nunique()) if "Mfg_Ontology_Key" in hit else None,
            "categories": [{"name": str(k), "count": int(v), "pct": round(100 * v / len(hit), 1)} for k, v in cats.head(8).items()],
            "this_category_pct": round(100 * float(cats.get(category, 0)) / len(hit), 1), "similar": quotes,
            "source": {"label": "CDSCO NSQ alerts (single-ingredient products)", "url": "https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable"}}


def dissolution_block(key: str) -> list[dict[str, Any]]:
    reg = data.cdmo()["regulatory"].get(key)
    return list(getattr(reg, "dissolution_methods", None) or [])


def label_block(key: str) -> Optional[dict[str, Any]]:
    rec = (signals._load("fda_labels").get("data") or {}).get(key) or {}
    if not rec.get("found"):
        return None
    lab = rec["labels"][0]
    return {"brand": lab.get("brand"), "manufacturer": lab.get("manufacturer"), "application": lab.get("application_number"),
            "url": lab.get("url"), "inactive_ingredients": lab.get("inactive_ingredients") or [],
            "other_labels": [{k: x.get(k) for k in ("brand", "manufacturer", "application_number", "url", "inactive_ingredients")}
                             for x in rec["labels"][1:]],
            "pk": rec.get("pk") or {}, "pk_label": rec.get("pk_label")}


def recalls_all(key: str) -> dict[str, Any]:
    """The 100 most recent FDA enforcement reports whose product description names the molecule (cached a day)."""
    term = _names(key)[0]
    hit = _recall_cache.get(term.lower())
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    q = f'product_description:"{term}"'
    try:
        r = requests.get("https://api.fda.gov/drug/enforcement.json", params={"search": q, "limit": 100, "sort": "report_date:desc"}, timeout=15)
        if r.status_code == 404:  # openFDA: no matches
            rows, total = [], 0
        elif r.status_code == 200:
            rows, total = r.json().get("results", []), (r.json().get("meta") or {}).get("results", {}).get("total", 0)
        else:
            return {"error": f"openFDA returned {r.status_code}", "items": [], "total": 0, "query": q}
    except (requests.RequestException, ValueError):
        return {"error": "openFDA unreachable", "items": [], "total": 0, "query": q}
    items = [{"recall_number": x.get("recall_number"), "date": x.get("report_date"), "class": x.get("classification"),
              "firm": x.get("recalling_firm"), "country": x.get("country"), "reason": x.get("reason_for_recall"),
              "product": (x.get("product_description") or "")[:160],
              "url": f"https://api.fda.gov/drug/enforcement.json?search=recall_number:%22{x.get('recall_number')}%22"} for x in rows]
    out = {"total": total, "items": items, "query": q}
    _recall_cache[term.lower()] = (time.time(), out)
    return out


def recalls_block(key: str, category: str) -> dict[str, Any]:
    out = recalls_all(key)
    if out.get("error"):
        return {"error": out["error"]}
    rx = _RECALL_WORDS.get(category)
    matching = [x for x in out.get("items", []) if rx and re.search(rx, x.get("reason") or "", re.I)]
    return {"total": out.get("total", 0), "matching_category": len(matching), "items": (matching + [x for x in out.get("items", []) if x not in matching])[:6],
            "source": {"label": "FDA enforcement reports (openFDA)", "url": "https://open.fda.gov/apis/drug/enforcement/"}}


def patents_block(key: str) -> Optional[dict[str, Any]]:
    p = data.cdmo()["patents"].get(key)
    if not p:
        return None
    geo = [{"code": g.country_code, "name": g.country_name, "status": g.market_status, "date": g.loe_date.isoformat() if g.loe_date else None,
            "basis": g.basis, "note": g.notes, "sources": g.sources} for g in p.geo_coverage if g.country_code in ("US", "EU", "IN")]
    us = [{"text": e.description, "expiry": e.expiry_date.isoformat() if e.expiry_date else None, "url": e.url}
          for e in [*p.formulation_patents, *p.secondary_patents]][:8]
    return {"compound": p.compound_patent or None, "us_patents": us, "markets": geo}


def guidance(category: str) -> list[dict[str, str]]:
    return [GUIDES[g] for g in CATEGORY_GUIDES.get(category, [])] + [GUIDES["q9"], GUIDES["q10"]]


def for_alert(product: str, category: str) -> dict[str, Any]:
    key = _molecule(product)
    out: dict[str, Any] = {"molecule": None, "guidance": guidance(category)}
    if not key:
        out["note"] = ("This product is a combination or its molecule isn't in the universe yet, so no molecule-level evidence is shown; "
                       "the alert's own record and the guidance documents still apply.")
        return out
    p = data.cdmo()["patents"].get(key)
    out["molecule"] = {"key": key, "name": p.api_name if p else key.replace("_", " ").title()}
    out["nsq"] = nsq_block(key, product, category)
    out["dissolution"] = {"methods": dissolution_block(key), "source": _src("fda_dissolution")}
    out["label"] = label_block(key)
    out["recalls"] = recalls_block(key, category)
    out["patents"] = patents_block(key)
    from . import pharmacopoeia as ph

    out["pheur"] = ph.molecule_changes(key, {category} if category else None)
    return out
