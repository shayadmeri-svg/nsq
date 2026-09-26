"""The lab: structure-based molecule profiles, drug-product models and
crystallisation, tied back to the NSQ alerts for each molecule.

Structures come from the PubChem source (data/sources/pubchem.json) and fall
back to data/structures_seed.json. Crystallisation runs in the PharmaPy
sidecar when SIM_URL is set and reachable, else in the built-in engine.
"""

from __future__ import annotations

import json
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
    key = (_mtime(seed_p), _mtime(pc_p))
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
                      "xlogp": v.get("xlogp"), "mp_c": v.get("mp_c"), "mp_values": v.get("mp_values"), "iupac": v.get("iupac")}
    _cache["structures"] = (key, out)
    return out


# --- NSQ per ingredient ---------------------------------------------------------------------------------

def nsq_by_ingredient() -> dict[str, dict[str, Any]]:
    base = data.frame()
    key = (id(base), len(base))
    hit = _cache.get("nsq")
    if hit and hit[0] == key:
        return hit[1]
    df = data.attributable(base)
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"alerts": 0, "dissolution": 0, "categories": Counter(), "strengths": Counter(), "forms": Counter()})
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
                for m in _STRENGTH.findall(name):
                    v = float(m)
                    if 0.05 <= v <= 2000:
                        s["strengths"][v] += 1
    out = {}
    for k, s in stats.items():
        strengths = sorted(s["strengths"])
        out[k] = {"alerts": s["alerts"], "dissolution": s["dissolution"],
                  "dissolution_pct": round(100 * s["dissolution"] / s["alerts"], 1) if s["alerts"] else 0.0,
                  "categories": [{"name": c, "count": n} for c, n in s["categories"].most_common(6)],
                  "forms": [{"name": c, "count": n} for c, n in s["forms"].most_common(5)],
                  "strengths_mg": strengths[-6:], "max_strength_mg": strengths[-1] if strengths else None}
    _cache["nsq"] = (key, out)
    return out


def _nsq_for(rec: dict[str, Any]) -> dict[str, Any]:
    nsq = nsq_by_ingredient()
    keys = [rec["key"], *rec.get("aliases", [])]
    rows = [nsq[k] for k in keys if k in nsq]
    if not rows:
        return {"alerts": 0, "dissolution": 0, "dissolution_pct": 0.0, "categories": [], "forms": [], "strengths_mg": [], "max_strength_mg": None}
    best = max(rows, key=lambda r: r["alerts"])
    if len(rows) > 1:
        alerts = sum(r["alerts"] for r in rows)
        dis = sum(r["dissolution"] for r in rows)
        best = {**best, "alerts": alerts, "dissolution": dis, "dissolution_pct": round(100 * dis / alerts, 1),
                "max_strength_mg": max((r["max_strength_mg"] or 0) for r in rows) or None}
    return best


# --- molecule profile -------------------------------------------------------------------------------------

def profile(key: str) -> Optional[dict[str, Any]]:
    rec = structures().get(key)
    if rec is None or not rec.get("smiles"):
        return None
    nsq = _nsq_for(rec)
    fus = thermo_props.fusion(rec["name"], rec["smiles"], rec.get("mp_c"))
    dose = nsq["max_strength_mg"]
    logp = float(rec["xlogp"]) if rec.get("xlogp") is not None else None
    # GSE needs a measured melting point; with only an estimate, ESOL (structure only) is safer.
    mp_for_gse = fus["mp_c"] if fus.get("mp_measured") else None
    prof = molecule.profile(rec["smiles"], mp_for_gse, dose, logp, "PubChem XLogP3")
    if prof is None:
        return None
    mw = prof["descriptors"]["mw"]
    s25 = prof["solubility"]["mg_per_ml"]
    s37 = molecule.mg_ml_at(37.0, s25, fus["dh_fus"]) if fus["dh_fus"] else s25
    diff = molecule.hayduk_laudie_diffusivity(prof["descriptors"]["mcgowan_volume"])
    return {
        "key": key, "name": rec["name"], "source": rec["source"], "cid": rec.get("cid"), "url": rec.get("url"),
        "iupac": rec.get("iupac"), **prof, "thermal": fus,
        "derived": {"solubility_37_mg_ml": float(f"{s37:.4g}"), "diffusivity_cm2_s": float(f"{diff:.3g}"), "dose_mg": dose},
        "nsq": nsq,
        "provenance": {
            "structure": "PubChem" if rec["source"] == "PubChem" else "hand-entered seed (checked against formula); run the PubChem job to replace",
            "logp": prof["solubility"]["logp_source"],
            "melting_point": fus["mp_source"] or "unknown (solubility falls back to ESOL)",
            "enthalpy_of_fusion": fus["dh_source"] or "unknown",
            "dose": "highest strength in single-ingredient NSQ product names" if dose else "unknown",
        },
    }


