"""Thermal properties and solubility-temperature curves.

Melting point and enthalpy of fusion come, in order, from: an experimental
value (PubChem, passed in), or the `chemicals` property database (by CAS) using
only its data-backed sources (CRC, Common Chemistry, Open Notebook, ...).
The `chemicals` library silently falls back to the Joback group-contribution
estimate, which is tens to hundreds of kelvin off for drug-like molecules
(cloxacillin comes out at 750 °C), so Joback is never used here. With a
melting point but no measured enthalpy, Walden's rule (entropy of fusion
~56.5 J/mol/K) gives an estimate, labelled as such.

Solvent density and molar mass come from `thermo`.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Optional

import numpy as np

R = 8.314
WALDEN_DS = 56.5  # J/mol/K

SOLVENTS = {
    "water": "Water", "ethanol": "Ethanol", "methanol": "Methanol", "isopropanol": "Isopropanol",
    "acetone": "Acetone", "ethyl acetate": "Ethyl acetate", "heptane": "n-Heptane", "toluene": "Toluene",
}


def _cas(name: str) -> Optional[str]:
    try:
        from chemicals import CAS_from_any
        return CAS_from_any(name)
    except Exception:
        return None


_ESTIMATE_METHODS = {"JOBACK"}  # group-contribution estimates, not data


def _db_value(kind: str, cas: str) -> tuple[Optional[float], Optional[str]]:
    """A data-backed Tm (K) or Hfus (J/mol) from `chemicals`, never its Joback fallback."""
    try:
        from chemicals import phase_change as pc
        fn, methods = (pc.Tm, pc.Tm_methods) if kind == "Tm" else (pc.Hfus, pc.Hfus_methods)
        for m in methods(cas) or []:
            if m.upper() in _ESTIMATE_METHODS:
                continue
            v = fn(cas, method=m)
            if v:
                return float(v), f"chemicals database ({m})"
    except Exception:
        pass
    return None, None


@lru_cache(maxsize=1024)
def fusion(name: str, smiles: str, mp_exp_c: Optional[float] = None) -> dict[str, Any]:
    """Melting point (C) and enthalpy of fusion (J/mol), each with its source and kind
    ("measured" = experimental / curated database, "estimate" = Walden's rule)."""
    tm_k, dh, src_tm, src_h = None, None, None, None
    if mp_exp_c is not None:
        tm_k, src_tm = mp_exp_c + 273.15, "experimental (PubChem)"
    cas = _cas(name) if name else None
    if cas:
        if tm_k is None:
            tm_k, src_tm = _db_value("Tm", cas)
        dh, src_h = _db_value("Hfus", cas)
    dh_kind = "measured" if dh else None
    if tm_k is not None and dh is None:
        dh, src_h, dh_kind = WALDEN_DS * tm_k, "estimate: Walden's rule (56.5 J/mol/K × Tm), ±30%", "estimate"
    return {"mp_c": round(tm_k - 273.15, 1) if tm_k else None, "mp_source": src_tm,
            "mp_measured": tm_k is not None, "mp_kind": "measured" if tm_k is not None else None,
            "dh_fus": round(dh) if dh else None, "dh_source": src_h, "dh_kind": dh_kind, "cas": cas}


@lru_cache(maxsize=64)
def solvent(key: str) -> dict[str, Any]:
    from thermo import Chemical
    name = SOLVENTS.get(key, key)
    c = Chemical(name, T=298.15)
    return {"key": key, "name": name, "mw": float(c.MW), "rho_25": float(c.rhol or c.rho), "bp_c": round(float(c.Tb) - 273.15, 1),
            "mp_c": round(float(c.Tm) - 273.15, 1) if c.Tm else None, "cas": c.CAS}


def solvent_density(key: str, temp_c: float) -> float:
    from thermo import Chemical
    try:
        c = Chemical(SOLVENTS.get(key, key), T=temp_c + 273.15)
        return float(c.rhol or c.rho)  # liquid density, also extrapolated just past the boiling point
    except Exception:
        return solvent(key)["rho_25"]


def ideal_mole_fraction(temp_c: float, mp_c: float, dh_fus: float) -> float:
    """Schröder-van Laar ideal solubility (mole fraction)."""
    t, tm = temp_c + 273.15, mp_c + 273.15
    return min(1.0, math.exp(-dh_fus / R * (1 / t - 1 / tm)))


@lru_cache(maxsize=512)
def unifac_groups(cas: Optional[str]) -> Optional[tuple[tuple[int, int], ...]]:
    """Modified UNIFAC (Dortmund) subgroups for a compound, as the Dortmund Data Bank (DDBST) assigns them.

    Only published assignments are used (thermo ships the DDBST table): no automatic fragmentation, which fails
    on most drug molecules and would be a guess."""
    if not cas:
        return None
    try:
        from thermo.unifac import UNIFAC_group_assignment_DDBST
        g = UNIFAC_group_assignment_DDBST(cas, "MODIFIED_UNIFAC")
    except Exception:
        return None
    return tuple(sorted(g.items())) if g else None


def unifac_gamma(api_groups, solvent_groups, temp_c: float, x_api: float) -> float:
    """Activity coefficient of the API in a binary API–solvent mixture, Modified UNIFAC (Dortmund, 2016 parameters)."""
    from thermo.unifac import DOUFIP2016, DOUFSG, UNIFAC

    x = min(max(x_api, 1e-9), 0.999)
    m = UNIFAC.from_subgroups(T=temp_c + 273.15, xs=[x, 1 - x], chemgroups=[dict(api_groups), dict(solvent_groups)],
                              version=1, interaction_data=DOUFIP2016, subgroups=DOUFSG)
    return float(m.gammas()[0])


def unifac_solubility(temp_c: float, mp_c: float, dh_fus: float, api_groups, solvent_groups) -> tuple[float, float]:
    """Solid–liquid equilibrium x = x_ideal / γ(x), solved by fixed-point iteration. Returns (x, γ)."""
    xi = ideal_mole_fraction(temp_c, mp_c, dh_fus)
    x = xi
    g = 1.0
    for _ in range(200):
        g = unifac_gamma(api_groups, solvent_groups, temp_c, x)
        nx = min(xi / max(g, 1e-9), 0.95)
        if abs(nx - x) < 1e-10 * max(x, 1e-12):
            x = nx
            break
        x = 0.5 * x + 0.5 * nx
    return x, g


def curve(api_mw: float, mp_c: float, dh_fus: float, solvent_key: str, gamma: float = 1.0,
          aq_mg_ml_25: Optional[float] = None, t_min: float = -10.0, t_max: float = 90.0,
          api_cas: Optional[str] = None) -> dict[str, Any]:
    """Solubility (kg/m3 of solvent) vs temperature.

    Organic solvents: ideal solubility divided by an activity coefficient (1 = ideal,
    an upper bound). Water: the structure-based 25 C estimate, extended with van 't
    Hoff using the enthalpy of fusion.
    """
    sv = solvent(solvent_key)
    temps = np.linspace(t_min, t_max, 41)
    vals = []
    # Modified UNIFAC when the DDBST assigns groups to both the API and the solvent and no γ was entered
    ag, sg = unifac_groups(api_cas), unifac_groups(sv.get("cas"))
    use_unifac = solvent_key != "water" and abs(gamma - 1.0) < 1e-9 and ag is not None and sg is not None
    gammas = []
    for tc in temps:
        if solvent_key == "water" and aq_mg_ml_25 is not None:
            vals.append(aq_mg_ml_25 * math.exp(-dh_fus / R * (1 / (tc + 273.15) - 1 / 298.15)))
            continue
        if use_unifac:
            try:
                x, g_ = unifac_solubility(tc, mp_c, dh_fus, ag, sg)
                gammas.append(g_)
                rho = solvent_density(solvent_key, tc)
                vals.append(x / (1 - x) * api_mw / sv["mw"] * rho)
                continue
            except Exception:
                use_unifac = False
                vals, gammas = [], []
        x = ideal_mole_fraction(tc, mp_c, dh_fus) / max(gamma, 1e-6)
        x = min(x, 0.95)
        rho = solvent_density(solvent_key, tc)
        vals.append(x / (1 - x) * api_mw / sv["mw"] * rho)  # kg API per m3 solvent
    vals = np.array(vals)
    if use_unifac and len(vals) != len(temps):  # UNIFAC failed part-way: recompute the whole curve as ideal
        return curve(api_mw, mp_c, dh_fus, solvent_key, gamma, aq_mg_ml_25, t_min, t_max, api_cas=None)
    model = ("aqueous solubility at 25 °C + van 't Hoff (ΔHfus as ΔHsol)" if solvent_key == "water" and aq_mg_ml_25 is not None
             else f"Modified UNIFAC (Dortmund, DDBST group assignments): γ {min(gammas):.2g}–{max(gammas):.2g}" if use_unifac
             else f"ideal solubility / γ={gamma:g}")
    ideal = solvent_key != "water" and abs(gamma - 1.0) < 1e-9 and not use_unifac
    return {"ideal": ideal, "unifac": use_unifac,
            "unifac_note": None if use_unifac or solvent_key == "water" else
            ("no Modified UNIFAC group assignment for this molecule in the DDBST table, so the solvent is not modelled"
             if ag is None else "no UNIFAC groups for this solvent"),
            "solvent_modelled": solvent_key == "water" or not ideal,"temps_c": temps.round(1).tolist(), "kg_m3": [float(f"{v:.5g}") for v in vals],
            "model": model, "solvent": sv}


def interp(temps_c: list[float], kg_m3: list[float], temp_k: np.ndarray | float) -> np.ndarray:
    """Solubility at temp_k by log-linear interpolation of a curve (also used by the PharmaPy sidecar)."""
    t = np.asarray(temp_k, dtype=float) - 273.15
    return np.exp(np.interp(t, temps_c, np.log(np.maximum(kg_m3, 1e-12))))
