"""Every field a molecule profile has, in one place.

Used by the API (validation + the form schema the web app renders) and by
build_universe.py (applying values typed in the app on top of the curated
seed and the public sources). A typed value always wins; the value the
sources would have given is kept in provenance as `source_value` so
reviewers can see when they disagree.

record: which stored record the field lives in (patent | regulatory | demand | signals)
prov:   the provenance key the dashboards' source icons read
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

GROUPS = [
    {"id": "identity", "title": "Identity", "hint": "What the molecule is and what it is called."},
    {"id": "patent", "title": "Patents & exclusivity", "hint": "When generics can launch in each market, and what blocks them."},
    {"id": "regulatory", "title": "Regulatory", "hint": "Reference product, equivalence and pharmacopoeia standards."},
    {"id": "demand", "title": "Demand", "hint": "How much the molecule is needed and how crowded the market is."},
]

MODALITIES = ["small_molecule", "biologic", "peptide"]
FTO = ["low", "medium", "high"]
TRENDS = ["growing", "stable", "declining"]
CLUSTERS = ["oncology", "specialty injectable", "immunology", "lifestyle / chronic", "commodity"]
JURISDICTIONS = ["US", "EU", "IN", "global"]
PATENT_KINDS = ["formulation", "process", "secondary"]

FIELDS: list[dict[str, Any]] = [
    # identity
    {"key": "api_name", "group": "identity", "record": "patent", "label": "Molecule (API) name", "type": "text", "required": True,
     "help": "INN as used in India, e.g. Paracetamol."},
    {"key": "brand_name", "group": "identity", "record": "patent", "label": "Originator brand", "type": "text"},
    {"key": "originator", "group": "identity", "record": "patent", "label": "Originator company", "type": "text"},
    {"key": "therapeutic_area", "group": "identity", "record": "patent", "label": "Therapeutic area", "type": "text", "prov": "therapeutic_area"},
    {"key": "modality", "group": "identity", "record": "signals", "label": "Modality", "type": "select", "options": MODALITIES,
     "help": "Drives the manufacturing requirements (biologics need cell culture, aseptic fill…)."},
    {"key": "aliases", "group": "identity", "record": "patent", "label": "Other names / spellings", "type": "list",
     "help": "One per line. Used to match CDSCO product names (e.g. acetaminophen, paracetmol)."},
    # patent
    {"key": "estimated_loe_us", "group": "patent", "record": "patent", "label": "US loss of exclusivity", "type": "date", "prov": "loe_us",
     "help": "YYYY-MM or YYYY-MM-DD. Leave empty if already off-patent."},
    {"key": "estimated_loe_eu", "group": "patent", "record": "patent", "label": "EU loss of exclusivity", "type": "date", "prov": "loe_eu"},
    {"key": "estimated_loe_in", "group": "patent", "record": "patent", "label": "India loss of exclusivity", "type": "date", "prov": "loe_in"},
    {"key": "fto_risk", "group": "patent", "record": "patent", "label": "Freedom-to-operate risk", "type": "select", "options": FTO, "prov": "fto_risk"},
    {"key": "market_size_usd_bn", "group": "patent", "record": "patent", "label": "Global market (USD bn)", "type": "number", "min": 0, "max": 500,
     "prov": "market_size_usd_bn"},
    {"key": "patents", "group": "patent", "record": "patent", "label": "Patents", "type": "patents", "prov": "patents",
     "help": "Kind, description, jurisdiction, expiry, risk."},
    {"key": "notes", "group": "patent", "record": "patent", "label": "Notes", "type": "textarea"},
    # regulatory
    {"key": "rld", "group": "regulatory", "record": "regulatory", "label": "Reference listed drug", "type": "text", "prov": "rld"},
    {"key": "rld_applicant", "group": "regulatory", "record": "regulatory", "label": "RLD holder", "type": "text"},
    {"key": "te_code", "group": "regulatory", "record": "regulatory", "label": "Therapeutic-equivalence code", "type": "text", "prov": "te_code",
     "help": "e.g. AB, BX. The first letter becomes the TE rating."},
    {"key": "dosage_form", "group": "regulatory", "record": "regulatory", "label": "Dosage form", "type": "text", "prov": "dosage_form",
     "help": "e.g. Tablet, Capsule, Injection, Delayed-release tablet — decides the manufacturing route."},
    {"key": "strength", "group": "regulatory", "record": "regulatory", "label": "Strength", "type": "text"},
    {"key": "ip_2026_monograph", "group": "regulatory", "record": "regulatory", "label": "IP monograph", "type": "text", "prov": "monographs"},
    {"key": "ph_eur_monograph", "group": "regulatory", "record": "regulatory", "label": "Ph. Eur. monograph", "type": "text", "prov": "monographs"},
    {"key": "usp_monograph", "group": "regulatory", "record": "regulatory", "label": "USP monograph", "type": "text", "prov": "monographs"},
    {"key": "bcs_class", "group": "regulatory", "record": "regulatory", "label": "BCS class", "type": "select", "options": ["", "BCS I", "BCS II", "BCS III", "BCS IV", "N/A (biologic)"]},
    {"key": "exclusivity", "group": "regulatory", "record": "regulatory", "label": "Regulatory exclusivities", "type": "exclusivity", "prov": "exclusivity"},
    {"key": "analytical_specs", "group": "regulatory", "record": "regulatory", "label": "Key analytical tests", "type": "list"},
    {"key": "stability_conditions", "group": "regulatory", "record": "regulatory", "label": "Stability / process conditions", "type": "textarea"},
    {"key": "bioequivalence_notes", "group": "regulatory", "record": "regulatory", "label": "Bioequivalence notes", "type": "textarea"},
    # demand
    {"key": "disease_area", "group": "demand", "record": "demand", "label": "Disease area", "type": "text"},
    {"key": "disease_prevalence_india_millions", "group": "demand", "record": "demand", "label": "India prevalence (millions)", "type": "number", "min": 0,
     "prov": "disease_prevalence"},
    {"key": "disease_prevalence_global_millions", "group": "demand", "record": "demand", "label": "Global prevalence (millions)", "type": "number", "min": 0,
     "prov": "disease_prevalence"},
    {"key": "growth_trend", "group": "demand", "record": "demand", "label": "Demand trend", "type": "select", "options": TRENDS, "prov": "growth_trend"},
    {"key": "cluster", "group": "demand", "record": "demand", "label": "Market cluster", "type": "select", "options": CLUSTERS},
    {"key": "trial_count_total", "group": "demand", "record": "demand", "label": "Clinical trials (total)", "type": "int", "min": 0, "prov": "trial_counts"},
    {"key": "trial_count_phase_3_plus", "group": "demand", "record": "demand", "label": "Phase 3+ trials", "type": "int", "min": 0, "prov": "trial_counts"},
    {"key": "competitor_anda_count", "group": "demand", "record": "demand", "label": "Generic competitors (ANDAs)", "type": "int", "min": 0,
     "prov": "competitor_anda_count"},
    {"key": "buyer_activity_score", "group": "demand", "record": "demand", "label": "Buyer activity (0–100)", "type": "number", "min": 0, "max": 100,
     "prov": "buyer_activity_score"},
    {"key": "market_momentum_score", "group": "demand", "record": "demand", "label": "Market momentum (0–100)", "type": "number", "min": 0, "max": 100,
     "prov": "market_momentum_score"},
]
BY_KEY = {f["key"]: f for f in FIELDS}


class FieldError(ValueError):
    pass


def _date(v: Any) -> str | None:
    s = str(v or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}", s):
        s += "-01"
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError as exc:
        raise FieldError("use YYYY-MM or YYYY-MM-DD") from exc


def clean(key: str, value: Any) -> Any:
    """Validate and normalise one typed value (None = cleared)."""
    f = BY_KEY.get(key)
    if f is None:
        raise FieldError("unknown field")
    t = f["type"]
    if value is None:
        return None
    if t in ("text", "textarea"):
        v = str(value).strip()
        if f.get("required") and not v:
            raise FieldError("required")
        return v[:4000]
    if t == "select":
        v = str(value).strip()
        if v not in f["options"]:
            raise FieldError(f"one of {', '.join(o for o in f['options'] if o)}")
        return v
    if t == "date":
        return _date(value)
    if t in ("number", "int"):
        if value == "":
            return None
        try:
            v = int(value) if t == "int" else float(value)
        except (TypeError, ValueError) as exc:
            raise FieldError("must be a number") from exc
        if "min" in f and v < f["min"] or "max" in f and v > f["max"]:
            raise FieldError(f"between {f.get('min', '−∞')} and {f.get('max', '∞')}")
        return v
    if t == "list":
        items = value if isinstance(value, list) else re.split(r"[\n,;]+", str(value))
        return [str(x).strip() for x in items if str(x).strip()][:40]
    if t == "patents":
        out = []
        for p in value or []:
            if not (p.get("description") or "").strip():
                continue
            kind = p.get("kind") or "formulation"
            if kind not in PATENT_KINDS:
                raise FieldError(f"patent kind must be one of {', '.join(PATENT_KINDS)}")
            j = p.get("jurisdiction") or "US"
            if j not in JURISDICTIONS:
                raise FieldError(f"jurisdiction must be one of {', '.join(JURISDICTIONS)}")
            risk = p.get("risk_level") or "medium"
            if risk not in FTO:
                raise FieldError("risk must be low, medium or high")
            out.append({"kind": kind, "description": str(p["description"]).strip()[:300], "jurisdiction": j,
                        "expiry_date": _date(p.get("expiry_date")), "risk_level": risk})
        return out[:40]
    if t == "exclusivity":
        out = []
        for x in value or []:
            if not (x.get("type") or "").strip():
                continue
            out.append({"type": str(x["type"]).strip()[:20], "expiry_date": _date(x.get("expiry_date")),
                        "description": str(x.get("description") or "").strip()[:300]})
        return out[:20]
    raise FieldError("unsupported")


def current_value(key: str, patent: dict, regulatory: dict, demand: dict) -> Any:
    """Read a field's value from the stored records (the form's starting value)."""
    f = BY_KEY[key]
    if key == "patents":
        out = []
        for kind, lst in (("formulation", "formulation_patents"), ("process", "process_patents"), ("secondary", "secondary_patents")):
            for p in patent.get(lst) or []:
                out.append({"kind": kind, **{k: p.get(k) for k in ("description", "jurisdiction", "expiry_date", "risk_level")}})
        return out
    if key == "modality":
        return (patent.get("signals") or {}).get("modality") or "small_molecule"
    rec = {"patent": patent, "regulatory": regulatory, "demand": demand}.get(f["record"], {})
    return rec.get(key)


def apply(key: str, value: Any, patent: dict, regulatory: dict, demand: dict) -> None:
    """Write a typed value into the records (in place)."""
    f = BY_KEY[key]
    if key == "patents":
        for lst in ("formulation_patents", "process_patents", "secondary_patents"):
            patent[lst] = []
        for p in value or []:
            patent[f"{p['kind']}_patents"].append({k: p[k] for k in ("description", "expiry_date", "jurisdiction", "risk_level")})
        return
    if key == "modality":
        patent.setdefault("signals", {})["modality"] = value
        return
    if key == "te_code":
        regulatory["te_code"] = value or ""
        regulatory["te_rating"] = (value or "")[:1]
        return
    rec = {"patent": patent, "regulatory": regulatory, "demand": demand}[f["record"]]
    rec[key] = value


def schema() -> dict[str, Any]:
    return {"groups": GROUPS, "fields": FIELDS}
