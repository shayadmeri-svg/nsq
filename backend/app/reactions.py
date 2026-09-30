"""Reaction lab: a synthesis step as a batch-reactor kinetic model, fitted to measured data.

Routes come from the Open Reaction Database scan (data/sources/ord.json): for each tracked molecule, the
patent / paper reactions that make it. Each record's atom-mapped reaction SMILES is checked (chem.rxn_smiles):
salt formations and isolations (no bond made) are flagged and never simulated; for real steps the partner
molecules come from the atom maps. The rate constant is fitted to every published point (temperature, time,
yield) of the same transformation — and Ea too when those span ≥ 10 °C — or to the user's own measurements.
Every input and headline output carries its basis: measured / fitted / within data / extrapolated / assumed.

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


AMBIENT_C = 22.0  # ORD "AMBIENT" temperature control with no set point: taken as 22 °C and flagged as such


def _patent_url(pat: Optional[str]) -> Optional[str]:
    if not pat:
        return None
    m = re.match(r"^([A-Z]{2})0*(\d+)([A-Z]\d?)?$", pat)
    return f"https://patents.google.com/patent/{m.group(1)}{m.group(2)}{m.group(3) or ''}" if m else None


def _source(e: dict[str, Any]) -> dict[str, Any]:
    return {"id": e["id"], "patent": e.get("patent"), "patent_url": _patent_url(e.get("patent")),
            "doi": e.get("doi"), "doi_url": f"https://doi.org/{e['doi']}" if e.get("doi") else None,
            "ord_url": f"https://open-reaction-database.org/client/id/{e['id']}", "dataset": e.get("dataset")}


def _example(e: dict[str, Any], target_smiles: Optional[str]) -> dict[str, Any]:
    from chem import rxn_smiles

    a = rxn_smiles.analyse(e.get("smiles"), target_smiles)
    y = e.get("yield")
    y = y if isinstance(y, (int, float)) and 0 < y <= 100 else None
    t, h = e.get("temp_c"), e.get("hours")
    temp_basis = "record" if t is not None else None
    if t is None and e.get("temp_control") == "AMBIENT":
        t, temp_basis = AMBIENT_C, "ambient"
    step = a["kind"] == "covalent"
    point = step and y is not None and t is not None and h is not None and 0 < h <= 200
    solv = next((s for s in (e.get("solvents") or []) if s and s.lower() != "mixture"), None)
    n = a.get("n_partners") or 0
    # name and recorded starting concentration of each partner, matched by structure (newer ORD scans carry them)
    c0_data, names = None, {}
    if step and a.get("partners"):
        from rdkit import Chem

        def plain(smi: Optional[str]) -> Optional[str]:
            m = Chem.MolFromSmiles(smi) if smi else None
            return rxn_smiles._plain(rxn_smiles._largest(m)) if m is not None else None

        comp = {plain(c.get("smiles")): c for c in e.get("components") or [] if c.get("smiles")}
        conc = {plain(k): v for k, v in ((e.get("c0") or {}).get("mol_l") or {}).items()}
        for pt in a["partners"]:
            if comp.get(pt["smiles"], {}).get("name"):
                names[pt["smiles"]] = comp[pt["smiles"]]["name"]
        top = a["partners"][:2] if n >= 2 else a["partners"][:1]
        vals = [conc.get(pt["smiles"]) for pt in top]
        if vals and all(v for v in vals):
            # the limiting partner is species A (the templates' limiting reagent)
            order = sorted(vals) if len(vals) == 2 else vals
            c0_data = {"A": order[0], **({"B": order[1]} if len(order) == 2 else {}),
                       "volume_ml": (e.get("c0") or {}).get("volume_ml")}
    for pt in a.get("partners") or []:
        pt["name"] = names.get(pt["smiles"])
    return {**_source(e), "c0_data": c0_data, "temp_c": t, "temp_basis": temp_basis, "hours": h, "yield_pct": y, "anchor": point,
            "synthesis": step, "step": a, "solvent": solv, "solvents": sorted(set(e.get("solvents") or [])),
            "catalysts": e.get("catalysts") or [], "reagents": e.get("reagents") or [],
            "reactants": [r for r in (e.get("reactants") or []) if r],
            "needs": e.get("needs") or [], "hazards": e.get("hazards") or [],
            # the template follows from how many molecules the atom mapping says end up in the product
            "suggested_template": "first" if n == 1 else "second",
            "template_basis": (f"atom mapping: {n} molecule(s) contribute atoms to the product" + (" (modelled as the two largest)" if n > 2 else ""))
            if step else None}


def routes(key: str) -> dict[str, Any]:
    """ORD reactions that make this molecule, each checked against its atom-mapped reaction SMILES: covalent steps
    with temperature, time and yield first; salt formations / isolations flagged (they are not kinetic steps)."""
    d = signals._load("ord")
    m = (d.get("data") or {}).get(key)
    if not m:
        return {"available": bool(d), "found": False, "molecules": molecules_with_routes()}
    out = [_example(e, m.get("smiles")) for e in m.get("examples") or []]
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in out:
        if r["anchor"]:
            groups.setdefault(r["step"]["group_key"], []).append(r)
    for r in out:  # how many published points share this exact transformation (same partner molecules)
        g = groups.get(r["step"].get("group_key") or "", [])
        r["same_reaction_points"] = len(g)
        r["same_reaction_temps"] = sorted({x["temp_c"] for x in g})
    out.sort(key=lambda r: (not r["anchor"], -len(r["same_reaction_temps"]), not r["synthesis"], -(r["yield_pct"] or 0)))
    return {"available": True, "found": True, "key": key, "name": m.get("name"), "smiles": m.get("smiles"),
            "routes": out, "anchors": sum(r["anchor"] for r in out),
            "not_steps": sum(1 for r in out if not r["synthesis"]), "licence": d.get("licence"),
            "molecules": molecules_with_routes()}


def points_for(key: str, route_id: str) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """Every published point (T, time, yield) of the same transformation as route_id."""
    r = routes(key)
    sel = next((x for x in r.get("routes") or [] if x["id"] == route_id), None)
    if not sel or not sel["anchor"]:
        return [], sel
    gk = sel["step"]["group_key"]
    pts = [{"temp_c": x["temp_c"], "hours": x["hours"], "value_pct": x["yield_pct"], "measure": "yield", "id": x["id"],
            "patent": x["patent"], "patent_url": x["patent_url"], "temp_basis": x["temp_basis"]}
           for x in r["routes"] if x["anchor"] and x["step"]["group_key"] == gk]
    return pts, sel


def molecules_with_routes() -> list[dict[str, Any]]:
    from chem import rxn_smiles

    d = signals._load("ord")
    key = (id(d),)
    if _mol_cache.get("key") == key:
        return _mol_cache["rows"]
    rows = []
    for k, m in (d.get("data") or {}).items():
        ex = [_example(e, m.get("smiles")) for e in m.get("examples") or []]
        steps = [e for e in ex if e["synthesis"]]
        if steps:  # molecules whose records are all salt formations / formulations have nothing to simulate
            rows.append({"key": k, "name": m.get("name") or k, "routes": len(steps), "anchors": sum(e["anchor"] for e in ex)})
    rows.sort(key=lambda r: (-r["anchors"], -r["routes"], r["name"]))
    _mol_cache.update(key=key, rows=rows)
    return rows


_mol_cache: dict[str, Any] = {}


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


def _pharmapy_check(req: dict[str, Any], builtin: dict[str, Any], notes: list[str], want: str):
    isothermal = req["program"]["ramp_h"] <= 0 or req["program"]["t0_c"] == req["program"]["t1_c"]
    reversible = any("keq" in rx for rx in req["rxns"])
    if want in ("auto", "pharmapy") and SIM_URL and isothermal and not reversible:
        try:
            ph = _pharmapy(req)
            yb, yp = np.asarray(builtin["yield"]), np.interp(builtin["time_h"], ph["time_h"], ph["yield"])
            return ph, {"max_yield_diff_pct": round(100 * float(np.max(np.abs(yb - yp))), 3),
                        "final_yield_builtin": builtin["summary"]["yield_pct"], "final_yield_pharmapy": ph["summary"]["yield_pct"]}
        except Exception as exc:
            notes.append(f"PharmaPy run failed ({exc.__class__.__name__}: {str(exc)[:160]}); showing the built-in engine.")
    elif want == "pharmapy":
        notes.append("PharmaPy runs isothermal, irreversible mechanisms here; this one ran in the built-in engine."
                     if SIM_URL else "PharmaPy sim service not configured (SIM_URL); built-in engine used.")
    return builtin, None


def _envelope(pts: list[dict[str, Any]], ea_fitted: bool) -> Optional[dict[str, float]]:
    if not pts:
        return None
    ts, hs = [float(p["temp_c"]) for p in pts], [float(p["hours"]) for p in pts]
    # without a fitted Ea only the measured temperature(s) are pinned by data
    return {"t_lo": min(ts) - (5 if ea_fitted else 2), "t_hi": max(ts) + (5 if ea_fitted else 2),
            "h_lo": 0.5 * min(hs), "h_hi": 2 * max(hs), "temps": sorted(set(ts)), "ea_fitted": ea_fitted}


def _cell(env: Optional[dict[str, Any]], t: float, h: float) -> str:
    """'i' = inside what the data pins, 'x' = extrapolated, 'a' = no data behind the model at all."""
    if env is None:
        return "a"
    if env["ea_fitted"]:
        inside = env["t_lo"] <= t <= env["t_hi"]
    else:
        inside = any(abs(t - x) <= 2 for x in env["temps"])
    return "i" if inside and env["h_lo"] <= h <= env["h_hi"] else "x"


def run(p: dict[str, Any]) -> dict[str, Any]:
    """Simulate one step. Rate constants come from data when there is data — the published examples of the same
    transformation (ORD) or the user's own measurements — and every input and output says where it comes from."""
    req = reaction.build_request(p)
    notes: list[str] = []
    tpl = reaction.TEMPLATES[req["template"]]

    # ---- data behind the rate constants: the user's measurements win over published examples
    lab = [x for x in (p.get("lab_points") or []) if isinstance(x, dict)]
    pts, route, src = [], None, None
    if p.get("route"):
        _pts, route = points_for(str(p["route"].get("key", "")), str(p["route"].get("id", "")))
    if lab:
        pts = [{"temp_c": float(x["temp_c"]), "hours": float(x["hours"]), "value_pct": float(x["value_pct"]),
                "measure": x.get("measure", "yield")} for x in lab
               if x.get("temp_c") not in (None, "") and x.get("hours") not in (None, "") and x.get("value_pct") not in (None, "")]
        src = "lab"
    elif route is not None:
        pts = _pts
        src = "published" if pts else None
    fitres = None
    if pts:
        fitres = reaction.fit(req, pts)
        if fitres.get("ok"):
            req = {**req, "rxns": fitres["rxns"], "temp_ref_c": fitres["temp_ref_c"]}
        else:
            notes.append(fitres["reason"])
            fitres = None
    ea_fitted = bool(fitres and "ea" in fitres["fitted"])
    env = _envelope(pts, ea_fitted) if fitres else None

    builtin = reaction.builtin(req)
    result, cross = _pharmapy_check(req, builtin, notes, p.get("engine", "auto"))

    # ---- temperature × time map; the window and the "best" only where data pins the model
    t_op, h_op = req["program"]["t1_c"], req["hours"]
    temps = sorted({round(t_op + d) for d in range(-40, 45, 5)} | {round(t_op)} | {round(x) for x in (env["temps"] if env else [])})
    temps = [t for t in temps if -30 <= t <= 250]
    hours = sorted({round(h_op * f, 2) for f in (0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4)} | {h_op})
    ymap = reaction.yield_map(req, temps, hours)
    cells = [[_cell(env, t, h) for h in hours] for t in temps]
    ymap["cell_basis"] = cells
    inside = np.array(cells) == "i"
    tg = p.get("targets") or {}
    if inside.any():
        arr = np.where(inside, np.array(ymap["yield_pct"]), -1)
        i, j = np.unravel_index(int(np.argmax(arr)), arr.shape)
        ymap["best"] = {"temp_c": temps[i], "hours": hours[j], "yield_pct": float(arr[i, j]), "within_data": True}
    else:
        ymap["best"] = None
    min_y = float(tg.get("min_yield_pct") or max(0.0, round((ymap["best"] or {"yield_pct": 0})["yield_pct"] - 5)))
    max_imp = tg.get("max_impurity_pct")
    max_imp = float(max_imp) if max_imp not in (None, "") else (0.5 if req["impurities"] else None)
    par = reaction.acceptable_range({**ymap, "yield_pct": np.where(inside, np.array(ymap["yield_pct"]), -1).tolist()}, min_y, max_imp) \
        if inside.any() else {"ok": np.zeros_like(inside, dtype=int).tolist(), "share_pct": 0.0, "widest": None,
                              "reason": "no part of the map is pinned by data — needs measured points"
                                        + ("" if ea_fitted or not fitres else " at a second temperature (≥ 10 °C apart) to fit Ea")}
    ci_ea = (fitres.get("ci95") or {}).get("ea") if fitres else None
    band = reaction.ea_band(req, temps, h_op, round((ci_ea[1] - ci_ea[0]) / 2, 1) if ci_ea else float(p.get("ea_delta", 15)))
    band["from_ci"] = bool(ci_ea)
    if ea_fitted and not (25 <= fitres["ea"] <= 150):
        notes.append(f"Fitted Ea = {fitres['ea']:.0f} kJ/mol is outside the usual 25–150 kJ/mol for solution reactions: the points "
                     "probably differ in more than temperature (work-up losses, concentration, catalyst loading). Treat the temperature trend with caution.")

    # ---- provenance of every input and of the headline numbers
    src_list = [{k: x.get(k) for k in ("id", "patent", "patent_url", "temp_c", "hours", "value_pct", "temp_basis")} for x in pts] if src == "published" else []
    basis = {
        "mechanism": {"kind": "data" if route and route.get("template_basis") and route.get("suggested_template") == req["template"] else "chosen",
                      "text": (route or {}).get("template_basis") or "chosen by you",
                      "rate_law": "assumed elementary (order = stoichiometry)"},
        "k": ({"kind": "fitted", "n": fitres["n"], "source": src, "ci95": (fitres.get("ci95") or {}).get("k_ref"),
               "rmse_pct": fitres["rmse_pct"], "note": fitres.get("note")} if fitres else
              {"kind": "entered" if p.get("k_entered") else "assumed", "text": "template default" if not p.get("k_entered") else "entered by you"}),
        "ea": ({"kind": "fitted", "ci95": (fitres.get("ci95") or {}).get("ea")} if ea_fitted else
               {"kind": "entered" if p.get("ea_entered") else "assumed",
                "text": ("entered by you" if p.get("ea_entered") else f"typical value, not measured — needs points at two temperatures")}),
        "side": {"kind": "assumed", "text": "side-reaction rate constants and Ea are template values, scaled with the main k"} if req["impurities"] else None,
        "c0": ({"kind": "entered", "text": "entered by you"} if p.get("c0_entered") else
               {"kind": "data", "text": "from the amounts and volumes recorded for this reaction"} if p.get("c0_source") == "record" else
               {"kind": "assumed", "text": "1 M-scale defaults (this record has no amounts); a second-order k is only valid at these concentrations"}),
        "dh": {"kind": "entered", "value": req["rxns"][0]["dh"]} if req["rxns"][0]["dh"] is not None else {"kind": "missing", "text": "enter ΔH from reaction calorimetry (RC1) or DSC"},
        "solvent": {"kind": "source" if p.get("solvent_source") else ("entered" if p.get("solvent_entered") else "assumed"), "text": p.get("solvent_source") or ""},
        "yield_is_isolated": src == "published",
    }
    op_cell = _cell(env, t_op, h_op)
    measured = next((x for x in pts if abs(float(x["temp_c"]) - t_op) <= 1 and abs(float(x["hours"]) - h_op) <= 0.05 * h_op), None)
    basis["operating"] = {"kind": "measured" if measured else {"i": "interpolated", "x": "extrapolated", "a": "assumed"}[op_cell],
                          "measured_pct": measured["value_pct"] if measured else None}
    assumptions = [
        "Well-mixed batch, constant volume; elementary rate laws (orders = stoichiometric coefficients)",
        ("Rate constant fitted to " + (f"{fitres['n']} of your measured points" if src == "lab" else f"{fitres['n']} published example(s) of this transformation")
         + (f" at {len(env['temps'])} temperatures (Ea fitted too)" if ea_fitted else "; Ea not fitted (one temperature)") if fitres
         else "No data behind the rate constants: every number is illustrative"),
        *(["Published yields are isolated yields (after work-up), so the fitted rate is a lower bound"] if src == "published" else []),
        *(["Examples from different patents differ in solvent and concentration: their scatter is part of the fit's error"]
          if src == "published" and len({x.get("patent") for x in pts}) > 1 else []),
        *(["An ORD 'ambient' temperature is taken as 22 °C"] if any(x.get("temp_basis") == "ambient" for x in pts) else []),
        "Heat and thermal safety only from an entered reaction enthalpy (none is assumed)",
    ]
    return {"request": req, "result": result, "fit": fitres, "points": pts, "sources": src_list, "data_source": src,
            "cross_check": cross, "notes": notes, "basis": basis, "map": ymap,
            "acceptable": {**par, "min_yield_pct": min_y, "max_impurity_pct": max_imp}, "ea_band": band,
            "envelope": env, "assumptions": assumptions, "template": {k: tpl[k] for k in ("label", "hint")}}


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
