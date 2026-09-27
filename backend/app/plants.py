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
              "cdsco_sugam": "https://cdscoonline.gov.in/CDSCO/manuf_site",
              "eudragmdp": "https://eudragmdp.ema.europa.eu/inspections/gmpc/searchGMPCompliance.do"}


def _path(name: str = "cdsco_plants"):
    return settings.data_dir / "sources" / f"{name}.json"


_files: dict[str, tuple[float, dict[str, Any]]] = {}


def _load(name: str = "cdsco_plants") -> tuple[float, dict[str, Any]]:
    """Parsed source file, re-read only when its mtime changes."""
    p = _path(name)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return 0.0, {}
    hit = _files.get(name)
    if hit and hit[0] == mtime:
        return hit
    try:
        _files[name] = (mtime, json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return 0.0, {}
    return _files[name]


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


EU_URL = "https://eudragmdp.ema.europa.eu/inspections/gmpc/searchGMPCompliance.do"


def _eu_summary(site: dict[str, Any]) -> dict[str, Any]:
    forms, stated = capability_rules.from_eu_scope(site.get("scope") or [])
    recent = bool(site.get("last_gmp_inspection")) and site["last_gmp_inspection"] >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 365.25 * 86400))
    return {**{k: site.get(k) for k in ("key", "name", "address", "city", "postcode", "oms_org", "oms_loc", "duns", "status",
                                         "last_gmp_inspection", "last_ncr", "roles", "scope", "substances", "documents")},
            "forms": sorted(forms), "stated": stated, "certified": site.get("status") == "compliant" and recent}


def _eu_plant(site: dict[str, Any], eu: dict[str, Any]) -> dict[str, Any]:
    pin = (site.get("postcode") or "").replace(" ", "")[:6] or None
    forms = eu["forms"]
    pid = f"eu-{re.sub(r'[^a-z0-9]+', '-', (site.get('name') or '').lower()).strip('-')[:50]}--{pin or site.get('key')}"
    return {"id": pid, "name": site.get("name") or site.get("manufacturer") or "?", "aliases": [], "address": site.get("address"),
            "district": site.get("city"), "state": pin_state(pin), "pin": pin, "phones": [], "sources": ["eudragmdp"],
            "licences": [], "loan_licensees": [], "who_gmp": [], "who_gmp_certified": False,
            "capabilities": {"dosage_forms": forms, "segregated": {}, "therapeutic": [], "evidence": [], "raw": "",
                             "sterile": bool(set(forms) & capability_rules.STERILE), "api": "api" in forms,
                             "finished_dose": bool(set(forms) - {"api"}), "licence_classes": [], "schedule_c": False}}


