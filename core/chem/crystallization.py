"""Batch cooling crystallisation.

Two engines share one request format:
  * "pharmapy": the PharmaPy BatchCryst model (1-D finite-volume population
    balance, Purdue), run in the separate sim service (sim/app.py).
  * "builtin": the method of moments below, with the same kinetic rate laws as
    PharmaPy's CrystKinetics so results are comparable when the sidecar is off.

Rate laws (PharmaPy form): rate = k·exp(−E/RT)·σ^n with relative
supersaturation σ = (c − c*)/c*; secondary nucleation also multiplied by
(k_v·μ3)^s2. The default kinetic constants are PharmaPy's own example values
for a generic compound: they illustrate behaviour and are not fitted to any
molecule. Fitting them needs lab data (PharmaPy's ParamEstim does this).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.integrate import solve_ivp

from .thermo_props import interp

R = 8.314
KV = math.pi / 6  # volume shape factor (spheres)

DEFAULT_KINETICS = {
    "prim": [3e8, 0.0, 3.0],          # k (#/m3/s), E (J/mol), b
    "sec": [4.46e10, 0.0, 2.0, 1e-5],  # k, E, s1, s2
    "growth": [5.0, 0.0, 1.32],        # k (µm/s), E, g
    "dissol": [1.0, 0.0, 1.0],
}


def temperature(t_s: np.ndarray | float, p: dict[str, float]) -> np.ndarray:
    """Linear cool from t0 to t1 over cool_min, then hold (°C)."""
    t = np.asarray(t_s, dtype=float) / 60
    frac = np.clip(t / max(p["cool_min"], 1e-6), 0, 1)
    return p["t0_c"] + (p["t1_c"] - p["t0_c"]) * frac


def builtin(req: dict[str, Any]) -> dict[str, Any]:
    curve = req["curve"]
    prog = req["program"]
    kin = {**DEFAULT_KINETICS, **(req.get("kinetics") or {})}
    rho_c = float(req.get("rho_solid", 1300.0))
    t_total = (prog["cool_min"] + prog.get("hold_min", 0)) * 60
    sol = lambda tc: float(interp(curve["temps_c"], curve["kg_m3"], tc + 273.15))
    c0 = sol(prog["t0_c"]) * (1 + float(req.get("initial_supersat", 0.0)))
    # seeds: mass loading % of dissolved API, monodisperse at seed_um
    seed_frac = float(req.get("seed_pct", 0.0)) / 100
    seed_l = float(req.get("seed_um", 50.0)) * 1e-6
    n_seed = seed_frac * c0 / (rho_c * KV * seed_l ** 3) if seed_frac > 0 else 0.0
    mu0 = [n_seed, n_seed * seed_l, n_seed * seed_l ** 2, n_seed * seed_l ** 3, n_seed * seed_l ** 4]

    kp, ep, bexp = kin["prim"]
    ks, es, s1, s2 = kin["sec"]
    kg, eg, gexp = kin["growth"]

    def rhs(t, y):
        c, m0, m1, m2, m3, m4 = y
        tc = float(temperature(t, prog))
        tk = tc + 273.15
        cs = sol(tc)
        sigma = (c - cs) / cs
        if sigma > 0:
            b_p = kp * math.exp(-ep / (R * tk)) * sigma ** bexp
            b_s = ks * math.exp(-es / (R * tk)) * sigma ** s1 * max(KV * m3, 0) ** s2
            g = kg * 1e-6 * math.exp(-eg / (R * tk)) * sigma ** gexp  # m/s
        else:
            b_p = b_s = g = 0.0
        b = b_p + b_s
        return [-rho_c * KV * 3 * g * m2, b, g * m0, 2 * g * m1, 3 * g * m2, 4 * g * m3]

    t_eval = np.linspace(0, t_total, 121)
    out = solve_ivp(rhs, (0, t_total), [c0, *mu0], t_eval=t_eval, method="LSODA", rtol=1e-6, atol=[1e-8, 1, 1e-6, 1e-12, 1e-18, 1e-24])
    c, m0, m1, m2, m3, m4 = out.y
    temps = temperature(out.t, prog)
    cs = np.array([sol(x) for x in temps])
    return _summary(out.t, temps, c, cs, m0, m1, m2, m3, m4, c0, sol(prog["t1_c"]), rho_c, "builtin",
                    ["Method of moments (μ0–μ4), size-independent growth, no agglomeration or breakage",
                     "Kinetics: PharmaPy example constants (generic compound), not fitted to this molecule"
                     if not req.get("kinetics") else "Kinetics: user-supplied constants"])


def _summary(t, temps, c, cs, m0, m1, m2, m3, m4, c0, cs_end, rho_c, engine, assumptions) -> dict[str, Any]:
    safe = np.where(m3 > 0, m3, np.nan)
    l43 = np.nan_to_num(m4 / safe * 1e6)
    lmean = np.nan_to_num(m1 / np.where(m0 > 0, m0, np.nan) * 1e6)
    var = np.nan_to_num(m2 / np.where(m0 > 0, m0, np.nan) - (m1 / np.where(m0 > 0, m0, np.nan)) ** 2)
    cv = float(np.sqrt(max(var[-1], 0)) * 1e6 / lmean[-1]) if lmean[-1] > 0 else None
    yield_pct = 100 * (c0 - c[-1]) / c0 if c0 > 0 else 0.0
    max_yield = 100 * (c0 - cs_end) / c0 if c0 > 0 else 0.0
    sigma = (c - cs) / cs
    return {
        "engine": engine,
        "time_min": (np.asarray(t) / 60).round(2).tolist(),
        "temp_c": np.round(temps, 2).tolist(),
        "conc_kg_m3": [float(f"{x:.5g}") for x in c],
        "sat_kg_m3": [float(f"{x:.5g}") for x in cs],
        "supersat": np.round(sigma, 4).tolist(),
        "l43_um": np.round(l43, 2).tolist(),
        "summary": {
            "yield_pct": round(yield_pct, 1), "max_yield_pct": round(max_yield, 1),
            "l43_um": round(float(l43[-1]), 1), "mean_um": round(float(lmean[-1]), 1), "cv": round(cv, 2) if cv else None,
            "number_per_m3": float(f"{m0[-1]:.3g}"), "peak_supersat": round(float(np.max(sigma)), 3),
            "solid_kg_m3": round(float(rho_c * KV * m3[-1]), 3),
        },
        "assumptions": assumptions,
    }
