"""Batch-reactor engine (core/chem/reaction.py): exact solutions, calibration, maps, thermal safety."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from chem import reaction as r  # noqa: E402


def test_engine_matches_closed_form_solutions():
    cases = r.validate()
    failed = [c for c in cases if not c["pass"]]
    assert not failed, failed
    assert len(cases) >= 9


def test_calibration_reproduces_the_anchor_on_every_template():
    for tpl, t, h, y in [("first", 80, 4, 90), ("second", 60, 8, 75), ("consecutive", 90, 6, 84), ("parallel", 25, 12, 88),
                         ("comp_consec", 40, 3, 70), ("reversible", 80, 6, 85)]:
        req = r.build_request({"template": tpl, "temp_c": t, "hours": h})
        cal = r.calibrate(req, t, h, y)
        assert cal["ok"], (tpl, cal)
        assert abs(cal["check_yield_pct"] - y) < 0.01, (tpl, cal["check_yield_pct"])


def test_unreachable_yield_is_reported_not_faked():
    req = r.build_request({"template": "consecutive", "temp_c": 90, "hours": 6})
    cal = r.calibrate(req, 90, 6, 99)
    assert not cal["ok"] and "cannot reach" in cal["reason"]


def test_consecutive_yield_peaks_then_falls_and_map_finds_it():
    req = r.build_request({"template": "consecutive", "temp_c": 90, "hours": 40})
    out = r.builtin(req)
    s = out["summary"]
    assert s["peak_yield_pct"] > s["yield_pct"] and 0 < s["peak_yield_h"] < 40
    m = r.yield_map(req, [70, 90, 110], [1, 5, 20])
    assert m["best"]["yield_pct"] == max(max(row) for row in m["yield_pct"])


def test_fast_and_tight_solvers_agree():
    req = r.build_request({"template": "comp_consec", "temp_c": 50, "hours": 8})
    a, b = r.builtin(req), r.builtin(req, fast=True)
    assert abs(a["summary"]["yield_pct"] - b["summary"]["yield_pct"]) < 0.01


def test_stoessel_classes():
    assert r.safety_class(60, 90, 100, 150)["criticality"] == 1
    assert r.safety_class(60, 130, 100, 150)["criticality"] == 3
    assert r.safety_class(60, 160, 100, 150)["criticality"] == 4  # boils first, decomposition beyond
    assert r.safety_class(60, 160, 180, 150)["criticality"] == 5  # decomposes before it can boil
    assert r.safety_class(60, 90, 180, 150)["criticality"] == 2
    assert r.safety_class(60, 90, None, None)["criticality"] is None
