"""Pharmacopoeia change tracker: which of an organisation's products are touched by Ph. Eur. revisions, what changes,
and from when — from EDQM's free Knowledge Database and its published schedule (redis-loader/sources/edqm_kd.py).

No monograph text is shown (the Ph. Eur. is a paid, copyrighted publication): only EDQM's own public summary of each
revision, the issue it appears in, and that issue's implementation date where EDQM's schedule gives one.

An organisation's products are the molecules named in its CDSCO alerts (single-ingredient and combinations). A change
is flagged when the section it revises corresponds to a test the organisation has already failed for that molecule.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Optional

from . import data, signals

# Ph. Eur. section heading → CDSCO failure category
_SECTION_CATEGORY = [
    (r"assay|content", "Assay / Content"),
    (r"related substances|impurit|enantiomeric", "Related Substances"),
    (r"dissolution", "Dissolution"),
    (r"identification", "Identification"),
    (r"water|loss on drying", "Water / LOD"),
    (r"appearance|characters|description|colour|clarity", "Description / Appearance"),
    (r"sterility|endotoxin|microbial", "Sterility / Microbial"),
    (r"\bph\b|acidity|alkalinity", "pH"),
]
_CATEGORY_ALIASES = {"Identification": ("Identification", "Spurious / Identity"), "Water / LOD": ("Water / LOD", "Loss on Drying")}


def section_category(section: str) -> Optional[str]:
    s = (section or "").lower()
    for rx, cat in _SECTION_CATEGORY:
        if re.search(rx, s):
            return cat
    return None


def source() -> dict[str, Any]:
    d = signals._load("edqm_kd")
    return d or {}


def monographs_for(key: str) -> list[dict[str, Any]]:
    return ((source().get("data") or {}).get(key) or {}).get("monographs") or []


def _state_today(e: dict[str, Any], today: str) -> dict[str, Any]:
    """Re-evaluate upcoming / in force against today's date (the file stores the state at fetch time)."""
    if e.get("implementation"):
        return {**e, "state": "upcoming" if e["implementation"] > today else "in_force"}
    return e


def molecule_changes(key: str, failed_categories: Optional[set[str]] = None, today: Optional[str] = None) -> list[dict[str, Any]]:
    today = today or date.today().isoformat()
    out = []
    for m in monographs_for(key):
        hist = [_state_today(e, today) for e in m.get("history") or []]
        for e in hist:
            for c in e.get("changes") or []:
                c["category"] = section_category(c.get("section", ""))
                c["you_failed_it"] = bool(c["category"] and failed_categories and (
                    c["category"] in failed_categories or any(a in failed_categories for a in _CATEGORY_ALIASES.get(c["category"], ()))))
        upcoming = sorted([e for e in hist if e.get("state") == "upcoming"], key=lambda e: e["implementation"])
        out.append({
            "number": m["number"], "name": m["name"], "status": m.get("status"), "last_published": m.get("last_published"),
            "url": m.get("url"), "history_url": m.get("history_url"), "reference_standards": m.get("reference_standards"),
            "upcoming": upcoming,
            "under_revision": {"text": m.get("revision"), "pharmeuropa": m.get("pharmeuropa"), "state": m.get("revision_state")}
            if m.get("revision_in_progress") else None,
            "recent": [e for e in hist if e.get("state") != "upcoming"][:3],
            "touches_your_failures": any(c.get("you_failed_it") for e in hist for c in e.get("changes") or [])
            or bool(m.get("revision_in_progress") and failed_categories and section_category(m.get("revision") or "") in failed_categories),
        })
    return out


def org_tracker(ontology_keys: list[str], today: Optional[str] = None) -> dict[str, Any]:
    from .insights import tracked_for

    today = today or date.today().isoformat()
    src = source()
    df = data.org_frame(ontology_keys)
    rows: dict[str, dict[str, Any]] = {}
    if not df.empty:
        cats: dict[str, Counter] = defaultdict(Counter)
        prods: dict[str, Counter] = defaultdict(Counter)
        for name, cat in zip(df["Name of Product"].astype(str), df["Failure_Category_Primary"].fillna("").astype(str)):
            for k in tracked_for(name):
                cats[k][cat] += 1
                prods[k][name] += 1
        for k in cats:
            mons = molecule_changes(k, set(cats[k]), today)
            p = data.cdmo()["patents"].get(k)
            rows[k] = {"key": k, "name": p.api_name if p else k.replace("_", " ").title(), "alerts": sum(cats[k].values()),
                       "your_failures": [{"name": c, "count": n} for c, n in cats[k].most_common(4) if c],
                       "products": [n for n, _ in prods[k].most_common(3)], "monographs": mons,
                       "has_monograph": bool(mons)}
    items = sorted(rows.values(), key=lambda r: (
        not any(m["upcoming"] for m in r["monographs"]),
        not any(m["under_revision"] for m in r["monographs"]),
        not any(m["touches_your_failures"] for m in r["monographs"]),
        not r["has_monograph"], -r["alerts"]))
    upcoming = sorted(({"molecule": r["name"], "key": r["key"], "monograph": m["number"], "monograph_name": m["name"], **e}
                       for r in items for m in r["monographs"] for e in m["upcoming"]), key=lambda x: x["implementation"])
    return {
        "today": today, "molecules": items, "upcoming": upcoming,
        "counts": {"molecules": len(items), "with_monograph": sum(r["has_monograph"] for r in items),
                   "upcoming": len(upcoming), "under_revision": sum(1 for r in items for m in r["monographs"] if m["under_revision"]),
                   "touching_failures": sum(1 for r in items if any(m["touches_your_failures"] for m in r["monographs"]))},
        "source": {"label": src.get("title") or "EDQM Knowledge Database", "url": src.get("url"), "retrieved_at": src.get("retrieved_at")},
        "schedule": src.get("schedule") or {}, "schedule_source": src.get("schedule_source"),
        "scope": ("European Pharmacopoeia monographs for the active substances in your CDSCO-listed products. Indian products are tested "
                  "to the IP: its revision lists are not connected yet. Monograph texts are not shown (EDQM licence); each change links to "
                  "EDQM's own summary."),
    }
