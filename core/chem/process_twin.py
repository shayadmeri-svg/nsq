"""Process twin of a wet-granulated, immediate-release tablet: process parameters → quality tests, with error
injection, Monte Carlo failure probabilities, Morris sensitivity (SALib) and tipping points.

The chain, unit operation by unit operation, and the basis of every link:

  dispensing    API potency, weighing error ─────────────────────────────→ assay mean            (arithmetic)
  granulation   granulation liquid ─→ granule break-up half-life                                   (ASSUMED power law)
                                    ─→ water load to remove in drying                               (mass balance)
  drying        inlet T, dew point, air flow, time ─→ evaporation capacity ─→ final LOD             (psychrometrics, ASHRAE;
                                                                                                      constant-rate period only)
  blending      blend time ─→ non-random mixing remainder (exp. decay)                             (ASSUMED rate constant)
                API d50/GSD, dose ─→ random-mix limit RSD = √(mass-weighted particle mass / dose)  (Yalkowsky & Bolton 1990)
                blend time ─→ lubricant film raises the contact angle                              (ASSUMED saturation curve)
  compression   pressure ─→ porosity (Heckel) ─→ tensile strength (Ryshkewitch-Duckworth)
                porosity, contact angle, thickness ─→ wetting time (Washburn)
                tensile strength ─→ bond-breaking time; contact angle slows water uptake           (ASSUMED proportionalities)
                fill-weight RSD ─→ content spread
  tests         content uniformity: acceptance value AV = |M − X̄| + 2.4·s (n = 10), limit 15     (IP / USP <905> / Ph. Eur. 2.9.40)
                dissolution: tablet model (chem.product.tablet_dissolution) at Q
                disintegration ≤ limit, tensile ≥ 1.7 MPa (Pitt & Heasley 2013), LOD ≤ limit, assay within limits

Everything marked ASSUMED (and every default value) is illustrative: replace it with the plant's own numbers. The
tree ranks where to look first; it does not diagnose a particular batch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np

from . import product

WATER_37 = {"mu_pa_s": 0.000692, "gamma_n_m": 0.0700}  # viscosity and surface tension of water at 37 °C


@dataclass(frozen=True)
class Param:
    id: str
    unit_op: str
    label: str
    unit: str
    nominal: float
    lo: float  # normal operating range (NOR)
    hi: float
    sweep: tuple[float, float]  # range searched for tipping points
    basis: str = "assumed"  # how its effect is modelled: mechanistic | correlation | assumed
    note: str = ""


UNIT_OPS = [
    {"id": "dispensing", "label": "Dispensing", "what": "API and excipients weighed"},
    {"id": "granulation", "label": "Granulation", "what": "Wet granulation with a binder solution"},
    {"id": "drying", "label": "Drying", "what": "Fluid-bed drying to the LOD limit"},
    {"id": "blending", "label": "Blending", "what": "Final blend with lubricant"},
    {"id": "compression", "label": "Compression", "what": "Tablets pressed to target weight and strength"},
    {"id": "testing", "label": "QC tests", "what": "Assay, uniformity, disintegration, dissolution, LOD, strength"},
]

PARAMS: list[Param] = [
    Param("api_potency_pct", "dispensing", "API potency (CoA)", "%", 100.0, 99.0, 101.0, (90.0, 110.0), "mechanistic",
          "Assay of the API lot used"),
    Param("weighing_error_pct", "dispensing", "Dispensing error", "%", 0.0, -0.5, 0.5, (-8.0, 8.0), "mechanistic",
          "Error in the API quantity charged"),
    Param("granulation_liquid_pct", "granulation", "Granulation liquid", "% w/w", 25.0, 22.0, 28.0, (12.0, 45.0), "assumed",
          "More liquid: denser granules that break up more slowly (assumed power law), and more water to dry"),
    Param("inlet_c", "drying", "Inlet air temperature", "°C", 60.0, 55.0, 65.0, (35.0, 85.0), "mechanistic"),
    Param("dew_point_c", "drying", "Inlet dew point", "°C", 10.0, 6.0, 14.0, (0.0, 30.0), "mechanistic"),
    Param("air_m3_h", "drying", "Air flow", "m³/h", 3000.0, 2700.0, 3300.0, (1200.0, 4500.0), "mechanistic"),
    Param("drying_min", "drying", "Drying time", "min", 60.0, 55.0, 65.0, (15.0, 100.0), "mechanistic"),
    Param("blend_min", "blending", "Lubricated blend time", "min", 5.0, 4.0, 6.0, (0.5, 30.0), "assumed",
          "Too short: non-random mix remains; too long: the lubricant film makes the tablet hydrophobic (both assumed rates)"),
    Param("api_d50_um", "blending", "API particle size d50", "µm", 20.0, 15.0, 25.0, (2.0, 150.0), "mechanistic",
          "Sets the random-mix limit (Yalkowsky-Bolton) and the dissolution surface"),
    Param("pressure_mpa", "compression", "Compression pressure", "MPa", 150.0, 135.0, 165.0, (40.0, 350.0), "mechanistic"),
    Param("weight_rsd_pct", "compression", "Tablet weight RSD", "%", 1.0, 0.7, 1.3, (0.2, 6.0), "mechanistic",
          "Die-fill variation"),
]
P_BY_ID = {p.id: p for p in PARAMS}

# Formulation / equipment constants (illustrative defaults — replace with the product's own)
FORMULATION = {
    "batch_dry_kg": 100.0, "tablet_mg": 0.0,  # 0 = from the dose: 80% drug load above 250 mg, else a 200 mg tablet (min. 20 mg excipient)
    "diameter_mm": 0.0,  # 0 = scaled with tablet mass (10 mm at 400 mg)
    "true_density": 1.45, "excipient_d_um": 30.0,
    "bond_min_per_mpa": 2.5,  # disintegration time per MPa of tensile strength (ASSUMED slope; disintegrant-specific)
    "py_mpa": 140.0, "sigma0_mpa": 9.0, "rd_b": 7.5, "d0": 0.40,  # chem.product MATERIALS "mixed"
    "contact_angle_deg": 45.0, "contact_angle_lub_deg": 30.0, "lub_tau_min": 6.0,
    "mix_rsd0_pct": 15.0, "mix_k_per_min": 0.9,
    "breakup_ref_min": 2.0, "breakup_exponent": 2.0,
    "evap_efficiency": 0.75, "lod_floor_pct": 1.0,
    "rpm": 50.0, "gsd": 1.8,
}
SPECS = {"assay_lo": 95.0, "assay_hi": 105.0, "av_max": 15.0, "lod_max": 3.0, "dt_max_min": 15.0,
         "tensile_min": product.TARGET_TENSILE_MPA, "q_pct": 75.0, "q_time_min": 45.0}

# Where each specification default comes from. Monograph-specific limits (assay, Q, LOD) are not public for free
# (IP / USP / Ph. Eur. are paid texts): those are defaults to be replaced with the product's own monograph limits.
SPEC_BASIS = {
    "assay": {"kind": "default", "text": "Default 95–105% of label claim: assay limits are set per monograph (commonly 90–110% or 95–105%). Enter your product's."},
    "uniformity": {"kind": "source", "text": "AV ≤ 15 for 10 units (L1): uniformity of dosage units, Ph. Eur. 2.9.40 / USP <905>, harmonised under ICH Q4B Annex 6",
                   "url": "https://database.ich.org/sites/default/files/Q4B%20Annex%206%20Guideline.pdf"},
    "dissolution": {"kind": "default", "text": "Default Q = 75% at 45 min: Q is set per monograph. The FDA Dissolution Methods Database gives the method, not the limit."},
    "disintegration": {"kind": "source", "text": "15 min for uncoated tablets (30 min if film-coated): Ph. Eur. monograph Tablets (0478), test 2.9.1"},
    "lod": {"kind": "default", "text": "Default ≤ 3%: loss on drying of the granules is an in-house specification. Enter yours."},
    "strength": {"kind": "source", "text": "Tensile strength ≥ 1.7 MPa gives acceptable friability for most tablets: Pitt & Heasley, Powder Technol. 2013",
                 "url": "https://doi.org/10.1016/j.powtec.2013.01.024"},
}

# What the twin leaves out for each test: a failure the model cannot reproduce may come from any of these.
NOT_MODELLED = {
    "assay": ["degradation on storage", "analytical method error", "overage"],
    "uniformity": ["segregation after blending", "API agglomerates"],
    "dissolution": ["disintegrant type and level", "binder type", "hardening on storage", "coating", "polymorph or salt form",
                    "the test method (medium, deaeration, apparatus)"],
    "disintegration": ["disintegrant type and level", "binder type", "hardening on storage", "coating"],
    "lod": ["falling-rate drying period", "moisture pick-up in storage or packing"],
    "strength": ["excipient grade changes", "punch tooling", "press speed (dwell time)"],
}

# Quality tests, the CDSCO failure categories they fall under, and the words that name them in a CDSCO result text
# or an FDA recall reason (the records are matched on their own text, quoted in the UI).
CQAS = [
    {"id": "assay", "label": "Assay", "cdsco": ["Assay / Content"], "unit": "%",
     "record_rx": r"\bassay\b|label claim|sub-?potent|super-?potent|\bpotency\b"},
    {"id": "uniformity", "label": "Content uniformity (AV)", "cdsco": ["Uniformity of Weight"], "unit": "AV",
     "record_rx": r"uniformity|weight variation|average weight"},
    {"id": "dissolution", "label": "Dissolution", "cdsco": ["Dissolution"], "unit": "% at Q time", "record_rx": r"dissolution"},
    {"id": "disintegration", "label": "Disintegration", "cdsco": ["Disintegration"], "unit": "min", "record_rx": r"disintegrat"},
    {"id": "lod", "label": "Loss on drying", "cdsco": [], "unit": "%", "record_rx": r"loss on drying|moisture|water content"},
    {"id": "strength", "label": "Tablet strength (friability risk)", "cdsco": ["Hardness / Friability"], "unit": "MPa",
     "record_rx": r"hardness|friab|crumbl|broken tablets?|chipped"},
]

# Which parameters can move which test (the edges of the cycle)
EDGES = {
    "assay": ["api_potency_pct", "weighing_error_pct"],
    "uniformity": ["api_potency_pct", "weighing_error_pct", "blend_min", "api_d50_um", "weight_rsd_pct"],
    "dissolution": ["granulation_liquid_pct", "blend_min", "api_d50_um", "pressure_mpa"],
    "disintegration": ["blend_min", "pressure_mpa"],
    "lod": ["granulation_liquid_pct", "inlet_c", "dew_point_c", "air_m3_h", "drying_min"],
    "strength": ["pressure_mpa"],
}
LINKS = [  # the equations behind the edges, for the UI
    {"to": "lod", "basis": "mechanistic", "what": "Evaporation capacity of the drying air (psychrometrics, ASHRAE) × time vs the water added in granulation; constant-rate period only"},
    {"to": "uniformity", "basis": "mechanistic", "what": "Random-mix limit RSD = √(mass-weighted API particle mass / dose) (Yalkowsky & Bolton 1990), fill-weight RSD, AV = |M − X̄| + 2.4·s (IP / USP <905>)"},
    {"to": "uniformity", "basis": "assumed", "what": "Non-random mixing remainder decays exponentially with blend time (rate constant is blender-specific)"},
    {"to": "strength", "basis": "mechanistic", "what": "Heckel porosity from pressure, Ryshkewitch-Duckworth tensile strength (material constants illustrative)"},
    {"to": "disintegration", "basis": "mechanistic", "what": "Washburn water penetration t = 2·L²·μ / (γ·r·cosθ), pore radius from porosity (Kozeny hydraulic radius)"},
    {"to": "disintegration", "basis": "assumed", "what": "Bond breaking takes longer the stronger the tablet (time ∝ tensile strength, disintegrant-specific slope)"},
    {"to": "disintegration", "basis": "assumed", "what": "Lubricant film raises the contact angle with blend time (saturation curve) and slows water uptake ∝ 1/cos θ"},
    {"to": "dissolution", "basis": "mechanistic", "what": "Weibull disintegration → granule break-up → Noyes-Whitney particles, diffusion layer from paddle speed (chem.product.tablet_dissolution)"},
    {"to": "dissolution", "basis": "assumed", "what": "Granule break-up half-life grows with granulation liquid (power law)"},
    {"to": "assay", "basis": "mechanistic", "what": "Assay = API potency × (1 + dispensing error)"},
]


@dataclass
class Molecule:
    name: str
    dose_mg: float
    cs37_mg_ml: float
    diff_cm2_s: float
    density: float = 1.3
    volume_ml: float = 900.0
    cdsco_categories: list[dict[str, Any]] = field(default_factory=list)  # [{name, count}] for this molecule
    alerts: int = 0
    test_alerts: Optional[dict[str, int]] = None  # CDSCO notices whose result text names each test (record_rx)


def _api_rsd_random(dose_mg: float, d50_um: float, gsd: float, rho: float) -> float:
    """Yalkowsky & Bolton (1990): relative SD of drug content in a perfectly random mix = √(w̄ / D), w̄ the
    mass-weighted mean mass of one drug particle — here over the log-normal size distribution."""
    z = np.linspace(-3, 3, 61)
    w_num = np.exp(-z ** 2 / 2)
    d_cm = d50_um * gsd ** z * 1e-4
    m = rho * math.pi / 6 * d_cm ** 3 * 1000  # mg per particle
    m_w = float(np.sum(w_num * m ** 2) / np.sum(w_num * m))
    return 100 * math.sqrt(m_w / dose_mg)


def evaluate(mol: Molecule, x: dict[str, float], form: Optional[dict[str, Any]] = None, specs: Optional[dict[str, Any]] = None,
             fast: bool = True) -> dict[str, Any]:
    """Every quality test for one set of process parameters. `fast` uses a coarser dissolution grid (for Monte Carlo)."""
    F = {**FORMULATION, **(form or {})}
    S = {**SPECS, **(specs or {})}
    v = {p.id: float(x.get(p.id, p.nominal)) for p in PARAMS}
    tablet_mg = F["tablet_mg"] or (mol.dose_mg / 0.8 if mol.dose_mg > 250 else max(200.0, mol.dose_mg + 20))
    diameter_mm = F["diameter_mm"] or 10.0 * (tablet_mg / 400.0) ** (1 / 3)

    # dispensing → assay
    assay = v["api_potency_pct"] * (1 + v["weighing_error_pct"] / 100)

    # granulation + drying → LOD (psychrometric evaporation capacity × time × efficiency vs water added)
    water_kg = F["batch_dry_kg"] * v["granulation_liquid_pct"] / 100
    try:
        fb = product.fluid_bed(v["inlet_c"], min(v["dew_point_c"], v["inlet_c"] - 1), v["air_m3_h"], spray_g_min=1.0, solids_pct=0.0, heat_loss_pct=10.0)
        cap_kg_min = fb["evaporation_capacity_g_min"] / 1000
    except ValueError:
        cap_kg_min = 0.0
    removed = min(water_kg, cap_kg_min * F["evap_efficiency"] * v["drying_min"])
    left = water_kg - removed
    lod = max(F["lod_floor_pct"], 100 * left / (F["batch_dry_kg"] + left))

    # blending + compression → content uniformity (AV)
    rsd_rand = _api_rsd_random(mol.dose_mg, v["api_d50_um"], F["gsd"], mol.density)
    rsd_mix = F["mix_rsd0_pct"] * math.exp(-F["mix_k_per_min"] * v["blend_min"])
    s_pct = math.sqrt(rsd_rand ** 2 + rsd_mix ** 2 + v["weight_rsd_pct"] ** 2)
    xbar = assay
    m_ref = min(max(xbar, 98.5), 101.5)  # reference value M (IP / USP <905>)
    av = abs(m_ref - xbar) + 2.4 * s_pct * xbar / 100

    # compression → porosity, strength, disintegration (Washburn)
    rel_d = 1 - math.exp(-(v["pressure_mpa"] / F["py_mpa"] + math.log(1 / (1 - F["d0"]))))
    eps = max(1 - rel_d, 0.02)
    tensile = F["sigma0_mpa"] * math.exp(-F["rd_b"] * eps)
    vol_cm3 = tablet_mg / 1000 / (F["true_density"] * rel_d)
    area = math.pi * (diameter_mm / 20) ** 2
    half_thick_m = vol_cm3 / area / 2 / 100
    r_pore_m = 2 * eps * (F["excipient_d_um"] * 1e-6) / (6 * (1 - eps))  # 2 × Kozeny hydraulic radius
    theta = F["contact_angle_deg"] + F["contact_angle_lub_deg"] * (1 - math.exp(-v["blend_min"] / F["lub_tau_min"]))
    cos_t = max(math.cos(math.radians(min(theta, 89.0))), 0.017)
    t_pen_s = 2 * half_thick_m ** 2 * WATER_37["mu_pa_s"] / (WATER_37["gamma_n_m"] * r_pore_m * cos_t)
    # Wetting (Washburn) is fast; breaking the bonds takes longer the stronger the tablet (ASSUMED proportional to
    # tensile strength), and a lubricant film slows the disintegrant's uptake of water (ASSUMED ∝ 1/cos θ).
    wet_slow = math.cos(math.radians(F["contact_angle_deg"])) / cos_t
    dt_min = (t_pen_s / 60 + F["bond_min_per_mpa"] * F["sigma0_mpa"] * math.exp(-F["rd_b"] * eps)) * wet_slow

    # dissolution: tablet model
    breakup = F["breakup_ref_min"] * (v["granulation_liquid_pct"] / 25.0) ** F["breakup_exponent"]
    kw = dict(bins=7, cohort_min=1.0, dt_s=4.0) if fast else {}
    tab = product.tablet_dissolution(mol.dose_mg, mol.cs37_mg_ml, mol.diff_cm2_s, d50_um=v["api_d50_um"], gsd=F["gsd"],
                                     density_g_cm3=mol.density, volume_ml=mol.volume_ml, rpm=F["rpm"],
                                     disintegration_min=max(dt_min, 0.05), granule_breakup_min=max(breakup, 0.05),
                                     t_end_min=max(S["q_time_min"], 30.0), **kw)
    diss = float(np.interp(S["q_time_min"], tab["times_min"], tab["pct"]))

    values = {"assay": assay, "uniformity": av, "dissolution": diss, "disintegration": dt_min, "lod": lod, "strength": tensile}
    fails = {
        "assay": not (S["assay_lo"] <= assay <= S["assay_hi"]),
        "uniformity": av > S["av_max"],
        "dissolution": diss < S["q_pct"],
        "disintegration": dt_min > S["dt_max_min"],
        "lod": lod > S["lod_max"],
        "strength": tensile < S["tensile_min"],
    }
    inter = {"porosity": eps, "contact_angle_deg": theta, "rsd_random_pct": rsd_rand, "rsd_mix_pct": rsd_mix, "content_sd_pct": s_pct,
             "granule_breakup_min": breakup, "water_kg": water_kg, "evap_kg_min": cap_kg_min, "tablet_mg": tablet_mg,
             "thickness_mm": 2 * half_thick_m * 1000, "diameter_mm": diameter_mm, "wetting_s": t_pen_s}
    out = {"values": {k: round(v_, 3) for k, v_ in values.items()}, "fails": fails, "intermediate": {k: round(v_, 4) for k, v_ in inter.items()}}
    if not fast:
        out["curve"] = {"times_min": tab["times_min"], "pct": tab["pct"]}
    return out


def _limit_value(cqa: str, S: dict[str, Any]) -> list[tuple[str, float]]:
    return {"assay": [("lo", S["assay_lo"]), ("hi", S["assay_hi"])], "uniformity": [("hi", S["av_max"])],
            "dissolution": [("lo", S["q_pct"])], "disintegration": [("hi", S["dt_max_min"])], "lod": [("hi", S["lod_max"])],
            "strength": [("lo", S["tensile_min"])]}[cqa]


def tipping_points(mol: Molecule, x: dict[str, float], form=None, specs=None, n: int = 21) -> dict[str, dict[str, Any]]:
    """For each parameter (others held at x), the value where each test it moves crosses its limit, by a grid sweep
    over the parameter's search range and linear interpolation between the bracketing points."""
    S = {**SPECS, **(specs or {})}
    out: dict[str, dict[str, Any]] = {}
    for p in PARAMS:
        cqas = [c for c, ps in EDGES.items() if p.id in ps]
        grid = np.linspace(p.sweep[0], p.sweep[1], n)
        vals = {c: [] for c in cqas}
        for g in grid:
            r = evaluate(mol, {**x, p.id: float(g)}, form, specs)
            for c in cqas:
                vals[c].append(r["values"][c])
        res = {}
        for c in cqas:
            y = np.array(vals[c])
            hits = []
            for side, lim in _limit_value(c, S):
                bad = (y < lim) if side == "lo" else (y > lim)
                for i in range(1, len(grid)):
                    if bad[i] != bad[i - 1]:
                        g0, g1, y0, y1 = grid[i - 1], grid[i], y[i - 1], y[i]
                        at = g0 + (lim - y0) / (y1 - y0) * (g1 - g0) if y1 != y0 else g0
                        hits.append({"at": round(float(at), 3), "limit": lim, "side": side,
                                     "direction": "above" if bad[i] else "below"})  # fails when the parameter goes above/below `at`
            cur = float(x.get(p.id, p.nominal))
            nearest = min(hits, key=lambda h: abs(h["at"] - cur)) if hits else None
            margin = None
            if nearest:
                half = (p.hi - p.lo) / 2 or 1.0
                margin = round(abs(nearest["at"] - cur) / half, 2)  # in NOR half-widths
            res[c] = {"crossings": hits, "nearest": nearest, "margin_nor": margin,
                      "sweep": [round(float(g), 3) for g in grid], "values": [round(float(t), 3) for t in y]}
        out[p.id] = res
    return out


