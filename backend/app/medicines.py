"""Medicines: look up a finished product's composition in open databases,
fill each active ingredient's chemistry, and report what is still missing.

Open sources used (no API keys):
  openFDA NDC      api.fda.gov/drug/ndc.json      active ingredients + strengths, dosage form, route (US products)
  openFDA label    api.fda.gov/drug/label.json    inactive ingredients (excipients) from the US label
  RxNav (RxNorm)   rxnav.nlm.nih.gov/REST         normalised ingredient, marketed strengths and forms
  ChEMBL           ebi.ac.uk/chembl/api/data      structure, predicted pKa / logP, max phase, ATC, mechanism
  PubChem          pubchem.ncbi.nlm.nih.gov       structure, XLogP3, experimental melting point

Indian-only products (most NSQ fixed-dose combinations) are usually absent from
these US/EU databases; their composition is parsed from the product name
("Telmisartan 40 mg + Hydrochlorothiazide 12.5 mg Tablets") and flagged.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from typing import Any, Callable, Optional

import requests

import ingredients as ing

from . import data, insights

TIMEOUT = 12
HEADERS = {"User-Agent": "nsq-platform/2.0 (medicine lookup)", "Accept": "application/json"}
_lock = threading.Lock()
VERSION = {"n": 0}  # bumped on every save so the lab's structure cache refreshes

FORMS = [
    ("tablet", "Tablet"), ("caplet", "Tablet"), ("capsule", "Capsule"), ("syrup", "Syrup"), ("suspension", "Suspension"),
    ("injection", "Injection"), ("infusion", "Injection"), ("cream", "Cream"), ("ointment", "Ointment"), ("gel", "Gel"),
    ("drops", "Drops"), ("eye drop", "Drops"), ("powder", "Powder"), ("sachet", "Powder"), ("granules", "Granules"),
    ("inhaler", "Inhaler"), ("solution", "Solution"), ("lotion", "Lotion"), ("spray", "Spray"), ("suppositor", "Suppository"),
]
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(mcg|µg|ug|mg|g|iu|i\.u\.|%|ml)(?![a-z])(?:\s*(?:/\s*(\d+(?:\.\d+)?)?\s*(ml|g|tablet|capsule)|(w/w|w/v|v/v)))?", re.I)
_SPLIT = re.compile(r"\s*(?:\+|&|,|;|\bwith\b|\band\b)\s*", re.I)
_NOISE = re.compile(r"\b(i\.?\s?p\.?|b\.?\s?p\.?|u\.?\s?s\.?\s?p\.?|ph\.?\s?eur\.?|tablets?|capsules?|film[- ]coated|sustained|extended|"
                    r"release|prolonged|modified|oral|dispersible|chewable|uncoated|coated|er|sr|xr|cr|mr|ds|forte|syrup|"
                    r"suspension|injection|cream|ointment|gel|drops|powder|sachet|granules|solution|lotion|spray|kit|combi(?:-?pack)?)\b",
                    re.I)


# --- composition from a product name ---------------------------------------------------------

def dosage_form(text: str) -> str:
    low = text.lower()
    for k, v in FORMS:
        if k in low:
            return v
    return ""


def parse_composition(text: str) -> dict[str, Any]:
    """Split a product name into active ingredients with strengths where the name gives them."""
    text = (text or "").strip()
    form = dosage_form(text)
    parts = [p for p in _SPLIT.split(text) if p and p.strip()]
    actives: list[dict[str, Any]] = []
    trailing: Optional[str] = None
    for i, part in enumerate(parts):
        m = _STRENGTH.search(part)
        strength = None
        if m:
            unit = m.group(2).lower().replace("ug", "mcg").replace("µg", "mcg").replace("i.u.", "iu")
            per = f"{m.group(3) or ''}{m.group(4) or ''}".strip() or (m.group(5) or "").lower() or None
            strength = {"value": float(m.group(1)), "unit": unit, "per": per}
        name = _STRENGTH.sub(" ", part)
        name = _NOISE.sub(" ", name)
        name = re.sub(r"[()\[\].]", " ", name)
        name = re.sub(r"\s+", " ", name).strip(" -/")
        if not name:
            continue
        # "Amoxycillin & Potassium Clavulanate Tablets I.P. 625 mg": a strength that
        # follows the dosage-form word belongs to the whole product, not the last ingredient.
        if strength and len(parts) > 1 and i == len(parts) - 1 and form and re.search(rf"{form.lower()}\w*\W.*{re.escape(m.group(0))}", part.lower()):
            trailing, strength = m.group(0), None
        actives.append({"name": name.title(), "strength": strength, "role": "active", "source": "parsed from name"})
    keys = {a["name"].lower(): ing.molecule_key_for(a["name"]) for a in actives}
    for a in actives:
        a["molecule_key"] = keys[a["name"].lower()] or ""
    return {"name": text, "dosage_form": form, "actives": actives, "product_strength": trailing}


# --- HTTP ------------------------------------------------------------------------------------------

def _get(url: str, params: Optional[dict] = None) -> Optional[dict[str, Any]]:
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _try(sources: dict[str, Any], key: str, fn: Callable[[], Any]) -> Any:
    try:
        out = fn()
        sources[key] = {"status": "ok" if out else "not found"}
        return out
    except requests.RequestException as exc:
        sources[key] = {"status": "unreachable", "error": f"{exc.__class__.__name__}"}
    except Exception as exc:  # a bad payload from one source must not sink the lookup
        sources[key] = {"status": "error", "error": f"{exc.__class__.__name__}: {str(exc)[:120]}"}
    return None


def _fold(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


# --- openFDA ---------------------------------------------------------------------------------------

def openfda_ndc(actives: list[str]) -> Optional[dict[str, Any]]:
    """US products whose active ingredients match; the most common composition wins."""
    if not actives:
        return None
    q = " AND ".join(f'active_ingredients.name:"{a.upper()}"' for a in actives[:4])
    d = _get("https://api.fda.gov/drug/ndc.json", {"search": q, "limit": 100})
    rows = (d or {}).get("results") or []
    want = {_fold(a) for a in actives}
    exact = [r for r in rows if {_fold(x.get("name", "")) for x in r.get("active_ingredients") or []} == want] or rows
    if not exact:
        return None
    forms = Counter((r.get("dosage_form") or "").title() for r in exact)
    strengths: dict[str, set[str]] = {}
    for r in exact:
        for x in r.get("active_ingredients") or []:
            strengths.setdefault(x.get("name", "").title(), set()).add(x.get("strength", ""))
    ref = exact[0]
    return {
        "products": len(exact), "dosage_forms": [f for f, _ in forms.most_common(6)],
        "routes": [rt for rt, _ in Counter(rt.title() for r in exact for rt in (r.get("route") or [])).most_common(6)],
        "strengths": {k: sorted(v)[:12] for k, v in strengths.items()},
        "brands": sorted({r.get("brand_name", "") for r in exact if r.get("brand_name")})[:12],
        "labelers": sorted({r.get("labeler_name", "") for r in exact if r.get("labeler_name")})[:12],
        "pharm_class": sorted({c for r in exact for c in (r.get("pharm_class") or [])})[:8],
        "unii": sorted({u for r in exact for u in ((r.get("openfda") or {}).get("unii") or [])})[:8],
        "example_ndc": ref.get("product_ndc"),
    }


def parse_inactive(text: str) -> list[str]:
    text = re.sub(r"^\s*(inactive ingredients?|excipients?)\s*[:.-]?\s*", "", text or "", flags=re.I)
    text = re.sub(r"\([^)]*\)", "", text)
    items = re.split(r"\s*(?:,|;|\band\b|\.\s)\s*", text)
    out = []
    for it in items:
        it = it.strip(" .:").lower()
        if 2 < len(it) < 60 and not re.search(r"\b(tablets?|capsules?|contain|each|following|also)\b", it):
            out.append(it)
    return list(dict.fromkeys(out))[:40]


def openfda_label(actives: list[str]) -> Optional[dict[str, Any]]:
    if not actives:
        return None
    q = " AND ".join(f'openfda.generic_name:"{a}"' for a in actives[:3])
    d = _get("https://api.fda.gov/drug/label.json", {"search": q, "limit": 5})
    for r in (d or {}).get("results") or []:
        inact = " ".join(r.get("inactive_ingredient") or [])
        if inact:
            return {"excipients": parse_inactive(inact), "set_id": r.get("set_id"),
                    "url": f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={r.get('set_id')}" if r.get("set_id") else None}
    return None


# --- RxNav -----------------------------------------------------------------------------------------

def rxnav(name: str) -> Optional[dict[str, Any]]:
    d = _get("https://rxnav.nlm.nih.gov/REST/drugs.json", {"name": name})
    groups = ((d or {}).get("drugGroup") or {}).get("conceptGroup") or []
    clinical = [c["name"] for g in groups if g.get("tty") in ("SCD", "SBD") for c in g.get("conceptProperties") or []]
    if not clinical:
        return None
    rx = _get("https://rxnav.nlm.nih.gov/REST/rxcui.json", {"name": name, "search": 2})
    ids = ((rx or {}).get("idGroup") or {}).get("rxnormId") or []
    return {"rxcui": ids[0] if ids else None, "clinical_drugs": sorted(set(clinical))[:25], "count": len(set(clinical))}


# --- per-ingredient chemistry -------------------------------------------------------------------------

def chembl(name: str) -> Optional[dict[str, Any]]:
    d = _get("https://www.ebi.ac.uk/chembl/api/data/molecule/search.json", {"q": name, "limit": 5})
    mols = (d or {}).get("molecules") or []
    if not mols:
        return None
    exact = [m for m in mols if _fold(m.get("pref_name") or "") == _fold(name)]
    m = (exact or mols)[0]
    props = m.get("molecule_properties") or {}
    structs = m.get("molecule_structures") or {}
    out = {"chembl_id": m.get("molecule_chembl_id"), "pref_name": m.get("pref_name"), "max_phase": _num(m.get("max_phase")),
           "first_approval": m.get("first_approval"), "molecule_type": m.get("molecule_type"), "oral": m.get("oral"),
           "atc": m.get("atc_classifications") or [], "smiles": structs.get("canonical_smiles"),
           "pka_acid": _num(props.get("cx_most_apka")), "pka_base": _num(props.get("cx_most_bpka")),
           "logp": _num(props.get("cx_logp")), "mw": _num(props.get("full_mwt")), "psa": _num(props.get("psa")),
           "url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{m.get('molecule_chembl_id')}/"}
    try:
        mech = _get("https://www.ebi.ac.uk/chembl/api/data/mechanism.json", {"molecule_chembl_id": out["chembl_id"], "limit": 3})
        out["mechanisms"] = [x.get("mechanism_of_action") for x in (mech or {}).get("mechanisms") or [] if x.get("mechanism_of_action")]
    except requests.RequestException:
        out["mechanisms"] = []
    return out


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def pubchem(name: str) -> Optional[dict[str, Any]]:
    from sources import pubchem as pc  # redis-loader/sources (on sys.path)
    r = pc.lookup([name])
    return r if r.get("found") else None


def enrich_ingredient(a: dict[str, Any]) -> dict[str, Any]:
    src: dict[str, Any] = {}
    p = _try(src, "pubchem", lambda: pubchem(a["name"]))
    c = _try(src, "chembl", lambda: chembl(a["name"]))
    smiles = (p or {}).get("smiles") or (c or {}).get("smiles")
    out = {**a, "smiles": smiles, "structure_source": "PubChem" if (p or {}).get("smiles") else ("ChEMBL" if smiles else None),
           "cid": (p or {}).get("cid"), "chembl_id": (c or {}).get("chembl_id"),
           "mp_c": (p or {}).get("mp_c"), "xlogp": (p or {}).get("xlogp"), "logp_predicted": (c or {}).get("logp"),
           "pka_acid": (c or {}).get("pka_acid"), "pka_base": (c or {}).get("pka_base"),
           "max_phase": (c or {}).get("max_phase"), "first_approval": (c or {}).get("first_approval"),
           "atc": (c or {}).get("atc") or [], "mechanisms": (c or {}).get("mechanisms") or [],
           "molecule_type": (c or {}).get("molecule_type"), "sources": src,
           "links": {k: v for k, v in (("pubchem", (p or {}).get("url")), ("chembl", (c or {}).get("url"))) if v}}
    out["molecule_key"] = a.get("molecule_key") or ing.molecule_key_for(a["name"]) or ""
    if not out["smiles"] and out["molecule_key"]:
        # Offline or unknown to both databases: use a structure the platform already has
        try:
            from . import lab
            rec = lab.structures().get(out["molecule_key"])
        except Exception:
            rec = None
        if rec and rec.get("smiles"):
            out.update(smiles=rec["smiles"], structure_source=f"platform ({rec['source']})",
                       xlogp=out["xlogp"] if out["xlogp"] is not None else rec.get("xlogp"),
                       mp_c=out["mp_c"] if out["mp_c"] is not None else rec.get("mp_c"))
    return out


_TOPICAL = {"Cream", "Ointment", "Gel", "Lotion"}


def _route(form: str, us_routes: list[str]) -> str:
    """Route that fits the dosage form; US routes are only a hint (they span every product form)."""
    f = (form or "").title()
    if f in _TOPICAL:
        return "Topical"
    if f in ("Tablet", "Capsule", "Syrup", "Suspension", "Granules", "Powder"):
        return "Oral"
    if f == "Injection":
        return next((r for r in us_routes if r in ("Intravenous", "Intramuscular", "Subcutaneous")), "Parenteral")
    return us_routes[0] if us_routes else ""


def lookup(text: str) -> dict[str, Any]:
    """Everything the open databases know about a product, plus the gaps."""
    comp = parse_composition(text)
    names = [a["name"] for a in comp["actives"]]
    sources: dict[str, Any] = {}
    ndc = _try(sources, "openfda_ndc", lambda: openfda_ndc(names))
    label = _try(sources, "openfda_label", lambda: openfda_label(names))
    rx = _try(sources, "rxnav", lambda: rxnav(" / ".join(names) if len(names) > 1 else (names[0] if names else text)))
    actives = []
    for a in comp["actives"]:
        a = dict(a)
        if not a.get("strength") and ndc:
            us = next((v for k, v in ndc["strengths"].items() if _fold(k) == _fold(a["name"])), None)
            if us:
                a["us_strengths"] = us
        actives.append(enrich_ingredient(a))
    med = {"name": text, "brand": "", "dosage_form": comp["dosage_form"] or ((ndc or {}).get("dosage_forms") or [""])[0],
           "route": _route(comp["dosage_form"] or ((ndc or {}).get("dosage_forms") or [""])[0], (ndc or {}).get("routes") or []),
           "ingredients": actives, "excipients": (label or {}).get("excipients") or [],
           "identifiers": {"rxcui": (rx or {}).get("rxcui"), "unii": (ndc or {}).get("unii") or [], "ndc_example": (ndc or {}).get("example_ndc")},
           "sources": {**sources, "product_strength": comp["product_strength"]},
           "us_market": ndc, "rxnorm": rx, "label": label,
           "offline": [k for k, v in sources.items() if isinstance(v, dict) and v.get("status") == "unreachable"]}
    med["gaps"] = gaps(med)
    med["nsq"] = nsq_for([a["molecule_key"] or a["name"].lower() for a in actives])
    return med


# --- NSQ record for a composition ---------------------------------------------------------------------

_nsq_cache: dict[str, Any] = {}


def nsq_for(keys: list[str]) -> dict[str, Any]:
    """NSQ alerts for products with exactly this set of active ingredients."""
    df = data.attributable(data.frame())
    ck = (id(df), len(df))
    if _nsq_cache.get("key") != ck:
        idx: dict[frozenset, list[int]] = {}
        for i, name in enumerate(df["Name of Product"].astype(str)):
            idx.setdefault(frozenset(insights.product_ingredients(name)), []).append(i)
        _nsq_cache.update(key=ck, idx=idx, df=df)
    want = frozenset(k for k in keys if k)
    rows = _nsq_cache["idx"].get(want, [])
    if not rows:
        return {"alerts": 0}
    sub = _nsq_cache["df"].iloc[rows]
    return {"alerts": len(sub), "dissolution_pct": round(100 * float(sub["Is_Dissolution"].astype(bool).mean()), 1),
            "categories": [{"name": k, "count": int(v)} for k, v in sub["Failure_Category_Primary"].fillna("Uncategorized").value_counts().head(5).items()],
            "manufacturers": int(sub["Mfg_Company_Canonical"].nunique()),
            "last": sub["Parsed_Date"].max().strftime("%Y-%m") if sub["Parsed_Date"].notna().any() else None}


# --- gaps ----------------------------------------------------------------------------------------------

def gaps(med: dict[str, Any]) -> list[dict[str, Any]]:
    g: list[dict[str, Any]] = []

    def add(area: str, item: str, ok: bool, detail: str, fix: str = "", level: str = "missing"):
        g.append({"area": area, "item": item, "status": "ok" if ok else level, "detail": detail, "fix": "" if ok else fix})

    src = med.get("sources") or {}
    acts = [a for a in med.get("ingredients") or [] if a.get("role", "active") == "active"]
    add("Composition", "Active ingredients", bool(acts), f"{len(acts)} active ingredient(s)", "Enter the actives from the label.")
    for a in acts:
        s = a.get("strength")
        add("Composition", f"{a['name']}: strength", bool(s),
            f"{s['value']:g} {s['unit']}" if s else ("US strengths: " + ", ".join(a.get("us_strengths", [])[:4]) if a.get("us_strengths") else "not in the name"),
            "Take it from the label; for Indian FDCs no open database lists it.")
    add("Composition", "Dosage form", bool(med.get("dosage_form")), med.get("dosage_form") or "unknown", "Pick the form.")
    add("Composition", "Excipients (inactive ingredients)", bool(med.get("excipients")),
        f"{len(med.get('excipients') or [])} listed" + (" (US label)" if (src.get("openfda_label") or {}).get("status") == "ok" else ""),
        "Only US labels publish these openly; Indian labels must be entered by hand.")
    add("Composition", "Found in US product data (openFDA NDC)", (src.get("openfda_ndc") or {}).get("status") == "ok",
        _src_text(src.get("openfda_ndc")), "Normal for India-only products and fixed-dose combinations.", level="info")
    for a in acts:
        n = a["name"]
        add("Chemistry", f"{n}: structure", bool(a.get("smiles")), a.get("structure_source") or "no structure found",
            "Biologics and some salts have no small-molecule structure; paste a SMILES if you have one.")
        add("Chemistry", f"{n}: melting point (measured)", a.get("mp_c") is not None, f"{a['mp_c']} °C (PubChem)" if a.get("mp_c") is not None else "none published",
            "Needed for the solubility equation and crystallisation; the lab falls back to structure-only estimates.", level="estimate")
        add("Chemistry", f"{n}: log P", a.get("xlogp") is not None or a.get("logp_predicted") is not None,
            f"XLogP3 {a['xlogp']}" if a.get("xlogp") is not None else (f"ChemAxon {a['logp_predicted']} (predicted)" if a.get("logp_predicted") is not None else "none"),
            "RDKit estimate used instead.", level="estimate")
        add("Chemistry", f"{n}: pKa", a.get("pka_acid") is not None or a.get("pka_base") is not None,
            ", ".join(x for x in (f"acid {a['pka_acid']}" if a.get("pka_acid") is not None else "", f"base {a['pka_base']}" if a.get("pka_base") is not None else "") if x) + " (ChEMBL, predicted)"
            if (a.get("pka_acid") is not None or a.get("pka_base") is not None) else "none",
            "Needed for pH-dependent solubility and dissolution.", level="estimate")
        add("Chemistry", f"{n}: measured aqueous solubility", False, "no open database gives this reliably",
            "Enter a lab or literature value; until then solubility is computed (GSE / ESOL).", level="estimate")
        add("Regulatory", f"{n}: approval status", a.get("max_phase") is not None,
            f"max phase {a['max_phase']}" + (f", first approved {a['first_approval']}" if a.get("first_approval") else "") if a.get("max_phase") is not None else "unknown",
            "Not in ChEMBL.", level="info")
    add("Regulatory", "India approval (CDSCO)", False, "no open API",
        "Check CDSCO's approved-drug lists by hand; state licences are not published centrally.", level="info")
    add("Regulatory", "Pharmacopoeial monograph (IP / USP / Ph. Eur.)", False, "monographs are licensed, not open",
        "Enter the dissolution spec (Q and time) and assay limits from the monograph you hold.", level="info")
    add("Manufacturing", "API particle size, polymorph, salt form", False, "never public",
        "Enter supplier CoA values; the dissolution and crystallisation models use defaults until then.", level="estimate")
    return g


def _src_text(s: Optional[dict[str, Any]]) -> str:
    if not s:
        return "not queried"
    return {"ok": "found", "not found": "no match", "unreachable": f"unreachable ({s.get('error', '')})"}.get(s.get("status"), s.get("status", ""))


def gap_score(g: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter(x["status"] for x in g)
    return {"ok": c.get("ok", 0), "missing": c.get("missing", 0), "estimate": c.get("estimate", 0), "info": c.get("info", 0), "total": len(g)}


def to_dict(m) -> dict[str, Any]:
    d = {"id": m.id, "name": m.name, "brand": m.brand, "dosage_form": m.dosage_form, "route": m.route,
         "ingredients": m.ingredients or [], "excipients": m.excipients or [], "identifiers": m.identifiers or {},
         "sources": m.sources or {}, "notes": m.notes, "created_by": m.created_by,
         "updated_at": m.updated_at.isoformat() if m.updated_at else None}
    d["gaps"] = gaps(d)
    d["gap_score"] = gap_score(d["gaps"])
    return d
