"""Thermal properties and solubility-temperature curves.

Melting point and enthalpy of fusion are taken, in order, from: an
experimental value (PubChem, passed in), the `chemicals` property database
(by CAS), or the Joback group-contribution estimate (flagged: Joback is often
tens of kelvin off for drug-like molecules). When only the melting point is
known, Walden's rule (entropy of fusion ~ 56.5 J/mol/K) gives the enthalpy.

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


@lru_cache(maxsize=1024)
def fusion(name: str, smiles: str, mp_exp_c: Optional[float] = None) -> dict[str, Any]:
    """Melting point (C) and enthalpy of fusion (J/mol) with where each came from."""
    tm_k, dh, src_tm, src_h = None, None, None, None
    if mp_exp_c is not None:
        tm_k, src_tm = mp_exp_c + 273.15, "experimental (PubChem)"
    cas = _cas(name) if name else None
    if cas:
        try:
            from chemicals import Hfus, Tm
            if tm_k is None:
                v = Tm(cas)
                if v:
                    tm_k, src_tm = float(v), "chemicals database"
            h = Hfus(cas)
            if h:
                dh, src_h = float(h), "chemicals database"
        except Exception:
            pass
    if tm_k is None or dh is None:
        try:
            from rdkit import Chem
            from thermo.group_contribution.joback import Joback
            est = Joback(Chem.MolFromSmiles(smiles)).estimate()
            # Joback is often far off for drug-like molecules; keep it only when plausible.
            if tm_k is None and est.get("Tm") and 293.15 < float(est["Tm"]) < 623.15:
                tm_k, src_tm = float(est["Tm"]), "Joback estimate (low confidence)"
        except Exception:
            pass
    if tm_k is not None and dh is None:
        dh, src_h = WALDEN_DS * tm_k, "Walden's rule (56.5 J/mol/K × Tm)"
    return {"mp_c": round(tm_k - 273.15, 1) if tm_k else None, "mp_source": src_tm,
            "mp_measured": bool(src_tm) and "Joback" not in src_tm,
            "dh_fus": round(dh) if dh else None, "dh_source": src_h, "cas": cas}


@lru_cache(maxsize=64)
def solvent(key: str) -> dict[str, Any]:
    from thermo import Chemical
    name = SOLVENTS.get(key, key)
    c = Chemical(name, T=298.15)
    return {"key": key, "name": name, "mw": float(c.MW), "rho_25": float(c.rho), "bp_c": round(float(c.Tb) - 273.15, 1),
            "cas": c.CAS}


def solvent_density(key: str, temp_c: float) -> float:
    from thermo import Chemical
    try:
        return float(Chemical(SOLVENTS.get(key, key), T=temp_c + 273.15).rho)
    except Exception:
        return solvent(key)["rho_25"]


def ideal_mole_fraction(temp_c: float, mp_c: float, dh_fus: float) -> float:
    """Schröder-van Laar ideal solubility (mole fraction)."""
    t, tm = temp_c + 273.15, mp_c + 273.15
    return min(1.0, math.exp(-dh_fus / R * (1 / t - 1 / tm)))


def curve(api_mw: float, mp_c: float, dh_fus: float, solvent_key: str, gamma: float = 1.0,
          aq_mg_ml_25: Optional[float] = None, t_min: float = 0.0, t_max: float = 70.0) -> dict[str, Any]:
    """Solubility (kg/m3 of solvent) vs temperature.

    Organic solvents: ideal solubility divided by an activity coefficient (1 = ideal,
    an upper bound). Water: the structure-based 25 C estimate, extended with van 't
    Hoff using the enthalpy of fusion.
    """
    sv = solvent(solvent_key)
    temps = np.linspace(t_min, t_max, 29)
    vals = []
    for tc in temps:
        if solvent_key == "water" and aq_mg_ml_25 is not None:
            vals.append(aq_mg_ml_25 * math.exp(-dh_fus / R * (1 / (tc + 273.15) - 1 / 298.15)))
            continue
        x = ideal_mole_fraction(tc, mp_c, dh_fus) / max(gamma, 1e-6)
        x = min(x, 0.95)
        rho = solvent_density(solvent_key, tc)
        vals.append(x / (1 - x) * api_mw / sv["mw"] * rho)  # kg API per m3 solvent
    vals = np.array(vals)
    model = ("structure-based aqueous estimate + van 't Hoff" if solvent_key == "water" and aq_mg_ml_25 is not None
             else f"ideal solubility / γ={gamma:g}")
    return {"temps_c": temps.round(1).tolist(), "kg_m3": [float(f"{v:.5g}") for v in vals],
            "model": model, "solvent": sv}


def interp(temps_c: list[float], kg_m3: list[float], temp_k: np.ndarray | float) -> np.ndarray:
    """Solubility at temp_k by log-linear interpolation of a curve (also used by the PharmaPy sidecar)."""
    t = np.asarray(temp_k, dtype=float) - 273.15
    return np.exp(np.interp(t, temps_c, np.log(np.maximum(kg_m3, 1e-12))))
