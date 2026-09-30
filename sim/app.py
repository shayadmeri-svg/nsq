"""PharmaPy sidecar: runs Purdue's PharmaPy crystalliser for the lab.

Separate container because PharmaPy needs assimulo (SUNDIALS) and numpy<2.
The API sends the same request it gives its built-in engine (core/chem/crystallization.py):
a solubility curve computed from the molecule, a cooling programme and kinetics.
"""
from __future__ import annotations

import json
import os
import tempfile
import traceback
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException

app = FastAPI(title="NSQ sim (PharmaPy)")

try:
    from PharmaPy.Reactors import BatchReactor
    from PharmaPy.Kinetics import RxnKinetics
except Exception:  # the crystalliser can still work; /react reports it
    BatchReactor = RxnKinetics = None

try:
    from PharmaPy.Crystallizers import BatchCryst
    from PharmaPy.Interpolation import PiecewiseLagrange
    from PharmaPy.Kinetics import CrystKinetics
    from PharmaPy.Phases import LiquidPhase, SolidPhase
    from PharmaPy.Utilities import CoolingWater
    IMPORT_ERROR = None
except Exception as exc:  # the health check reports it
    IMPORT_ERROR = f"{exc.__class__.__name__}: {exc}"

DEFAULT_KINETICS = {"prim": [3e8, 0.0, 3.0], "sec": [4.46e10, 0.0, 2.0, 1e-5], "growth": [5.0, 0.0, 1.32], "dissol": [1.0, 0.0, 1.0]}
# Property template (PharmaPy's own example compound). Only molar mass and densities are
# molecule-specific here; the temperature follows the programme, so heat capacities,
# viscosity and vapour pressure do not affect the result.
_TEMPLATE = {"t_crit": 540.2, "p_crit": 5190, "mol_vol": 0.0811, "cp_liq": [63.393, 0.40257, -0.0012686, 1.8275e-06, 0],
             "cp_solid": [1600], "visc_liq": [-0.011485634166334, 0, 0, 0], "p_vap": [9.23027, 1256.68, -40.529],
             "delta_hvap": 32300, "tref_hvap": 305, "surf_tension": 0.0264}


@app.get("/health")
def health() -> dict[str, Any]:
    ver = None
    try:
        from importlib.metadata import version
        ver = version("PharmaPy")
    except Exception:
        pass
    return {"ok": True, "pharmapy": IMPORT_ERROR is None, "version": ver, "error": IMPORT_ERROR}


@app.post("/crystallize")
def crystallize(req: dict[str, Any]) -> dict[str, Any]:
    if IMPORT_ERROR:
        raise HTTPException(503, IMPORT_ERROR)
    try:
        return _run(req)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"{exc.__class__.__name__}: {exc}")


def _run(req: dict[str, Any]) -> dict[str, Any]:
    curve, prog = req["curve"], req["program"]
    kin = {**DEFAULT_KINETICS, **(req.get("kinetics") or {})}
    temps_c = np.asarray(curve["temps_c"], float)
    logs = np.log(np.maximum(np.asarray(curve["kg_m3"], float), 1e-12))
    solub = lambda temp, conc=None: np.exp(np.interp(np.asarray(temp, float) - 273.15, temps_c, logs))
    sv = req["solvent"]
    db = {"API": {**_TEMPLATE, "mw": req["api"]["mw"], "rho_liq": req.get("rho_solid", 1300), "rho_solid": req.get("rho_solid", 1300)},
          "solvent": {**_TEMPLATE, "mw": sv["mw"], "rho_liq": sv["rho_25"], "rho_solid": sv["rho_25"]}}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "compounds.json")
        with open(path, "w") as fh:
            json.dump(db, fh)
        t0k, t1k = prog["t0_c"] + 273.15, prog["t1_c"] + 273.15
        cool_s, hold_s = prog["cool_min"] * 60, max(prog.get("hold_min", 0), 1) * 60
        lagr = PiecewiseLagrange(cool_s + hold_s, np.array([[t0k, t1k], [t1k, t1k]]), time_k=[0, cool_s, cool_s + hold_s])
        cr = BatchCryst(target_comp="API", method="1D-FVM", scale=1e-9, controls={"temp": lagr.evaluate_poly})
        cr.Kinetics = CrystKinetics(None, solub_fn=solub, nucl_prim=tuple(kin["prim"]), nucl_sec=tuple(kin["sec"]),
                                    growth=tuple(kin["growth"]), dissolution=tuple(kin["dissol"]))
        vol = float(req.get("volume_l", 1.0)) / 1000
        c0 = float(solub(t0k))
        liq = LiquidPhase(path, temp=t0k, vol=vol, mass_conc=np.array([c0, 0.0]), name_solv="solvent", verbose=False)
        x = np.geomspace(1, 1500, 35)
        sol = SolidPhase(path, x_distrib=x, distrib=np.zeros_like(x), mass_frac=[1, 0])
        cr.Utility = CoolingWater(mass_flow=1, temp_in=max(t1k - 5, 274.15))
        cr.Phases = (liq, sol)
        cr.solve_unit(runtime=cool_s + hold_s, sundials_opts={"maxh": 60}, verbose=False)
        res = cr.result
    t = np.asarray(res.time, float)
    temp = np.asarray(res.temp, float) - 273.15
    conc = np.asarray(res.mass_conc)
    conc = conc[:, 0] if conc.ndim == 2 else conc
    sat = np.asarray(res.solubility, float)
    distrib = np.asarray(res.distrib)[-1]
    xg = np.asarray(getattr(res, "x_cryst", x), float)
    dx = np.gradient(xg)
    m3 = distrib * xg ** 3 * dx
    l43 = float((distrib * xg ** 4 * dx).sum() / m3.sum()) if m3.sum() > 0 else 0.0
    n = (distrib * dx).sum()
    mean = float((distrib * xg * dx).sum() / n) if n > 0 else 0.0
    cv = float(np.sqrt(max((distrib * xg ** 2 * dx).sum() / n - mean ** 2, 0)) / mean) if mean > 0 else None
    idx = np.linspace(0, len(t) - 1, min(len(t), 121)).astype(int)
    sigma = (conc - sat) / sat
    return {
        "engine": "pharmapy",
        "time_min": (t[idx] / 60).round(2).tolist(), "temp_c": temp[idx].round(2).tolist(),
        "conc_kg_m3": [float(f"{v:.5g}") for v in conc[idx]], "sat_kg_m3": [float(f"{v:.5g}") for v in sat[idx]],
        "supersat": sigma[idx].round(4).tolist(),
        "distribution": {"x_um": xg.round(2).tolist(), "vol_pct": (100 * m3 / m3.sum()).round(3).tolist() if m3.sum() > 0 else []},
        "summary": {"yield_pct": round(100 * (conc[0] - conc[-1]) / conc[0], 1), "max_yield_pct": round(100 * (c0 - float(solub(t1k))) / c0, 1),
                    "l43_um": round(l43, 1), "mean_um": round(mean, 1), "cv": round(cv, 2) if cv else None,
                    "peak_supersat": round(float(sigma.max()), 3)},
        "assumptions": ["PharmaPy BatchCryst, 1-D finite-volume population balance (35 size classes, 1–1500 µm), unseeded",
                        "Kinetics: PharmaPy example constants (generic compound), not fitted to this molecule" if not req.get("kinetics") else "Kinetics: user-supplied",
                        "Temperature follows the programme exactly (energy balance not used)"],
    }


