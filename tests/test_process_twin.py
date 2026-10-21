"""chem.process_twin: errors injected at a process parameter travel to the quality tests they physically affect."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from chem import process_twin as T  # noqa: E402

PARA = T.Molecule("Paracetamol", 650, 22.5, 9.9e-6)
LOW_DOSE = T.Molecule("Low-dose API", 2, 0.5, 8e-6)


def fails(mol, **x):
    return {k for k, v in T.evaluate(mol, x)["fails"].items() if v}


def test_nominal_process_passes_every_test():
    assert fails(PARA) == set()


def test_injected_errors_hit_the_expected_tests():
    assert "disintegration" in fails(PARA, pressure_mpa=280)  # over-compression
    assert "lod" in fails(PARA, drying_min=35)  # short drying
    # humid inlet air cuts the evaporation capacity (psychrometrics): a dry that just passes with dry air fails
    assert "lod" not in fails(PARA, drying_min=51) and "lod" in fails(PARA, drying_min=51, dew_point_c=26)
    assert "assay" in fails(PARA, api_potency_pct=93)  # sub-potent API lot
    assert "strength" in fails(PARA, pressure_mpa=80)  # under-compression


def test_coarse_api_breaks_content_uniformity_only_for_a_low_dose():
    # Yalkowsky & Bolton: the random-mix limit scales with √(particle mass / dose)
    assert "uniformity" in fails(LOW_DOSE, api_d50_um=100)
    assert "uniformity" not in fails(PARA, api_d50_um=100)


def test_tablet_geometry_is_realistic():
    i = T.evaluate(PARA, {})["intermediate"]
    assert 700 < i["tablet_mg"] < 900 and 3 < i["thickness_mm"] < 8 and 10 < i["diameter_mm"] < 15


def test_tipping_point_brackets_the_limit():
    tips = T.tipping_points(PARA, {p.id: p.nominal for p in T.PARAMS}, n=15)
    near = tips["pressure_mpa"]["disintegration"]["nearest"]
    assert near and near["direction"] == "above"
    over = T.evaluate(PARA, {"pressure_mpa": near["at"] * 1.05})["values"]["disintegration"]
    under = T.evaluate(PARA, {"pressure_mpa": near["at"] * 0.95})["values"]["disintegration"]
    assert under <= T.SPECS["dt_max_min"] <= over


def test_withheld_tests_are_not_scored():
    out = T.run(PARA, {"pressure_mpa": 280}, withheld={"dissolution": "pKa unknown"})
    assert out["mc"]["p_fail"]["dissolution"] is None
    node = next(c for c in out["tree"]["children"] if c["id"] == "dissolution")
    assert node["withheld"] == "pKa unknown" and node["fails_now"] is None


def test_every_link_and_parameter_declares_its_basis():
    assert all(p.basis in ("mechanistic", "correlation", "assumed") for p in T.PARAMS)
    assert all(link["basis"] in ("mechanistic", "correlation", "assumed") for link in T.LINKS)
    assert set(T.EDGES) == {c["id"] for c in T.CQAS}
