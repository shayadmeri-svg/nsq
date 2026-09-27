"""Plant fit from the molecule's dosage form (core/plant_fit.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import plant_fit  # noqa: E402
from intelligence_models import PlantAsset  # noqa: E402
from intelligence_scorer import plant_available_capabilities  # noqa: E402


def _p(**kw):
    base = dict(asset_id="x", site_name="X", capabilities=[], approved_forms=[], certifications_active=[])
    return PlantAsset(**{**base, **kw})


def test_form_capabilities_and_inferred_half_credit():
    stated = _p(approved_forms=["solid_oral", "tablet"], capabilities=["compression", "dissolution_testing", "wet_granulation"],
                certifications_active=["EU_GMP"])
    inferred = _p(approved_forms=["tablet"], capabilities=["compression", "dissolution_testing", "wet_granulation"],
                  capability_basis={"compression": "inferred", "dissolution_testing": "inferred", "wet_granulation": "inferred"},
                  certifications_active=["EU_GMP"])
    a, ea = plant_fit.score(["tablet"], [], stated, plant_available_capabilities(stated))
    b, eb = plant_fit.score(["tablet"], [], inferred, plant_available_capabilities(inferred))
    assert ea["parts"]["form"] == 25 and ea["parts"]["standing"] == 20 and a > b
    assert eb["parts"]["capabilities"] == ea["parts"]["capabilities"] / 2


def test_wrong_form_missing_block_and_bad_standing():
    osd = _p(approved_forms=["tablet"], capabilities=["compression"], certifications_active=["WHO_GMP"])
    s, e = plant_fit.score(["topical"], [], osd, plant_available_capabilities(osd))
    assert e["parts"]["form"] == 0 and any("does not make" in w for w in e["warnings"])
    reg = _p(approved_forms=["tablet"], capabilities=["tablet", "compression"], reference={"registry_plant": "r1"},
             certifications_active=["WHO_GMP", "EU_NCR"])
    s2, e2 = plant_fit.score(["tablet"], ["cytotoxic"], reg, plant_available_capabilities(reg))
    assert e2["parts"]["segregation"] == 0 and e2["parts"]["standing"] == 0
    onco = _p(approved_forms=["tablet"], capabilities=["tablet", "segregated_cytotoxic"], reference={"registry_plant": "r2"})
    assert plant_fit.score(["tablet"], ["cytotoxic"], onco, plant_available_capabilities(onco))[1]["parts"]["segregation"] == 15


def test_track_record_and_nsq_penalty():
    p = _p(approved_forms=["tablet"], capabilities=["compression"], certifications_active=["WHO_GMP"])
    av = plant_available_capabilities(p)
    clean = plant_fit.score(["tablet"], [], p, av, {"listed": True})[1]["parts"]
    failed = plant_fit.score(["tablet"], [], p, av, {"made": 2, "nsq_alerts": 3})[1]["parts"]
    none = plant_fit.score(["tablet"], [], p, av, {})[1]["parts"]
    assert clean["record"] == 15 and failed["record"] == 8 and none["record"] == 0
    assert clean["standing"] == 12 and failed["standing"] == 2  # 12 − min(10, 2·3 + 2·2)
