"""Build the molecule universe: curated seeds + public sources + NSQ alerts.

Reads
  data/patent_seed.json, regulatory_seed.json, demand_seed.json   curated (hand) records
  data/sources/{orange_book,purple_book,ema,clinical_trials}.json   normalised public data
  nsq:record:* in Redis                                           CDSCO NSQ alerts (candidates)
  data/generated/watchlist.json                                   admin additions / exclusions

Writes (same structure as the seeds, so the existing loaders read them):
  data/generated/patents.json, regulatory.json, demand.json
  data/generated/molecule_universe.json   one summary row per molecule (+ skipped candidates)
  data/generated/candidates.json          names the ClinicalTrials fetcher queries

Rules
* Curated molecules are always included; public data overrides the fields it
  covers (US LOE, patents, exclusivity, RLD/TE, ANDA count, EU generics, trial
  counts) and each overridden field is marked in `provenance`.
* An NSQ ingredient with >= --min-alerts alerts becomes a molecule only when a
  public source confirms it (Orange Book single-ingredient product, EMA
  central authorisation or Purple Book licence). Watchlist names are always
  included; watchlist exclusions never are.
* Nothing is invented: a value no source covers is left empty/neutral and
  marked "unknown" or "derived" (with the rule) in provenance.

  python build_universe.py --redis-url redis://localhost:6379/0 [--min-alerts 5] [--max-auto 250]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import ingredients as ing  # noqa: E402
from sources.common import data_dir, now_iso, read_normalized, write_json_atomic  # noqa: E402
from sources.purple_book import proper_key  # noqa: E402

TODAY = date.today()
OB_PAGE = "https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files"
_LABELS = {"ip": re.compile(r"\bI\.?\s?P\.?\b"), "bp": re.compile(r"\bB\.?\s?P\.?\b"), "usp": re.compile(r"\bU\.?\s?S\.?\s?P\.?\b")}
_FORMS = [("injection", ("injection", "inj", "infusion", "vial", "ampoule")), ("syrup", ("syrup", "suspension", "elixir", "linctus", "oral solution")),
          ("capsule", ("capsule",)), ("tablet", ("tablet", "tab ")), ("topical", ("cream", "ointment", "gel", "lotion")),
          ("drops", ("drops",))]


# --- helpers --------------------------------------------------------------------

def _d(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = str(s)
    try:
        return date.fromisoformat(s[:10]) if len(s) >= 10 else date.fromisoformat(s[:7] + "-01")
    except ValueError:
        return None


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _prov(status: str, source: str = "", note: str = "", retrieved_at: str = "") -> dict[str, str]:
    return {k: v for k, v in {"status": status, "source": source, "note": note, "retrieved_at": retrieved_at}.items() if v}


# INN names that differ from the US name: India uses the INN, so show it first.
INN_DIFFERS = {"salbutamol", "levosalbutamol", "paracetamol", "adrenaline", "noradrenaline", "lignocaine", "frusemide",
               "glibenclamide", "rifampicin", "pethidine", "isoprenaline", "aciclovir", "valaciclovir", "ciclosporin",
               "mesalazine", "glyceryl trinitrate", "colecalciferol", "hyoscine", "chlorphenamine", "dicycloverine"}


def _title(s: str) -> str:
    return " ".join(w.capitalize() if not w.isupper() or len(w) > 3 else w for w in (s or "").lower().split())


def _form_of(product: str) -> str:
    p = product.lower()
    for form, words in _FORMS:
        if any(w in p for w in words):
            return form
    return "other"


_AREA_RULES = [
    (r"(mab|cept)$", "Biologic / Immunology"), (r"(tinib|ciclib|platin|taxel|rubicin|mustine|parib|zomib)$", "Oncology"),
    (r"^(tamoxifen|letrozole|anastrozole|capecitabine|methotrexate|imatinib|bicalutamide|temozolomide)", "Oncology"),
    (r"(cillin|floxacin|mycin|micin|cycline|cef|penem|bactam|nidazole|sulfa|trimethoprim|linezolid|vancomycin)", "Anti-infective"),
    (r"(conazole|fungin|terbinafine|nystatin)", "Antifungal"), (r"(vir)$", "Antiviral"),
    (r"(sartan|pril|olol|dipine|statin|grel|xaban|gatran|thiazide|semide|parin)$|^(aspirin|digoxin|ivabradine|ranolazine)", "Cardiovascular"),
    (r"(gliptin|gliflozin|glitazone|glutide)$|^(metformin|glimepiride|gliclazide|glibenclamide|glyburide|insulin|voglibose)", "Diabetes / Metabolic"),
    (r"(prazole|tidine)$|^(domperidone|ondansetron|itopride|mosapride|lactulose|ursodeoxycholic|sucralfate)", "Gastroenterology"),
    (r"(tirizine|tadine|lukast|terol|tropium)$|^(chlorpheniramine|phenylephrine|ambroxol|bromhexine|guaifenesin|guaiphenesin|dextromethorphan|levosalbutamol|salbutamol|albuterol|levalbuterol|terbutaline|theophylline|doxofylline)", "Respiratory / Allergy"),
    (r"(profen|fenac|coxib|oxicam)$|^(acetaminophen|paracetamol|tramadol|nimesulide|mefenamic|serratiopeptidase)", "Pain / Inflammation"),
    (r"(sone|olone|nide)$", "Corticosteroid"), (r"(pine|done|pam|lam|triptan|racetam)$|^(sertraline|escitalopram|fluoxetine|pregabalin|gabapentin|levetiracetam|valproate|lamotrigine|carbamazepine)", "CNS"),
    (r"^(vitamin|folic|cholecalciferol|cyanocobalamin|methylcobalamin|ferrous|iron|calcium|zinc|thiamine|pyridoxine|niacinamide)", "Nutrition / Supplements"),
    (r"(azole)$|^(albendazole|ivermectin|mebendazole|praziquantel)", "Anti-parasitic"),
]


def area_from_name(name: str) -> str:
    n = (name or "").lower().strip()
    for rx, area in _AREA_RULES:
        if re.search(rx, n):
            return area
    return ""


def cluster_for(area: str, forms: list[str], anda_active: int, biologic: bool) -> str:
    a = (area or "").lower()
    if "oncolog" in a or "neoplasm" in a or "cancer" in a:
        return "oncology"
    if biologic or "immun" in a or "arthritis" in a or "psoria" in a:
        return "immunology" if not biologic or "oncolog" not in a else "oncology"
    if any("inject" in f for f in forms):
        return "specialty injectable"
    if anda_active >= 20 or "nutrition" in a or "pain" in a or "respiratory" in a:
        return "commodity"
    if any(k in a for k in ("cardio", "diabet", "metabolic", "cns", "hypert", "gastro")):
        return "lifestyle / chronic"
    return ""


# --- inputs ---------------------------------------------------------------------------

def load_seed(name: str, list_key: str) -> list[dict[str, Any]]:
    p = data_dir() / f"{name}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get(list_key, [])


def nsq_stats(redis_url: Optional[str]) -> dict[str, dict[str, Any]]:
    """ingredient key -> NSQ facts, with misspellings folded into the common spelling."""
    if not redis_url:
        return {}
    import redis

    r = redis.from_url(redis_url, decode_responses=True)
    ids = list(r.smembers("nsq:records"))
    raw: dict[str, dict[str, Any]] = defaultdict(lambda: {"alerts": 0, "mfrs": set(), "forms": Counter(), "labels": Counter(),
                                                          "last": "", "products": Counter()})
    pipe = r.pipeline(transaction=False)
    for i in ids:
        pipe.hmget(f"nsq:record:{i}", "str_product_name", "str_manufactured_by", "dt_reporting_month_year")
    for product, mfr, month in pipe.execute():
        if not product:
            continue
        keys = ing.extract_ingredients(product)
        form = _form_of(product)
        ym = ""
        parts = (month or "").split("-")
        if len(parts) == 2:
            mm = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}.get(parts[0][:3].upper())
            if mm:
                ym = f"{parts[1]}-{mm:02d}"
        company = (mfr or "").split(",")[0].strip().lower()
        for k in keys:
            e = raw[k]
            e["alerts"] += 1
            if company:
                e["mfrs"].add(company)
            e["forms"][form] += 1
            for lab, rx in _LABELS.items():
                if rx.search(product):
                    e["labels"][lab] += 1
            if ym > e["last"]:
                e["last"] = ym
            if len(e["products"]) < 50:
                e["products"][product.strip()] += 1
    fold = ing.fold_variants({k: v["alerts"] for k, v in raw.items()})
    out: dict[str, dict[str, Any]] = {}
    for k, e in raw.items():
        c = fold.get(k, k)
        o = out.setdefault(c, {"alerts": 0, "mfrs": set(), "forms": Counter(), "labels": Counter(), "last": "", "products": Counter(), "variants": set()})
        o["alerts"] += e["alerts"]
        o["mfrs"] |= e["mfrs"]
        o["forms"] += e["forms"]
        o["labels"] += e["labels"]
        o["last"] = max(o["last"], e["last"])
        o["products"] += e["products"]
        if c != k:
            o["variants"].add(k)
    return out


def load_watchlist() -> tuple[list[dict[str, Any]], set[str]]:
    p = data_dir() / "generated" / "watchlist.json"
    if not p.exists():
        return [], set()
    rows = json.loads(p.read_text(encoding="utf-8"))
    add = [r for r in rows if not r.get("exclude")]
    excl: set[str] = set()
    for r in rows:
        if r.get("exclude"):
            n = r.get("name", "")
            excl |= {x for x in (r.get("key"), ing.ingredient_key(n), ing.molecule_key_for(n),
                                 ing.molecule_key_for(ing.us_name(ing.ingredient_key(n)))) if x}
    return add, excl


class Sources:
    def __init__(self) -> None:
        self.meta: dict[str, dict[str, Any]] = {}
        self.data: dict[str, dict[str, Any]] = {}
        for name in ("orange_book", "purple_book", "ema", "clinical_trials"):
            n = read_normalized(name)
            self.data[name] = (n or {}).get("data", {}) or {}
            self.meta[name] = {k: v for k, v in (n or {}).items() if k != "data"}

    def at(self, name: str) -> str:
        return (self.meta.get(name) or {}).get("retrieved_at", "")

    def ob(self, names: list[str]) -> Optional[dict[str, Any]]:
        d = self.data["orange_book"]
        for n in names:
            for k in (ing.ingredient_key(ing.us_name(ing.ingredient_key(n))), ing.ingredient_key(n)):
                if not k:
                    continue
                for cand in (k, k.split()[0]):
                    e = d.get(cand)
                    if e and not e.get("combination_only"):
                        return e
        return None

    def ema(self, names: list[str]) -> Optional[dict[str, Any]]:
        d = self.data["ema"]
        for n in names:
            k = ing.ingredient_key(n)
            for cand in (k, ing.us_name(k), k.split()[0] if k else ""):
                if cand and cand in d:
                    return d[cand]
        return None

    def pb(self, names: list[str]) -> Optional[dict[str, Any]]:
        d = self.data["purple_book"]
        for n in names:
            k = proper_key(n)
            if k in d:
                return d[k]
        return None


# --- record builders -------------------------------------------------------------------

def _patent_entries(ob: dict[str, Any]) -> tuple[list[dict], list[dict], str]:
    """(formulation_patents, secondary_patents, barrier) from Orange Book patents still in force."""
    form, sec = [], []
    barrier = "none"
    for p in ob.get("patents", []):
        exp = _d(p.get("expires"))
        if not exp or exp < TODAY:
            continue
        if p.get("substance"):
            form.append({"description": f"US {p['no']} — drug substance (compound)", "expiry_date": p["expires"], "jurisdiction": "US", "risk_level": "high"})
            barrier = "composition"
        elif p.get("product"):
            form.append({"description": f"US {p['no']} — drug product (formulation)", "expiry_date": p["expires"], "jurisdiction": "US", "risk_level": "medium"})
            if barrier == "none":
                barrier = "formulation"
        else:
            uc = ", ".join(p.get("use_codes") or [])
            sec.append({"description": f"US {p['no']} — method of use{f' ({uc})' if uc else ''}", "expiry_date": p["expires"], "jurisdiction": "US", "risk_level": "low"})
            if barrier == "none":
                barrier = "secondary"
    return form[:10], sec[:10], barrier


def us_loe(ob: Optional[dict], pb: Optional[dict]) -> tuple[Optional[date], str]:
    if ob:
        subst = _d(ob.get("last_substance_patent_expiry"))
        excl = _d(ob.get("last_exclusivity_expiry"))
        future = [d for d in (subst, excl) if d and d >= TODAY]
        if future:
            return max(future), "Latest of the unexpired drug-substance patent and FDA exclusivity in the Orange Book."
        if ob.get("anda_active"):
            fg = _d(ob.get("first_generic_approval"))
            return fg, "Off-patent: first ANDA (generic) approval in the Orange Book."
        last = _d(ob.get("last_patent_expiry")) or _d(ob.get("last_exclusivity_expiry"))
        if last and last >= TODAY:
            return last, "Only formulation / method patents remain (Orange Book)."
        if last:
            return last, "All listed patents and exclusivities have expired (Orange Book)."
        rld = (ob.get("rld") or {}).get("approval")
        if rld and _d(rld) and _d(rld) < TODAY - timedelta(days=20 * 365):
            return _d(rld), "No patents listed and approved over 20 years ago (Orange Book)."
        return None, ""
    if pb and pb.get("reference"):
        ref = pb["reference"]
        ex = _d(ref.get("exclusivity_expires"))
        if ex:
            return ex, "Reference-product exclusivity expiry in the Purple Book."
        if pb.get("biosimilars"):
            return _d(ref.get("approval")), "Biosimilars licensed (Purple Book); reference exclusivity has lapsed."
    return None, ""


def eu_loe(ema: Optional[dict], us: Optional[date]) -> tuple[Optional[date], str, str]:
    """(date, rule, status)"""
    if ema:
        if ema.get("generics") or ema.get("biosimilars"):
            return _d(ema.get("first_generic_authorised")), "First EU generic/biosimilar authorisation (EMA).", "sourced"
        auth = _d((ema.get("originator") or {}).get("authorised"))
        if auth:
            return auth.replace(year=auth.year + 10) if not (auth.month == 2 and auth.day == 29) else date(auth.year + 10, 2, 28), \
                "EMA authorisation + 10 years of data/market protection; SPCs not checked.", "derived"
    if us and us < TODAY - timedelta(days=5 * 365):
        return us, "Not centrally authorised; long off-patent in the US, so treated as off-patent in the EU (national authorisations not checked).", "derived"
    return None, "", "unknown"


def geo(code: str, name: str, loe: Optional[date], barrier: str, note: str) -> dict[str, Any]:
    if loe is None:
        status, eligible = "patented", False
    elif loe < TODAY:
        status, eligible = "off_patent", True
    elif loe <= TODAY + timedelta(days=5 * 365):
        status, eligible = "loe_pending", False
    else:
        status, eligible = "patented", False
    return {"country_code": code, "country_name": name, "market_status": status, "loe_date": _iso(loe),
            "export_eligible": eligible, "patent_barrier": barrier if status != "off_patent" else "none", "notes": note}


def build_molecule(key: str, names: list[str], origin: str, src: Sources, nsq: Optional[dict[str, Any]],
                   cur_p: Optional[dict], cur_r: Optional[dict], cur_d: Optional[dict]) -> Optional[tuple[dict, dict, dict, dict]]:
    ob, ema, pb = src.ob(names), src.ema(names), src.pb(names)
    ct = src.data["clinical_trials"].get(key)
    if not (ob or ema or pb or cur_p or origin == "manual"):
        return None
    at_ob, at_ema, at_pb, at_ct = src.at("orange_book"), src.at("ema"), src.at("purple_book"), src.at("clinical_trials")
    prov: dict[str, Any] = {}
    rprov: dict[str, Any] = {}
    dprov: dict[str, Any] = {}
    biologic = bool(pb and not ob) or (cur_p is not None and bool(re.search(r"mab\b", (cur_p.get("api_name") or "").lower())))

    display = (cur_p or {}).get("api_name") or (ema or {}).get("inn") or ((ob or {}).get("names") or [None])[0] or names[0]
    display = display if cur_p else _title(display)
    if not cur_p:
        inn = next((n for n in names if n in INN_DIFFERS), None)
        if inn:
            display = f"{_title(inn)} ({ing.us_name(inn)})"
    area = (cur_p or {}).get("therapeutic_area") or ((ema or {}).get("therapeutic_areas") or [""])[0] or area_from_name(ing.ingredient_key(display))
    if not cur_p:
        prov["therapeutic_area"] = _prov("sourced", "EMA", retrieved_at=at_ema) if (ema or {}).get("therapeutic_areas") else \
            _prov("derived", note="From the molecule's name class (e.g. -sartan ⇒ cardiovascular).") if area else _prov("unknown")

    # --- LOE ---
    loe_us, us_rule = us_loe(ob, pb)
    loe_eu, eu_rule, eu_status = eu_loe(ema, loe_us)
    form_p, sec_p, barrier = _patent_entries(ob) if ob else ([], [], "none")
    p = dict(cur_p) if cur_p else {
        "molecule_key": key, "brand_name": "", "api_name": display, "therapeutic_area": area, "originator": "",
        "estimated_loe_us": None, "estimated_loe_eu": None, "estimated_loe_in": None, "market_size_usd_bn": None,
        "formulation_patents": [], "process_patents": [], "secondary_patents": [], "geo_coverage": [], "fto_risk": "medium",
        "notes": "", "source_url": "",
    }
    p["molecule_key"] = key
    p["origin"] = origin
    p["therapeutic_area"] = p.get("therapeutic_area") or area
    if ob or pb:
        brand = ((ob or {}).get("rld") or {}).get("trade_name") or ((pb or {}).get("reference") or {}).get("proprietary_name") or ""
        orig = ((ob or {}).get("rld") or {}).get("applicant") or ((pb or {}).get("reference") or {}).get("applicant") or ""
        if not cur_p:
            p["brand_name"] = _title(brand)
            p["originator"] = _title(orig) if orig.isupper() else orig
        src_name = "FDA Orange Book" if ob else "FDA Purple Book"
        src_at = at_ob if ob else at_pb
        if loe_us or ob:
            p["estimated_loe_us"] = _iso(loe_us)
            prov["loe_us"] = _prov("sourced" if loe_us else "unknown", src_name, us_rule, src_at)
        if ob:
            p["formulation_patents"] = [x for x in (p.get("formulation_patents") or []) if x.get("jurisdiction") not in ("US",)] + form_p
            p["secondary_patents"] = [x for x in (p.get("secondary_patents") or []) if x.get("jurisdiction") not in ("US",)] + sec_p
            prov["patents"] = _prov("sourced", "FDA Orange Book", f"{len(form_p) + len(sec_p)} US patents in force.", at_ob)
    elif not cur_p:
        prov["loe_us"] = _prov("unknown", note="No Orange Book / Purple Book record.")
    if ema and (eu_status == "sourced" or not cur_p or not p.get("estimated_loe_eu")):
        p["estimated_loe_eu"] = _iso(loe_eu)
        prov["loe_eu"] = _prov(eu_status, "EMA", eu_rule, at_ema)
    elif not cur_p and loe_eu:
        p["estimated_loe_eu"] = _iso(loe_eu)
        prov["loe_eu"] = _prov(eu_status, note=eu_rule)
    elif not cur_p:
        prov["loe_eu"] = _prov("unknown", note="Not centrally authorised in the EU; national authorisations are not covered.")
    if not cur_p:
        us_d, eu_d = _d(p.get("estimated_loe_us")), _d(p.get("estimated_loe_eu"))
        if us_d and eu_d and us_d < TODAY and eu_d < TODAY:
            p["estimated_loe_in"] = _iso(min(us_d, eu_d))
            prov["loe_in"] = _prov("derived", note="Off-patent in both the US and EU; India has no patent API, so treated as off-patent.")
        else:
            prov["loe_in"] = _prov("unknown", note="India has no public patent API.")
    # FTO
    if ob:
        ex = _d(ob.get("last_exclusivity_expiry"))
        if barrier == "composition" or (ex and ex > TODAY + timedelta(days=365)):
            fto = "high"
        elif barrier in ("formulation", "secondary"):
            fto = "medium"
        else:
            fto = "low"
        p["fto_risk"] = fto
        prov["fto_risk"] = _prov("derived", "FDA Orange Book", "high = compound patent or >1 y exclusivity left; medium = formulation/method patents only; low = none in force. US only; no claims analysis.", at_ob)
    elif pb and not cur_p:
        p["fto_risk"] = "high" if (loe_us and loe_us > TODAY) else "medium"
        prov["fto_risk"] = _prov("derived", "FDA Purple Book", "Biologics: process/formulation patents usually remain after exclusivity.", at_pb)
    elif not cur_p:
        prov["fto_risk"] = _prov("unknown")
    # geo coverage: replace US/EU(/IN) rows we can speak to; keep curated rows for other countries.
    geos = {g.get("country_code"): g for g in (p.get("geo_coverage") or [])}
    if ob or pb or not cur_p:
        geos["US"] = geo("US", "United States", _d(p.get("estimated_loe_us")), barrier, us_rule or "No US record")
    if ema or not cur_p:
        geos["EU"] = geo("EU", "European Union", _d(p.get("estimated_loe_eu")), "none" if eu_status != "unknown" else "none", eu_rule or "Not centrally authorised")
    if not cur_p:
        geos["IN"] = geo("IN", "India", _d(p.get("estimated_loe_in")), "none", "Derived from US/EU status" if p.get("estimated_loe_in") else "Unknown")
    p["geo_coverage"] = list(geos.values())
    if ob or pb or ema:
        prov["geo_coverage"] = _prov("derived", note="US from the Orange/Purple Book, EU from EMA; other countries keep curated values.")
    if not cur_p:
        prov["market_size_usd_bn"] = _prov("unknown", note="No free public source for sales by molecule.")
        p["source_url"] = OB_PAGE if ob else ((ema or {}).get("originator") or {}).get("url") or ""
        bits = []
        if ob:
            bits.append(f"Orange Book: {ob.get('anda_active', 0)} active ANDAs, {ob.get('nda_active', 0)} active NDAs")
        if pb:
            bits.append(f"Purple Book: {pb.get('biosimilars', 0)} biosimilars")
        if ema:
            bits.append(f"EMA: {ema.get('authorised', 0)} centrally authorised ({ema.get('generics', 0)} generics)")
        if nsq:
            bits.append(f"CDSCO NSQ: {nsq['alerts']} alerts across {len(nsq['mfrs'])} manufacturers")
        p["notes"] = "Auto-built from public sources. " + "; ".join(bits) + "."
    aliases = sorted({n.lower() for n in names if n} | set((nsq or {}).get("variants", set())) | {ing.ingredient_key(x) for x in (ob or {}).get("names", [])})
    p["aliases"] = [a for a in aliases if a and a != key][:20]
    forms = (ob or {}).get("dosage_forms") or [f for f, _ in ((nsq or {}).get("forms") or Counter()).most_common(4)]
    p["signals"] = {
        "modality": "biologic" if biologic else "small_molecule",
        "orange_book": {k: ob.get(k) for k in ("anda_active", "nda_active", "indian_anda_holders", "first_generic_approval",
                                                "last_patent_expiry", "last_exclusivity_expiry", "dosage_forms", "te_codes")} if ob else None,
        "purple_book": {k: pb.get(k) for k in ("biosimilars", "interchangeables", "biosimilar_holders")} if pb else None,
        "ema": {k: ema.get(k) for k in ("authorised", "generics", "biosimilars", "orphan", "first_generic_authorised", "therapeutic_areas")} if ema else None,
        "trials": ct,
        "nsq": {"alerts": nsq["alerts"], "manufacturers": len(nsq["mfrs"]), "last": nsq["last"],
                "forms": dict(nsq["forms"].most_common(4)), "labels": dict(nsq["labels"])} if nsq else None,
        "sources": [s for s, v in (("orange_book", ob), ("purple_book", pb), ("ema", ema), ("clinical_trials", ct), ("cdsco", nsq)) if v],
    }
    p["provenance"] = {**(cur_p or {}).get("provenance", {}), **prov}

    # --- regulatory passport ---
    r = dict(cur_r) if cur_r else {
        "molecule_key": key, "ip_2026_monograph": "", "ph_eur_monograph": "", "usp_monograph": "", "analytical_specs": [],
        "stability_conditions": "", "bcs_class": "", "rld": "", "rld_applicant": "", "te_code": "", "te_rating": "",
        "dosage_form": "", "strength": "", "exclusivity": [], "bioequivalence_notes": "", "readiness": "placeholder",
        "source_url": "", "notes": "",
    }
    r["molecule_key"] = key
    if ob:
        rld = ob.get("rld") or {}
        te = next(iter(ob.get("te_codes") or {}), "")
        r.update({
            "rld": _title(rld.get("trade_name", "")), "rld_applicant": rld.get("applicant", ""),
            "te_code": te, "te_rating": te[:1] if te else "", "dosage_form": _title(rld.get("dosage_form", "")) or r.get("dosage_form", ""),
            "strength": rld.get("strength", "") or r.get("strength", ""),
            "exclusivity": [{"type": x["code"].split("-")[0], "expiry_date": x["expires"], "description": f"FDA exclusivity {x['code']}"}
                            for x in ob.get("exclusivity", [])],
            "source_url": r.get("source_url") or OB_PAGE,
        })
        for f in ("rld", "te_code", "exclusivity", "dosage_form"):
            rprov[f] = _prov("sourced", "FDA Orange Book", retrieved_at=at_ob)
        if r.get("readiness") == "placeholder":
            r["readiness"] = "partial"
    elif pb and pb.get("reference"):
        ref = pb["reference"]
        r.update({"rld": ref.get("proprietary_name", ""), "rld_applicant": ref.get("applicant", ""),
                  "dosage_form": _title(ref.get("dosage_form", "")) or r.get("dosage_form", ""), "te_code": r.get("te_code") or "BX"})
        rprov["rld"] = _prov("sourced", "FDA Purple Book", retrieved_at=at_pb)
        if r.get("readiness") == "placeholder":
            r["readiness"] = "partial"
    if nsq and not cur_r:
        labels = nsq["labels"]
        if labels.get("ip"):
            r["ip_2026_monograph"] = f"IP (labelled 'IP' on {labels['ip']} alerted products)"
        if labels.get("usp"):
            r["usp_monograph"] = f"USP (labelled 'USP' on {labels['usp']} alerted products)"
        if labels.get("bp"):
            r["ph_eur_monograph"] = f"BP (labelled 'BP' on {labels['bp']} alerted products; BP carries Ph. Eur. monographs)"
        if any(labels.values()):
            rprov["monographs"] = _prov("derived", "CDSCO NSQ", "A monograph exists because Indian products are labelled IP/BP/USP; edition not checked.")
    if not r.get("dosage_form") and forms:
        r["dosage_form"] = _title(forms[0])
    r["provenance"] = {**(cur_r or {}).get("provenance", {}), **rprov}

    # --- demand profile ---
    d = dict(cur_d) if cur_d else {
        "molecule_key": key, "disease_area": area, "disease_prevalence_global_millions": 0, "disease_prevalence_india_millions": 0,
        "growth_trend": "stable", "trial_count_total": 0, "trial_count_phase_3_plus": 0, "cluster": "", "buyer_activity_score": 0,
        "competitor_anda_count": 0, "market_momentum_score": 0, "notes": "", "source_url": "",
    }
    d["molecule_key"] = key
    if ct:
        d["trial_count_total"] = int(ct.get("total") or 0)
        d["trial_count_phase_3_plus"] = int(ct.get("phase3plus") or 0)
        dprov["trial_counts"] = _prov("sourced", "ClinicalTrials.gov", f"Query: {ct.get('term', '')}", ct.get("fetched_at") or at_ct)
        tot, rec = int(ct.get("total") or 0), int(ct.get("recent") or 0)
        if tot >= 10:
            share = rec / tot
            d["growth_trend"] = "growing" if share >= 0.3 else "declining" if share < 0.08 else "stable"
            d["market_momentum_score"] = round(max(0.0, min(100.0, 30 + 150 * share)), 1)
            dprov["growth_trend"] = _prov("derived", "ClinicalTrials.gov", f"{rec} of {tot} trials started in the last 3 years.")
            dprov["market_momentum_score"] = _prov("derived", "ClinicalTrials.gov", "30 + 150 × share of trials started in the last 3 years (0–100).")
    if ob:
        d["competitor_anda_count"] = int(ob.get("anda_active") or 0)
        dprov["competitor_anda_count"] = _prov("sourced", "FDA Orange Book", "Active (not discontinued) ANDAs for single-ingredient products.", at_ob)
    elif pb:
        d["competitor_anda_count"] = int(pb.get("biosimilars") or 0)
        dprov["competitor_anda_count"] = _prov("sourced", "FDA Purple Book", "Licensed biosimilars.", at_pb)
    if nsq and not cur_d:
        m = len(nsq["mfrs"])
        d["buyer_activity_score"] = round(100 * min(1.0, math.log10(1 + m) / math.log10(61)), 1)
        dprov["buyer_activity_score"] = _prov("derived", "CDSCO NSQ", f"Indian market breadth: {m} manufacturers had alerts (log scale, 60+ = 100).")
    if not cur_d:
        d["disease_area"] = area
        d["cluster"] = cluster_for(area, forms, int((ob or {}).get("anda_active") or 0), biologic)
        dprov["disease_prevalence"] = _prov("unknown", note="No automated prevalence source (IHME GBD is manual).")
        if not ct:
            dprov["trial_counts"] = _prov("unknown", note="Not queried yet — the ClinicalTrials.gov fetch walks the universe weekly.")
    d["provenance"] = {**(cur_d or {}).get("provenance", {}), **dprov}

    summary = {
        "key": key, "name": p["api_name"], "brand": p.get("brand_name", ""), "origin": origin, "area": p.get("therapeutic_area", ""),
        "sources": p["signals"]["sources"], "alerts": (nsq or {}).get("alerts", 0), "manufacturers": len((nsq or {}).get("mfrs", ())),
        "loe_us": p.get("estimated_loe_us"), "loe_eu": p.get("estimated_loe_eu"), "fto": p.get("fto_risk"),
        "anda": d.get("competitor_anda_count"), "trials": d.get("trial_count_total"), "modality": p["signals"]["modality"],
        "included": True,
    }
    return p, r, d, summary


def _json_default(o):
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, Counter):
        return dict(o)
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o))


def build(redis_url: Optional[str], min_alerts: int, max_auto: int) -> dict[str, Any]:
    src = Sources()
    curated_p = {m["molecule_key"]: m for m in load_seed("patent_seed", "molecules")}
    curated_r = {m["molecule_key"]: m for m in load_seed("regulatory_seed", "passports")}
    curated_d = {m["molecule_key"]: m for m in load_seed("demand_seed", "profiles")}
    stats = nsq_stats(redis_url)
    watch, excluded = load_watchlist()

    # NSQ ingredient -> curated key (so curated molecules pick up their NSQ facts)
    class _P:  # minimal object for ing.tracked_index
        def __init__(self, api):
            self.api_name = api
    cur_index = ing.tracked_index({k: _P(v.get("api_name", "")) for k, v in curated_p.items()})

    cands: dict[str, dict[str, Any]] = {}
    for k, m in curated_p.items():
        cands[k] = {"key": k, "names": [m.get("api_name", ""), m.get("brand_name", "")], "origin": "curated", "nsq": None}
    for key_, e in stats.items():
        ck = ing.match_tracked(key_, cur_index)
        if ck and ck in cands and cands[ck]["nsq"] is None:
            cands[ck]["nsq"] = e
    for w in watch:
        name = w.get("name", "")
        k = w.get("key") or ing.molecule_key_for(ing.us_name(ing.ingredient_key(name)))
        if k and k not in cands:
            nsq = stats.get(ing.ingredient_key(name))
            cands[k] = {"key": k, "names": [name], "origin": "manual", "nsq": nsq}
    auto = sorted(((k, e) for k, e in stats.items() if e["alerts"] >= min_alerts), key=lambda kv: -kv[1]["alerts"])
    skipped: list[dict[str, Any]] = []
    n_auto = 0
    for ingk, e in auto:
        if ing.match_tracked(ingk, cur_index):
            continue
        key = ing.molecule_key_for(ing.us_name(ingk))
        if not key or key in excluded or ingk in excluded:
            skipped.append({"key": key, "name": ingk, "alerts": e["alerts"], "reason": "excluded by an admin"})
            continue
        if key in cands:
            if cands[key]["nsq"] is None:
                cands[key]["nsq"] = e
            continue
        if n_auto >= max_auto:
            skipped.append({"key": key, "name": ingk, "alerts": e["alerts"], "reason": f"beyond the {max_auto}-molecule cap"})
            continue
        cands[key] = {"key": key, "names": [ingk, ing.us_name(ingk)] + sorted(e.get("variants", []))[:3], "origin": "auto", "nsq": e}
        n_auto += 1

    patents, regs, dems, rows = [], [], [], []
    for k, c in cands.items():
        res = build_molecule(k, [n for n in c["names"] if n], c["origin"], src, c["nsq"],
                             curated_p.get(k), curated_r.get(k), curated_d.get(k))
        if res is None:
            e = c["nsq"] or {}
            skipped.append({"key": k, "name": c["names"][0], "alerts": e.get("alerts", 0),
                            "reason": "no public source confirms it (not in the Orange Book, Purple Book or EMA)"
                            if any(src.data[s] for s in ("orange_book", "ema", "purple_book")) else "public sources not fetched yet"})
            continue
        p, r, d, row = res
        patents.append(p)
        regs.append(r)
        dems.append(d)
        rows.append(row)

    out_dir = data_dir() / "generated"
    stamp = now_iso()
    comment = f"Generated by build_universe.py at {stamp} from curated seeds + public sources; do not edit (edit the seeds or the watchlist)."
    write_json_atomic(out_dir / "patents.json", json.loads(json.dumps({"_comment": comment, "molecules": patents}, default=_json_default)))
    write_json_atomic(out_dir / "regulatory.json", json.loads(json.dumps({"_comment": comment, "passports": regs}, default=_json_default)))
    write_json_atomic(out_dir / "demand.json", json.loads(json.dumps({"_comment": comment, "profiles": dems}, default=_json_default)))
    by_origin = Counter(r["origin"] for r in rows)
    universe = {
        "built_at": stamp, "min_alerts": min_alerts, "max_auto": max_auto,
        "counts": {"molecules": len(rows), **by_origin, "skipped": len(skipped), "nsq_ingredients": len(stats)},
        "sources": {k: {kk: vv for kk, vv in v.items() if kk in ("retrieved_at", "records", "title")} for k, v in src.meta.items() if v},
        "molecules": sorted(rows, key=lambda r: (r["origin"] != "curated", -r["alerts"], r["key"])),
        "skipped": sorted(skipped, key=lambda s: -s["alerts"])[:300],
    }
    write_json_atomic(out_dir / "molecule_universe.json", json.loads(json.dumps(universe, default=_json_default)))
    ct_cands = [{"key": r["key"], "names": sorted({r["name"], *(ing.us_name(ing.ingredient_key(r["name"])),)} - {""})} for r in rows]
    write_json_atomic(out_dir / "candidates.json", ct_cands)
    return universe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL"))
    ap.add_argument("--min-alerts", type=int, default=int(os.environ.get("UNIVERSE_MIN_ALERTS", "5")))
    ap.add_argument("--max-auto", type=int, default=int(os.environ.get("UNIVERSE_MAX_AUTO", "250")))
    args = ap.parse_args()
    u = build(args.redis_url, args.min_alerts, args.max_auto)
    c = u["counts"]
    print(f"molecule universe: {c['molecules']} molecules "
          f"({c.get('curated', 0)} curated, {c.get('auto', 0)} auto, {c.get('manual', 0)} watchlist); "
          f"{c['skipped']} candidates skipped; {c['nsq_ingredients']} NSQ ingredients seen")
    for name, m in u["sources"].items():
        print(f"  source {name}: {m.get('records', 0):,} records, retrieved {m.get('retrieved_at', '—')}")
    if not u["sources"]:
        print("  no public sources fetched yet — the universe is the curated seed set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
