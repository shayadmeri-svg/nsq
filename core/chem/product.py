"""Drug-product models built on published equations instead of fixed thresholds.

dissolution()  Noyes-Whitney with Hintz-Johnson diffusion layer (h = min(r, h_max))
               over a log-normal particle size distribution, in a USP vessel.
compaction()   Heckel (porosity vs pressure) + Ryshkewitch-Duckworth (tensile strength
               vs porosity).
fluid_bed()    Steady-state air-side mass and energy balance with psychrometrics
               (psychrolib, ASHRAE formulations): outlet temperature, outlet RH and
               the share of the air's drying capacity the spray uses.

Material parameters that can't be derived from structure (yield pressure,
tensile constants, particle size) are inputs with editable defaults, and every
result lists the assumptions it used.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np


# --- dissolution ---------------------------------------------------------------------------------

def dissolution(dose_mg: float, cs_mg_ml: float, diff_cm2_s: float, d50_um: float = 20.0, gsd: float = 1.8,
                density_g_cm3: float = 1.3, volume_ml: float = 900.0, h_max_um: float = 30.0, lag_min: float = 2.0,
                t_end_min: float = 60.0, q_time_min: float = 45.0, q_pct: float = 75.0, bins: int = 25,
                ionization: str = "none", pka: Optional[float] = None, ph: float = 6.8) -> dict[str, Any]:
    if dose_mg <= 0 or cs_mg_ml <= 0 or d50_um <= 0:
        raise ValueError("dose, solubility and particle size must be positive")
    intrinsic = cs_mg_ml
    ion_note = None
    if ionization in ("acid", "base") and pka is not None:
        # Henderson-Hasselbalch pH-solubility; capped at 10^4 x intrinsic (salt solubility limit)
        exp = (ph - pka) if ionization == "acid" else (pka - ph)
        factor = min(1 + 10 ** exp, 1e4)
        cs_mg_ml = intrinsic * factor
        ion_note = f"Weak {ionization}, pKa {pka:g}, medium pH {ph:g}: solubility ×{factor:.3g} over the neutral form (Henderson-Hasselbalch, capped at ×10⁴)"
    # Log-normal mass distribution discretised into size classes
    z = np.linspace(-2.5, 2.5, bins)
    w = np.exp(-z ** 2 / 2)
    w /= w.sum()
    radii0 = (d50_um * gsd ** z) / 2 * 1e-4  # cm
    mass0 = w * dose_mg * 1e-3  # g
    rho = density_g_cm3
    n = mass0 / (rho * 4 / 3 * math.pi * radii0 ** 3)
    cs = cs_mg_ml * 1e-3  # g/cm3
    hmax = h_max_um * 1e-4

    # Explicit march with the exact update for the diffusion-limited regime:
    # r > h_max: dr/dt = -D(cs-c)/(rho*h_max);  r <= h_max: d(r^2)/dt = -2D(cs-c)/rho
    dt = 0.5
    t_run = max(t_end_min - lag_min, 1e-3) * 60
    steps = int(t_run / dt)
    r = radii0.copy()
    record = max(1, steps // 120)
    t_eval, remaining = [0.0], [mass0.sum()]
    vol_const = rho * 4 / 3 * math.pi
    for k in range(1, steps + 1):
        rem = float(np.sum(n * vol_const * r ** 3))
        c = (mass0.sum() - rem) / volume_ml
        drive = diff_cm2_s * (cs - c) / rho
        big = r > hmax
        r = np.where(big, r - drive / hmax * dt, np.sqrt(np.maximum(r ** 2 - 2 * drive * dt, 0.0)))
        r = np.maximum(r, 0.0)
        if k % record == 0 or k == steps:
            t_eval.append(k * dt)
            remaining.append(float(np.sum(n * vol_const * r ** 3)))
    t_eval = np.array(t_eval)
    remaining = np.array(remaining)
    pct = 100 * (1 - remaining / mass0.sum())
    times = [0.0] + [round(float(x), 2) for x in lag_min + t_eval / 60]
    pct = [0.0] + [round(float(p), 2) for p in pct]

    def t_at(target: float) -> Optional[float]:
        for (t0, p0), (t1, p1) in zip(zip(times, pct), zip(times[1:], pct[1:])):
            if p1 >= target > p0:
                return round(t0 + (target - p0) / (p1 - p0) * (t1 - t0), 1)
        return None

    at_q = float(np.interp(q_time_min, times, pct))
    sink = cs_mg_ml * volume_ml / dose_mg
    plateau = min(100.0, 100 * sink)
    verdict = "pass" if at_q >= q_pct else "fail"
    why = []
    if sink < 1:
        why.append(f"Not enough solubility to dissolve the dose: the {volume_ml:g} mL medium holds only {plateau:.0f}% of it (sink index {sink:.2f}).")
    elif sink < 3:
        why.append(f"Non-sink conditions (sink index {sink:.2f} < 3): rate slows as the medium approaches saturation.")
    if verdict == "fail" and sink >= 1:
        why.append("Particles dissolve too slowly: reduce particle size or improve wetting/disintegration.")
    return {
        "times_min": times, "pct": pct, "at_q": round(at_q, 1), "t50": t_at(50), "t85": t_at(85), "plateau_pct": round(plateau, 1),
        "sink_index": round(sink, 2), "verdict": verdict, "why": why,
        "spec": {"q_pct": q_pct, "q_time_min": q_time_min},
        "assumptions": [
            f"Noyes-Whitney with a Hintz-Johnson diffusion layer (h = min(r, {h_max_um:g} µm)), log-normal PSD d50 {d50_um:g} µm, GSD {gsd:g}",
            f"Diffusivity {diff_cm2_s:.2e} cm²/s (Hayduk-Laudie from McGowan volume unless overridden)",
            f"Particles released after a {lag_min:g} min disintegration lag; perfectly mixed {volume_ml:g} mL vessel",
            ion_note or "Neutral form only (no pKa given): pH has no effect",
        ],
        "solubility_mg_ml": float(f"{cs_mg_ml:.4g}"), "intrinsic_mg_ml": float(f"{intrinsic:.4g}"),
    }


# --- compaction ------------------------------------------------------------------------------------

MATERIALS = {
    # Typical literature ranges; editable in the UI. Py: Heckel mean yield pressure.
    "plastic": {"label": "Plastic (MCC-like)", "py_mpa": 80.0, "sigma0_mpa": 12.0, "b": 7.0},
    "mixed": {"label": "Mixed blend", "py_mpa": 140.0, "sigma0_mpa": 9.0, "b": 7.5},
    "brittle": {"label": "Brittle (lactose / DCP-like)", "py_mpa": 250.0, "sigma0_mpa": 7.0, "b": 8.0},
}
TARGET_TENSILE_MPA = 1.7  # Pitt & Heasley (2013): ~1.7 MPa gives acceptable friability for most tablets


def compaction(py_mpa: float, sigma0_mpa: float, b: float, d0: float = 0.40, target_mpa: float = TARGET_TENSILE_MPA,
               p_max_mpa: float = 350.0) -> dict[str, Any]:
    if py_mpa <= 0 or not 0 < d0 < 1:
        raise ValueError("yield pressure must be positive and initial relative density between 0 and 1")
    p = np.linspace(0, p_max_mpa, 71)
    a = math.log(1 / (1 - d0))
    rel_density = 1 - np.exp(-(p / py_mpa + a))
    porosity = 1 - rel_density
    tensile = sigma0_mpa * np.exp(-b * porosity)
    hit = np.nonzero(tensile >= target_mpa)[0]
    p_target = float(p[hit[0]]) if len(hit) else None
    sf_target = float(rel_density[hit[0]]) if len(hit) else None
    notes = []
    if p_target is None:
        notes.append(f"Never reaches {target_mpa} MPa within {p_max_mpa:g} MPa: add a more plastic binder or a dry binder.")
    elif p_target > 250:
        notes.append("Needs very high pressure: tooling stress and lamination risk; consider a more compactable filler.")
    if sf_target and sf_target > 0.92:
        notes.append("Solid fraction above 0.92 at the target strength: slower disintegration and dissolution are likely.")
    return {"pressure_mpa": p.round(1).tolist(), "solid_fraction": rel_density.round(4).tolist(), "porosity": porosity.round(4).tolist(),
            "tensile_mpa": tensile.round(3).tolist(), "p_for_target": p_target, "sf_at_target": round(sf_target, 3) if sf_target else None,
            "target_mpa": target_mpa, "notes": notes,
            "assumptions": [f"Heckel: ln(1/(1−D)) = P/Py + A, Py {py_mpa:g} MPa, initial relative density {d0:g}",
                            f"Ryshkewitch-Duckworth: σ = σ0·exp(−b·ε), σ0 {sigma0_mpa:g} MPa, b {b:g}",
                            f"Target tensile strength {target_mpa} MPa (friability guidance, Pitt & Heasley 2013)"]}


# --- fluid bed -------------------------------------------------------------------------------------

def fluid_bed(inlet_c: float, dew_point_c: float, air_m3_h: float, spray_g_min: float, solids_pct: float = 8.0,
              heat_loss_pct: float = 10.0, pressure_pa: float = 101325.0) -> dict[str, Any]:
    import psychrolib as ps
    ps.SetUnitSystem(ps.SI)
    if dew_point_c >= inlet_c:
        raise ValueError("dew point must be below the inlet temperature")
    w_in = ps.GetHumRatioFromTDewPoint(dew_point_c, pressure_pa)
    rho_moist = ps.GetMoistAirDensity(inlet_c, w_in, pressure_pa)
    m_da = air_m3_h / 3600 * rho_moist / (1 + w_in)  # kg dry air / s
    water = spray_g_min / 60 / 1000 * (1 - solids_pct / 100)  # kg/s
    h_in = ps.GetMoistAirEnthalpy(inlet_c, w_in) / 1000  # kJ/kg dry air
    t_wb = ps.GetTWetBulbFromHumRatio(inlet_c, w_in, pressure_pa)
    w_wb = ps.GetSatHumRatio(t_wb, pressure_pa)
    capacity = m_da * (w_wb - w_in)  # kg water/s the air can take up adiabatically
    load = water / capacity if capacity > 0 else float("inf")
    loss = heat_loss_pct / 100 * m_da * 1.006 * (inlet_c - 20.0)  # kW lost through walls
    w_out = w_in + water / m_da
    h_out = h_in - loss / m_da
    t_out = (h_out - 2501 * w_out) / (1.006 + 1.86 * w_out)
    # More water than the air can evaporate: the outlet sits at the wet-bulb, saturated.
    saturated = load >= 1.0 or t_out <= t_wb or w_out >= ps.GetSatHumRatio(t_out, pressure_pa)
    if saturated:
        t_out, rh_out = t_wb, 1.0
    else:
        rh_out = ps.GetRelHumFromHumRatio(t_out, w_out, pressure_pa)
    if load > 0.85 or saturated:
        regime, msg = "overwetting", "The spray uses almost all of the air's drying capacity: wet mass builds up, granules grow uncontrolled and the bed can collapse."
    elif load < 0.30:
        regime, msg = "spray-drying", "Most droplets can dry before reaching the particles: binder is lost as fines and granule growth is weak."
    else:
        regime, msg = "controlled", "Evaporation balances the spray: steady wet granulation."
    return {"outlet_c": round(t_out, 1), "outlet_rh_pct": round(100 * rh_out, 1), "wet_bulb_c": round(t_wb, 1),
            "inlet_rh_pct": round(100 * ps.GetRelHumFromHumRatio(inlet_c, w_in, pressure_pa), 2),
            "drying_load_pct": round(100 * load, 1), "evaporation_capacity_g_min": round(capacity * 60000, 1),
            "water_g_min": round(water * 60000, 1), "regime": regime, "message": msg,
            "assumptions": ["Steady-state air-side mass and energy balance, psychrometrics from psychrolib (ASHRAE)",
                            f"Heat loss {heat_loss_pct:g}% of inlet sensible heat above 20 °C; spray at room temperature",
                            "Regimes by drying load (share of adiabatic-saturation capacity used): <30% spray-drying, 30-85% controlled, >85% overwetting (rule of thumb)"]}
