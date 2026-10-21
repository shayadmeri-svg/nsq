"""chem.batch_data: apparatus files read into one row per batch, charted, diagnosed, and turned into a twin calibration."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from chem import batch_data as bd  # noqa: E402
from chem import process_twin as twin  # noqa: E402


def _load(fmt: str):
    df = bd.read_table(bd.sample_csv(fmt).encode(), f"{fmt}.csv")
    det, mapping = bd.detect_format(list(df.columns))
    return det, mapping, bd.aggregate(df, det, mapping), df


@pytest.mark.parametrize("fmt", [f["id"] for f in bd.FORMATS])
def test_every_sample_file_is_recognised_and_fully_mapped(fmt):
    det, mapping, batches, df = _load(fmt)
    assert det == fmt
    assert set(mapping.values()) == set(df.columns)
    assert len(batches) == 10


def test_plant_headers_with_units_and_abbreviations():
    fmt, m = bd.detect_format(["Batch No.", "Main Compression Force (kN)", "Punch Dia (mm)", "Tablet Wt (mg)", "Turret Speed (rpm)"])
    assert fmt == "press" and m["punch_diameter_mm"] == "Punch Dia (mm)" and m["force_kn"] == "Main Compression Force (kN)"
    # a unit in the header decides the field: CFM is not m³/h
    _, m = bd.detect_format(["Lot Number", "Inlet Temp (°C)", "RH (%)", "Air Flow (CFM)", "LOD %", "Elapsed Time (min)"])
    assert m["air_cfm"] == "Air Flow (CFM)" and "air_m3_h" not in m


def test_derived_values_follow_their_equations():
    import pandas as pd

    df = pd.DataFrame({"batch_no": ["B1"] * 5, "force_kn": ["10"] * 5, "punch_diameter_mm": ["10"] * 5,
                       "tablet_weight_mg": ["98", "99", "100", "101", "102"]})
    v = bd.aggregate(df, "press", {c: c for c in df.columns})["B1"]["values"]
    assert v["pressure_mpa"] == pytest.approx(10_000 / (math.pi * 25), rel=1e-3)  # F / (πd²/4)
    assert v["weight_rsd_pct"] == pytest.approx(100 * 1.5811 / 100, rel=1e-3)
    assert bd.tensile_mpa(100, 10, 4) == pytest.approx(2 * 100 / (math.pi * 40))  # Fell & Newton
    assert bd.dew_point_c(25, 100) == pytest.approx(25, abs=0.01)  # saturated air: dew point = temperature
    assert bd.dew_point_c(25, 50) == pytest.approx(13.9, abs=0.2)


def test_merged_files_find_the_two_example_excursions():
    a = bd.analyse(bd.merge([{"name": f["id"], "batches": _load(f["id"])[2]} for f in bd.FORMATS]))
    diag = {d["batch"]: d for d in a["diagnoses"]}
    assert set(diag) == {"EX007", "EX009"}
    # each failed batch's most deviant linked parameter is the one the example was built with
    assert diag["EX007"]["deviations"][0]["field"] == "pressure_mpa" and diag["EX007"]["deviations"][0]["linked"]
    assert diag["EX009"]["deviations"][0]["field"] == "drying_min" and diag["EX009"]["deviations"][0]["z"] < -2


def test_control_chart_rules():
    assert [s["rule"] for s in bd.nelson([0, 0, 0, 0, 10], 0, 1)] == [1]
    assert 2 in [s["rule"] for s in bd.nelson([1] * 9, 0, 1)]
    assert 3 in [s["rule"] for s in bd.nelson([1, 2, 3, 4, 5, 6], 3.5, 10)]


def test_calibration_feeds_the_twin():
    a = bd.analyse(bd.merge([{"name": "s", "batches": _load("batch_summary")[2]}]))
    cal = a["calibration"]
    assert set(cal["baseline"]) <= set(bd.PARAM_IDS) and "pressure_mpa" in cal["nor"]
    mol = twin.Molecule("Paracetamol", 500, 14.0, 9.9e-6)
    out = twin.run(mol, None, analyses=False, baseline=cal["baseline"], nor=cal["nor"])
    assert out["baseline"]["pressure_mpa"] == pytest.approx(cal["baseline"]["pressure_mpa"])
    lo, hi = cal["nor"]["pressure_mpa"]
    p = next(p for u in out["unit_ops"] for p in u["params"] if p["id"] == "pressure_mpa")
    assert (p["lo"], p["hi"]) == (lo, hi) and p["plant"]
    # outside run() the generic ranges are back
    assert twin._pb()["pressure_mpa"].lo == twin.P_BY_ID["pressure_mpa"].lo
