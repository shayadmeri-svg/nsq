"""The lab: structure-based molecule profiles, drug-product models and
crystallisation, tied back to the NSQ alerts for each molecule.

Structures come from the PubChem source (data/sources/pubchem.json) and fall
back to data/structures_seed.json. Crystallisation runs in the PharmaPy
sidecar when SIM_URL is set and reachable, else in the built-in engine.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Any, Optional

import requests

from chem import crystallization, molecule, product, thermo_props

from . import data, insights
from .config import settings

SIM_URL = os.environ.get("SIM_URL", "").rstrip("/")
_cache: dict[str, Any] = {}
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.I)
# BCS and dissolution need the oral solid dose: only tablets / capsules, and never a name that
# says it is an injection, liquid or topical (their "mg" is per mL, per vial or per gram).
_ORAL_SOLID_FORMS = {"Tablet", "Capsule"}
_NOT_ORAL_SOLID = re.compile(r"\b(inj\w*|infusion|vial|ampoule|syrup|suspension|solution|elixir|drops?|emulsion|cream|"
                             r"ointment|gel|lotion|spray|inhal\w*|nebul\w*|sachet|powder|granules|dry syrup)\b|/\s*\d*\s*ml\b|\bper\s*ml\b", re.I)


# --- structures --------------------------------------------------------------------------------------

def _mtime(p) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def structures() -> dict[str, dict[str, Any]]:
    """molecule key -> structure record (PubChem wins over the seed)."""
    seed_p = settings.data_dir / "structures_seed.json"
    pc_p = settings.data_dir / "sources" / "pubchem.json"
    from . import medicines as med_mod
    live_p = settings.data_dir / "generated" / "structures_live.json"
    uni_p = settings.data_dir / "generated" / "molecule_universe.json"
    key = (_mtime(seed_p), _mtime(pc_p), _mtime(live_p), _mtime(uni_p), med_mod.VERSION["n"])
    hit = _cache.get("structures")
    if hit and hit[0] == key:
        return hit[1]
    out: dict[str, dict[str, Any]] = {}
    if seed_p.exists():
        for k, v in json.loads(seed_p.read_text(encoding="utf-8")).get("molecules", {}).items():
            out[k] = {"key": k, "name": v["name"], "smiles": v["smiles"], "aliases": v.get("aliases", []), "source": "seed",
                      "xlogp": None, "mp_c": None, "cid": None, "url": None}
    if pc_p.exists():
        for k, v in (json.loads(pc_p.read_text(encoding="utf-8")).get("data") or {}).items():
            if not v.get("found") or not v.get("smiles"):
                if k not in out:
                    out[k] = {"key": k, "name": v.get("query") or k, "smiles": None, "aliases": [], "source": "pubchem: no structure"}
                continue
            prev = out.get(k, {})
            out[k] = {"key": k, "name": (v.get("query") or k).title() if not prev else prev["name"], "smiles": v["smiles"],
                      "aliases": prev.get("aliases", []), "source": "PubChem", "cid": v.get("cid"), "url": v.get("url"),
                      "xlogp": v.get("xlogp"), "mp_c": v.get("mp_c"), "mp_values": v.get("mp_values"), "iupac": v.get("iupac"),
                      "exp": v.get("exp") or {}}
    # Structures fetched on demand from the Lab (PubChem, else ChEMBL)
    if live_p.exists():
        for k, v in json.loads(live_p.read_text(encoding="utf-8")).items():
            if v.get("smiles") and not (out.get(k) or {}).get("smiles"):
                out[k] = {**v, "key": k, "aliases": (out.get(k) or {}).get("aliases", [])}
    # Every molecule in the universe is listed, with or without a structure yet
    if uni_p.exists():
        try:
            u = json.loads(uni_p.read_text(encoding="utf-8"))
            for m in (u.get("molecules") if isinstance(u, dict) else u) or []:
                if m.get("key") and m["key"] not in out and m.get("modality", "small_molecule") == "small_molecule":
                    out[m["key"]] = {"key": m["key"], "name": m.get("name") or m["key"], "smiles": None, "aliases": [], "source": "universe (no structure yet)"}
        except (OSError, ValueError):
            pass
    # Ingredients of medicines added in the Playground (PubChem / ChEMBL at save time)
    try:
        from sqlalchemy import select
        from .db import SessionLocal
        from .models import Medicine
        with SessionLocal() as db:
            for m in db.scalars(select(Medicine)):
                for a in m.ingredients or []:
                    k = a.get("molecule_key") or ""
                    if not k or not a.get("smiles"):
                        continue
                    prev = out.get(k)
                    if prev and prev.get("smiles") and prev["source"] == "PubChem":
                        prev.setdefault("pka_acid", a.get("pka_acid"))
                        prev.setdefault("pka_base", a.get("pka_base"))
                        continue
                    out[k] = {"key": k, "name": a["name"], "smiles": a["smiles"], "aliases": (prev or {}).get("aliases", []),
                              "source": f"medicine ({a.get('structure_source') or 'typed'})", "cid": a.get("cid"),
                              "url": (a.get("links") or {}).get("pubchem") or (a.get("links") or {}).get("chembl"),
                              "xlogp": a.get("xlogp"), "mp_c": a.get("mp_c"), "pka_acid": a.get("pka_acid"), "pka_base": a.get("pka_base")}
    except Exception:  # database unavailable: structures from files still work
        pass
    _fold_onto_universe(out, uni_p)
    _cache["structures"] = (key, out)
    return out


def _fold_onto_universe(out: dict[str, dict[str, Any]], uni_p) -> None:
    """Universe keys are often salt forms (amlodipine_besylate) while structures are keyed by
    the parent molecule (amlodipine). Give the universe key the parent's structure and hide the
    duplicate parent entry from the picker (it still resolves for links and medicines)."""
    import ingredients as ing
    if not uni_p.exists():
        return
    try:
        u = json.loads(uni_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for m in (u.get("molecules") if isinstance(u, dict) else u) or []:
        k = m.get("key")
        if not k:
            continue
        parent = ing.molecule_key_for(m.get("name") or k) or ing.molecule_key_for(k)
        if not parent or parent == k or parent not in out:
            continue
        src = out[parent]
        if src.get("smiles") and not (out.get(k) or {}).get("smiles"):
            out[k] = {**src, "key": k, "name": m.get("name") or src["name"],
                      "aliases": sorted({*(src.get("aliases") or []), parent}), "folded_from": parent}
        if (out.get(k) or {}).get("smiles"):
            out[parent] = {**src, "hidden": True, "canonical": k}


# --- NSQ per ingredient ---------------------------------------------------------------------------------

def nsq_by_ingredient() -> dict[str, dict[str, Any]]:
    base = data.frame()
    key = (id(base), len(base))
    hit = _cache.get("nsq")
    if hit and hit[0] == key:
        return hit[1]
    df = data.attributable(base)
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"alerts": 0, "dissolution": 0, "categories": Counter(), "strengths": Counter(),
                                                            "other_strengths": Counter(), "forms": Counter()})
    names = df["Name of Product"].astype(str).tolist()
    diss = df["Is_Dissolution"].astype(bool).tolist() if "Is_Dissolution" in df else [False] * len(df)
    cats = df["Failure_Category_Primary"].fillna("Uncategorized").astype(str).tolist()
    forms = df["Form type"].fillna("Other").astype(str).tolist()
    for name, dis, cat, form in zip(names, diss, cats, forms):
        ings = insights.product_ingredients(name)
        for i in set(ings):
            s = stats[i]
            s["alerts"] += 1
            s["dissolution"] += int(dis)
            s["categories"][cat] += 1
            s["forms"][form] += 1
            if len(ings) == 1:
                oral_solid = form in _ORAL_SOLID_FORMS and not _NOT_ORAL_SOLID.search(name)
                for m in _STRENGTH.findall(name):
                    v = float(m)
                    if 0.05 <= v <= 2000:
                        s["strengths" if oral_solid else "other_strengths"][v] += 1
    out = {}
    for k, s in stats.items():
        strengths = sorted(s["strengths"])
        out[k] = {"alerts": s["alerts"], "dissolution": s["dissolution"],
                  "dissolution_pct": round(100 * s["dissolution"] / s["alerts"], 1) if s["alerts"] else 0.0,
                  "categories": [{"name": c, "count": n} for c, n in s["categories"].most_common(6)],
                  "forms": [{"name": c, "count": n} for c, n in s["forms"].most_common(5)],
                  "strengths_mg": strengths[-6:], "max_strength_mg": strengths[-1] if strengths else None,
                  "other_strengths": bool(s["other_strengths"])}
    _cache["nsq"] = (key, out)
    return out


def _nsq_for(rec: dict[str, Any]) -> dict[str, Any]:
    nsq = nsq_by_ingredient()
    keys = [rec["key"], *rec.get("aliases", [])]
    rows = [nsq[k] for k in keys if k in nsq]
    if not rows:
        return {"alerts": 0, "dissolution": 0, "dissolution_pct": 0.0, "categories": [], "forms": [], "strengths_mg": [], "max_strength_mg": None,
                "other_strengths": False}
    best = max(rows, key=lambda r: r["alerts"])
    if len(rows) > 1:
        alerts = sum(r["alerts"] for r in rows)
        dis = sum(r["dissolution"] for r in rows)
        best = {**best, "alerts": alerts, "dissolution": dis, "dissolution_pct": round(100 * dis / alerts, 1),
                "max_strength_mg": max((r["max_strength_mg"] or 0) for r in rows) or None,
                "other_strengths": any(r.get("other_strengths") for r in rows)}
    return best


# --- molecule profile -------------------------------------------------------------------------------------
#
# Every value carries a `kind`: "source" (a cited record), "estimate" (a named published method, with its
# uncertainty) or "assumption" (a default the user can replace). The UI shows the kind next to the value.

def _src(value: Any, kind: str, label: str, url: Optional[str] = None, text: Optional[str] = None, **extra: Any) -> dict[str, Any]:
    return {"value": value, "kind": kind, "label": label, "url": url, "text": text, **extra}


def _cite(e: dict[str, Any]) -> str:
    return f"PubChem › {e.get('source') or 'cited source'}"


def _pka_choice(rec: dict[str, Any], groups: list[dict[str, Any]]) -> dict[str, Any]:
    """pKa for the dissolution model: PubChem experimental (cited) first, then ChEMBL's predicted
    value from a Playground medicine. Returns the single acid or base pKa the Henderson-Hasselbalch
    model can use, or why none can be used."""
    gi_kinds = {g["kind"] for g in groups if g.get("gi")}
    exp = [p for p in (rec.get("exp") or {}).get("pka") or [] if p.get("value") is not None]
    if exp:
        acids = [p for p in exp if p.get("kind") == "acid"]
        bases = [p for p in exp if p.get("kind") == "base"]
        unk = [p for p in exp if not p.get("kind")]
        if unk and len(gi_kinds) == 1:  # the text didn't say; the structure has only one kind of group
            (acids if "acid" in gi_kinds else bases).extend(unk)
            unk = []
        all_vals = "; ".join(p.get("text") or f"{p['value']}" for p in exp[:3])
        first = exp[0]
        cite = {"source": _cite(first), "url": first.get("url"), "text": all_vals}
        if acids and bases or ("acid" in gi_kinds and "base" in gi_kinds):
            return {"pka_acid": None, "pka_base": None, "values": exp, "kind": "source", **cite,
                    "why_not": "zwitterion / amphoteric: a single-pKa Henderson-Hasselbalch model does not apply"}
        if acids:
            p = min(acids, key=lambda x: x["value"])
            return {"pka_acid": p["value"], "pka_base": None, "values": exp, "kind": "source", **cite}
        if bases:
            p = max(bases, key=lambda x: x["value"])
            return {"pka_acid": None, "pka_base": p["value"], "values": exp, "kind": "source", **cite}
        return {"pka_acid": None, "pka_base": None, "values": exp, "kind": "source", **cite,
                "why_not": "the source doesn't say whether the pKa is acidic or basic; enter it with its type"}
    if rec.get("pka_acid") is not None or rec.get("pka_base") is not None:
        a, b = rec.get("pka_acid"), rec.get("pka_base")
        # ChemAxon's "most acidic/basic" pKa exists for almost any molecule; only use the one
        # that can matter in pH 1-8 (acid < 9, base > 3)
        a = a if a is not None and a < 9 else None
        b = b if b is not None and b > 3 else None
        base = {"values": [], "kind": "estimate", "source": "ChEMBL (ChemAxon, predicted)", "url": rec.get("url"), "text": None}
        if a is not None and b is not None:
            return {"pka_acid": None, "pka_base": None, **base, "why_not": "predicted zwitterion: single-pKa model does not apply"}
        return {"pka_acid": a, "pka_base": b, **base}
    return {"pka_acid": None, "pka_base": None, "values": [], "kind": None, "source": None, "url": None, "text": None}


def profile(key: str) -> Optional[dict[str, Any]]:
    rec = structures().get(key)
    if rec and rec.get("hidden") and rec.get("canonical"):
        key, rec = rec["canonical"], structures().get(rec["canonical"])
    if rec is None or not rec.get("smiles"):
        return None
    exp = rec.get("exp") or {}
    nsq = _nsq_for(rec)
    fus = thermo_props.fusion(rec["name"], rec["smiles"], rec.get("mp_c"))
    dose = nsq["max_strength_mg"]
    # One log P throughout (Lipinski, GSE, permeability proxy): measured > PubChem XLogP3 > Crippen
    if (exp.get("logp") or {}).get("value") is not None:
        logp, logp_src, logp_kind = float(exp["logp"]["value"]), f"measured ({_cite(exp['logp'])})", "source"
    elif rec.get("xlogp") is not None:
        logp, logp_src, logp_kind = float(rec["xlogp"]), "PubChem XLogP3 (computed)", "estimate"
    else:
        logp, logp_src, logp_kind = None, "RDKit Crippen cLogP (computed)", "estimate"
    mp_for_gse = fus["mp_c"] if fus.get("mp_measured") else None
    prof = molecule.profile(rec["smiles"], mp_for_gse, dose, logp, logp_src)
    if prof is None:
        return None
    prof = {**prof}
    est = prof["solubility"]
    mw = prof["descriptors"]["mw"]
    meas = exp.get("solubility_water_mg_ml")
    if meas and meas.get("value"):
        t_c = meas.get("t_c")
        s_at = float(meas["value"])
        s25 = molecule.mg_ml_at(25.0, s_at, fus["dh_fus"]) if (t_c is not None and fus["dh_fus"] and abs(t_c - 25) > 0.5) else s_at
        sol = {"kind": "source", "model": f"measured in water{f' at {t_c:g} °C' if t_c is not None else ''} ({_cite(meas)})",
               "mg_per_ml": s25, "display_mg_ml": float(f"{s25:.2g}"), "log_s": round(math.log10(s25 / mw), 2),
               "text": meas.get("text"), "source": _cite(meas), "url": meas.get("url"), "t_c": t_c,
               "uncertainty": None, "in_domain": True,
               "flags": ["pH of the measurement not stated: for an ionisable drug this may not be the intrinsic solubility"]
               if est.get("ionisable_gi") else [],
               "ionisable": est["ionisable"], "ionisable_gi": est.get("ionisable_gi", []),
               "logp": est["logp"], "logp_source": est["logp_source"], "estimate": {k: est[k] for k in ("model", "log_s", "display_mg_ml", "uncertainty")}}
    else:
        sol = est
    sol = {**sol, "logp_kind": logp_kind}
    s25 = sol["mg_per_ml"]
    s37 = molecule.mg_ml_at(37.0, s25, fus["dh_fus"]) if fus["dh_fus"] else s25
    vol = prof["descriptors"]["le_bas_volume"]
    diff = molecule.hayduk_laudie_diffusivity(vol)
    pka = _pka_choice(rec, sol.get("ionisable") or [])
    # BCS: provisional, only with an oral solid dose and a solubility inside the model's domain
    if not dose:
        bcs = {"class": None, "reason": "No oral solid dose: " + ("NSQ strengths for this molecule are injections, liquids or topicals only."
                                                                 if nsq.get("other_strengths") else "no tablet or capsule strength in the NSQ product names.")}
    elif not sol.get("in_domain", True):
        bcs = {"class": None, "reason": "Solubility estimate is outside the model's domain, so no class is given."}
    elif sol["kind"] == "estimate" and set(sol.get("ionisable_gi") or []) == {"acid", "base"}:
        bcs = {"class": None, "reason": "Zwitterion: a neutral-form solubility estimate can be off by orders of magnitude, so no class is given. "
                                        "A measured solubility would allow one."}
    else:
        bcs = molecule.bcs(s25, sol["logp"], dose, sol["kind"] if sol["kind"] == "source" else "estimate")
        if sol["kind"] == "source":
            bcs["reason"] = bcs["reason"].replace("estimated solubility (±1 log unit)", "measured solubility")
            bcs["basis"] = bcs["basis"].replace("estimated solubility (±1 log unit)", "measured solubility")
    prof["bcs"] = bcs
    prof["solubility"] = sol
    return {
        "key": key, "name": rec["name"], "source": rec["source"], "cid": rec.get("cid"), "url": rec.get("url"),
        "iupac": rec.get("iupac"), **prof, "thermal": fus,
        "derived": {"solubility_37_mg_ml": float(f"{s37:.4g}"), "diffusivity_cm2_s": float(f"{diff:.3g}"),
                    "diffusivity_note": "Hayduk-Laudie (1974) from the Le Bas volume, ±30%",
                    "dose_mg": dose, "dose_kind": "source" if dose else None,
                    "pka_acid": pka["pka_acid"], "pka_base": pka["pka_base"], "pka": pka,
                    "ionisable": sol.get("ionisable_gi") or []},
        "nsq": nsq,
        "experimental": {"solubility_texts": exp.get("solubility_texts") or [], "pka": exp.get("pka") or [], "logp": exp.get("logp")},
        "provenance": {
            "structure": _src(rec.get("cid"), "source" if rec["source"] == "PubChem" else "assumption",
                              f"PubChem CID {rec['cid']}" if rec.get("cid") else rec["source"], rec.get("url")),
            "log_p": _src(sol["logp"], logp_kind, logp_src, (exp.get("logp") or {}).get("url") if logp_kind == "source" else rec.get("url")),
            "aqueous_solubility": _src(sol.get("display_mg_ml"), sol["kind"], sol["model"] + (f" · {sol['uncertainty']}" if sol.get("uncertainty") else ""),
                                       sol.get("url"), sol.get("text")),
            "melting_point": _src(fus["mp_c"], "source" if fus["mp_c"] is not None else None,
                                  fus["mp_source"] or "unknown (no experimental or curated value; solubility uses ESOL)",
                                  rec.get("url") if (fus["mp_source"] or "").startswith("experimental") else None),
            "enthalpy_of_fusion": _src(fus["dh_fus"], "source" if fus.get("dh_kind") == "measured" else ("estimate" if fus["dh_fus"] else None),
                                       fus["dh_source"] or "unknown"),
            "pka": _src(pka["pka_acid"] if pka["pka_acid"] is not None else pka["pka_base"], pka["kind"],
                        (pka["source"] or "none published") + (f" — {pka['why_not']}" if pka.get("why_not") else ""), pka.get("url"), pka.get("text")),
            "dose": _src(dose, "source" if dose else None,
                         "highest tablet/capsule strength in single-ingredient NSQ product names (CDSCO)" if dose else "no oral solid strength in NSQ names"),
            "diffusivity": _src(float(f"{diff:.3g}"), "estimate", "Hayduk-Laudie 1974, Le Bas volume, ±30%"),
        },
    }


def molecules() -> dict[str, Any]:
    """Picker list (no computed classes in the picker: those are estimates, shown on the molecule page)."""
    ckey = (id(structures()), id(nsq_by_ingredient()))
    hit = _cache.get("molecules")
    if hit and hit[0] == ckey:
        return {**hit[1], "engines": engines()}
    out = _molecules()
    _cache["molecules"] = (ckey, out)
    return {**out, "engines": engines()}


def _molecules() -> dict[str, Any]:
    rows = []
    for k, rec in structures().items():
        if rec.get("hidden"):
            continue
        nsq = _nsq_for(rec)
        rows.append({"key": k, "name": rec["name"], "source": rec["source"], "has_structure": bool(rec.get("smiles")), "alerts": nsq["alerts"],
                     "dissolution_pct": nsq["dissolution_pct"]})
    rows.sort(key=lambda r: (-r["alerts"], r["name"]))
    return {"molecules": rows, "solvents": list(thermo_props.SOLVENTS), "materials": product.MATERIALS,
            "materials_note": product.MATERIALS_NOTE}


# --- simulations ---------------------------------------------------------------------------------------

def _source_rec(name: str, key: str) -> dict[str, Any]:
    """A per-molecule record from a source file, by molecule key or its US name / ingredient key."""
    import ingredients as ing

    from . import signals

    data_ = (signals._load(name).get("data") or {})
    rec = structures().get(key) or {}
    cands = [key, ing.ingredient_key(rec.get("name") or ""), ing.us_name(ing.ingredient_key(rec.get("name") or key.replace("_", " ")))]
    for c in cands:
        if c and c in data_:
            return data_[c]
        if c and c.split()[0] in data_:
            return data_[c.split()[0]]
    return {}


def fda_method(key: str) -> Optional[dict[str, Any]]:
    """FDA Dissolution Methods Database: the immediate-release tablet / capsule method for this molecule, if FDA gives one."""
    rows = _source_rec("fda_dissolution", key)
    rows = rows if isinstance(rows, list) else []
    for form in ("Tablet", "Capsule", "Tablet (Film Coated)", "Tablet, Film Coated"):
        for r in rows:
            if (r.get("dosage_form") or "").strip().lower() == form.lower():
                ph = re.search(r"pH\s*(\d+(?:\.\d+)?)", r.get("medium") or "", re.I)
                hcl = re.search(r"(0\.1|0\.01)\s*N\s*HCl", r.get("medium") or "", re.I)
                return {**r, "ph": float(ph.group(1)) if ph else (1.2 if hcl and hcl.group(1) == "0.1" else 2.0 if hcl else None),
                        "source": "FDA Dissolution Methods Database",
                        "url": "https://www.accessdata.fda.gov/scripts/cder/dissolution/index.cfm"}
    return None


def label_pk(key: str) -> dict[str, Any]:
    """PK inputs from the US label (openFDA), each with the sentence it came from. Missing values stay missing."""
    rec = _source_rec("fda_labels", key)
    pk_ = (rec or {}).get("pk") or {}
    lab = (rec or {}).get("pk_label") or {}
    out: dict[str, Any] = {}
    cite = {"label": f"US label: {lab.get('brand') or ''} ({lab.get('application_number') or ''})", "url": lab.get("url")}
    t_half = (pk_.get("half_life_h") or {}).get("value")
    vd = (pk_.get("vd_l") or {}).get("value")
    vd_note = ""
    if vd is None and (pk_.get("vd_l_kg") or {}).get("value") is not None:
        vd, vd_note = float(pk_["vd_l_kg"]["value"]) * 70.0, " (label gives L/kg; × 70 kg adult)"
    cl_stated = None
    if (pk_.get("cl") or {}).get("value") is not None:
        unit, v_ = pk_["cl"].get("unit", ""), float(pk_["cl"]["value"])
        per_kg = "/kg" in unit
        cl_stated = (v_ * 0.06 if unit.lower().startswith("ml/min") else v_) * (70.0 if per_kg else 1.0)
    if vd:
        out["v_l"] = {"value": round(float(vd), 2), "text": (pk_.get("vd_l") or pk_.get("vd_l_kg"))["text"], **cite, "note": vd_note.strip()}
    if cl_stated:  # a stated clearance beats one derived from the terminal half-life (which understates it for multi-phase drugs)
        out["cl_l_h"] = {"value": round(cl_stated, 3), "text": pk_["cl"]["text"], **cite,
                         "note": f"stated clearance {pk_['cl']['value']:g} {pk_['cl'].get('unit', '')}" + (" × 70 kg" if "/kg" in pk_["cl"].get("unit", "") else "")}
    elif t_half and vd:
        out["cl_l_h"] = {"value": round(math.log(2) / float(t_half) * float(vd), 3), "text": pk_["half_life_h"]["text"], **cite,
                         "note": f"CL = ln2 / t½ × V (t½ {t_half:g} h, V {vd:g} L; terminal half-life, so a lower bound for multi-phase drugs)"}
    if "cl_l_h" in out and vd:
        ke = out["cl_l_h"]["value"] / float(vd)
        tmax = (pk_.get("tmax_h") or {}).get("value")
        if tmax and ke > 0:
            from scipy.optimize import brentq

            f = lambda ka: math.log(ka / ke) / (ka - ke) - float(tmax)  # noqa: E731 — one-compartment Tmax
            try:
                ka = brentq(f, ke * 1.0001, 50.0) if f(ke * 1.0001) > 0 > f(50.0) else None
            except ValueError:
                ka = None
            if ka:
                out["ka_h"] = {"value": round(ka, 3), "text": pk_["tmax_h"]["text"], **cite,
                               "note": f"ka solved from Tmax = ln(ka/ke)/(ka−ke) with Tmax {tmax:g} h"}
    if (pk_.get("f_pct") or {}).get("value"):
        out["f_abs"] = {"value": round(float(pk_["f_pct"]["value"]) / 100, 3), "text": pk_["f_pct"]["text"], **cite}
    return out


# Inputs the UI shows as "assumed" unless the user changed them; the model can't know them.
DISSOLUTION_DEFAULTS = {"d50_um": 20.0, "gsd": 1.8, "lag_min": 2.0, "volume_ml": 900.0, "q_pct": 75.0, "q_time_min": 45.0, "density": 1.3}


def dissolution(key: str, p: dict[str, Any]) -> dict[str, Any]:
    prof = profile(key)
    if prof is None:
        raise KeyError(key)
    d = prof["derived"]
    sol = prof["solubility"]
    withheld: list[str] = []
    if p.get("dose_mg"):
        dose, dose_kind = float(p["dose_mg"]), ("source" if d["dose_mg"] and float(p["dose_mg"]) == float(d["dose_mg"]) else "user")
    elif d["dose_mg"]:
        dose, dose_kind = float(d["dose_mg"]), "source"
    else:
        dose, dose_kind = 100.0, "assumption"
        withheld.append("no oral solid dose known (100 mg assumed): enter the dose")
    if p.get("solubility_mg_ml"):
        cs, cs_kind = float(p["solubility_mg_ml"]), "user"
    else:
        cs, cs_kind = float(d["solubility_37_mg_ml"]), sol["kind"]
        if sol["kind"] == "estimate" and not sol.get("in_domain", True):
            withheld.append("solubility estimate is outside the model's domain")
    # Ionisation: an explicit request wins; else the sourced pKa; never an invented one
    ion = p.get("ionization")
    pka = p.get("pka")
    pka = float(pka) if pka not in (None, "") else None
    pka_kind = "user" if pka is not None else None
    if ion in (None, "", "auto"):
        if d["pka_acid"] is not None:
            ion, pka, pka_kind = "acid", float(d["pka_acid"]), d["pka"]["kind"]
        elif d["pka_base"] is not None:
            ion, pka, pka_kind = "base", float(d["pka_base"]), d["pka"]["kind"]
        else:
            ion = "none"
    if ion in ("acid", "base") and pka is None:
        withheld.append(f"weak {ion} selected but no pKa entered")
        ion = "none"
    if ion == "none" and d.get("ionisable") and not p.get("solubility_mg_ml"):
        if set(d["ionisable"]) == {"acid", "base"}:
            withheld.append("zwitterion / amphoteric molecule: its pH-solubility profile isn't a single-pKa curve; enter a measured solubility at the medium pH")
        else:
            why = d["pka"].get("why_not") or "pKa unknown"
            withheld.append(f"weak {d['ionisable'][0]} ({why}): enter the pKa, since solubility depends on pH")
    # FDA's recommended method sets the medium volume, pH and sampling window unless the user changed them.
    meth = fda_method(key)
    volume = float(p["volume_ml"]) if p.get("volume_ml") not in (None, "") else float((meth or {}).get("volume_ml") or 900)
    ph = float(p["ph"]) if p.get("ph") not in (None, "") else float((meth or {}).get("ph") or 6.8)
    t_end = float(p["t_end_min"]) if p.get("t_end_min") not in (None, "") else max(60.0, max((meth or {}).get("times_min") or [60.0]))
    res = product.dissolution(dose_mg=dose, cs_mg_ml=cs, diff_cm2_s=float(p.get("diffusivity") or d["diffusivity_cm2_s"]),
                              d50_um=float(p.get("d50_um", 20)), gsd=float(p.get("gsd", 1.8)), density_g_cm3=float(p.get("density", 1.3)),
                              volume_ml=volume, lag_min=float(p.get("lag_min", 2)), q_pct=float(p.get("q_pct", 75)),
                              q_time_min=float(p.get("q_time_min", 45)), t_end_min=t_end,
                              ionization=ion, pka=pka, ph=ph)
    if withheld:
        res = {**res, "verdict": "withheld", "why": [f"Verdict withheld: {w}." for w in withheld] + res["why"]}
    def _given(k: str, dflt: float) -> float:
        v_ = p.get(k)
        return dflt if v_ in (None, "") else float(v_)

    assumed = [k for k, v in DISSOLUTION_DEFAULTS.items() if _given(k, v) == v and not (k == "volume_ml" and meth and meth.get("volume_ml"))]
    sol_label = sol.get("model")
    if cs_kind != "user":
        sol_label = (f"{cs:.3g} mg/mL at 37 °C, extrapolated from {sol.get('display_mg_ml')} mg/mL at 25 °C ({sol.get('model')}) "
                     "with the van 't Hoff equation and ΔHfus")
    return {**res, "withheld": withheld,
            "verdict_basis": "model result under the assumed particle size" + (" and generic Q" if {"q_pct", "q_time_min"} & set(assumed) else ""),
            "inputs": {"dose_mg": {"value": dose, "kind": dose_kind, "label": prof["provenance"]["dose"]["label"] if dose_kind == "source" else None},
                       "solubility_mg_ml": {"value": float(f"{cs:.3g}"), "kind": cs_kind if cs_kind == "user" else "estimate", "label": sol_label,
                                            "url": sol.get("url")},
                       "medium": {"volume_ml": volume, "ph": ph, "t_end_min": t_end,
                                  "kind": "source" if meth and not any(p.get(x) not in (None, "") for x in ("volume_ml", "ph")) else ("user" if any(p.get(x) not in (None, "") for x in ("volume_ml", "ph")) else "assumption"),
                                  "label": (f"FDA method: {meth.get('dosage_form')}, {meth.get('apparatus')} {meth.get('rpm_text') or ''} rpm, "
                                            f"{meth.get('medium')}, {meth.get('volume_text')} mL, sampling {meth.get('times_text')} min") if meth else
                                           "no FDA method with a medium for this tablet/capsule: USP-style 900 mL, pH 6.8 assumed",
                                  "url": (meth or {}).get("url")},
                       "pka": {"value": pka, "kind": pka_kind, "ionization": ion, "label": d["pka"].get("source") if pka_kind in ("source", "estimate") else None,
                               "url": d["pka"].get("url")},
                       "diffusivity": {"value": d["diffusivity_cm2_s"], "kind": "estimate", "label": d["diffusivity_note"]}},
            "assumed": assumed, "fda_method": meth}


def engines() -> dict[str, Any]:
    draw = {"rdkit_draw": molecule.DRAW_ERROR is None, "draw_error": molecule.DRAW_ERROR}
    return {**_engines(), **draw}


def _engines() -> dict[str, Any]:
    if not SIM_URL:
        return {"pharmapy": {"available": False, "reason": "SIM_URL not set (start the sim service)"}, "builtin": {"available": True}}
    try:
        r = requests.get(f"{SIM_URL}/health", timeout=3)
        info = r.json()
        return {"pharmapy": {"available": bool(info.get("pharmapy")), "version": info.get("version"), "reason": info.get("error")},
                "builtin": {"available": True}}
    except Exception as exc:
        return {"pharmapy": {"available": False, "reason": f"sim service unreachable: {exc.__class__.__name__}"}, "builtin": {"available": True}}


def crystallize(key: str, p: dict[str, Any]) -> dict[str, Any]:
    prof = profile(key)
    if prof is None:
        raise KeyError(key)
    fus = prof["thermal"]
    if not (p.get("mp_c") or fus["mp_c"]) or not (p.get("dh_fus") or fus["dh_fus"]):
        raise ValueError("No measured melting point for this molecule, so no solubility curve: enter the melting point.")
    solvent = p.get("solvent", "ethanol")
    gamma = float(p.get("gamma", 1.0))
    mp = float(p.get("mp_c") or fus["mp_c"])
    dh = float(p.get("dh_fus") or fus["dh_fus"])
    aq = prof["solubility"]["mg_per_ml"] if solvent == "water" else None
    curve = thermo_props.curve(prof["descriptors"]["mw"], mp, dh, solvent, gamma=gamma, aq_mg_ml_25=aq,
                               api_cas=prof["thermal"].get("cas"))
    prog = {"t0_c": float(p.get("t0_c", 50)), "t1_c": float(p.get("t1_c", 5)), "cool_min": float(p.get("cool_min", 120)),
            "hold_min": float(p.get("hold_min", 30))}
    sv = curve["solvent"]
    if prog["t0_c"] >= sv["bp_c"] - 1:
        raise ValueError(f"Start temperature {prog['t0_c']:g} °C is at or above the boiling point of {sv['name']} ({sv['bp_c']:g} °C).")
    if sv.get("mp_c") is not None and prog["t1_c"] <= sv["mp_c"]:
        raise ValueError(f"End temperature {prog['t1_c']:g} °C is at or below the freezing point of {sv['name']} ({sv['mp_c']:g} °C).")
    if not curve["temps_c"][0] <= prog["t1_c"] < prog["t0_c"] <= curve["temps_c"][-1]:
        raise ValueError(f"Temperatures must satisfy {curve['temps_c'][0]:g} ≤ end < start ≤ {curve['temps_c'][-1]:g} °C.")
    notes = []
    if curve.get("ideal"):
        notes.append("Ideal solubility (γ = 1): " + (curve.get("unifac_note") or "the solvent is not modelled") +
                     ". Only its molar mass and density enter. Enter an activity coefficient (or measured solubility) for solvent-specific results.")
    elif curve.get("unifac"):
        notes.append("Solvent modelled with Modified UNIFAC (Dortmund), using the Dortmund Data Bank's published group assignment "
                     "for this molecule; typical accuracy for drug solubility is within a factor of 2–3.")
    if solvent == "water" and prof["solubility"]["kind"] == "estimate":
        notes.append("Water curve starts from the structure-based 25 °C estimate (±1 log unit).")
    if fus.get("dh_kind") == "estimate" and not p.get("dh_fus"):
        notes.append("Enthalpy of fusion is a Walden's-rule estimate (±30%).")
    kin_user = bool(p.get("kinetics"))
    req = {"api": {"name": prof["name"], "mw": prof["descriptors"]["mw"]}, "solvent": curve["solvent"], "curve": curve, "program": prog,
           "rho_solid": float(p.get("rho_solid", 1300)), "seed_pct": float(p.get("seed_pct", 0)), "seed_um": float(p.get("seed_um", 50)),
           "volume_l": float(p.get("volume_l", 1.0)), "kinetics": p.get("kinetics") or None}
    want = p.get("engine", "auto")
    seeded = float(p.get("seed_pct", 0) or 0) > 0

    def done(res: dict[str, Any], note: Optional[str] = None) -> dict[str, Any]:
        n = [x for x in [note, *notes] if x]
        if res.get("engine") == "pharmapy" and seeded:
            n.append("Seed loading is ignored by the PharmaPy engine (unseeded run); use the built-in engine for seeded runs.")
        return {**res, "note": " ".join(n) or None, "notes": n, "kinetics_illustrative": not kin_user,
                "curve": curve, "request": {k: v for k, v in req.items() if k != "curve"}}

    note = None
    # A seeded run in "auto" goes to the built-in engine, which models seeds.
    if want == "pharmapy" or (want == "auto" and not seeded):
        if SIM_URL:
            try:
                r = requests.post(f"{SIM_URL}/crystallize", json=req, timeout=120)
                r.raise_for_status()
                return done(r.json())
            except Exception as exc:
                note = f"PharmaPy run failed ({exc.__class__.__name__}: {str(exc)[:160]}); used the built-in engine."
        elif want == "pharmapy":
            note = "PharmaPy sim service not configured (SIM_URL); used the built-in engine."
    return done(crystallization.builtin(req), note)


def compaction(p: dict[str, Any]) -> dict[str, Any]:
    mat = product.MATERIALS.get(p.get("material", "plastic"), product.MATERIALS["plastic"])
    return product.compaction(py_mpa=float(p.get("py_mpa", mat["py_mpa"])), sigma0_mpa=float(p.get("sigma0_mpa", mat["sigma0_mpa"])),
                              b=float(p.get("b", mat["b"])), d0=float(p.get("d0", 0.40)), target_mpa=float(p.get("target_mpa", product.TARGET_TENSILE_MPA)))


def fluid_bed(p: dict[str, Any]) -> dict[str, Any]:
    return product.fluid_bed(inlet_c=float(p.get("inlet_c", 60)), dew_point_c=float(p.get("dew_point_c", 10)), air_m3_h=float(p.get("air_m3_h", 300)),
                             spray_g_min=float(p.get("spray_g_min", 50)), solids_pct=float(p.get("solids_pct", 8)),
                             heat_loss_pct=float(p.get("heat_loss_pct", 10)))


def fetch_structure(key: str) -> dict[str, Any]:
    """Look a molecule up in PubChem (else ChEMBL) now and keep the result for the lab."""
    from . import medicines as med_mod
    rec = structures().get(key) or {"name": key.replace("_", " ")}
    got = med_mod.enrich_ingredient({"name": rec["name"], "molecule_key": key, "role": "active", "source": "lab"})
    if not got.get("smiles"):
        status = {k: v.get("status") for k, v in (got.get("sources") or {}).items()}
        # A ChEMBL/PubChem "match" with no SMILES usually means the record found is
        # unnamed, a related-but-different drug, or a complex/colloid with no single
        # well-defined structure (e.g. iron-carbohydrate complexes, some aluminum/
        # sulfate salts) — not a lookup bug. Say that plainly instead of implying
        # the databases just need to be retried.
        no_structure_hint = (status.get("chembl") == "ok" or status.get("pubchem") == "ok")
        detail = f"(PubChem: {status.get('pubchem')}, ChEMBL: {status.get('chembl')})"
        if no_structure_hint:
            raise ValueError(f"{rec['name']} has no small-molecule structure in PubChem/ChEMBL {detail} — "
                              "likely a biologic, colloid, or complex/salt with no single defined structure. "
                              "Enter a SMILES manually if you have one.")
        raise ValueError(f"No structure found for {rec['name']} {detail}.")
    live_p = settings.data_dir / "generated" / "structures_live.json"
    live_p.parent.mkdir(parents=True, exist_ok=True)
    cur = json.loads(live_p.read_text(encoding="utf-8")) if live_p.exists() else {}
    cur[key] = {"name": rec["name"], "smiles": got["smiles"], "source": got.get("structure_source") or "PubChem", "cid": got.get("cid"),
                "url": (got.get("links") or {}).get("pubchem") or (got.get("links") or {}).get("chembl"), "xlogp": got.get("xlogp"),
                "mp_c": got.get("mp_c"), "pka_acid": got.get("pka_acid"), "pka_base": got.get("pka_base")}
    tmp = live_p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    tmp.replace(live_p)
    _cache.pop("structures", None)
    _cache.pop("molecules", None)
    return cur[key]


# --- bioequivalence risk and safety signals -------------------------------------------------------

PK_DEFAULTS = {"cl_l_h": 10.0, "v_l": 50.0, "ka_h": 1.0, "f_abs": 1.0}


def bioequivalence(key: str, p: dict[str, Any]) -> dict[str, Any]:
    """Test dissolution vs a fast-dissolving reference, each pushed through a one-compartment PK model."""
    from chem import pk
    prof = profile(key)
    if prof is None:
        raise KeyError(key)
    d = prof["derived"]
    window_h = float(p.get("window_h", 4.0))
    base = {"dose_mg": p.get("dose_mg") or d["dose_mg"], "solubility_mg_ml": p.get("solubility_mg_ml"),
            "ionization": p.get("ionization"), "pka": p.get("pka"), "ph": p.get("ph"), "volume_ml": p.get("volume_ml"),
            "t_end_min": max(60.0, window_h * 60 + 30)}
    test = dissolution(key, {**base, "d50_um": p.get("d50_um", 20), "gsd": p.get("gsd", 1.8), "lag_min": p.get("lag_min", 2)})
    ref = dissolution(key, {**base, "d50_um": p.get("ref_d50_um", 5), "gsd": 1.5, "lag_min": p.get("ref_lag_min", 1)})
    dose = float(test["inputs"]["dose_mg"]["value"])
    # PK inputs: what the user typed, else what the US label states (quoted), else a placeholder flagged as assumed.
    lab = label_pk(key)
    pk_in: dict[str, Any] = {}
    for k_, dflt in PK_DEFAULTS.items():
        if p.get(k_) not in (None, "") and float(p[k_]) != dflt:
            pk_in[k_] = {"value": float(p[k_]), "kind": "user"}
        elif k_ in lab:
            pk_in[k_] = {**lab[k_], "kind": "source"}
        else:
            pk_in[k_] = {"value": dflt, "kind": "assumption"}
    kw = dict(dose_mg=dose, cl_l_h=pk_in["cl_l_h"]["value"], v_l=pk_in["v_l"]["value"], ka_h=pk_in["ka_h"]["value"],
              f_abs=pk_in["f_abs"]["value"], window_h=window_h, in_vivo_scale=float(p.get("in_vivo_scale", 1.0)))
    pt, pr = pk.simulate(test["times_min"], test["pct"], **kw), pk.simulate(ref["times_min"], ref["pct"], **kw)
    cmp = pk.compare(pt, pr)
    pk_assumed = [k_ for k_, v in pk_in.items() if v["kind"] == "assumption"]
    if test["withheld"] and cmp["risk"] != "not_assessable":
        cmp = {**cmp, "risk": "withheld", "message": "Verdict withheld: " + "; ".join(test["withheld"]) + ". Ratios shown for exploration only."}
    return {"test": {"dissolution": {k: test[k] for k in ("times_min", "pct", "at_q", "t85", "sink_index")}, "pk": pt},
            "reference": {"dissolution": {k: ref[k] for k in ("times_min", "pct", "at_q", "t85")}, "pk": pr},
            "compare": cmp, "inputs": {**kw, "ref_d50_um": p.get("ref_d50_um", 5), "dose": test["inputs"]["dose_mg"],
                                         "solubility": test["inputs"]["solubility_mg_ml"], "pka": test["inputs"]["pka"]},
            "pk_assumed": pk_assumed, "pk_inputs": pk_in,
            "assumptions": [
                "One-compartment PK with first-order absorption of dissolved drug; absorption stops after the absorption window (small-intestine transit)",
                "In-vivo dissolution = the in-vitro profile (time-scaling factor adjustable); no permeability, gut-wall or first-pass effects beyond F",
                "Reference = the same molecule with fine particles (d50 %g µm) dissolving fast, not the innovator product" % float(p.get("ref_d50_um", 5)),
                ("PK from the US label where it states a value (half-life, volume, bioavailability, Tmax — quoted); "
                 + ("still ASSUMED: " + ", ".join(pk_assumed) + " (the label doesn't state it — enter a literature value)" if pk_assumed else "nothing assumed")),
                "The AUC ratio depends only on how much dissolves inside the absorption window, not on clearance or volume",
            ]}


def safety(key: str) -> dict[str, Any]:
    from . import safety as faers
    rec = structures().get(key) or {}
    name = rec.get("name") or key.replace("_", " ")
    import ingredients as ing
    parent = ing.ingredient_key(name) or name  # FAERS uses the parent generic name (no salt)
    term = ing.us_name(parent) if hasattr(ing, "us_name") else parent
    alts = tuple(x for x in {name, ing.us_name(name) if hasattr(ing, "us_name") else name} if x and x.lower() != term.lower())
    try:
        out = faers.signals(term, alts=alts)
    except requests.RequestException as exc:
        raise ValueError(f"openFDA is unreachable from the server ({exc.__class__.__name__}). Try again later.")
    return {**out, "query_name": out.get("search_term") or term.upper(), "local_name": parent}