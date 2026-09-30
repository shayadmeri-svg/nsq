"""Batch reaction engine: kinetics, yield, selectivity, heat release and thermal safety.

One request format, two engines (like crystallization.py):
  * "builtin": the ODE system below, integrated with SciPy (Radau, stiff-safe, tight tolerances);
  * "pharmapy": PharmaPy's BatchReactor + RxnKinetics (Purdue), run in the sim sidecar (sim/app.py).

Model
-----
Species concentrations c_j (mol/L) in a well-mixed batch of constant volume. Reaction i has rate

    r_i = k_i(T) · Π_j c_j^a_ij          (a_ij = the reactant's stoichiometric coefficient: elementary)
    k_i(T) = k_ref,i · exp[−(Ea_i/R)·(1/T − 1/T_ref)]      (Arrhenius, referenced at T_ref)

and a reversible reaction subtracts k_i(T)/K_i · Π products. dc_j/dt = Σ_i ν_ij r_i. Time is in hours,
so k_ref is in 1/h (first order) or L/(mol·h) (second order).

Heat: q = Σ_i (−ΔH_i) r_i  [kJ/(L·h)]; the adiabatic temperature rise of what has not yet reacted is
ΔT_ad,acc(t) = Σ_i (−ΔH_i)·ξ_i,remaining / (ρ·cp). Stoessel's thermal-safety method compares
MTSR = T_process + max ΔT_ad,acc  with the solvent's boiling point (MTT) and, when known, TD24
(the temperature at which a decomposition reaches its maximum rate in 24 h).

Calibration: a published outcome (the ORD/patent example's temperature, time and yield) fixes the main
reaction's rate constant for an assumed activation energy; everything else is then prediction, and the
yield map shows how far a different temperature or time moves it. Change Ea to see how much the
prediction rests on it.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

R = 8.314462618e-3  # kJ/(mol·K)

# Mechanism templates: the shapes process chemists meet every day. Species letters are placeholders the UI names.
TEMPLATES: dict[str, dict[str, Any]] = {
    "first": {
        "label": "A → P", "hint": "Single first-order step (cyclisation, deprotection, rearrangement)",
        "rxns": [{"r": {"A": 1}, "p": {"P": 1}, "k": 0.5, "ea": 70, "dh": -60}],
        "c0": {"A": 1.0}, "limiting": "A", "target": "P", "impurities": [],
    },
    "second": {
        "label": "A + B → P", "hint": "Bimolecular coupling (amidation, N-alkylation, SNAr)",
        "rxns": [{"r": {"A": 1, "B": 1}, "p": {"P": 1}, "k": 0.8, "ea": 60, "dh": -90}],
        "c0": {"A": 1.0, "B": 1.2}, "limiting": "A", "target": "P", "impurities": [],
    },
    "consecutive": {
        "label": "A → P → D", "hint": "Product degrades if held too long or too hot (over-reaction, hydrolysis)",
        "rxns": [{"r": {"A": 1}, "p": {"P": 1}, "k": 0.6, "ea": 65, "dh": -70},
                 {"r": {"P": 1}, "p": {"D": 1}, "k": 0.03, "ea": 95, "dh": -30}],
        "c0": {"A": 1.0}, "limiting": "A", "target": "P", "impurities": ["D"],
    },
    "parallel": {
        "label": "A + B → P,  A + B → S", "hint": "Competing by-product with a different activation energy (regio-isomer)",
        "rxns": [{"r": {"A": 1, "B": 1}, "p": {"P": 1}, "k": 0.8, "ea": 55, "dh": -80},
                 {"r": {"A": 1, "B": 1}, "p": {"S": 1}, "k": 0.05, "ea": 85, "dh": -80}],
        "c0": {"A": 1.0, "B": 1.1}, "limiting": "A", "target": "P", "impurities": ["S"],
    },
    "comp_consec": {
        "label": "A + B → P,  P + B → S", "hint": "Over-alkylation / bis-adduct: excess reagent eats the product",
        "rxns": [{"r": {"A": 1, "B": 1}, "p": {"P": 1}, "k": 1.0, "ea": 60, "dh": -85},
                 {"r": {"P": 1, "B": 1}, "p": {"S": 1}, "k": 0.08, "ea": 70, "dh": -85}],
        "c0": {"A": 1.0, "B": 1.3}, "limiting": "A", "target": "P", "impurities": ["S"],
    },
    "reversible": {
        "label": "A ⇌ P", "hint": "Equilibrium-limited (esterification, epimerisation)",
        "rxns": [{"r": {"A": 1}, "p": {"P": 1}, "k": 0.4, "ea": 60, "dh": -20, "keq": 9.0}],
        "c0": {"A": 1.0}, "limiting": "A", "target": "P", "impurities": [],
    },
}


# --------------------------------------------------------------------------- request

def build_request(p: dict[str, Any]) -> dict[str, Any]:
    """A complete, explicit request from a template name plus overrides — the same dict goes to either engine."""
    tpl = TEMPLATES[p.get("template", "consecutive")]
    rxns = []
    over = p.get("rxns") or []
    for i, base in enumerate(tpl["rxns"]):
        o = over[i] if i < len(over) and isinstance(over[i], dict) else {}
        rx = {"r": dict(base["r"]), "p": dict(base["p"]),
              "k": float(o.get("k", base["k"])), "ea": float(o.get("ea", base["ea"])), "dh": float(o.get("dh", base["dh"]))}
        if "keq" in base:
            rx["keq"] = float(o.get("keq", base["keq"]))
        rxns.append(rx)
    species = sorted({s for rx in rxns for s in (*rx["r"], *rx["p"])}, key=lambda s: "ABPDS".find(s) if s in "ABPDS" else 9)
    c0 = {s: float((p.get("c0") or {}).get(s, tpl["c0"].get(s, 0.0))) for s in species}
    t_c = float(p.get("temp_c", 60))
    return {
        "template": p.get("template", "consecutive"), "species": species, "rxns": rxns, "c0": c0,
        "limiting": tpl["limiting"], "target": tpl["target"], "impurities": tpl["impurities"],
        "temp_ref_c": float(p.get("temp_ref_c", t_c)),
        "program": {"t0_c": float(p.get("t0_c", t_c)), "t1_c": t_c, "ramp_h": float(p.get("ramp_h", 0.0))},
        "hours": float(p.get("hours", 6.0)),
        "rho_kg_l": float(p.get("rho_kg_l", 0.9)), "cp_kj_kg_k": float(p.get("cp_kj_kg_k", 1.9)),
        "bp_c": None if p.get("bp_c") in (None, "") else float(p["bp_c"]),
        "td24_c": None if p.get("td24_c") in (None, "") else float(p["td24_c"]),
        "volume_l": float(p.get("volume_l", 1.0)),
    }


def temp_at(t_h: np.ndarray | float, prog: dict[str, float]) -> np.ndarray:
    """°C: linear ramp from t0 to t1 over ramp_h, then hold."""
    t = np.asarray(t_h, dtype=float)
    frac = np.clip(t / prog["ramp_h"], 0, 1) if prog["ramp_h"] > 0 else np.ones_like(t)
    return prog["t0_c"] + (prog["t1_c"] - prog["t0_c"]) * frac


def k_of(rx: dict[str, Any], temp_c: float | np.ndarray, temp_ref_c: float) -> np.ndarray:
    return rx["k"] * np.exp(-(rx["ea"] / R) * (1 / (np.asarray(temp_c) + 273.15) - 1 / (temp_ref_c + 273.15)))


def _matrices(req: dict[str, Any]):
    sp = req["species"]
    idx = {s: i for i, s in enumerate(sp)}
    n = len(req["rxns"])
    nu = np.zeros((n, len(sp)))
    order_f = np.zeros((n, len(sp)))
    order_b = np.zeros((n, len(sp)))
    for i, rx in enumerate(req["rxns"]):
        for s, v in rx["r"].items():
            nu[i, idx[s]] -= v
            order_f[i, idx[s]] = v
        for s, v in rx["p"].items():
            nu[i, idx[s]] += v
            order_b[i, idx[s]] = v
    return idx, nu, order_f, order_b


def rates(req: dict[str, Any], c: np.ndarray, temp_c: float) -> np.ndarray:
    _, _, of, ob = _matrices(req)
    cp = np.maximum(c, 0.0)
    out = np.empty(len(req["rxns"]))
    for i, rx in enumerate(req["rxns"]):
        k = float(k_of(rx, temp_c, req["temp_ref_c"]))
        fwd = k * np.prod(cp ** of[i])
        if "keq" in rx:
            fwd -= k / rx["keq"] * np.prod(cp ** ob[i])
        out[i] = fwd
    return out


# --------------------------------------------------------------------------- built-in engine

def builtin(req: dict[str, Any], n_out: int = 121, fast: bool = False) -> dict[str, Any]:
    idx, nu, of, ob = _matrices(req)
    sp = req["species"]
    c0 = np.array([req["c0"].get(s, 0.0) for s in sp])
    kref = np.array([rx["k"] for rx in req["rxns"]])
    ea = np.array([rx["ea"] for rx in req["rxns"]])
    keq = np.array([rx.get("keq", np.inf) for rx in req["rxns"]])
    tref = req["temp_ref_c"] + 273.15
    prog = req["program"]
    # extents are integrated alongside the concentrations: exact bookkeeping of heat released per reaction
    n_r = len(req["rxns"])

    def f(t, y):
        c = np.maximum(y[: len(sp)], 0.0)
        tk = float(temp_at(t, prog)) + 273.15
        k = kref * np.exp(-(ea / R) * (1 / tk - 1 / tref))
        r = k * np.prod(c ** of, axis=1) - np.where(np.isfinite(keq), k / keq, 0.0) * np.prod(c ** ob, axis=1)
        return np.concatenate([r @ nu, r])

    t_eval = np.linspace(0, req["hours"], n_out)
    # fast: for maps and calibration sweeps (isothermal, smooth) — LSODA at rtol 1e-7 is ~20× quicker and agrees
    # with the tight run to better than 0.01 percentage points of yield
    opts = dict(method="LSODA", rtol=1e-7, atol=1e-10) if fast else dict(method="Radau", rtol=1e-9, atol=1e-12,
                                                                          max_step=max(req["hours"] / 200, 1e-3))
    sol = solve_ivp(f, (0, req["hours"]), np.concatenate([c0, np.zeros(n_r)]), t_eval=t_eval, **opts)
    if not sol.success:
        raise RuntimeError(f"integration failed: {sol.message}")
    return _summarise(req, sol.t, sol.y[: len(sp)].T, sol.y[len(sp):].T, engine="builtin")


def _summarise(req: dict[str, Any], t: np.ndarray, conc: np.ndarray, extents: Optional[np.ndarray], engine: str) -> dict[str, Any]:
    sp = req["species"]
    idx = {s: i for i, s in enumerate(sp)}
    lim, tgt = req["limiting"], req["target"]
    a0 = req["c0"][lim]
    temp = temp_at(t, req["program"])
    conv = 1 - conc[:, idx[lim]] / a0
    yld = conc[:, idx[tgt]] / a0
    imp = {s: conc[:, idx[s]] / a0 for s in req["impurities"] if s in idx}
    dh = np.array([rx["dh"] for rx in req["rxns"]])
    rho_cp = req["rho_kg_l"] * req["cp_kj_kg_k"]  # kJ/(L·K)
    if extents is None:  # PharmaPy gives concentrations only: recover extents from the stoichiometry (least squares)
        _, nu, _, _ = _matrices(req)
        extents = np.linalg.lstsq(nu.T, (conc - conc[0]).T, rcond=None)[0].T
    released = -(extents * dh).sum(axis=1)  # kJ/L released so far, all reactions
    # Stoessel: the heat still stored is that of the desired reaction on the unconverted limiting reagent
    rx0 = req["rxns"][0]
    heat_total = float(-rx0["dh"] * a0 / rx0["r"].get(lim, 1))  # kJ/L
    acc = heat_total * (1 - conv) / rho_cp  # K
    q = np.gradient(released, t) if len(t) > 1 else np.zeros_like(t)  # kJ/(L·h)
    mtsr = float(np.max(temp + acc))
    i95 = next((i for i, x in enumerate(conv) if x >= 0.95), None)
    ipk = int(np.argmax(yld))
    sel = float(yld[-1] / conv[-1]) if conv[-1] > 1e-9 else None
    return {
        "engine": engine,
        "time_h": np.round(t, 4).tolist(), "temp_c": np.round(temp, 2).tolist(),
        "conc": {s: [float(f"{v:.6g}") for v in conc[:, idx[s]]] for s in sp},
        "conversion": np.round(conv, 5).tolist(), "yield": np.round(yld, 5).tolist(),
        "impurities": {s: np.round(v, 5).tolist() for s, v in imp.items()},
        "heat_kw_per_l": np.round(q / 3600, 6).tolist(),  # kJ/(L·h) → kW/L
        "acc_k": np.round(acc, 3).tolist(),
        "summary": {
            "conversion_pct": round(100 * float(conv[-1]), 2), "yield_pct": round(100 * float(yld[-1]), 2),
            "selectivity_pct": round(100 * sel, 2) if sel is not None else None,
            "impurity_pct": {s: round(100 * float(v[-1]), 3) for s, v in imp.items()},
            "peak_yield_pct": round(100 * float(yld[ipk]), 2), "peak_yield_h": round(float(t[ipk]), 3),
            "t95_h": round(float(t[i95]), 3) if i95 is not None else None,
            "dt_ad_total_k": round(heat_total / rho_cp, 1), "heat_total_kj_l": round(heat_total, 1),
            "peak_heat_w_per_l": round(float(np.max(q)) / 3.6, 2), "mtsr_c": round(mtsr, 1),
            **safety_class(float(temp[0]), mtsr, req.get("bp_c"), req.get("td24_c")),
        },
    }


def safety_class(t_process: float, mtsr: float, mtt: Optional[float], td24: Optional[float]) -> dict[str, Any]:
    """Stoessel criticality class (1 = safe … 5 = worst) from T_process, MTSR, MTT (boiling point) and TD24."""
    if mtt is None:
        return {"criticality": None, "criticality_note": "enter the solvent's boiling point (MTT) to classify"}
    if td24 is None:
        cls = 1 if mtsr < mtt else 3
        note = ("MTSR below the boiling point: a cooling failure cannot boil the batch"
                if cls == 1 else "MTSR above the boiling point: on cooling failure the batch would reach reflux — "
                                  "evaporative cooling must be sized; add TD24 (from DSC/ARC) for a full class")
        return {"criticality": cls, "criticality_note": note, "criticality_partial": True}
    if mtsr < mtt:
        cls = 1 if mtsr < td24 and mtt < td24 else (2 if mtsr < td24 else 5)
    else:
        cls = 3 if mtt < td24 and mtsr < td24 else (4 if mtt < td24 else 5)
    notes = {1: "safe: neither boiling nor decomposition can be reached", 2: "safe if the batch is not held at MTSR for long",
             3: "relies on evaporative cooling (reflux) as a safety barrier", 4: "reflux must hold; decomposition reachable beyond it",
             5: "decomposition can be triggered before boiling can stop it — redesign (semi-batch, lower concentration)"}
    return {"criticality": cls, "criticality_note": notes[cls], "criticality_partial": False}


# --------------------------------------------------------------------------- calibration, maps, uncertainty

def yield_at(req: dict[str, Any], temp_c: float, hours: float) -> float:
    r = {**req, "program": {"t0_c": temp_c, "t1_c": temp_c, "ramp_h": 0.0}, "hours": hours}
    out = builtin(r, n_out=2, fast=True)
    return out["summary"]["yield_pct"]


def calibrate(req: dict[str, Any], temp_c: float, hours: float, yield_pct: float) -> dict[str, Any]:
    """Main reaction's k_ref so the model gives the published yield at the published temperature and time.
    For mechanisms where yield rises then falls (A→P→D), the rising branch is used; an unreachable yield is reported."""
    target = float(yield_pct)
    base = {**req, "temp_ref_c": temp_c}
    # the other reactions keep their rate *relative* to the main one at T_ref
    rel = [rx["k"] / req["rxns"][0]["k"] for rx in req["rxns"]]

    def model(logk: float) -> float:
        k = 10 ** logk
        rxns = [{**rx, "k": k * rel[i]} for i, rx in enumerate(req["rxns"])]
        return yield_at({**base, "rxns": rxns}, temp_c, hours)

    grid = np.linspace(-4, 4, 17)
    ys = np.array([model(g) for g in grid])
    # refine the peak (yield vs k rises then may fall when a later step eats the product)
    from scipy.optimize import minimize_scalar
    ip = int(np.argmax(ys))
    lo_b, hi_b = grid[max(ip - 1, 0)], grid[min(ip + 1, len(grid) - 1)]
    pk = minimize_scalar(lambda g: -model(g), bounds=(lo_b, hi_b), method="bounded", options={"xatol": 1e-4})
    g_peak, best = (float(pk.x), -float(pk.fun)) if -pk.fun >= ys[ip] else (float(grid[ip]), float(ys[ip]))
    if target > best + 1e-6:
        return {"ok": False, "reason": f"this mechanism cannot reach {target:.0f}% at {temp_c:g} °C in {hours:g} h "
                                       f"(best {best:.1f}%): lower the side reactions or pick another template"}
    # rising branch: the lowest k that reaches the target
    rising = [g for g in grid if g < g_peak] + [g_peak]
    vals = [model(g) if g != g_peak else best for g in rising]
    i = next(j for j, v in enumerate(vals) if v >= target - 1e-9)
    logk = brentq(lambda g: model(g) - target, rising[i - 1], rising[i], xtol=1e-6) if i > 0 else rising[0]
    k = 10 ** logk
    rxns = [{**rx, "k": float(k * rel[j])} for j, rx in enumerate(req["rxns"])]
    return {"ok": True, "k_ref": float(k), "temp_ref_c": temp_c, "rxns": rxns,
            "check_yield_pct": round(model(logk), 3)}


def yield_map(req: dict[str, Any], temps_c: list[float], hours: list[float]) -> dict[str, Any]:
    """Yield (and main impurity) over a temperature × time grid, isothermal: one integration per temperature,
    sampled at every time — so the grid costs one run per row."""
    ys, imps = [], []
    tmax = max(hours)
    for tc in temps_c:
        r = {**req, "program": {"t0_c": tc, "t1_c": tc, "ramp_h": 0.0}, "hours": tmax}
        out = builtin(r, n_out=400, fast=True)
        t = np.asarray(out["time_h"])
        y = np.asarray(out["yield"])
        ys.append([round(100 * float(np.interp(h, t, y)), 2) for h in hours])
        imp = req["impurities"][0] if req["impurities"] else None
        if imp:
            v = np.asarray(out["impurities"][imp])
            imps.append([round(100 * float(np.interp(h, t, v)), 3) for h in hours])
    arr = np.array(ys)
    i, j = np.unravel_index(int(np.argmax(arr)), arr.shape)
    return {"temps_c": temps_c, "hours": hours, "yield_pct": ys, "impurity_pct": imps or None,
            "impurity": req["impurities"][0] if req["impurities"] else None,
            "best": {"temp_c": temps_c[i], "hours": hours[j], "yield_pct": float(arr[i, j])}}


def acceptable_range(ymap: dict[str, Any], min_yield: float, max_impurity: Optional[float]) -> dict[str, Any]:
    """Cells meeting the targets (a proven-acceptable-range sketch), and the largest temperature window that holds
    for one batch time."""
    ok = np.array(ymap["yield_pct"]) >= min_yield
    if max_impurity is not None and ymap["impurity_pct"]:
        ok &= np.array(ymap["impurity_pct"]) <= max_impurity
    best = None
    for j, h in enumerate(ymap["hours"]):
        col = ok[:, j]
        run = start = 0
        for i, v in enumerate(col):
            if v:
                run += 1
                if best is None or run > best[0]:
                    best = (run, i - run + 1, i, h)
            else:
                run = 0
    rng = None
    if best:
        rng = {"hours": best[3], "temp_from_c": ymap["temps_c"][best[1]], "temp_to_c": ymap["temps_c"][best[2]]}
    return {"ok": ok.astype(int).tolist(), "share_pct": round(100 * float(ok.mean()), 1), "widest": rng}


def ea_band(req: dict[str, Any], temps_c: list[float], hours: float, delta: float = 15.0) -> dict[str, Any]:
    """Yield vs temperature at one batch time for Ea − δ, Ea, Ea + δ on every reaction — how much the prediction
    away from the calibration point rests on the assumed activation energies."""
    out = {}
    for tag, d in (("low", -delta), ("mid", 0.0), ("high", delta)):
        rx = [{**r, "ea": max(5.0, r["ea"] + d)} for r in req["rxns"]]
        out[tag] = [yield_at({**req, "rxns": rx}, t, hours) for t in temps_c]
    return {"temps_c": temps_c, "hours": hours, "delta_kj": delta, **out}


# --------------------------------------------------------------------------- validation against exact solutions

def validate() -> list[dict[str, Any]]:
    """The engine against closed-form solutions. Each case: max relative error over the run, and pass/fail at 1e-5."""
    cases = []

    def run(tpl: str, c0: dict[str, float], rx: list[dict[str, Any]], hours: float, temp_c: float = 50.0):
        req = build_request({"template": tpl, "c0": c0, "rxns": rx, "temp_c": temp_c, "hours": hours})
        return req, builtin(req, n_out=81)

    def add(name: str, what: str, model: np.ndarray, exact: np.ndarray):
        scale = max(float(np.max(np.abs(exact))), 1e-12)
        err = float(np.max(np.abs(model - exact)) / scale)
        cases.append({"case": name, "checks": what, "max_rel_error": float(f"{err:.2e}"), "pass": err < 1e-5})

    # 1. first order
    req, out = run("first", {"A": 1.0}, [{"k": 0.7, "ea": 60, "dh": -50}], 8)
    t = np.array(out["time_h"])
    add("First order A → P", "A(t) = A₀·e^(−kt)", np.array(out["conc"]["A"]), np.exp(-0.7 * t))
    # 2. second order, equal and unequal starting concentrations
    req, out = run("second", {"A": 1.0, "B": 1.0}, [{"k": 0.9, "ea": 60, "dh": -50}], 8)
    t = np.array(out["time_h"])
    add("Second order, A₀ = B₀", "1/A = 1/A₀ + kt", np.array(out["conc"]["A"]), 1 / (1 + 0.9 * t))
    req, out = run("second", {"A": 1.0, "B": 1.5}, [{"k": 0.9, "ea": 60, "dh": -50}], 8)
    t = np.array(out["time_h"])
    a0, b0, k = 1.0, 1.5, 0.9
    e = np.exp((b0 - a0) * k * t)
    add("Second order, A₀ ≠ B₀", "A = A₀(B₀−A₀)/(B₀e^((B₀−A₀)kt) − A₀)", np.array(out["conc"]["A"]), a0 * (b0 - a0) / (b0 * e - a0))
    # 3. consecutive (Bateman)
    k1, k2 = 0.8, 0.15
    req, out = run("consecutive", {"A": 1.0}, [{"k": k1, "ea": 60, "dh": -50}, {"k": k2, "ea": 80, "dh": -20}], 30)
    t = np.array(out["time_h"])
    add("Consecutive A → P → D", "P = A₀k₁/(k₂−k₁)(e^(−k₁t) − e^(−k₂t))", np.array(out["conc"]["P"]),
        k1 / (k2 - k1) * (np.exp(-k1 * t) - np.exp(-k2 * t)))
    tmax = math.log(k2 / k1) / (k2 - k1)
    fine = builtin({**req, "hours": tmax * 2}, n_out=4001)
    tt = np.array(fine["time_h"])
    add("Consecutive: time of maximum P", "t* = ln(k₂/k₁)/(k₂−k₁)", np.array([tt[int(np.argmax(fine["conc"]["P"]))]]), np.array([tmax]))
    cases[-1]["pass"] = cases[-1]["max_rel_error"] < 1e-3  # limited by the output grid (t*/2000)
    # 4. reversible
    kf, keq = 0.5, 4.0
    req, out = run("reversible", {"A": 1.0}, [{"k": kf, "ea": 60, "dh": -20, "keq": keq}], 20)
    t = np.array(out["time_h"])
    ae = 1 / (1 + keq)
    add("Reversible A ⇌ P", "A = Aₑ + (A₀ − Aₑ)e^(−(k_f+k_b)t)", np.array(out["conc"]["A"]),
        ae + (1 - ae) * np.exp(-(kf + kf / keq) * t))
    # 5. Arrhenius temperature dependence
    rx = {"k": 0.3, "ea": 75.0}
    add("Arrhenius", "k(T₂)/k(T₁) = e^(−Ea/R(1/T₂ − 1/T₁))", np.array([float(k_of(rx, 80.0, 50.0) / rx["k"])]),
        np.array([math.exp(-(75.0 / R) * (1 / 353.15 - 1 / 323.15))]))
    # 6. mass balance and adiabatic temperature rise
    req, out = run("comp_consec", {"A": 1.0, "B": 1.5}, [{"k": 1.0, "ea": 60, "dh": -85}, {"k": 0.2, "ea": 70, "dh": -85}], 12)
    c = out["conc"]
    atoms_a = np.array(c["A"]) + np.array(c["P"]) + np.array(c["S"])  # A-core conserved
    add("Mass balance (A + P + S)", "Σ A-containing species = A₀", atoms_a, np.ones_like(atoms_a))
    req, out = run("first", {"A": 2.0}, [{"k": 5.0, "ea": 60, "dh": -100}], 10)
    exp_dt = 100 * 2.0 / (0.9 * 1.9)
    add("Adiabatic temperature rise", "ΔT_ad = (−ΔH)·c₀/(ρ·c_p)", np.array([out["summary"]["dt_ad_total_k"]]), np.array([round(exp_dt, 1)]))
    cases[-1]["pass"] = cases[-1]["max_rel_error"] < 1e-3  # reported to 0.1 K
    return cases
