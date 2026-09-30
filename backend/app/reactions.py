"""Reaction lab: run a synthesis step as a batch-reactor kinetic model, anchored to a published example.

Routes come from the Open Reaction Database scan (data/sources/ord.json): for each tracked molecule, the
patent / paper reactions that make it, with temperature, time, solvent and reported yield. A route with all
three becomes the calibration anchor: the main rate constant is set so the model gives that yield at that
temperature and time (for the assumed activation energy), and everything else is prediction.

Engines: the built-in SciPy integrator (chem.reaction) and, when the sim sidecar is up, PharmaPy's
BatchReactor — the built-in result is always computed too, so the two are compared on every PharmaPy run.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

import numpy as np
import requests

from chem import reaction, thermo_props

from . import signals
from .lab import SIM_URL, _engines

# ORD solvent names -> a name `thermo` resolves (boiling point, density, heat capacity)
_SOLVENT_ALIAS = {"dmso": "dimethyl sulfoxide", "dmf": "dimethylformamide", "thf": "tetrahydrofuran", "dcm": "dichloromethane",
                  "mek": "methyl ethyl ketone", "ipa": "isopropanol", "etoac": "ethyl acetate", "meoh": "methanol",
                  "etoh": "ethanol", "mecn": "acetonitrile", "nmp": "n-methyl-2-pyrrolidone", "dma": "dimethylacetamide"}


def solvent_props(name: Optional[str]) -> Optional[dict[str, Any]]:
    if not name or name.lower() in ("mixture", "water/mixture"):
        return None
    key = _SOLVENT_ALIAS.get(name.lower(), name)
    try:
        s = thermo_props.solvent(key)
    except Exception:
        return None
    cp = None
    try:
        from thermo import Chemical
        c = Chemical(s["name"], T=298.15)
        cp = round(float(c.Cpl) / 1000, 3) if c.Cpl else None  # J/(kg·K) -> kJ/(kg·K)
    except Exception:
        pass
    return {"name": name, "bp_c": s["bp_c"], "rho_kg_l": round(s["rho_25"] / 1000, 3), "cp_kj_kg_k": cp}


def routes(key: str) -> dict[str, Any]:
    """ORD reactions that make this molecule, anchors (T + time + a sane yield) first."""
    d = signals._load("ord")
    m = (d.get("data") or {}).get(key)
    if not m:
        return {"available": bool(d), "found": False, "molecules": molecules_with_routes()}
    out = []
    for e in m.get("examples") or []:
        y = e.get("yield")
        y = y if isinstance(y, (int, float)) and 0 < y <= 100 else None
        t, h = e.get("temp_c"), e.get("hours")
        anchor = y is not None and t is not None and h is not None and 0 < h <= 200
        solv = next((s for s in (e.get("solvents") or []) if s and s.lower() != "mixture"), None)
        reactants = [r for r in (e.get("reactants") or []) if r]
        out.append({"id": e["id"], "patent": e.get("patent"), "doi": e.get("doi"), "dataset": e.get("dataset"),
                    "temp_c": t, "hours": h, "yield_pct": y, "anchor": anchor, "solvent": solv,
                    "solvents": sorted(set(e.get("solvents") or [])), "catalysts": e.get("catalysts") or [],
                    "reagents": e.get("reagents") or [], "reactants": reactants,
                    "needs": e.get("needs") or [], "hazards": e.get("hazards") or [],
                    "suggested_template": "second" if len(reactants) >= 2 else "first"})
    out.sort(key=lambda r: (not r["anchor"], -(r["yield_pct"] or 0)))
    return {"available": True, "found": True, "key": key, "name": m.get("name"), "smiles": m.get("smiles"),
            "routes": out, "anchors": sum(r["anchor"] for r in out), "licence": d.get("licence"),
            "molecules": molecules_with_routes()}


def molecules_with_routes() -> list[dict[str, Any]]:
    d = signals._load("ord")
    rows = []
    for k, m in (d.get("data") or {}).items():
        ex = m.get("examples") or []
        anchors = sum(1 for e in ex if isinstance(e.get("yield"), (int, float)) and 0 < e["yield"] <= 100
                      and e.get("temp_c") is not None and e.get("hours"))
        rows.append({"key": k, "name": m.get("name") or k, "routes": len(ex), "anchors": anchors})
    rows.sort(key=lambda r: (-r["anchors"], -r["routes"], r["name"]))
    return rows


def templates() -> dict[str, Any]:
    return {"templates": [{"id": k, "label": v["label"], "hint": v["hint"], "rxns": v["rxns"], "c0": v["c0"],
                           "limiting": v["limiting"], "target": v["target"], "impurities": v["impurities"]}
                          for k, v in reaction.TEMPLATES.items()],
            "engines": _engines()}


def _pharmapy(req: dict[str, Any]) -> dict[str, Any]:
    r = requests.post(f"{SIM_URL}/react", json=req, timeout=120)
    r.raise_for_status()
    res = r.json()
    t = np.asarray(res["time_h"], float)
    conc = np.column_stack([np.asarray(res["conc"][s], float) for s in req["species"]])
    return reaction._summarise(req, t, conc, None, engine="pharmapy")


def run(p: dict[str, Any]) -> dict[str, Any]:
    """Simulate; calibrate to an anchor if given; yield map, Ea band and acceptable range around the operating point."""
    req = reaction.build_request(p)
    notes: list[str] = []
    cal = None
    anchor = p.get("anchor")
    if anchor and all(anchor.get(k) is not None for k in ("temp_c", "hours", "yield_pct")):
        cal = reaction.calibrate(req, float(anchor["temp_c"]), float(anchor["hours"]), float(anchor["yield_pct"]))
        if cal["ok"]:
            req = {**req, "rxns": cal["rxns"], "temp_ref_c": cal["temp_ref_c"]}
        else:
            notes.append(cal["reason"])
    builtin = reaction.builtin(req)
    result, cross = builtin, None
    want = p.get("engine", "auto")
    isothermal = req["program"]["ramp_h"] <= 0 or req["program"]["t0_c"] == req["program"]["t1_c"]
    reversible = any("keq" in rx for rx in req["rxns"])
    if want in ("auto", "pharmapy") and SIM_URL and isothermal and not reversible:
        try:
            ph = _pharmapy(req)
            yb, yp = np.asarray(builtin["yield"]), np.interp(builtin["time_h"], ph["time_h"], ph["yield"])
            cross = {"max_yield_diff_pct": round(100 * float(np.max(np.abs(yb - yp))), 3),
                     "final_yield_builtin": builtin["summary"]["yield_pct"], "final_yield_pharmapy": ph["summary"]["yield_pct"]}
            result = ph
        except Exception as exc:
            notes.append(f"PharmaPy run failed ({exc.__class__.__name__}: {str(exc)[:160]}); showing the built-in engine.")
    elif want == "pharmapy":
        notes.append("PharmaPy runs isothermal, irreversible mechanisms here; this one ran in the built-in engine."
                     if SIM_URL else "PharmaPy sim service not configured (SIM_URL); built-in engine used.")
    t_op = req["program"]["t1_c"]
    temps = sorted({round(t_op + d) for d in range(-40, 45, 5)} | {round(t_op)})
    temps = [t for t in temps if -30 <= t <= 250]
    h_op = req["hours"]
    hours = sorted({round(h_op * f, 2) for f in (0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4)} | {h_op})
    ymap = reaction.yield_map(req, temps, hours)
    tg = p.get("targets") or {}
    min_y = float(tg.get("min_yield_pct", max(0.0, round(ymap["best"]["yield_pct"] - 5))))
    max_imp = tg.get("max_impurity_pct")
    max_imp = float(max_imp) if max_imp not in (None, "") else (0.5 if req["impurities"] else None)
    par = reaction.acceptable_range(ymap, min_y, max_imp)
    band = reaction.ea_band(req, temps, h_op, float(p.get("ea_delta", 15)))
    return {"request": req, "result": result, "calibration": cal, "cross_check": cross, "notes": notes,
            "map": ymap, "acceptable": {**par, "min_yield_pct": min_y, "max_impurity_pct": max_imp}, "ea_band": band,
            "assumptions": [
                "Well-mixed batch, constant volume; elementary rate laws (orders = stoichiometric coefficients)",
                "Arrhenius temperature dependence referenced at the operating / calibration temperature",
                ("Main rate constant calibrated to the published example (" + f"{anchor['yield_pct']:g}% at {anchor['temp_c']:g} °C, "
                 f"{anchor['hours']:g} h); side-reaction constants keep their ratio to it"
                 if cal and cal.get("ok") else "Rate constants as entered (not calibrated)"),
                "Activation energies are assumptions unless you have them — the band shows ±" + f"{p.get('ea_delta', 15)} kJ/mol",
                "Heat: the desired reaction's enthalpy on the unconverted limiting reagent (Stoessel accumulation)",
            ]}


def validation() -> dict[str, Any]:
    cases = reaction.validate()
    eng = _engines()
    cross = None
    if eng["pharmapy"]["available"]:
        req = reaction.build_request({"template": "consecutive", "temp_c": 80, "hours": 10})
        try:
            b = reaction.builtin(req)
            ph = _pharmapy(req)
            yp = np.interp(b["time_h"], ph["time_h"], ph["yield"])
            cross = {"case": "A → P → D, 80 °C, 10 h", "max_yield_diff_pct": round(100 * float(np.max(np.abs(np.asarray(b["yield"]) - yp))), 4),
                     "pass": bool(np.max(np.abs(np.asarray(b["yield"]) - yp)) < 0.005)}
        except Exception as exc:
            cross = {"case": "A → P → D, 80 °C, 10 h", "error": f"{exc.__class__.__name__}: {str(exc)[:200]}", "pass": False}
    return {"cases": cases, "passed": sum(c["pass"] for c in cases), "total": len(cases), "pharmapy": cross, "engines": eng}
