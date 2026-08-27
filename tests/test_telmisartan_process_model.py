"""Regression tests for the telmisartan manufacturing process model.

Locks the CQA formulas, the failure-mode precedence, and the range
contracts so a future mechanistic model swap is a conscious, reviewed
behavior change rather than a silent drift. The model is pure Python;
these tests run without FastAPI/Streamlit.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_model():
    """Load the process_models package standalone (no simulator venv deps)."""
    pkg_dir = REPO / "simulator" / "process_models"
    spec = importlib.util.spec_from_file_location(
        "process_models", pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["process_models"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load_model()


# ---------------------------------------------------------------------------
# Stage 1 — CQA formulas
# ---------------------------------------------------------------------------
def test_stage1_ph_tracks_naoh_and_caps_at_14():
    assert M.simulate_stage1(M.Stage1Params(naoh_ratio_pct=100)).ph == 11.2
    assert abs(M.simulate_stage1(M.Stage1Params(naoh_ratio_pct=70)).ph - 9.94) < 1e-9
    assert M.simulate_stage1(M.Stage1Params(naoh_ratio_pct=130)).ph == 12.46
    # Capped: a huge NaOH ratio cannot push pH past 14.
    assert M.simulate_stage1(M.Stage1Params(naoh_ratio_pct=1000)).ph == 14.0


def test_stage1_viscosity_regimes():
    # In-band: 320 cP baseline across the 30-50 C optimum.
    for t in (30, 35, 40, 45, 50):
        assert M.simulate_stage1(M.Stage1Params(mixing_temp_c=t)).viscosity_cp == 320.0
    # Hot shear: thins linearly above 50 C, floored at 80.
    assert M.simulate_stage1(M.Stage1Params(mixing_temp_c=60)).viscosity_cp == 210.0
    assert M.simulate_stage1(M.Stage1Params(mixing_temp_c=70)).viscosity_cp == 100.0
    assert M.simulate_stage1(M.Stage1Params(mixing_temp_c=200)).viscosity_cp == 80.0
    # Cold sludge: thickens linearly below 30 C.
    assert M.simulate_stage1(M.Stage1Params(mixing_temp_c=20)).viscosity_cp == 470.0
    assert M.simulate_stage1(M.Stage1Params(mixing_temp_c=15)).viscosity_cp == 545.0


# ---------------------------------------------------------------------------
# Stage 1 — failure-mode precedence
# ---------------------------------------------------------------------------
def test_stage1_optimal_baseline():
    r = M.simulate_stage1(M.Stage1Params())  # defaults: 40 C, 100%, 45 min
    assert r.severity == M.Severity.OPTIMAL
    assert r.failure_mode == M.FailureMode.NONE


def test_stage1_crystalline_danger_takes_precedence_over_polymer_shear():
    # temp > 50 (polymer shear) AND naoh < 90 (crystalline) -> crystalline wins.
    r = M.simulate_stage1(M.Stage1Params(mixing_temp_c=55, naoh_ratio_pct=80, mixing_time_min=45))
    assert r.severity == M.Severity.DANGER
    assert r.failure_mode == M.FailureMode.CRYSTALLINE_PRECIPITATION


def test_stage1_low_naoh_is_danger():
    r = M.simulate_stage1(M.Stage1Params(naoh_ratio_pct=85))
    assert r.severity == M.Severity.DANGER
    assert r.failure_mode == M.FailureMode.CRYSTALLINE_PRECIPITATION


def test_stage1_short_mix_time_is_danger():
    r = M.simulate_stage1(M.Stage1Params(mixing_time_min=20))
    assert r.severity == M.Severity.DANGER
    assert r.failure_mode == M.FailureMode.CRYSTALLINE_PRECIPITATION


def test_stage1_cold_temp_is_danger():
    r = M.simulate_stage1(M.Stage1Params(mixing_temp_c=25))
    assert r.severity == M.Severity.DANGER
    assert r.failure_mode == M.FailureMode.CRYSTALLINE_PRECIPITATION


def test_stage1_polymer_shear_warning():
    # Hot but otherwise valid -> polymer shear warning, not crystalline.
    r = M.simulate_stage1(M.Stage1Params(mixing_temp_c=55, naoh_ratio_pct=100, mixing_time_min=45))
    assert r.severity == M.Severity.WARNING
    assert r.failure_mode == M.FailureMode.POLYMER_SHEAR


# ---------------------------------------------------------------------------
# Stage 2 — CQA formulas
# ---------------------------------------------------------------------------
def test_stage2_baseline_cqas():
    r = M.simulate_stage2(M.Stage2Params())  # 60 C, 50 g/min, 2.0 bar
    assert abs(r.bed_moisture_pct - 2.4) < 1e-9
    assert abs(r.mean_granule_size_um - 180.0) < 1e-9


def test_stage2_moisture_tracks_evap_deficit():
    # spray high, temp low -> wet.
    r = M.simulate_stage2(M.Stage2Params(spray_rate_g_min=100, inlet_air_temp_c=35))
    deficit = (100 / 50) - (35 / 60)
    assert abs(r.bed_moisture_pct - (2.4 + deficit * 3.5)) < 1e-9
    # spray low, temp high -> dry, floored at 0.5.
    r2 = M.simulate_stage2(M.Stage2Params(spray_rate_g_min=15, inlet_air_temp_c=85))
    assert r2.bed_moisture_pct >= 0.5


def test_stage2_granule_size_pressure_fines():
    # Higher atomization pressure -> smaller granules.
    base = M.simulate_stage2(M.Stage2Params(atomization_pressure_bar=2.0)).mean_granule_size_um
    fine = M.simulate_stage2(M.Stage2Params(atomization_pressure_bar=3.5)).mean_granule_size_um
    assert fine < base
    # Floored at 40 um.
    r = M.simulate_stage2(M.Stage2Params(spray_rate_g_min=15, inlet_air_temp_c=85, atomization_pressure_bar=4.0))
    assert r.mean_granule_size_um >= 40.0


# ---------------------------------------------------------------------------
# Stage 2 — failure-mode precedence
# ---------------------------------------------------------------------------
def test_stage2_over_wetting_danger_takes_precedence():
    # moisture > 5.5 -> bed collapse, even if pressure would also trigger fines.
    r = M.simulate_stage2(M.Stage2Params(spray_rate_g_min=100, inlet_air_temp_c=35, atomization_pressure_bar=3.5))
    assert r.severity == M.Severity.DANGER
    assert r.failure_mode == M.FailureMode.BED_OVER_WETTING


def test_stage2_spray_drying_fines_warning():
    # High pressure alone -> fines warning, moisture in-band.
    r = M.simulate_stage2(M.Stage2Params(atomization_pressure_bar=3.5, spray_rate_g_min=50, inlet_air_temp_c=60))
    assert r.severity == M.Severity.WARNING
    assert r.failure_mode == M.FailureMode.SPRAY_DRYING_FINES


def test_stage2_hot_inlet_is_fines_warning():
    r = M.simulate_stage2(M.Stage2Params(inlet_air_temp_c=80))
    assert r.severity == M.Severity.WARNING
    assert r.failure_mode == M.FailureMode.SPRAY_DRYING_FINES


def test_stage2_dry_bed_is_fines_warning():
    # moisture < 1.0 -> fines.
    r = M.simulate_stage2(M.Stage2Params(spray_rate_g_min=15, inlet_air_temp_c=85))
    assert r.bed_moisture_pct < 1.0
    assert r.severity == M.Severity.WARNING
    assert r.failure_mode == M.FailureMode.SPRAY_DRYING_FINES


def test_stage2_optimal_in_band():
    r = M.simulate_stage2(M.Stage2Params(inlet_air_temp_c=60, spray_rate_g_min=50, atomization_pressure_bar=2.0))
    assert r.severity == M.Severity.OPTIMAL
    assert r.failure_mode == M.FailureMode.NONE


# ---------------------------------------------------------------------------
# Range contract — the API and UI read these; drift here would desync sliders.
# ---------------------------------------------------------------------------
def test_ranges_cover_defaults_and_extremes():
    for key, spec in M.STAGE1_RANGES.items():
        assert {"min", "max", "step"}.issubset(spec)
        assert spec["min"] < spec["max"]
    for key, spec in M.STAGE2_RANGES.items():
        assert {"min", "max", "step"}.issubset(spec)
        assert spec["min"] < spec["max"]
    # Defaults must lie inside the ranges.
    d1 = M.Stage1Params()
    assert M.STAGE1_RANGES["mixing_temp_c"]["min"] <= d1.mixing_temp_c <= M.STAGE1_RANGES["mixing_temp_c"]["max"]
    assert M.STAGE1_RANGES["naoh_ratio_pct"]["min"] <= d1.naoh_ratio_pct <= M.STAGE1_RANGES["naoh_ratio_pct"]["max"]
    assert M.STAGE1_RANGES["mixing_time_min"]["min"] <= d1.mixing_time_min <= M.STAGE1_RANGES["mixing_time_min"]["max"]
    d2 = M.Stage2Params()
    for attr, key in [
        ("inlet_air_temp_c", "inlet_air_temp_c"),
        ("spray_rate_g_min", "spray_rate_g_min"),
        ("atomization_pressure_bar", "atomization_pressure_bar"),
    ]:
        assert M.STAGE2_RANGES[key]["min"] <= getattr(d2, attr) <= M.STAGE2_RANGES[key]["max"]


# ---------------------------------------------------------------------------
# Determinism — same inputs, same outputs (the model is the seam).
# ---------------------------------------------------------------------------
def test_model_is_deterministic():
    p1 = M.Stage1Params(mixing_temp_c=42, naoh_ratio_pct=95, mixing_time_min=35)
    p2 = M.Stage2Params(inlet_air_temp_c=58, spray_rate_g_min=55, atomization_pressure_bar=2.2)
    assert M.simulate_stage1(p1) == M.simulate_stage1(p1)
    assert M.simulate_stage2(p2) == M.simulate_stage2(p2)


if __name__ == "__main__":
    # Run as: python tests/test_telmisartan_process_model.py
    import inspect
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            raise
    print(f"{passed}/{len(fns)} passed")