# --- batch reactor --------------------------------------------------------------------------------------

def _side(d: dict[str, float]) -> str:
    return " + ".join(s if v == 1 else f"{v:g} {s}" for s, v in d.items())


@app.post("/react")
def react(req: dict[str, Any]) -> dict[str, Any]:
    """The same request the API gives its built-in engine (core/chem/reaction.py): isothermal batch, elementary
    kinetics. PharmaPy works in seconds and J/mol; the request is in hours and kJ/mol."""
    if IMPORT_ERROR or BatchReactor is None:
        raise HTTPException(503, IMPORT_ERROR or "PharmaPy.Reactors not importable")
    if any("keq" in rx for rx in req["rxns"]):
        raise HTTPException(422, "reversible reactions run in the built-in engine")
    try:
        return _react(req)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"{exc.__class__.__name__}: {exc}")


def _react(req: dict[str, Any]) -> dict[str, Any]:
    species = list(req["species"])
    db = {s: {**_TEMPLATE, "mw": 100.0, "rho_liq": 1000.0, "rho_solid": 1000.0} for s in species}
    db["solvent"] = {**_TEMPLATE, "mw": 78.0, "rho_liq": 1000.0 * float(req.get("rho_kg_l", 0.9)), "rho_solid": 1000.0}
    rxn_list = [f"{_side(rx['r'])} --> {_side(rx['p'])}" for rx in req["rxns"]]
    k = np.array([rx["k"] / 3600.0 for rx in req["rxns"]])  # 1/h -> 1/s (L/mol/h -> L/mol/s)
    ea = np.array([rx["ea"] * 1000.0 for rx in req["rxns"]])  # kJ/mol -> J/mol
    temp_k = float(req["program"]["t1_c"]) + 273.15
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "compounds.json")
        with open(path, "w") as fh:
            json.dump(db, fh)
        kin = RxnKinetics(path=path, rxn_list=rxn_list, k_params=k, ea_params=ea,
                          temp_ref=float(req["temp_ref_c"]) + 273.15)
        c0 = np.array([float(req["c0"].get(s, 0.0)) for s in species] + [0.0])
        liq = LiquidPhase(path, temp=temp_k, mole_conc=c0, vol=float(req.get("volume_l", 1.0)) / 1000, name_solv="solvent",
                          verbose=False)
        rx = BatchReactor(isothermal=True)
        rx.Utility = CoolingWater(mass_flow=0.01, temp_in=temp_k)  # results post-processing evaluates the heat balance
        rx.Phases = liq
        rx.Kinetics = kin
        runtime = float(req["hours"]) * 3600.0
        rx.solve_unit(runtime=runtime, time_grid=np.linspace(0, runtime, 121), verbose=False)
        res = rx.result
    t = np.asarray(res.time, float) / 3600.0
    mc = np.atleast_2d(np.asarray(res.mole_conc, float))
    if mc.shape[0] != len(t) and mc.shape[1] == len(t):
        mc = mc.T
    names = list(getattr(rx, "name_species", species + ["solvent"]))
    conc = {}
    for i, s in enumerate(species):
        j = names.index(s) if s in names and len(names) == mc.shape[1] else i
        conc[s] = [float(f"{v:.6g}") for v in mc[:, j]]
    return {"engine": "pharmapy", "time_h": np.round(t, 4).tolist(), "conc": conc,
            "rxn_list": rxn_list, "version": health().get("version")}
