"""Lab models checked against exact solutions and reference values (no Redis/Postgres needed)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from chem import molecule, pk, product, thermo_props  # noqa: E402


def test_pk_matches_bateman_one_compartment():
    """Instant release + first-order absorption: C(t) = F·D·ka / (V (ka − k)) · (e^−kt − e^−ka·t)."""
    dose, cl, v, ka = 100.0, 10.0, 50.0, 1.0
    k = cl / v
    r = pk.simulate([0, 0.001, 1440], [0, 100, 100], dose, cl, v, ka, window_h=24)
    tmax = math.log(ka / k) / (ka - k)
    cmax = dose * ka / (v * (ka - k)) * (math.exp(-k * tmax) - math.exp(-ka * tmax))
    assert r["cmax"] == pytest.approx(cmax, rel=0.005)
    assert r["tmax_h"] == pytest.approx(tmax, abs=0.03)
    assert r["auc_inf"] == pytest.approx(dose / cl, rel=0.005)  # AUC∞ = F·D/CL
    assert r["half_life_h"] == pytest.approx(math.log(2) / k, abs=0.01)


def test_pk_compare_guards_zero_and_near_zero():
    zero = {"cmax": 0.0, "auc_inf": 0.0, "absorbed_pct": 0.0}
    c = pk.compare(zero, zero)
    assert c["risk"] == "not_assessable" and c["cmax_ratio"] is None and c["auc_ratio"] is None
    tiny = {"cmax": 0.002, "auc_inf": 0.01, "absorbed_pct": 0.2}
    assert pk.compare(tiny, tiny)["risk"] == "not_assessable"
    fast = pk.simulate([0, 5, 10, 30, 360], [0, 90, 100, 100, 100], 100, 10, 50, 1.5)
    assert pk.compare(fast, fast)["risk"] == "inside"


def test_hintz_johnson_monodisperse_shrinking_sphere():
    """r ≤ h: d(r²)/dt = −2·D·Cs/ρ under sink, so fraction dissolved = 1 − (1 − 2DCs·t/(ρ r0²))^1.5."""
    D, cs, rho, r0 = 1e-5, 1e-3, 1.3, 10e-4  # cm²/s, g/cm³, g/cm³, cm (d = 20 µm)
    res = product.dissolution(1.0, cs * 1000, D, d50_um=20, gsd=1.0001, lag_min=0, t_end_min=3, volume_ml=900)
    t_full = rho * r0 ** 2 / (2 * D * cs) / 60  # min
    for t, p in zip(res["times_min"], res["pct"]):
        if 0 < t < t_full:
            exact = 100 * (1 - (1 - t / t_full) ** 1.5)
            assert p == pytest.approx(exact, abs=1.5)  # times are rounded to 0.01 min
    assert res["pct"][-1] == pytest.approx(100, abs=0.1)


def test_fluid_bed_psychrometric_reference_point():
    """No spray-loss case against ASHRAE psychrometrics: 60 °C air, dew point 10 °C."""
    r = product.fluid_bed(60, 10, 300, 1e-6, heat_loss_pct=0)
    assert r["inlet_rh_pct"] == pytest.approx(6.2, abs=0.2)
    assert r["wet_bulb_c"] == pytest.approx(26.3, abs=0.3)
    assert r["outlet_c"] == pytest.approx(60.0, abs=0.1)
    # heat loss now shrinks the drying capacity
    lossy = product.fluid_bed(60, 10, 300, 50, heat_loss_pct=20)
    ideal = product.fluid_bed(60, 10, 300, 50, heat_loss_pct=0)
    assert lossy["evaporation_capacity_g_min"] < ideal["evaporation_capacity_g_min"]
    assert "rule of thumb" in lossy["message"].lower()


def test_joback_is_never_used_for_melting_point_or_enthalpy():
    thermo_props.fusion.cache_clear()
    f = thermo_props.fusion("Cloxacillin", "CC1=C(C(=NO1)c1ccccc1Cl)C(=O)NC1C2SC(C)(C)C(N2C1=O)C(=O)O", None)
    # chemicals' only value for cloxacillin is a Joback estimate of ~750 °C
    assert f["mp_c"] is None or f["mp_c"] < 400
    assert "JOBACK" not in (f["mp_source"] or "").upper() and "JOBACK" not in (f["dh_source"] or "").upper()
    p = thermo_props.fusion("Paracetamol", "CC(=O)Nc1ccc(O)cc1", 169.8)
    assert p["mp_source"] == "experimental (PubChem)" and p["mp_measured"]
    d = thermo_props.fusion("Diclofenac", "OC(=O)Cc1ccccc1Nc1c(Cl)cccc1Cl", 284.0)
    assert d["dh_kind"] == "estimate" and "Walden" in d["dh_source"]  # chemicals has only Joback Hfus for it


def test_solubility_estimate_is_labelled_and_flagged():
    amikacin = molecule.parse("NCCC(O)C(=O)NC1CC(N)C(OC2OC(CN)C(O)C(O)C2O)C(O)C1OC1OC(CO)C(O)C(N)C1O")
    s = molecule.solubility(amikacin, 203.5, -7.9, "XLogP3")
    assert s["kind"] == "estimate" and not s["in_domain"] and "outside model domain" in s["flags"][0]
    ibu = molecule.solubility(molecule.parse("CC(C)Cc1ccc(cc1)C(C)C(=O)O"), 76.0, 3.5, "XLogP3")
    assert ibu["uncertainty"].startswith("±1 log") and any("ionisable" in f for f in ibu["flags"])
    assert ibu["display_mg_ml"] == float(f"{ibu['mg_per_ml']:.1g}")
    amox = molecule.parse("CC1(C)SC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N2C1C(=O)O")
    assert set(molecule.solubility(amox, 194.0)["ionisable_gi"]) == {"acid", "base"}
    assert molecule.solubility(molecule.parse("CC(=O)Nc1ccc(O)cc1"), 169.8)["flags"] == []  # phenol pKa ~9.5: not ionised in the GI range


def test_one_log_p_for_lipinski():
    mol = molecule.parse("CCCCCCCCCCCCCCCCCC(=O)O")
    assert molecule.descriptors(mol, 2.0)["lipinski_violations"] == 0
    assert molecule.descriptors(mol)["lipinski_violations"] == 1  # Crippen > 5


def test_le_bas_diffusivity_benzene():
    """Benzene in water at 25 °C: D ≈ 1.02e-5 cm²/s (Wilke-Chang data); Le Bas volume 96 cm³/mol."""
    v = molecule.le_bas_volume(molecule.parse("c1ccccc1"))
    assert v == pytest.approx(96.0, abs=0.1)
    assert molecule.hayduk_laudie_diffusivity(v, 25.0) == pytest.approx(1.02e-5, rel=0.1)


def test_crystallisation_curve_covers_slider_range_and_flags_ideal():
    c = thermo_props.curve(151.16, 169.8, 27000, "ethanol")
    assert c["temps_c"][0] <= -10 and c["temps_c"][-1] >= 85
    assert c["ideal"] and not c["solvent_modelled"]
    assert not thermo_props.curve(151.16, 169.8, 27000, "ethanol", gamma=3)["ideal"]
