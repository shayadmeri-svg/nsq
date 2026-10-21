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
import patent_terms as pt  # noqa: E402
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


def _nsq_rows(redis_url: Optional[str], csv_path: Optional[str]):
    """(product, manufacturer, 'Mon-YYYY') for every NSQ alert — from Redis, or from the CDSCO CSV."""
    if csv_path:
        import csv

        with open(csv_path, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                yield row.get("Name of Product"), row.get("Manufactured By"), row.get("Reporting Month & Year")
        return
    if not redis_url:
        return
    import redis

    r = redis.from_url(redis_url, decode_responses=True)
    ids = list(r.smembers("nsq:records"))
    pipe = r.pipeline(transaction=False)
    for i in ids:
        pipe.hmget(f"nsq:record:{i}", "str_product_name", "str_manufactured_by", "dt_reporting_month_year")
    yield from pipe.execute()


def nsq_stats(redis_url: Optional[str], csv_path: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """ingredient key -> NSQ facts, with misspellings folded into the common spelling."""
    raw: dict[str, dict[str, Any]] = defaultdict(lambda: {"alerts": 0, "mfrs": set(), "forms": Counter(), "labels": Counter(),
                                                          "last": "", "products": Counter()})
    for product, mfr, month in _nsq_rows(redis_url, csv_path):
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


def load_entries() -> list[dict[str, Any]]:
    """Molecules added or edited in the app (exported from Postgres by the job runner)."""
    p = data_dir() / "generated" / "molecules.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def find_nsq(stats: dict[str, dict[str, Any]], names: list[str]) -> Optional[dict[str, Any]]:
    idx = {k: k for k in stats}
    for n in names:
        k = ing.ingredient_key(n)
        if not k:
            continue
        for cand in (k, k.split()[0], ing.us_name(k)):
            if cand in stats:
                return stats[cand]
        hit = ing.match_tracked(k, idx)
        if hit:
            return stats[hit]
    return None


class Sources:
    def __init__(self) -> None:
        self.meta: dict[str, dict[str, Any]] = {}
        self.data: dict[str, dict[str, Any]] = {}
        for name in ("orange_book", "purple_book", "ema", "clinical_trials", "chembl", "patent_families"):
            n = read_normalized(name)
            self.data[name] = (n or {}).get("data", {}) or {}
            self.meta[name] = {k: v for k, v in (n or {}).items() if k != "data"}
        n = read_normalized("fda_dissolution")
        self.diss: dict[str, list[dict[str, Any]]] = (n or {}).get("data", {}) or {}
        self.meta["fda_dissolution"] = {k: v for k, v in (n or {}).items() if k != "data"}
        # Fallback index by salt-free ingredient key ("clopidogrel bisulfate" -> "clopidogrel")
        self.folded: dict[str, dict[str, Any]] = {
            name: {fk: v for k, v in d.items() if (fk := ing.ingredient_key(k)) and fk != k}
            for name, d in self.data.items()}

    def _fold(self, name: str, names: list[str]) -> Optional[dict[str, Any]]:
        idx = self.folded.get(name) or {}
        for n in names:
            for k in (ing.ingredient_key(n), ing.ingredient_key(ing.us_name(ing.ingredient_key(n)))):
                if k and k in idx and not idx[k].get("combination_only"):
                    return idx[k]
        return None

    def dissolution(self, names: list[str]) -> list[dict[str, Any]]:
        """FDA Dissolution Methods Database rows for this single-ingredient molecule (any dosage form)."""
        d = self.diss
        for n in names:
            k = ing.ingredient_key(n)
            for cand in (k, ing.us_name(k) if k else "", k.split()[0] if k else ""):
                if cand and cand in d:
                    return [{x: r.get(x) for x in ("dosage_form", "apparatus", "rpm", "medium", "volume_ml", "times_min", "times_text", "updated")}
                            for r in d[cand]][:8]
        return []

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
        return self._fold("orange_book", names)

    def ema(self, names: list[str]) -> Optional[dict[str, Any]]:
        d = self.data["ema"]
        for n in names:
            k = ing.ingredient_key(n)
            for cand in (k, ing.us_name(k), k.split()[0] if k else ""):
                if cand and cand in d:
                    return d[cand]
        return self._fold("ema", names)

    def pb(self, names: list[str]) -> Optional[dict[str, Any]]:
        d = self.data["purple_book"]
        for n in names:
            k = proper_key(n)
            if k in d:
                return d[k]
        return self._fold("purple_book", names)


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


def apply_entry(entry: dict[str, Any], p: dict, r: dict, d: dict) -> list[str]:
    """Typed values win. The value the seed/sources gave is kept as source_value."""
    import molecule_fields as mf

    by = entry.get("by") or "an admin"
    at = entry.get("at") or ""
    typed: list[str] = []
    for key, value in (entry.get("values") or {}).items():
        f = mf.BY_KEY.get(key)
        if f is None:
            continue
        prev = mf.current_value(key, p, r, d)
        if key == "aliases":
            value = sorted({*(prev or []), *(value or [])})
        mf.apply(key, value, p, r, d)
        rec = {"patent": p, "signals": p, "regulatory": r, "demand": d}[f["record"]]
        prov_key = f.get("prov") or key
        old = (rec.get("provenance") or {}).get(prov_key) or {}
        entry_prov = {"status": "entered", "source": f"Entered by {by}", "retrieved_at": at}
        if prev not in (None, "", [], {}) and prev != value and key != "aliases":
            entry_prov["source_value"] = prev
            if old.get("status") in ("sourced", "derived") and old.get("source"):
                entry_prov["note"] = f"{old['source']} gives {prev}"
        rec.setdefault("provenance", {})[prov_key] = entry_prov
        typed.append(key)
    return typed


def build_molecule(key: str, names: list[str], origin: str, src: Sources, nsq: Optional[dict[str, Any]],
                   cur_p: Optional[dict], cur_r: Optional[dict], cur_d: Optional[dict],
                   entry: Optional[dict[str, Any]] = None) -> Optional[tuple[dict, dict, dict, dict]]:
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
    chem = src.data["chembl"].get(key) or {}
    chem = chem if chem.get("found") else {}
    fam_all = src.data["patent_families"].get(key) or None
    fa_year = chem.get("first_approval")
    # A family speaks for the molecule only when its anchor is the compound patent of a molecule young enough to still
    # have one; an old molecule's Orange Book "drug substance" patents are later forms (salts, crystals, formulations).
    young = not fa_year or TODAY.year - fa_year <= pt.TERM_YEARS + 5
    fam = fam_all if fam_all and fam_all.get("anchor_is_compound", True) and young else None
    # Therapeutic area: the WHO ATC class (ChEMBL), else EMA's therapeutic area. No name-suffix guessing.
    atc = (chem.get("atc") or [{}])[0]
    if atc.get("level2"):
        area = _title(atc["level2"])
        prov["therapeutic_area"] = _prov("sourced", "WHO ATC via ChEMBL", f"{atc['code']}: {atc.get('level1') or ''} › {atc['level2']}",
                                         src.at("chembl"))
    elif (ema or {}).get("therapeutic_areas"):
        area = (ema or {})["therapeutic_areas"][0]
        prov["therapeutic_area"] = _prov("sourced", "EMA", retrieved_at=at_ema)
    else:
        area = ""
        prov["therapeutic_area"] = _prov("unknown", note="No WHO ATC code in ChEMBL and no EMA therapeutic area.")
    if fa_year:
        prov["first_approval"] = _prov("sourced", "ChEMBL", f"First approval {fa_year} ({chem.get('chembl_id')}).", src.at("chembl"))

    # --- patent status per market: core/patent_terms.py (sourced facts + cited statutes; unknown stays unknown) ---
    form_p, sec_p, barrier = _patent_entries(ob) if ob else ([], [], "none")
    titles = {re.sub(r"\D", "", x.get("number") or ""): x for x in ((fam_all or {}).get("substance_patents") or [])}
    for x in form_p + sec_p:
        m = re.match(r"US (\d+)", x["description"])
        t = titles.get(m.group(1)) if m else None
        if t and t.get("title"):
            x["description"] += f": {t['title']}"
            x["url"] = t.get("url")
    p = {
        "molecule_key": key, "brand_name": "", "api_name": display, "therapeutic_area": area, "originator": "",
        "estimated_loe_us": None, "estimated_loe_eu": None, "estimated_loe_in": None, "market_size_usd_bn": None,
        "formulation_patents": [], "process_patents": [], "secondary_patents": [], "geo_coverage": [], "fto_risk": "medium",
        "notes": "", "source_url": "",
    }
    if cur_p:  # a curated seed contributes names only; every dated or numeric claim comes from a source below
        p.update({k: cur_p[k] for k in ("api_name", "brand_name", "originator") if cur_p.get(k)})
    p["molecule_key"] = key
    p["origin"] = origin
    p["therapeutic_area"] = area
    if ob or pb:
        brand = ((ob or {}).get("rld") or {}).get("trade_name") or ((pb or {}).get("reference") or {}).get("proprietary_name") or ""
        orig = ((ob or {}).get("rld") or {}).get("applicant") or ((pb or {}).get("reference") or {}).get("applicant") or ""
        if brand:
            p["brand_name"] = _title(brand)
        if orig:
            p["originator"] = _title(orig) if orig.isupper() else orig
    statuses: dict[str, pt.Status] = {}
    if ob or not pb:
        statuses["US"] = pt.us_status(ob, today=TODAY, first_approval_year=fa_year, family=fam)
    else:
        loe_us, us_rule = us_loe(None, pb)
        statuses["US"] = (pt._by_date("US", loe_us, TODAY, "sourced", us_rule,
                                      [{"label": "FDA Purple Book", "url": "https://purplebooksearch.fda.gov/"}], "composition")
                          if loe_us else pt.Status("US", "unknown", "unknown", None, "Purple Book record without an exclusivity date."))
    first_eu = _d(((ema or {}).get("originator") or {}).get("authorised"))
    eu_fam = pt.market_status("EU", today=TODAY, family=fam, first_approval_year=fa_year, first_eu_authorisation=first_eu)
    eu_ema = pt.eu_from_ema(ema, today=TODAY)
    if eu_fam.basis == "unknown" and eu_ema:
        statuses["EU"] = eu_ema
    else:
        statuses["EU"] = eu_fam
        if eu_ema and eu_fam.status != "off_patent":
            eu_fam.note += f" EMA has already authorised generics ({eu_ema.note}) — authorisation can precede launch while an SPC runs."
    for code in pt.MARKETS:
        if code not in statuses:
            statuses[code] = pt.market_status(code, today=TODAY, family=fam, first_approval_year=fa_year, first_eu_authorisation=first_eu)
    p["geo_coverage"] = [statuses[c].as_geo() for c in pt.MARKETS]
    for code, field in (("US", "estimated_loe_us"), ("EU", "estimated_loe_eu"), ("IN", "estimated_loe_in")):
        s = statuses[code]
        p[field] = _iso(s.date) if s.status != "unknown" and s.date else None
        prov[f"loe_{code.lower()}"] = _prov(s.basis, ", ".join(x["label"] for x in s.sources[:2]), s.note,
                                           src.at("patent_families") if fam and s.basis != "unknown" and code != "US" else (at_ob if code == "US" else ""))
        prov[f"loe_{code.lower()}"]["status_value"] = s.status
    prov["geo_coverage"] = _prov("derived", note="Per market: the publisher's own status where one exists (Orange Book, EMA, Google Patents "
                                                 "legal status), else a statutory term rule applied to sourced dates (core/patent_terms.py), else unknown.")
    if ob:
        p["formulation_patents"] = form_p
        p["secondary_patents"] = sec_p
        prov["patents"] = _prov("sourced", "FDA Orange Book", f"{len(form_p) + len(sec_p)} US patents in force.", at_ob)
    if fam:
        a = fam.get("anchor") or {}
        p["compound_patent"] = {**a, "international_filing": fam.get("international_filing"), "spcs": fam.get("spcs", [])[:8],
                                "family_countries": fam.get("countries", {})}
        prov["compound_patent"] = _prov("sourced", "Google Patents", f"{a.get('number')}: {a.get('title')}", src.at("patent_families"))
    # FTO: from the US status, which is the only market with a complete patent listing.
    us = statuses["US"]
    if us.status in ("patented", "loe_pending") and us.barrier == "composition":
        fto = "high"
    elif us.status in ("patented", "loe_pending") or us.barrier in ("formulation", "secondary"):
        fto = "medium"
    elif us.status == "unknown":
        fto = "unknown"
    else:
        fto = "low"
    p["fto_risk"] = fto
    prov["fto_risk"] = _prov("derived", "FDA Orange Book",
                             "high = compound patent / exclusivity blocks generics; medium = only product-specific patents remain; "
                             "low = open; US only, no claims analysis.", at_ob)
    prov["market_size_usd_bn"] = _prov("unknown", note="No free public source gives sales by molecule; no estimate is shown.")
    p["source_url"] = OB_PAGE if ob else ((ema or {}).get("originator") or {}).get("url") or ""
    bits = []
    if ob:
        bits.append(f"Orange Book: {ob.get('anda_active', 0)} active ANDAs, {ob.get('nda_active', 0)} active NDAs")
    if pb:
        bits.append(f"Purple Book: {pb.get('biosimilars', 0)} biosimilars")
    if ema:
        bits.append(f"EMA: {ema.get('authorised', 0)} centrally authorised ({ema.get('generics', 0)} generics)")
    if fa_year:
        bits.append(f"ChEMBL: first approved {fa_year}")
    if nsq:
        bits.append(f"CDSCO NSQ: {nsq['alerts']} alerts across {len(nsq['mfrs'])} manufacturers")
    p["notes"] = "Built from public sources. " + "; ".join(bits) + "."
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
    # Curated passports contributed hand-written monograph details, BCS classes and BE notes with no citation;
    # none of that is kept. Every field below comes from the Orange Book, Purple Book, FDA's dissolution
    # database or the monograph labels printed on CDSCO product names.
    r = {
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
    diss = src.dissolution(names)
    if diss:
        r["dissolution_methods"] = diss
        rprov["dissolution_methods"] = _prov("sourced", "FDA Dissolution Methods Database",
                                             f"{len(diss)} method(s) for this ingredient", src.at("fda_dissolution"))
    if nsq:
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
    r["provenance"] = rprov

    # --- demand profile ---
    # Curated demand profiles carried hand-typed prevalence, buyer-activity and momentum numbers with no source;
    # they are not used. Demand signals are ClinicalTrials.gov counts, Orange Book competition and CDSCO breadth.
    d = {
        "molecule_key": key, "disease_area": area, "disease_prevalence_global_millions": 0, "disease_prevalence_india_millions": 0,
        "growth_trend": "", "trial_count_total": 0, "trial_count_phase_3_plus": 0, "cluster": "", "buyer_activity_score": 0,
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
            dprov["growth_trend"] = _prov("derived", "ClinicalTrials.gov", f"{rec} of {tot} trials started in the last 3 years (research activity, not sales).")
    if ob:
        d["competitor_anda_count"] = int(ob.get("anda_active") or 0)
        dprov["competitor_anda_count"] = _prov("sourced", "FDA Orange Book", "Active (not discontinued) ANDAs for single-ingredient products.", at_ob)
    elif pb:
        d["competitor_anda_count"] = int(pb.get("biosimilars") or 0)
        dprov["competitor_anda_count"] = _prov("sourced", "FDA Purple Book", "Licensed biosimilars.", at_pb)
    if nsq:
        m = len(nsq["mfrs"])
        d["buyer_activity_score"] = round(100 * min(1.0, math.log10(1 + m) / math.log10(61)), 1)
        dprov["buyer_activity_score"] = _prov("derived", "CDSCO NSQ", f"Indian market breadth: {m} manufacturers had alerts (log scale, 60+ = 100).")
    if True:
        d["disease_area"] = area
        d["cluster"] = cluster_for(area, forms, int((ob or {}).get("anda_active") or 0), biologic)
        dprov["disease_prevalence"] = _prov("unknown", note="No automated prevalence source (IHME GBD is manual).")
        if not ct:
            dprov["trial_counts"] = _prov("unknown", note="Not queried yet — the ClinicalTrials.gov fetch walks the universe weekly.")
    d["provenance"] = dprov
    typed = apply_entry(entry, p, r, d) if entry else []

    summary = {
        "key": key, "name": p["api_name"], "brand": p.get("brand_name", ""), "origin": origin, "area": p.get("therapeutic_area", ""),
        "sources": p["signals"]["sources"], "alerts": (nsq or {}).get("alerts", 0), "manufacturers": len((nsq or {}).get("mfrs", ())),
        "loe_us": p.get("estimated_loe_us"), "loe_eu": p.get("estimated_loe_eu"), "fto": p.get("fto_risk"),
        "anda": d.get("competitor_anda_count"), "trials": d.get("trial_count_total"), "modality": p["signals"]["modality"],
        "included": True, "entered": typed, "edited_by": (entry or {}).get("by"), "edited_at": (entry or {}).get("at"),
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


def build(redis_url: Optional[str], min_alerts: int, max_auto: int, csv_path: Optional[str] = None) -> dict[str, Any]:
    src = Sources()
    curated_p = {m["molecule_key"]: m for m in load_seed("patent_seed", "molecules")}
    curated_r = {m["molecule_key"]: m for m in load_seed("regulatory_seed", "passports")}
    curated_d = {m["molecule_key"]: m for m in load_seed("demand_seed", "profiles")}
    stats = nsq_stats(redis_url, csv_path)
    watch, excluded = load_watchlist()
    entries = {e["key"]: e for e in load_entries() if e.get("key")}

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
    for k, e in entries.items():
        vals = e.get("values") or {}
        names = [e.get("name", ""), vals.get("api_name", "")] + list(vals.get("aliases") or [])
        names = [n for n in dict.fromkeys(names) if n]
        if k in cands:
            cands[k]["entry"] = e
        else:
            # Added in the app → always included ("manual"); an edit of an auto
            # molecule stays "auto" and still needs a public source to be included.
            cands[k] = {"key": k, "names": names, "origin": "manual" if e.get("added") else "auto",
                        "nsq": find_nsq(stats, names), "entry": e}
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
            # keep the NSQ spelling as an alias (e.g. amoxycillin for amoxicillin)
            for n in [ingk, *sorted(e.get("variants", []))[:3]]:
                if n not in cands[key]["names"]:
                    cands[key]["names"].append(n)
            continue
        if n_auto >= max_auto:
            skipped.append({"key": key, "name": ingk, "alerts": e["alerts"], "reason": f"beyond the {max_auto}-molecule cap"})
            continue
        cands[key] = {"key": key, "names": [ingk, ing.us_name(ingk)] + sorted(e.get("variants", []))[:3], "origin": "auto", "nsq": e}
        n_auto += 1

    patents, regs, dems, rows = [], [], [], []
    for k, c in cands.items():
        res = build_molecule(k, [n for n in c["names"] if n], c["origin"], src, c["nsq"],
                             curated_p.get(k), curated_r.get(k), curated_d.get(k), c.get("entry"))
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
    ap.add_argument("--csv", help="Read the NSQ alerts from the CDSCO CSV instead of Redis.")
    args = ap.parse_args()
    u = build(args.redis_url, args.min_alerts, args.max_auto, args.csv)
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
