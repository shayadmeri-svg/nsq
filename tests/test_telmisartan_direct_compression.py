"""Regression tests for the telmisartan Direct-Compression route and the
route registry/selector. Locks the DC CQA formulas, the failure-mode
precedence (dissolution failure > sticking > under-blending > meglumine
deficit), and the uniform route contract so the API/UI selector can rely on
it. Pure Python; no FastAPI/Streamlit needed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_model():
    pkg_dir = REPO / "simulator" / "process_models"
    spec = importlib.util.spec_from_file_location(
        "process_models", pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["process_models"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load_model()
DC = M.telmisartan_dc


# ---------------------------------------------------------------------------
# Route registry — the selector contract
# ---------------------------------------------------------------------------
def test_routes_registry_lists_both_routes():
    ids = sorted(M.ROUTES.keys())
    assert ids == ["direct_compression", "naoh_fluidbed"]


def test_route_metadata_shape_is_uniform():
    meta = M.route_metadata()
    assert len(meta) == 2
    for entry in meta:
        assert {"id", "label", "description", "stages"} <= set(entry)
        for stage in entry["stages"]:
            assert {"id", "label", "cpps", "cqas"} <= set(stage)
            for cpp in stage["cpps"]:
                assert {"name", "label", "unit", "min", "max", "step", "default"} <= set(cpp)
            for cqa in stage["cqas"]:
                assert {"name", "label", "unit"} <= set(cqa)


def test_every_route_simulate_returns_uniform_shape():
    for route_id, mod in M.ROUTES.items():
        defaults = {cpp["name"]: cpp["default"] for stage in mod.STAGES for cpp in stage["cpps"]}
        out = mod.simulate(defaults)
        assert out["route_id"] == route_id
        assert out["route_label"]
        assert len(out["stages"]) == 2
        for st in out["stages"]:
            assert {"stage_id", "label", "cqas", "severity", "failure_mode", "title", "description"} <= set(st)
        assert out["overall_severity"] in {"optimal", "warning", "danger"}
        # Defaults sit inside the validated corridor -> optimal overall.
        assert out["overall_severity"] == "optimal", route_id


# ---------------------------------------------------------------------------
# Stage 1 — dry blending CQAs
# ---------------------------------------------------------------------------
def test_dc_stage1_uniformity_degrades_below_20_min():
    assert M.simulate_dc_stage1(M.DCStage1Params(blending_time_min=20)).content_uniformity_rsd == 2.0
    # 15 min -> 2.0 + 5*0.3 = 3.5
    assert abs(M.simulate_dc_stage1(M.DCStage1Params(blending_time_min=15)).content_uniformity_rsd - 3.5) < 1e-9
    # 5 min -> 2.0 + 15*0.3 = 6.5
    assert abs(M.simulate_dc_stage1(M.DCStage1Params(blending_time_min=5)).content_uniformity_rsd - 6.5) < 1e-9


def test_dc_stage1_potency_tracks_meglumine_deficit():
    assert M.simulate_dc_stage1(M.DCStage1Params(meglumine_ratio_pct=100)).blend_potency_pct == 100.0
    # 70% meglumine -> 100 - 30*0.1 = 97.0
    assert abs(M.simulate_dc_stage1(M.DCStage1Params(meglumine_ratio_pct=70)).blend_potency_pct - 97.0) < 1e-9


# ---------------------------------------------------------------------------
# Stage 1 — failure-mode precedence (under_blending > meglumine_deficit > optimal)
# ---------------------------------------------------------------------------
def test_dc_stage1_under_blending_warning_below_15_min():
    r = M.simulate_dc_stage1(M.DCStage1Params(blending_time_min=10, meglumine_ratio_pct=100))
    assert r.severity == M.Severity.WARNING
    assert r.failure_mode == M.FailureMode.UNDER_BLENDING


def test_dc_stage1_meglumine_deficit_warning_below_85():
    # Blend time in-band, meglumine low -> meglumine_deficit.
    r = M.simulate_dc_stage1(M.DCStage1Params(blending_time_min=20, meglumine_ratio_pct=80))
    assert r.severity == M.Severity.WARNING
    assert r.failure_mode == M.FailureMode.MEGLUMINE_DEFICIT


def test_dc_stage1_under_blending_takes_precedence_over_meglumine_deficit():
    # Both conditions true (time<15 AND meglumine<85) -> under_blending wins.
    r = M.simulate_dc_stage1(M.DCStage1Params(blending_time_min=10, meglumine_ratio_pct=75))
    assert r.failure_mode == M.FailureMode.UNDER_BLENDING


def test_dc_stage1_optimal_in_corridor():
    r = M.simulate_dc_stage1(M.DCStage1Params(blending_time_min=20, meglumine_ratio_pct=100))
    assert r.severity == M.Severity.OPTIMAL
    assert r.failure_mode == M.FailureMode.NONE


# ---------------------------------------------------------------------------
# Stage 2 — compression CQAs (chained on Stage 1 CPPs)
# ---------------------------------------------------------------------------
def test_dc_stage2_hardness_tracks_press_speed():
    # 32 RPM -> 8.0 kN
    assert M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=32),
                                blending_time_min=20, meglumine_ratio_pct=100).tablet_hardness_kn == 8.0
    # 45 RPM -> 8.0 + 13*0.15 = 9.95
    assert abs(M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=45),
                blending_time_min=20, meglumine_ratio_pct=100).tablet_hardness_kn - 9.95) < 1e-9
    # Clamped at 14 for extreme speed.
    assert M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=200),
                                blending_time_min=20, meglumine_ratio_pct=100).tablet_hardness_kn == 14.0


def test_dc_stage2_dissolution_baseline_is_90_at_catalog_ideal():
    # Catalog ideal: 20 min blend, 32 RPM, 100% meglumine -> 90% dissolution (>= 75 spec).
    r = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=32),
                             blending_time_min=20, meglumine_ratio_pct=100)
    assert abs(r.dissolution_pct - 90.0) < 1e-9
    assert r.severity == M.Severity.OPTIMAL


def test_dc_stage2_dissolution_tracks_meglumine_deficit():
    # 80% meglumine -> 90 - 20*0.7 = 76.0 (passes, barely)
    r = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=32),
                             blending_time_min=20, meglumine_ratio_pct=80)
    assert abs(r.dissolution_pct - 76.0) < 1e-9
    assert r.severity == M.Severity.OPTIMAL


def test_dc_stage2_dissolution_failure_danger_below_75():
    # 70% meglumine -> 90 - 30*0.7 = 69.0 (< 75 -> DANGER dissolution_failure)
    r = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=32),
                             blending_time_min=20, meglumine_ratio_pct=70)
    assert r.dissolution_pct < 75.0
    assert r.severity == M.Severity.DANGER
    assert r.failure_mode == M.FailureMode.DISSOLUTION_FAILURE


def test_dc_stage2_over_compression_and_under_blending_stack_into_failure():
    # 5 min blend (-6.0), 60 RPM (-7.0), 100% meglumine -> 90 - 6 - 7 = 77 (passes)
    r = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=60),
                             blending_time_min=5, meglumine_ratio_pct=100)
    assert abs(r.dissolution_pct - 77.0) < 1e-9
    assert r.severity == M.Severity.OPTIMAL
    # Now add meglumine deficit: 5 min, 60 RPM, 80% -> 90 - 6 - 7 - 14 = 63 (fail)
    r2 = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=60),
                              blending_time_min=5, meglumine_ratio_pct=80)
    assert r2.dissolution_pct < 75.0
    assert r2.failure_mode == M.FailureMode.DISSOLUTION_FAILURE


# ---------------------------------------------------------------------------
# Stage 2 — sticking (hygroscopic) precedence below dissolution failure
# ---------------------------------------------------------------------------
def test_dc_stage2_sticking_warning_when_meglumine_excess_and_dissolution_ok():
    # 125% meglumine boosts dissolution (no deficit penalty) -> dissolution high,
    # but meglumine>120 -> sticking_hygroscopic warning.
    r = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=32),
                             blending_time_min=20, meglumine_ratio_pct=125)
    assert r.dissolution_pct >= 75.0
    assert r.severity == M.Severity.WARNING
    assert r.failure_mode == M.FailureMode.STICKING_HYGROSCOPIC


def test_dc_stage2_sticking_and_dissolution_failure_are_mutually_exclusive():
    # High meglumine (>120) removes the meglumine-deficit penalty, so even at the
    # worst blend/press excursion dissolution stays >= 77 (>= 75 spec). Sticking
    # is therefore the verdict whenever meglumine > 120, and dissolution_failure
    # only fires when meglumine is low (< 100). The two modes never co-occur.
    r = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=60),
                             blending_time_min=5, meglumine_ratio_pct=125)
    assert r.dissolution_pct >= 75.0
    assert r.failure_mode == M.FailureMode.STICKING_HYGROSCOPIC
    # And a genuine dissolution failure (low meglumine) has meglumine < 120 so
    # the sticking branch cannot fire — precedence is vacuous by construction.
    fail = M.simulate_dc_stage2(M.DCStage2Params(rotary_press_rpm=32),
                                blending_time_min=20, meglumine_ratio_pct=70)
    assert fail.failure_mode == M.FailureMode.DISSOLUTION_FAILURE


# ---------------------------------------------------------------------------
# Route-level simulate() — overall verdict is the worst stage
# ---------------------------------------------------------------------------
def test_dc_simulate_overall_is_worst_stage():
    # Optimal inputs -> both stages optimal -> overall optimal.
    out = DC.simulate({"blending_time_min": 20, "meglumine_ratio_pct": 100, "rotary_press_rpm": 32})
    assert out["overall_severity"] == "optimal"
    assert out["overall_failure_mode"] == "none"
    # Meglumine deficit that drops dissolution below 75 -> stage2 danger overall.
    out2 = DC.simulate({"blending_time_min": 20, "meglumine_ratio_pct": 70, "rotary_press_rpm": 32})
    assert out2["overall_severity"] == "danger"
    assert out2["overall_failure_mode"] == "dissolution_failure"
    # Under-blending only (meglumine fine, press fine) -> stage1 warning overall.
    out3 = DC.simulate({"blending_time_min": 10, "meglumine_ratio_pct": 100, "rotary_press_rpm": 32})
    assert out3["overall_severity"] == "warning"
    assert out3["overall_failure_mode"] == "under_blending"


def test_dc_ranges_cover_defaults_and_extremes():
    for cpp, spec in M.DC_STAGE1_RANGES.items():
        assert spec["min"] <= 20.0 if cpp == "blending_time_min" else spec["min"] <= 100.0
        assert spec["max"] >= 40.0 if cpp == "blending_time_min" else spec["max"] >= 130.0
    assert M.DC_STAGE2_RANGES["rotary_press_rpm"]["min"] <= 32.0
    assert M.DC_STAGE2_RANGES["rotary_press_rpm"]["max"] >= 45.0


def test_dc_model_is_deterministic():
    p = {"blending_time_min": 18, "meglumine_ratio_pct": 95, "rotary_press_rpm": 40}
    a = DC.simulate(p)
    b = DC.simulate(p)
    assert a == b


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL  {fn.__name__}: {exc}")
            traceback.print_exc()
    print(f"{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)