def molecules() -> dict[str, Any]:
    """Picker list plus the cross-molecule view: computed solubility / BCS vs NSQ dissolution failures."""
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
        nsq = _nsq_for(rec)
        row = {"key": k, "name": rec["name"], "source": rec["source"], "has_structure": bool(rec.get("smiles")), "alerts": nsq["alerts"],
               "dissolution_pct": nsq["dissolution_pct"]}
        if rec.get("smiles") and nsq["alerts"]:
            p = profile(k)
            if p:
                row.update({"log_s": p["solubility"]["log_s"], "bcs": p["bcs"].get("class"), "logp": p["solubility"]["logp"],
                            "mw": p["descriptors"]["mw"], "dose_number": p["bcs"].get("dose_number")})
        rows.append(row)
    rows.sort(key=lambda r: (-r["alerts"], r["name"]))
    by_class: dict[str, dict[str, int]] = defaultdict(lambda: {"alerts": 0, "dissolution": 0, "molecules": 0})
    for r in rows:
        if r.get("bcs") and r["alerts"] >= 5:
            c = by_class[r["bcs"]]
            c["molecules"] += 1
            c["alerts"] += r["alerts"]
            c["dissolution"] += round(r["alerts"] * r["dissolution_pct"] / 100)
    classes = [{"bcs": k, **v, "dissolution_pct": round(100 * v["dissolution"] / v["alerts"], 1) if v["alerts"] else 0.0}
               for k, v in sorted(by_class.items())]
    return {"molecules": rows, "by_bcs": classes, "solvents": list(thermo_props.SOLVENTS), "materials": product.MATERIALS}


# --- simulations ---------------------------------------------------------------------------------------

def dissolution(key: str, p: dict[str, Any]) -> dict[str, Any]:
    prof = profile(key)
    if prof is None:
        raise KeyError(key)
    d = prof["derived"]
    dose = float(p.get("dose_mg") or d["dose_mg"] or 100.0)
    cs = float(p.get("solubility_mg_ml") or d["solubility_37_mg_ml"])
    res = product.dissolution(dose_mg=dose, cs_mg_ml=cs, diff_cm2_s=float(p.get("diffusivity") or d["diffusivity_cm2_s"]),
                              d50_um=float(p.get("d50_um", 20)), gsd=float(p.get("gsd", 1.8)), density_g_cm3=float(p.get("density", 1.3)),
                              volume_ml=float(p.get("volume_ml", 900)), lag_min=float(p.get("lag_min", 2)), q_pct=float(p.get("q_pct", 75)),
                              q_time_min=float(p.get("q_time_min", 45)), t_end_min=float(p.get("t_end_min", 60)),
                              ionization=p.get("ionization") or "none", pka=float(p["pka"]) if p.get("pka") not in (None, "") else None,
                              ph=float(p.get("ph", 6.8)))
    return {**res, "inputs": {"dose_mg": dose, "solubility_mg_ml": cs, "diffusivity": d["diffusivity_cm2_s"]}}


def engines() -> dict[str, Any]:
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
    if not fus["mp_c"] or not fus["dh_fus"]:
        raise ValueError("No melting point for this molecule, so no solubility curve: run the PubChem job or enter it.")
    solvent = p.get("solvent", "ethanol")
    gamma = float(p.get("gamma", 1.0))
    mp = float(p.get("mp_c") or fus["mp_c"])
    dh = float(p.get("dh_fus") or fus["dh_fus"])
    aq = prof["solubility"]["mg_per_ml"] if solvent == "water" else None
    curve = thermo_props.curve(prof["descriptors"]["mw"], mp, dh, solvent, gamma=gamma, aq_mg_ml_25=aq)
    prog = {"t0_c": float(p.get("t0_c", 50)), "t1_c": float(p.get("t1_c", 5)), "cool_min": float(p.get("cool_min", 120)),
            "hold_min": float(p.get("hold_min", 30))}
    req = {"api": {"name": prof["name"], "mw": prof["descriptors"]["mw"]}, "solvent": curve["solvent"], "curve": curve, "program": prog,
           "rho_solid": float(p.get("rho_solid", 1300)), "seed_pct": float(p.get("seed_pct", 0)), "seed_um": float(p.get("seed_um", 50)),
           "volume_l": float(p.get("volume_l", 1.0)), "kinetics": p.get("kinetics") or None}
    want = p.get("engine", "auto")
    note = None
    if want in ("auto", "pharmapy") and SIM_URL:
        try:
            r = requests.post(f"{SIM_URL}/crystallize", json=req, timeout=120)
            r.raise_for_status()
            res = r.json()
            return {**res, "curve": curve, "request": {k: v for k, v in req.items() if k != "curve"}}
        except Exception as exc:
            note = f"PharmaPy run failed ({exc.__class__.__name__}: {str(exc)[:160]}); used the built-in engine."
    elif want == "pharmapy":
        note = "PharmaPy sim service not configured (SIM_URL); used the built-in engine."
    res = crystallization.builtin(req)
    if note:
        res["note"] = note
    return {**res, "curve": curve, "request": {k: v for k, v in req.items() if k != "curve"}}


def compaction(p: dict[str, Any]) -> dict[str, Any]:
    mat = product.MATERIALS.get(p.get("material", "plastic"), product.MATERIALS["plastic"])
    return product.compaction(py_mpa=float(p.get("py_mpa", mat["py_mpa"])), sigma0_mpa=float(p.get("sigma0_mpa", mat["sigma0_mpa"])),
                              b=float(p.get("b", mat["b"])), d0=float(p.get("d0", 0.40)), target_mpa=float(p.get("target_mpa", product.TARGET_TENSILE_MPA)))


def fluid_bed(p: dict[str, Any]) -> dict[str, Any]:
    return product.fluid_bed(inlet_c=float(p.get("inlet_c", 60)), dew_point_c=float(p.get("dew_point_c", 10)), air_m3_h=float(p.get("air_m3_h", 300)),
                             spray_g_min=float(p.get("spray_g_min", 50)), solids_pct=float(p.get("solids_pct", 8)),
                             heat_loss_pct=float(p.get("heat_loss_pct", 10)))
