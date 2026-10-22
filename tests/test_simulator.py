"""edge-agent/simulator.py: four machines in sequence, signals shaped by their settings."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("asyncua")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "edge-agent"))

import simulator as sim  # noqa: E402


def _run(cfg, minutes):
    e = sim.Engine(cfg)
    seen: dict[str, dict[str, list]] = {}
    for _ in range(minutes):
        e.step(1.0)
        for m, (b, v, _product) in e.readings().items():
            if b:
                seen.setdefault(m, {}).setdefault(b, []).append(v)
    return e, seen


def test_batches_flow_through_the_machines_in_order():
    _, seen = _run(sim.defaults(), 600)
    first = {m: sorted(bs)[0] for m, bs in seen.items()}
    assert set(first) == set(sim.ORDER)
    assert len({first[m] for m in sim.ORDER if m != "COATER-1"}) == 1  # the same first batch on every shared machine
    assert first["COATER-1"].startswith("AZI") and all(b.startswith("AZI") for b in seen["COATER-1"])  # only azithromycin is coated
    # at any moment the press works on an earlier batch than the dryer
    assert sorted(seen["PRESS-1"])[-1] < sorted(seen["FBD-1"])[-1]


def test_step_pattern_shortens_every_third_drying_and_leaves_lod_high():
    _, seen = _run(sim.defaults(), 1000)
    fbd = [(int(b.split("-")[-1]), r[-1]) for b, r in sorted(seen["FBD-1"].items())[:-1] if b.startswith("PCM")]  # one product
    short = [last["lod_pct"] for n, last in fbd if n % 3 == 0]
    normal = [last["lod_pct"] for n, last in fbd if n % 3]
    assert short and normal and min(short) > max(normal)


def test_settings_change_the_signals_and_clamp_to_the_range():
    cfg = sim.defaults()
    cfg["apparatus"]["PRESS-1"]["signals"]["force_kn"].update(setpoint=30, noise=0, max=20)
    _, seen = _run(cfg, 600)
    assert {round(r["force_kn"], 6) for rs in seen["PRESS-1"].values() for r in rs} == {20.0}
    cfg["apparatus"]["BLENDER-1"]["enabled"] = False
    _, seen = _run(cfg, 600)
    assert "BLENDER-1" not in seen


def test_each_product_runs_at_its_own_setpoints():
    _, seen = _run(sim.defaults(), 1200)
    w = {pre: [r["tablet_weight_mg"] for b, rs in seen["PRESS-1"].items() if b.startswith(pre) for r in rs] for pre in ("PCM", "AZI")}
    assert 630 < sum(w["PCM"]) / len(w["PCM"]) < 670 and 740 < sum(w["AZI"]) / len(w["AZI"]) < 780