def morris(mol: Molecule, x: dict[str, float], form=None, specs=None, r: int = 6, seed: int = 7) -> dict[str, list[dict[str, Any]]]:
    """Morris elementary effects (SALib) over each parameter's normal operating range, around x: μ* per test."""
    from SALib.analyze import morris as ma
    from SALib.sample import morris as ms

    names = [p.id for p in PARAMS]
    bounds = []
    for p in PARAMS:
        c = float(x.get(p.id, p.nominal))
        half = (p.hi - p.lo) / 2
        bounds.append([c - half, c + half])
    problem = {"num_vars": len(names), "names": names, "bounds": bounds}
    X = ms.sample(problem, N=r, num_levels=4, seed=seed)
    Y = {c["id"]: [] for c in CQAS}
    for row in X:
        e = evaluate(mol, dict(zip(names, map(float, row))), form, specs)
        for k in Y:
            Y[k].append(e["values"][k])
    out = {}
    for k, ys in Y.items():
        a = ma.analyze(problem, X, np.array(ys), num_levels=4, print_to_console=False, seed=seed)
        rows = [{"param": n, "mu_star": round(float(m), 4), "sigma": round(float(s), 4)} for n, m, s in zip(names, a["mu_star"], a["sigma"])]
        rows = [rw for rw in rows if rw["param"] in EDGES[k]]
        rows.sort(key=lambda rw: -rw["mu_star"])
        out[k] = rows
    return out


