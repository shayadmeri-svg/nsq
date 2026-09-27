"""Capabilities implied by a plant's CDSCO listing (core/capability_rules.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import capability_catalog  # noqa: E402
import capability_rules as cr  # noqa: E402


def test_every_rule_token_is_known():
    toks = {t for r in cr.RULES for t in r.required + r.inferred}
    assert not toks - set(capability_catalog.CAPABILITY_BY_TOKEN) - cr.EXTRA_TOKENS


def test_sterile_and_segregated_plant():
    d = cr.derive({"dosage_forms": ["tablet", "svp_dry_powder", "lyophilised"],
                   "segregated": {"cephalosporin": ["svp_dry_powder"], "cytotoxic": ["tablet"]}, "who_gmp": True})
    req = {t for t, v in d.items() if v["basis"] == "required"}
    assert {"grade_a_cleanroom", "wfi_generation", "aseptic_fill", "lyophilization", "endotoxin_testing", "compression",
            "building_in_building_segregation", "potent_containment", "serialization", "qms"} <= req
    assert d["film_coating"]["basis"] == "inferred" and "Grade A" in " ".join(d["grade_a_cleanroom"]["why"])
    assert cr.containment({"segregated": {"cytotoxic": []}}) == "cytotoxic"


def test_nothing_listed_means_nothing_derived():
    assert cr.derive({"dosage_forms": [], "segregated": {}}) == {}
    assert "qms" in cr.derive({"dosage_forms": [], "licence_classes": ["manufacture"]})
    oral = cr.derive({"dosage_forms": ["tablet"], "who_gmp": False})
    assert "grade_a_cleanroom" not in oral and "serialization" not in oral
