"""Plant registry: India's manufacturing plants from CDSCO's official lists, with
what each is licensed / certified to make, linked to the NSQ site directory.

Source: data/sources/cdsco_plants.json, written by redis-loader/sources/cdsco_plants.py
(CDSCO SUGAM approved manufacturing sites + the WHO-GMP certified-units list).

Linking to NSQ: every site in the NSQ site directory (company + PIN from "Manufactured
By") is matched to registry plants by normalised company name:

    site        same company, same PIN
    company     same company, same state, only one registry plant of that company there
    fuzzy       near-identical company name (token-set ratio >= 93) at the same PIN

The registry gives the pattern work its denominators: how many plants can make sterile
injectables, how many have a beta-lactam block, and how many of those had NSQ alerts.
It covers WHO-GMP certified units and SUGAM-listed sites, not every licensed plant in
India, so rates are "per registry plant", and every page says so.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter, defaultdict
from typing import Any, Optional

import capability_catalog
import capability_rules

from .config import settings
from . import sites

_lock = threading.Lock()
_cache: Optional[tuple[tuple, dict[str, Any]]] = None

CAPABILITY_LABELS = {
    "tablet": "Tablets", "capsule_hard": "Hard capsules", "capsule_soft": "Soft gelatin capsules", "lozenge": "Lozenges",
    "oral_film_gum": "Oral films / medicated gum", "oral_liquid": "Oral liquids", "dry_syrup": "Dry syrups", "oral_powder": "Oral powders / sachets",
    "svp_liquid": "Injectables (SVP liquid)", "svp_dry_powder": "Dry-powder injections", "lyophilised": "Lyophilised injectables",
    "lvp": "Large-volume parenterals", "prefilled_syringe": "Pre-filled syringes", "ophthalmic": "Ophthalmics", "otic_nasal": "Ear / nasal",
    "topical": "Topicals", "transdermal": "Transdermal patches", "suppository": "Suppositories / pessaries", "inhalation": "Inhalation",
    "api": "APIs (bulk drugs)", "finished_unspecified": "Formulations (unspecified)", "biological": "Biologicals / vaccines",
    "medical_device": "Medical devices",
}
SEGREGATED_LABELS = {
    "beta_lactam": "Beta-lactam (penicillin)", "cephalosporin": "Cephalosporin", "carbapenem": "Carbapenem", "hormone": "Hormones",
    "steroid": "Steroids", "cytotoxic": "Cytotoxic / oncology", "immunosuppressant": "Immunosuppressants", "potent_other": "Highly potent",
}
# NSQ "Form type" -> registry capabilities that can make it
NSQ_FORM_CAPS = {
    "Tablet": {"tablet"}, "Capsule": {"capsule_hard", "capsule_soft"},
    "Injection": {"svp_liquid", "svp_dry_powder", "lyophilised", "lvp", "prefilled_syringe"},
    "Syrup/Suspension": {"oral_liquid", "dry_syrup"}, "Ointment/Cream": {"topical"},
    "Powder/Granules": {"oral_powder", "dry_syrup"}, "Drops": {"ophthalmic", "otic_nasal", "oral_liquid"},
}
SOURCE_URL = {"cdsco_who_gmp": "https://cdsco.gov.in/opencms/opencms/en/Home/",
              "cdsco_sugam": "https://cdscoonline.gov.in/CDSCO/manuf_site"}


def _path():
    return settings.data_dir / "sources" / "cdsco_plants.json"


def _load() -> tuple[float, dict[str, Any]]:
    p = _path()
    try:
        return p.stat().st_mtime, json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0, {}


def _tokens(name: str, drop: set[str] = frozenset(), keep_generic: bool = False) -> list[str]:
    """Company-name tokens: legal suffixes dropped, plurals folded, town names removed."""
    name = re.sub(r"\((?=[^)]*\b(unit|division|div|formerly|w\.?e\.?f|a unit)\b)[^)]*\)?", " ", name or "", flags=re.I)
    name = re.split(r"[;]|\b(?:plot|khasra|kh\.?\s?no|village|vill|survey|sy\.?\s?no|gat|near|opp|sector|p\.?o\.?|post|mfgd)\b", name, maxsplit=1, flags=re.I)[0]
    out = []
    for t in sites.norm_company(name).split():
        if t.isdigit() or t == "no":
            continue
        t = re.sub(r"(?<=[a-z]{4})s$", "", t)  # pharmaceuticals -> pharmaceutical
        if t and t not in drop and (keep_generic or t not in _GENERIC):
            out.append(t)
    return out


_GENERIC = {"pharmaceutical", "pharma", "healthcare", "health", "care", "lifescience", "life", "science", "remedie", "formulation",
            "drug", "chemical", "biotech", "medicament", "product", "and", "of", "a", "an", "division", "unit", "ii", "iii", "i", "iv"}


_PIN_STATE = [("11", "Delhi"), ("12", "Haryana"), ("13", "Haryana"), ("14", "Punjab"), ("15", "Punjab"), ("160", "Chandigarh"),
              ("17", "Himachal Pradesh"), ("18", "Jammu and Kashmir"), ("19", "Jammu and Kashmir"),
              ("244", "Uttarakhand"), ("246", "Uttarakhand"), ("247", "Uttarakhand"), ("248", "Uttarakhand"), ("249", "Uttarakhand"),
              ("262", "Uttarakhand"), ("263", "Uttarakhand"), ("2", "Uttar Pradesh"), ("3", "Rajasthan"), ("36", "Gujarat"), ("37", "Gujarat"),
              ("38", "Gujarat"), ("39", "Gujarat"), ("396", "Daman and Diu"), ("403", "Goa"), ("4", "Maharashtra"), ("45", "Madhya Pradesh"),
              ("46", "Madhya Pradesh"), ("47", "Madhya Pradesh"), ("48", "Madhya Pradesh"), ("49", "Chhattisgarh"), ("50", "Telangana"),
              ("5", "Andhra Pradesh"), ("56", "Karnataka"), ("57", "Karnataka"), ("58", "Karnataka"), ("59", "Karnataka"), ("605", "Puducherry"),
              ("6", "Tamil Nadu"), ("67", "Kerala"), ("68", "Kerala"), ("69", "Kerala"), ("737", "Sikkim"), ("7", "West Bengal"), ("75", "Odisha"),
              ("76", "Odisha"), ("77", "Odisha"), ("78", "Assam"), ("79", "North East"), ("8", "Bihar"), ("81", "Jharkhand"), ("82", "Jharkhand"),
              ("83", "Jharkhand")]


def pin_state(pin: Optional[str]) -> Optional[str]:
    """Postal circle of a PIN (longest matching prefix). Approximate at circle borders (e.g. 396 = Daman or Valsad)."""
    if not pin:
        return None
    best = max((p for p in _PIN_STATE if pin.startswith(p[0])), key=lambda p: len(p[0]), default=None)
    return best[1] if best else None


_ADDRESS_STOP = {"plot", "industrial", "area", "estate", "village", "vill", "road", "sector", "phase", "district", "distt", "tehsil",
                 "near", "opposite", "post", "office", "india", "pradesh", "limited", "private", "khasra", "survey", "block", "unit",
                 "growth", "centre", "center", "park", "zone", "highway", "national", "main", "street", "nagar", "town", "city"}


def _town_words(*texts: Optional[str]) -> set[str]:
    return {w for t in texts if t for w in re.findall(r"[a-z]{4,}", t.lower())}


def _score_pair(site: dict[str, Any], site_tokens: list[str], p: dict[str, Any], same_state_count: int) -> Optional[tuple]:
    """(pin_equal, name_score, address_score) or None when the pair cannot be the same plant."""
    from rapidfuzz import fuzz

    pin, ppin = site.get("pincode") or "", p.get("pin") or ""
    if pin and ppin and pin != ppin:
        return None
    if not (pin and ppin):
        s_state = site.get("state") or ""
        if pin and pin_state(pin) and pin_state(pin) not in ("North East", "Daman and Diu"):
            s_state = pin_state(pin)  # the PIN says where the plant is better than the NSQ state column
        p_state = p.get("state") or pin_state(ppin) or ""
        if s_state and p_state and s_state != p_state and "Daman" not in s_state + p_state:
            return None
    towns = _town_words(p.get("district"), p.get("address")) - set(site_tokens)
    # names compared with their generic words ("healthcare", "lifesciences") kept, so sister companies stay apart
    a = " ".join(_tokens(site["company"], keep_generic=True))
    b = " ".join(_tokens(p["name"], drop=towns, keep_generic=True))
    if not a or not b:
        return None
    name = fuzz.token_sort_ratio(a, b)
    if name < (80 if (pin and ppin) else 88):
        return None
    addr = fuzz.token_set_ratio((site.get("address") or "").lower(), (p.get("address") or "").lower())
    if not (pin and ppin):
        site_words = _town_words(site.get("address"), site.get("city"))
        place_hit = bool((_town_words(p.get("district"), p.get("address")) - _ADDRESS_STOP) & site_words)
        # a site with a PIN needs address evidence; without one, a company with a single plant in the state is enough
        if addr < 55 and not place_hit and (pin or same_state_count != 1):
            return None
    return (bool(pin and ppin), name, addr)


def _link(plants: dict[str, dict[str, Any]], directory: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """site_id -> {plant_ids, match}; also fills plants[pid]['nsq']."""
    by_token: dict[str, set[str]] = defaultdict(set)
    for pid, p in plants.items():
        for n in [p["name"], *(p.get("aliases") or [])]:
            for t in _tokens(n)[:2]:
                by_token[t].add(pid)

    links: dict[str, dict[str, Any]] = {}
    for s in directory:
        stoks = _tokens(s["company"])
        if not stoks:
            continue
        cands = set().union(*(by_token.get(t, set()) for t in stoks[:2]))
        in_state = Counter(" ".join(_tokens(plants[c]["name"])) for c in cands if plants[c].get("state") == s.get("state"))
        scored = [(sc, pid) for pid in cands
                  for sc in [_score_pair(s, stoks, plants[pid], in_state.get(" ".join(_tokens(plants[pid]["name"])), 0))] if sc]
        if not scored:
            continue
        scored.sort(reverse=True)
        best = scored[0][0]
        top = [pid for sc, pid in scored if sc == best]
        if len(top) > 1 and not best[0]:
            continue  # two equally good plants and no PIN to choose: leave unlinked
        how = "site" if best[0] and best[1] >= 97 else ("site_fuzzy" if best[0] else "company")
        links[s["id"]] = {"plant_ids": top, "match": how, "score": list(best)}
        for pid in top:
            n = plants[pid].setdefault("nsq", {"alerts": 0, "sites": [], "forms": Counter(), "first": None, "last": None})
            n["alerts"] += s["alerts"]
            n["sites"].append({"id": s["id"], "company": s["company"], "alerts": s["alerts"], "match": how,
                               "pincode": s.get("pincode") or "", "last": s.get("last")})
            n["forms"].update(s.get("forms") or {})
            if s.get("first") and (not n["first"] or s["first"] < n["first"]):
                n["first"] = s["first"]
            if s.get("last") and (not n["last"] or s["last"] > n["last"]):
                n["last"] = s["last"]
    for p in plants.values():
        n = p.get("nsq")
        if n:
            n["forms"] = dict(n["forms"].most_common())
            # alerted forms the plant is not certified / licensed for (only meaningful with WHO-GMP data)
            caps = set(p["capabilities"]["dosage_forms"])
            if p.get("who_gmp"):
                p["nsq"]["outside_capabilities"] = sorted(f for f in n["forms"] if f in NSQ_FORM_CAPS and not (NSQ_FORM_CAPS[f] & caps))
    return links


def registry() -> dict[str, Any]:
    """{'meta', 'plants', 'links'}; rebuilt when the registry file or the NSQ frame changes."""
    global _cache
    mtime, raw = _load()
    directory = sites.directory()
    key = (mtime, id(directory))
    c = _cache
    if c is not None and c[0] == key:
        return c[1]
    with _lock:
        if _cache is None or _cache[0] != key:
            t0 = time.time()
            plants = {pid: {**p} for pid, p in (raw.get("data") or {}).items()}
            links = _link(plants, directory) if plants else {}
            meta = {k: raw.get(k) for k in ("title", "publisher", "url", "retrieved_at", "records", "inputs", "stats")}
            _cache = (key, {"meta": meta, "plants": plants, "links": links})
            print(f"[plants] {len(plants)} plants, {len(links)} NSQ sites linked in {time.time() - t0:.1f}s")
        return _cache[1]


def site_link(site_id: str) -> Optional[dict[str, Any]]:
    """Registry plant(s) for an NSQ directory site, trimmed for the site page."""
    reg = registry()
    link = reg["links"].get(site_id)
    if not link:
        return None
    return {"match": link["match"], "plants": [brief(reg["plants"][pid]) for pid in link["plant_ids"]]}


def who_valid_until(p: dict[str, Any]) -> Optional[str]:
    v = [e["valid_until"] for e in p["capabilities"].get("evidence", []) if e.get("source") == "cdsco_who_gmp" and e.get("valid_until")]
    return max(v) if v else None


def brief(p: dict[str, Any]) -> dict[str, Any]:
    c = p["capabilities"]
    return {"id": p["id"], "name": p["name"], "state": p.get("state"), "district": p.get("district"), "pin": p.get("pin"),
            "who_gmp": p.get("who_gmp_certified", False), "who_gmp_valid_until": who_valid_until(p),
            "licence_forms": sorted({l.get("form") for l in p.get("licences") or [] if l.get("form")}),
            "licence_classes": c.get("licence_classes", []),
            "sterile": c.get("sterile", False), "api": c.get("api", False), "schedule_c": c.get("schedule_c", False),
            "dosage_forms": c.get("dosage_forms", []), "segregated": c.get("segregated", {}), "therapeutic": c.get("therapeutic", []),
            "loan_licensees": p.get("loan_licensees", []), "sources": p.get("sources", []),
            "nsq_alerts": (p.get("nsq") or {}).get("alerts", 0), "nsq_last": (p.get("nsq") or {}).get("last")}


def rule_input(p: dict[str, Any]) -> dict[str, Any]:
    return {**p["capabilities"], "who_gmp": p.get("who_gmp_certified", False)}


def catalog_profile(p: dict[str, Any]) -> dict[str, Any]:
    """The plant in the capability catalog's 7 sections, from CDSCO's listing via capability_rules."""
    derived = capability_rules.derive(rule_input(p))
    sections = []
    for sec in capability_catalog.SECTIONS:
        have = [{"token": c.token, "label": c.label, **derived[c.token]} for c in sec.capabilities if c.token in derived]
        sections.append({"id": sec.section_id, "title": sec.title, "total": len(sec.capabilities), "have": have})
    cat = set(capability_catalog.CAPABILITY_BY_TOKEN)
    other = [{"token": t, "label": t.replace("_", " ").capitalize(), **v} for t, v in derived.items() if t not in cat]
    return {"sections": sections, "other": other, "containment": capability_rules.containment(rule_input(p)),
            "approved_forms": capability_rules.approved_forms(p["capabilities"]),
            "required": sum(1 for v in derived.values() if v["basis"] == "required"),
            "inferred": sum(1 for v in derived.values() if v["basis"] == "inferred")}


def _matches(p: dict[str, Any], q: str, state: str, capability: str, segregated: str, cert: str, nsq: str) -> bool:
    c = p["capabilities"]
    if q:
        ql = q.lower()
        hay = " ".join([p["name"], *(p.get("aliases") or []), p.get("address") or "", p.get("district") or "", p.get("pin") or "",
                        *(p.get("loan_licensees") or [])]).lower()
        if ql not in hay:
            return False
    if state and p.get("state") != state:
        return False
    if capability:
        if capability == "sterile" and not c.get("sterile"):
            return False
        if capability != "sterile" and capability not in c.get("dosage_forms", []):
            return False
    if segregated and segregated not in c.get("segregated", {}):
        return False
    if cert == "who_gmp" and not p.get("who_gmp_certified"):
        return False
    if cert == "sugam" and "cdsco_sugam" not in p.get("sources", []):
        return False
    if cert == "schedule_c" and not c.get("schedule_c"):
        return False
    if cert == "loan" and not p.get("loan_licensees"):
        return False
    alerts = (p.get("nsq") or {}).get("alerts", 0)
    if nsq == "yes" and not alerts:
        return False
    if nsq == "no" and alerts:
        return False
    return True


def search(q: str = "", state: str = "", capability: str = "", segregated: str = "", cert: str = "", nsq: str = "",
           sort: str = "nsq", page: int = 1, size: int = 25) -> dict[str, Any]:
    rows = [p for p in registry()["plants"].values() if _matches(p, q, state, capability, segregated, cert, nsq)]
    if sort == "name":
        rows.sort(key=lambda p: p["name"].lower())
    elif sort == "forms":
        rows.sort(key=lambda p: (-len(p["capabilities"]["dosage_forms"]), p["name"].lower()))
    else:
        rows.sort(key=lambda p: (-(p.get("nsq") or {}).get("alerts", 0), p["name"].lower()))
    total = len(rows)
    pages = max(1, (total + size - 1) // size)
    page = max(1, min(page, pages))
    return {"items": [brief(p) for p in rows[(page - 1) * size: page * size]], "total": total, "page": page, "pages": pages}


def get(plant_id: str) -> Optional[dict[str, Any]]:
    p = registry()["plants"].get(plant_id)
    if p is None:
        return None
    out = {**p, "brief": brief(p), "who_gmp_valid_until": who_valid_until(p), "catalog": catalog_profile(p)}
    out["source_links"] = [{"key": s, "url": SOURCE_URL.get(s)} for s in p.get("sources", [])]
    return out


def _rate(alerted: int, plants: int, alerts: int) -> dict[str, Any]:
    return {"plants": plants, "plants_with_nsq": alerted, "alerts": alerts,
            "share_with_nsq": round(100 * alerted / plants, 1) if plants else None,
            "alerts_per_100_plants": round(100 * alerts / plants, 1) if plants else None}


def summary() -> dict[str, Any]:
    reg = registry()
    plants = list(reg["plants"].values())
    directory = sites.directory()
    linked_sites = set(reg["links"])

    def group(keyfn) -> dict[str, dict[str, Any]]:
        acc: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # plants, plants with NSQ, alerts
        for p in plants:
            a = (p.get("nsq") or {}).get("alerts", 0)
            for k in keyfn(p):
                acc[k][0] += 1
                acc[k][1] += 1 if a else 0
                acc[k][2] += a
        return {k: _rate(v[1], v[0], v[2]) for k, v in acc.items()}

    caps = group(lambda p: p["capabilities"]["dosage_forms"] + (["sterile"] if p["capabilities"].get("sterile") else []))
    seg = group(lambda p: list(p["capabilities"]["segregated"]))
    states = group(lambda p: [p.get("state") or "Unknown"])
    tiers = group(lambda p: (["WHO-GMP certified"] if p.get("who_gmp_certified") else ["SUGAM only (not WHO-GMP)"]))
    breadth = group(lambda p: [("1 form" if n == 1 else "2–3 forms" if n <= 3 else "4–6 forms" if n <= 6 else "7+ forms")
                               for n in [len([f for f in p["capabilities"]["dosage_forms"] if f not in ("api", "finished_unspecified")])] if n])
    alerts_all = sum(s["alerts"] for s in directory)
    alerts_linked = sum(s["alerts"] for s in directory if s["id"] in linked_sites)
    outside = Counter(f for p in plants for f in (p.get("nsq") or {}).get("outside_capabilities", []))
    return {
        "meta": reg["meta"],
        "plants": len(plants),
        "who_gmp": sum(1 for p in plants if p.get("who_gmp_certified")),
        "sugam": sum(1 for p in plants if "cdsco_sugam" in p.get("sources", [])),
        "with_pin": sum(1 for p in plants if p.get("pin")),
        "with_nsq": sum(1 for p in plants if (p.get("nsq") or {}).get("alerts")),
        "sterile": sum(1 for p in plants if p["capabilities"].get("sterile")),
        "api": sum(1 for p in plants if p["capabilities"].get("api")),
        "loan_hosts": sum(1 for p in plants if p.get("loan_licensees")),
        "nsq_sites": len(directory),
        "nsq_sites_linked": len(linked_sites),
        "nsq_alerts_linked_pct": round(100 * alerts_linked / alerts_all, 1) if alerts_all else 0.0,
        "match_kinds": dict(Counter(v["match"] for v in reg["links"].values())),
        "capabilities": [{"key": k, "label": CAPABILITY_LABELS.get(k, "Sterile (any)" if k == "sterile" else k), **v}
                         for k, v in sorted(caps.items(), key=lambda kv: -kv[1]["plants"])],
        "segregated": [{"key": k, "label": SEGREGATED_LABELS.get(k, k), **v} for k, v in sorted(seg.items(), key=lambda kv: -kv[1]["plants"])],
        "states": [{"key": k, "label": k, **v} for k, v in sorted(states.items(), key=lambda kv: -kv[1]["plants"])],
        "tiers": [{"key": k, "label": k, **v} for k, v in tiers.items()],
        "breadth": [{"key": k, "label": k, **v} for k, v in sorted(breadth.items(), key=lambda kv: ["1 form", "2–3 forms", "4–6 forms", "7+ forms"].index(kv[0]))],
        "outside_capabilities": [{"form": k, "plants": v} for k, v in outside.most_common()],
        "labels": {"capabilities": CAPABILITY_LABELS, "segregated": SEGREGATED_LABELS},
        "caveat": "Rates are per plant in CDSCO's WHO-GMP and SUGAM lists (about 2,100 plants), not every licensed plant in India. "
                  "NSQ alerts are linked by company name and PIN; unlinked alerts are from makers not on these lists.",
    }


def facets() -> dict[str, Any]:
    plants = registry()["plants"].values()
    return {
        "states": [k for k, _ in Counter(p.get("state") for p in plants if p.get("state")).most_common()],
        "capabilities": [{"key": k, "label": CAPABILITY_LABELS.get(k, k)} for k, _ in
                         Counter(f for p in plants for f in p["capabilities"]["dosage_forms"]).most_common()],
        "segregated": [{"key": k, "label": SEGREGATED_LABELS.get(k, k)} for k, _ in
                       Counter(s for p in plants for s in p["capabilities"]["segregated"]).most_common()],
    }


def candidates(names: list[str], state: str = "", city: str = "", limit: int = 8) -> list[dict[str, Any]]:
    """Registry plants that could be an organisation's plant: same company name (fuzzy), ranked by place."""
    from rapidfuzz import fuzz

    keys = [" ".join(_tokens(n, keep_generic=True)) for n in names if n]
    keys = [k for k in keys if k]
    if not keys:
        return []
    out = []
    for p in registry()["plants"].values():
        pk = " ".join(_tokens(p["name"], drop=_town_words(p.get("district"), p.get("address")), keep_generic=True))
        if not pk:
            continue
        score = max(max(fuzz.token_sort_ratio(k, pk), fuzz.token_set_ratio(k, pk) if min(len(k.split()), len(pk.split())) >= 2 else 0)
                    for k in keys)
        if score < 85:
            continue
        place = 0
        if state and p.get("state") == state:
            place += 1
        if city and city.lower() in " ".join(filter(None, [p.get("address"), p.get("district")])).lower():
            place += 2
        out.append((place, score, p))
    out.sort(key=lambda x: (-x[0], -x[1], -len(x[2]["capabilities"]["dosage_forms"])))
    res = []
    for place, score, p in out[:limit]:
        prof = catalog_profile(p)
        res.append({**brief(p), "address": p.get("address"), "name_score": round(score), "same_state": place in (1, 3),
                    "same_city": place >= 2, "derived": prof["required"] + prof["inferred"], "required": prof["required"]})
    return res