def monte_carlo(mol: Molecule, x: dict[str, float], form=None, specs=None, n: int = 150, seed: int = 11,
                withheld: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Parameters drawn normally around x with σ = NOR half-width / 3 (a process running inside its range)."""
    rng = np.random.default_rng(seed)
    fails = {c["id"]: 0 for c in CQAS}
    any_fail = 0
    for _ in range(n):
        xs = {p.id: float(rng.normal(x.get(p.id, p.nominal), (p.hi - p.lo) / 6)) for p in PARAMS}
        xs["weight_rsd_pct"] = max(xs["weight_rsd_pct"], 0.05)
        xs["api_d50_um"] = max(xs["api_d50_um"], 1.0)
        xs["blend_min"] = max(xs["blend_min"], 0.1)
        xs["drying_min"] = max(xs["drying_min"], 1.0)
        e = evaluate(mol, xs, form, specs)
        hit = False
        for k, f in e["fails"].items():
            if f and k not in (withheld or {}):
                fails[k] += 1
                hit = True
        any_fail += hit
    return {"n": n, "p_fail": {k: (None if k in (withheld or {}) else round(v / n, 3)) for k, v in fails.items()},
            "p_batch_fail": round(any_fail / n, 3),
            "method": "parameters drawn around the current settings, σ = NOR half-width / 3"}


def _fails(cqa: str, v: float, S: dict[str, Any]) -> bool:
    return any((v < lim) if side == "lo" else (v > lim) for side, lim in _limit_value(cqa, S))


def injections(mol: Molecule, x: dict[str, float], sens: dict[str, list[dict[str, Any]]], tips: dict[str, dict[str, Any]],
               form=None, specs=None, withheld: Optional[dict[str, str]] = None, n: int = 16) -> dict[str, dict[str, Any]]:
    """Per test, the smallest error the model needs to fail it, found by the model (nothing hand-picked):

    single     the most influential parameters (Morris μ*) one at a time, each pushed 15% of its normal half-range
               past its tipping point;
    combined   when no single parameter tips the test inside its searched range: the two, three, then all
               linked ones (by influence) moved together from x toward their worse end (the end of each sweep where the test
               value is worse), and the first point on that path where the test fails.
    """
    S = {**SPECS, **(specs or {})}
    out: dict[str, dict[str, Any]] = {}
    for c in CQAS:
        cid = c["id"]
        if cid in (withheld or {}):
            out[cid] = {"kind": "withheld", "steps": []}
            continue
        ranked = [rw for rw in sens.get(cid, []) if rw["mu_star"] > 0]
        single = []
        for rw in ranked:
            p = P_BY_ID[rw["param"]]
            tp = (tips.get(p.id) or {}).get(cid, {}).get("nearest")
            if not tp:
                continue
            # the crossing is interpolated on a grid: step past it until the model confirms the test fails
            step = 0.15 * (p.hi - p.lo) / 2 * (1 if tp["direction"] == "above" else -1)
            v, ok = tp["at"], False
            for _ in range(12):
                v = float(f"{min(max(v + step, p.sweep[0]), p.sweep[1]):.3g}")
                if _fails(cid, evaluate(mol, {**x, p.id: v}, form, specs)["values"][cid], S):
                    ok = True
                    break
                if v in p.sweep:
                    break
            if not ok:
                continue
            single.append([{"param": p.id, "value": v, "tipping": tp["at"],
                            "direction": tp["direction"], "margin_nor": (tips.get(p.id) or {}).get(cid, {}).get("margin_nor")}])
            if len(single) == 2:
                break
        if single:
            out[cid] = {"kind": "single", "steps": single}
            continue
        # worse end of each parameter = the end of its sweep where the test value is worse; parameters ranked by
        # influence, or all linked ones when none has any influence around x (e.g. dissolution pinned at 100%)
        worse = {}
        lo_bad = any(side == "lo" for side, _ in _limit_value(cid, S))
        for pid in [rw["param"] for rw in ranked] or EDGES[cid]:
            t = (tips.get(pid) or {}).get(cid) or {}
            if t.get("values") and t["values"][0] != t["values"][-1]:
                ends = (t["values"][0], t["values"][-1])
                worse[pid] = P_BY_ID[pid].sweep[0] if ((ends[0] < ends[1]) == lo_bad) else P_BY_ID[pid].sweep[1]
        found, last = None, None
        for k in sorted({min(2, len(worse)), min(3, len(worse)), len(worse)} - {0, 1}):
            ids = list(worse)[:k]
            for f in np.linspace(0, 1, n + 1)[1:]:
                xs = {**x, **{i: x.get(i, P_BY_ID[i].nominal) + f * (worse[i] - x.get(i, P_BY_ID[i].nominal)) for i in ids}}
                v = evaluate(mol, xs, form, specs)["values"][cid]
                last = v
                if _fails(cid, v, S):
                    found = [{"param": i, "value": float(f"{xs[i]:.3g}"), "direction": "above" if worse[i] > x.get(i, P_BY_ID[i].nominal) else "below",
                              "tipping": None, "margin_nor": None} for i in ids]
                    break
            if found:
                break
        # "none": the model cannot fail this test with its parameters; `worst` is the value with the most influential
        # ones all at their worse ends — the twin does not reproduce this failure, and says so
        if last is None and not found:
            last = evaluate(mol, {**x, **worse}, form, specs)["values"][cid]
        out[cid] = {"kind": "combined", "steps": [found]} if found else {"kind": "none", "steps": [],
                                                                         "worst": None if last is None else round(float(last), 2),
                                                                         "worst_params": list(worse)}
    return out


def tree(mol: Molecule, x: dict[str, float], nominal: dict[str, Any], mc: dict[str, Any], sens: dict[str, list[dict[str, Any]]],
         tips: dict[str, dict[str, Any]], withheld: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Batch failure → test → parameters ranked by Morris μ*, each with its tipping point and margin."""
    total = (mol.alerts if mol.test_alerts is not None else sum(c["count"] for c in mol.cdsco_categories)) or 0
    by_cat = {c["name"]: c["count"] for c in mol.cdsco_categories}
    children = []
    for c in CQAS:
        cid = c["id"]
        national = (mol.test_alerts or {}).get(cid, 0) if mol.test_alerts is not None else sum(by_cat.get(n, 0) for n in c["cdsco"])
        kids = []
        top = max((rw["mu_star"] for rw in sens.get(cid, [])), default=0) or 1.0
        for rw in sens.get(cid, []):
            p = P_BY_ID[rw["param"]]
            tp = tips.get(p.id, {}).get(cid, {})
            kids.append({"id": f"{cid}:{p.id}", "kind": "param", "param": p.id, "label": p.label, "unit_op": p.unit_op, "unit": p.unit,
                         "current": float(x.get(p.id, p.nominal)), "nor": [p.lo, p.hi], "basis": p.basis,
                         "influence": round(rw["mu_star"] / top, 3), "mu_star": rw["mu_star"],
                         "tipping": tp.get("nearest"), "margin_nor": tp.get("margin_nor")})
        wh = (withheld or {}).get(cid)
        children.append({"id": cid, "kind": "test", "label": c["label"], "value": nominal["values"][cid],
                         "fails_now": None if wh else nominal["fails"][cid], "withheld": wh,
                         "p_fail": mc["p_fail"][cid], "cdsco": c["cdsco"], "national_alerts": national,
                         "national_share_pct": round(100 * national / total, 1) if total else None, "children": kids})
    children.sort(key=lambda n: (n["withheld"] is not None, -(n["p_fail"] or 0), not n["fails_now"], -(n["national_share_pct"] or 0)))
    return {"id": "batch", "kind": "root", "label": "Batch fails a quality test", "p_fail": mc["p_batch_fail"], "children": children,
            "national": {"alerts": mol.alerts, "categories": mol.cdsco_categories}}


def run(mol: Molecule, overrides: Optional[dict[str, float]] = None, form=None, specs=None, analyses: bool = True,
        withheld: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """`withheld`: tests the model cannot judge for this molecule (e.g. dissolution when the solubility at the medium
    pH is unknown), with the reason — reported as not assessable instead of pass/fail."""
    x = {p.id: p.nominal for p in PARAMS}
    injected = {k: float(v) for k, v in (overrides or {}).items() if k in P_BY_ID and v is not None}
    x.update(injected)
    nominal = evaluate(mol, {p.id: p.nominal for p in PARAMS}, form, specs, fast=False)
    current = evaluate(mol, x, form, specs, fast=False) if injected else nominal
    out: dict[str, Any] = {
        "unit_ops": [{**u, "params": [{**p.__dict__, "sweep": list(p.sweep), "current": x[p.id], "injected": p.id in injected}
                                      for p in PARAMS if p.unit_op == u["id"]]} for u in UNIT_OPS],
        "cqas": CQAS, "spec_basis": SPEC_BASIS, "edges": EDGES, "links": LINKS, "specs": {**SPECS, **(specs or {})}, "formulation": {**FORMULATION, **(form or {})},
        "nominal": nominal, "current": current, "injected": injected,
        "moved": {c["id"]: round(current["values"][c["id"]] - nominal["values"][c["id"]], 3) for c in CQAS},
        "withheld": withheld or {},
    }
    if analyses:
        mc = monte_carlo(mol, x, form, specs, withheld=withheld)
        sens = morris(mol, x, form, specs)
        tips = tipping_points(mol, x, form, specs)
        out.update(mc=mc, sensitivity=sens, tipping=tips, tree=tree(mol, x, current, mc, sens, tips, withheld),
                   injections=injections(mol, x, sens, tips, form, specs, withheld))
    out["assumptions"] = [
        "A generic wet-granulated immediate-release tablet: the defaults (batch size, materials, mixing and lubrication rates, "
        "operating ranges) are illustrative — replace them with the product's own.",
        "Links marked 'assumed' have no published equation here; links marked 'mechanistic' use the cited equation with "
        "illustrative constants.",
        "Drying covers the constant-rate period only; segregation after blending and coating are not modelled.",
        "The tree ranks which parameters to check first for each test; it does not diagnose a particular batch.",
    ]
    return out
