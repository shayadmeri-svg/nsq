"""From dissolution to plasma exposure: a bioequivalence risk estimate.

One-compartment model with first-order absorption of *dissolved* drug:

    dG/dt = dose·F·r(t) − ka·G        (dissolved drug in the gut; r = dissolution rate)
    dC/dt = ka·G/V − (CL/V)·C         (plasma concentration)

Absorption only happens inside an absorption window (small-intestine transit,
~3–4 h by default): drug that dissolves later is lost. That is how a slow or
incomplete dissolution profile turns into lower Cmax and AUC.

A test product (the dissolution profile being judged) is compared with a
reference that dissolves fast and completely. The Cmax and AUC ratios are
point estimates only: a real bioequivalence decision needs a crossover study
and 90% confidence intervals within 80–125%.

PK parameters (clearance, volume, absorption rate, bioavailability) are not in
any open database in bulk; they are inputs with neutral defaults.
"""

from __future__ import annotations

from typing import Any

import numpy as np

BE_LOW, BE_HIGH = 80.0, 125.0


def simulate(times_min: list[float], pct: list[float], dose_mg: float, cl_l_h: float, v_l: float, ka_h: float,
             f_abs: float = 1.0, window_h: float = 4.0, t_end_h: float = 24.0, in_vivo_scale: float = 1.0) -> dict[str, Any]:
    """Plasma profile from a dissolution profile (% dissolved vs minutes)."""
    if min(dose_mg, cl_l_h, v_l, ka_h) <= 0:
        raise ValueError("dose, clearance, volume and absorption rate must be positive")
    dt = 1 / 60  # h
    t = np.arange(0, t_end_h + dt, dt)
    # in-vivo release = in-vitro profile, time-scaled (Levy factor), held at its last value
    diss = np.interp(t * 60 / max(in_vivo_scale, 1e-6), times_min, np.asarray(pct, float) / 100, right=pct[-1] / 100)
    rel = np.diff(diss, prepend=0.0) * dose_mg * f_abs  # mg released in each step
    k = cl_l_h / v_l
    g = c = 0.0
    conc = np.empty_like(t)
    absorbed = 0.0
    for i, ti in enumerate(t):
        g += rel[i]
        if ti <= window_h:
            a = g * (1 - np.exp(-ka_h * dt))
            g -= a
            absorbed += a
            c += a / v_l
        c *= np.exp(-k * dt)
        conc[i] = c  # mg/L
    auc = float(np.trapz(conc, t))
    auc_inf = auc + float(conc[-1] / k)
    i_max = int(np.argmax(conc))
    step = max(1, len(t) // 240)
    return {"t_h": t[::step].round(3).tolist(), "conc_mg_l": [float(f"{x:.4g}") for x in conc[::step]],
            "cmax": float(f"{conc[i_max]:.4g}"), "tmax_h": round(float(t[i_max]), 2), "auc": float(f"{auc:.4g}"),
            "auc_inf": float(f"{auc_inf:.4g}"), "absorbed_pct": round(100 * absorbed / (dose_mg * f_abs), 1) if dose_mg else 0.0,
            "half_life_h": round(float(np.log(2) / k), 2)}


MIN_REF_ABSORBED_PCT = 80.0  # below this the "reference" itself is not a meaningful comparator


def compare(test: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any]:
    """Test/reference Cmax and AUC ratios, with a verdict only where it follows from the numbers.

    BE is decided on the 90% CI of the geometric mean ratio from a crossover study, which a
    single simulated profile can't give. What does follow: a point estimate outside 80-125%
    means the CI can't be inside it either. A point estimate inside says nothing about the CI.
    No ratio at all when the reference barely absorbs (0/0 or near-zero/near-zero)."""
    ref_abs = float(ref.get("absorbed_pct") or 0.0)
    if ref.get("cmax", 0) <= 0 or ref.get("auc_inf", 0) <= 0 or ref_abs < MIN_REF_ABSORBED_PCT:
        return {"cmax_ratio": None, "auc_ratio": None, "risk": "not_assessable", "limits": [BE_LOW, BE_HIGH],
                "message": f"Not assessable: the reference itself absorbs only {ref_abs:g}% of the dose in this model "
                           f"(needs ≥ {MIN_REF_ABSORBED_PCT:g}%), so a ratio would compare two near-zero numbers. "
                           "Usually this means the solubility input is wrong for this molecule (for example an ionisable drug with no pKa)."}

    def ratio(a: float, b: float) -> float:
        return round(100 * a / b, 1)
    cmax_r, auc_r = ratio(test["cmax"], ref["cmax"]), ratio(test["auc_inf"], ref["auc_inf"])
    inside = BE_LOW <= cmax_r <= BE_HIGH and BE_LOW <= auc_r <= BE_HIGH
    if inside:
        risk, msg = "inside", ("Point estimates are inside 80–125%. That alone does not show bioequivalence: the limits apply to "
                               "the 90% confidence interval from a crossover study, which also depends on subject variability.")
    else:
        risk, msg = "outside", ("A point estimate is outside 80–125%, so its 90% confidence interval cannot lie inside the limits: "
                                "under these inputs this dissolution difference would fail bioequivalence.")
    return {"cmax_ratio": cmax_r, "auc_ratio": auc_r, "risk": risk, "message": msg, "limits": [BE_LOW, BE_HIGH]}