def _merge_eu(plants: dict[str, dict[str, Any]], eu_sites: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Attach EudraGMDP sites to registry plants (company + PIN, or company + town); unmatched sites become plants."""
    from rapidfuzz import fuzz

    by_pin: dict[str, list[str]] = defaultdict(list)
    by_token: dict[str, set[str]] = defaultdict(set)
    for pid, p in plants.items():
        if p.get("pin"):
            by_pin[p["pin"]].append(pid)
        for t in _tokens(p["name"])[:2]:
            by_token[t].add(pid)
    matched = added = 0
    for site in eu_sites.values():
        eu = _eu_summary(site)
        name = " ".join(_tokens(site.get("name") or "", keep_generic=True))
        pin = (site.get("postcode") or "").replace(" ", "")[:6]
        best, best_score = [], 0.0
        for pid in set(by_pin.get(pin, [])) | set().union(*(by_token.get(t, set()) for t in _tokens(site.get("name") or "")[:2])):
            p = plants[pid]
            pn = " ".join(_tokens(p["name"], drop=_town_words(p.get("district"), p.get("address")), keep_generic=True))
            if not pn or not name:
                continue
            score = fuzz.token_sort_ratio(name, pn)
            if p.get("pin") and pin:
                if p["pin"] != pin or score < 80:
                    continue
                score += 20
            else:
                town = _town_words(site.get("city"), site.get("address")) - _ADDRESS_STOP
                if score < 92 or p.get("state") != pin_state(pin) or not (town & _town_words(p.get("district"), p.get("address"))):
                    continue
            if score > best_score:
                best, best_score = [pid], score
            elif score == best_score:
                best.append(pid)  # e.g. two CDSCO units of one company at the same PIN: the certificate covers the site
        if best:
            for pid in best:
                p = plants[pid]
                p["eu"] = eu
                caps = dict(p["capabilities"])
                caps["dosage_forms"] = sorted(set(caps.get("dosage_forms") or []) | set(eu["forms"]))
                caps["sterile"] = caps.get("sterile") or bool(set(eu["forms"]) & capability_rules.STERILE)
                caps["api"] = caps.get("api") or "api" in eu["forms"]
                p["capabilities"] = caps
                if "eudragmdp" not in p.get("sources", []):
                    p["sources"] = [*p.get("sources", []), "eudragmdp"]
            matched += 1
        else:
            np = _eu_plant(site, eu)
            np["eu"] = eu
            plants[np["id"]] = np
            added += 1
    return {"eu_sites": len(eu_sites), "eu_matched": matched, "eu_added": added}


def registry() -> dict[str, Any]:
    """{'meta', 'plants', 'links'}; rebuilt when a source file or the NSQ frame changes."""
    global _cache
    mtime, raw = _load()
    eu_mtime, eu_raw = _load("eudragmdp")
    directory = sites.directory()
    key = (mtime, eu_mtime, id(directory))
    c = _cache
    if c is not None and c[0] == key:
        return c[1]
    with _lock:
        if _cache is None or _cache[0] != key:
            t0 = time.time()
            plants = {pid: {**p} for pid, p in (raw.get("data") or {}).items()}
            eu_stats = _merge_eu(plants, eu_raw.get("data") or {}) if eu_raw.get("data") else {}
            links = _link(plants, directory) if plants else {}
            meta = {k: raw.get(k) for k in ("title", "publisher", "url", "retrieved_at", "records", "inputs", "stats")}
            meta["eudragmdp"] = {"retrieved_at": eu_raw.get("retrieved_at"), "listed": eu_raw.get("total_listed"), **eu_stats} if eu_raw else None
            _cache = (key, {"meta": meta, "plants": plants, "links": links})
            print(f"[plants] {len(plants)} plants ({eu_stats or 'no EU data'}), {len(links)} NSQ sites linked in {time.time() - t0:.1f}s")
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
            "nsq_alerts": (p.get("nsq") or {}).get("alerts", 0), "nsq_last": (p.get("nsq") or {}).get("last"),
            "eu_status": (p.get("eu") or {}).get("status"), "eu_gmp": bool((p.get("eu") or {}).get("certified")),
            "eu_last": (p.get("eu") or {}).get("last_gmp_inspection"), "eu_ncr": (p.get("eu") or {}).get("last_ncr"),
            "eu_stated": (p.get("eu") or {}).get("stated") or {}}


def rule_input(p: dict[str, Any]) -> dict[str, Any]:
    return {**p["capabilities"], "who_gmp": p.get("who_gmp_certified", False)}


def catalog_profile(p: dict[str, Any]) -> dict[str, Any]:
    """The plant in the capability catalog's 7 sections, from CDSCO's listing via capability_rules."""
    derived = capability_rules.derive(rule_input(p))
    for t, lines in ((p.get("eu") or {}).get("stated") or {}).items():
        derived[t] = {"basis": "stated", "why": [f"EU GMP certificate scope: {'; '.join(lines)}"]}
    sections = []
    for sec in capability_catalog.SECTIONS:
        have = [{"token": c.token, "label": c.label, **derived[c.token]} for c in sec.capabilities if c.token in derived]
        sections.append({"id": sec.section_id, "title": sec.title, "total": len(sec.capabilities), "have": have})
    cat = set(capability_catalog.CAPABILITY_BY_TOKEN)
    other = [{"token": t, "label": t.replace("_", " ").capitalize(), **v} for t, v in derived.items() if t not in cat]
    return {"sections": sections, "other": other, "containment": capability_rules.containment(rule_input(p)),
            "approved_forms": capability_rules.approved_forms(p["capabilities"]),
            "stated": sum(1 for v in derived.values() if v["basis"] == "stated"),
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
    if cert == "eu_gmp" and not (p.get("eu") or {}).get("certified"):
        return False
    if cert == "eu_ncr" and (p.get("eu") or {}).get("status") != "non_compliant":
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


def api_only(p: dict[str, Any]) -> bool:
    """Makes only APIs (bulk drugs): NSQ tests finished medicines, so such a plant cannot appear in the alerts."""
    forms = set(p["capabilities"].get("dosage_forms") or [])
    return bool(forms) and forms <= {"api", "medical_device"}


def summary(exclude_api_only: bool = False) -> dict[str, Any]:
    reg = registry()
    plants = [p for p in reg["plants"].values() if not (exclude_api_only and api_only(p))]
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
    tiers = group(lambda p: (["WHO-GMP certified"] if p.get("who_gmp_certified") else ["SUGAM only (not WHO-GMP)"] if "cdsco_sugam" in p.get("sources", []) else [])
                  + (["EU GMP certified (last 3 years)"] if (p.get("eu") or {}).get("certified") else [])
                  + (["EU non-compliance statement"] if (p.get("eu") or {}).get("status") == "non_compliant" else []))
    breadth = group(lambda p: [("1 form" if n == 1 else "2–3 forms" if n <= 3 else "4–6 forms" if n <= 6 else "7+ forms")
                               for n in [len([f for f in p["capabilities"]["dosage_forms"] if f not in ("api", "finished_unspecified")])] if n])
    alerts_all = sum(s["alerts"] for s in directory)
    alerts_linked = sum(s["alerts"] for s in directory if s["id"] in linked_sites)
    outside = Counter(f for p in plants for f in (p.get("nsq") or {}).get("outside_capabilities", []))
    return {
        "meta": reg["meta"],
        "exclude_api_only": exclude_api_only,
        "api_only_plants": sum(1 for p in reg["plants"].values() if api_only(p)),
        "plants": len(plants),
        "who_gmp": sum(1 for p in plants if p.get("who_gmp_certified")),
        "sugam": sum(1 for p in plants if "cdsco_sugam" in p.get("sources", [])),
        "eu_gmp": sum(1 for p in plants if (p.get("eu") or {}).get("certified")),
        "eu_ncr": sum(1 for p in plants if (p.get("eu") or {}).get("status") == "non_compliant"),
        "eu_only": sum(1 for p in plants if p.get("sources") == ["eudragmdp"]),
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
        "caveat": f"Rates are per plant in CDSCO's WHO-GMP and SUGAM lists and EudraGMDP ({len(plants):,} plants), not every licensed plant in India. "
                  "NSQ alerts are linked by company name and PIN; unlinked alerts are from makers on none of these lists.",
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


# --------------------------------------------------------------------------- who can make a molecule

_FORM_WORDS = [  # regulatory / Orange Book dosage-form words -> registry dosage forms
    (r"lyophil|for injection|powder.*inject", ["lyophilised", "svp_dry_powder"]),
    (r"pre-?filled|syringe|pen\b|cartridge", ["prefilled_syringe"]),
    (r"inject|infusion|vial|ampoule|parenteral|intravenous|subcutaneous|intramuscular", ["svp_liquid", "svp_dry_powder", "lyophilised", "lvp"]),
    (r"ophthalm|eye", ["ophthalmic"]),
    (r"inhal|aerosol|nebul", ["inhalation"]),
    (r"cream|ointment|gel|lotion|topical|external", ["topical"]),
    (r"patch|transdermal", ["transdermal"]),
    (r"suppositor", ["suppository"]),
    (r"for (oral )?suspension|dry syrup", ["dry_syrup"]),
    (r"syrup|suspension|solution;oral|oral solution|elixir|drops", ["oral_liquid"]),
    (r"capsule", ["capsule_hard", "capsule_soft"]),
    (r"tablet", ["tablet"]),
    (r"powder|granule|sachet", ["oral_powder"]),
]
_BETA = re.compile(r"(cillin|penem)\b", re.I)
_CEPH = re.compile(r"^(cef|ceph)", re.I)
_HORMONE = re.compile(r"estr|progest|testoster|levonorg|norethist|medroxyprog|dydrogest|contracep", re.I)
_makers_cache: dict[tuple, dict[str, Any]] = {}


def _molecule_requirements(key: str) -> dict[str, Any]:
    from . import data

    m = data.cdmo()
    p, reg, dem = m["patents"].get(key), m["regulatory"].get(key), m["demand"].get(key)
    if p is None:
        return {}
    name = (p.api_name or key)
    text = " ".join(filter(None, [reg.dosage_form if reg else "", p.therapeutic_area or ""])).lower()
    forms: list[str] = []
    for pat, fs in _FORM_WORDS:
        if re.search(pat, (reg.dosage_form or "").lower() if reg else ""):
            forms = fs
            break
    basis = "Orange Book / regulatory dosage form" if forms else None
    seg = []
    if _BETA.search(name):
        seg.append("beta_lactam")
    if _CEPH.search(name):
        seg.append("cephalosporin")
    if "oncolog" in text or "cancer" in text or ((dem.cluster if dem else "") or "").lower() == "oncology":
        seg.append("cytotoxic")
    if _HORMONE.search(name):
        seg.append("hormone")
    biologic = bool(p and getattr(p, "modality", "") and "small" not in (getattr(p, "modality", "") or "small"))
    return {"key": key, "name": name, "forms": forms, "forms_basis": basis, "segregated": seg, "biologic": biologic,
            "dosage_form": reg.dosage_form if reg else None, "names": [name, *(getattr(p, "aliases", None) or [])]}


def makers(key: str, limit: int = 30) -> Optional[dict[str, Any]]:
    """Who can make a tracked molecule: plants EU-inspected for its API, plants whose CDSCO listing names it,
    plants that made it (NSQ alerts), and plants permitted to make its dosage form (with its segregated block)."""
    import ingredients as ing
    from . import data

    req = _molecule_requirements(key)
    if not req:
        return None
    reg = registry()
    ck = (key, id(reg), id(data.frame()))
    if ck in _makers_cache:
        return _makers_cache[ck]
    plants = reg["plants"]
    keys = {ing.ingredient_key(n) for n in req["names"] if n}
    keys |= {k.split()[0] for k in keys if k and len(k.split()[0]) >= 5}
    keys.discard("")
    word_re = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True)) + r")", re.I) if keys else None

    api_makers, listed = [], []
    for p in plants.values():
        subs = [s for s in ((p.get("eu") or {}).get("substances") or []) if ing.ingredient_key(s) in keys
                or (ing.ingredient_key(s).split() or [""])[0] in keys]
        if subs:
            api_makers.append({**brief(p), "evidence": f"EU GMP inspection of the API: {', '.join(subs[:3])}"})
            continue
        raw = p["capabilities"].get("raw") or ""
        if word_re and raw and word_re.search(raw):
            m = word_re.search(raw)
            listed.append({**brief(p), "evidence": "CDSCO WHO-GMP listing: …" + raw[max(0, m.start() - 60):m.end() + 60] + "…"})

    # plants that made it: NSQ alerts for the molecule, through the site directory links
    df = data.attributable(data.frame())
    made: dict[str, dict[str, Any]] = {}
    unlinked = 0
    if not df.empty:
        idx = {k: key for k in keys}
        mask = df["Name of Product"].astype(str).map(lambda s: any(ing.match_tracked(i, idx) == key for i in ing.extract_ingredients(s)))
        rows = df[mask]
        site_ids = [sites.site_id_for(r) for _, r in rows.iterrows()]
        for sid in site_ids:
            link = reg["links"].get(sid)
            if not link:
                unlinked += 1
                continue
            for pid in link["plant_ids"]:
                e = made.setdefault(pid, {**brief(plants[pid]), "alerts_for_molecule": 0, "match": link["match"]})
                e["alerts_for_molecule"] += 1
    made_list = sorted(made.values(), key=lambda x: -x["alerts_for_molecule"])

    # plants permitted to make its dosage form (and with the segregated block it needs)
    capable = []
    if req["forms"]:
        for p in plants.values():
            c = p["capabilities"]
            if not set(req["forms"]) & set(c.get("dosage_forms") or []):
                continue
            if req["segregated"] and not set(req["segregated"]) & set(c.get("segregated") or {}):
                continue
            capable.append(p)
    rank = lambda p: (-(1 if (p.get("eu") or {}).get("certified") else 0), -(1 if p.get("who_gmp_certified") else 0),  # noqa: E731
                      (p.get("nsq") or {}).get("alerts", 0), p["name"].lower())
    capable.sort(key=rank)
    out = {
        "molecule": req,
        "api_makers": api_makers[:limit], "api_makers_total": len(api_makers),
        "listed": listed[:limit], "listed_total": len(listed),
        "made": made_list[:limit], "made_total": len(made_list), "nsq_alerts_unlinked": unlinked,
        "capable_total": len(capable),
        "capable_eu": sum(1 for p in capable if (p.get("eu") or {}).get("certified")),
        "capable_who": sum(1 for p in capable if p.get("who_gmp_certified")),
        "capable_ncr": sum(1 for p in capable if (p.get("eu") or {}).get("status") == "non_compliant"),
        "capable_by_state": dict(Counter(p.get("state") or "Unknown" for p in capable).most_common(8)),
        "capable": [brief(p) for p in capable[:limit]],
        "note": "Plants permitted to make the dosage form (and the segregated block it needs) — capability, not a claim that they make this molecule.",
    }
    if len(_makers_cache) > 200:
        _makers_cache.clear()
    _makers_cache[ck] = out
    return out
