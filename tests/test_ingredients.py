"""Ingredient extraction from CDSCO product names and tracked-set matching."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import ingredients as ing  # noqa: E402


def test_extract_combination_with_brand_and_dose():
    assert ing.extract_ingredients("Telmisartan 40 mg and Amlodipine 5 mg Tablets IP (Telma-AM Tablets)") == ["telmisartan", "amlodipine"]


def test_extract_strips_salts_forms_and_pharmacopoeia():
    assert ing.extract_ingredients("Metformin Hydrochloride Prolonged Release Tablets IP 500 mg") == ["metformin"]
    assert ing.extract_ingredients("Pantoprazole Gastro-resistant Tablets IP 40mg") == ["pantoprazole"]
    assert ing.extract_ingredients("Albendazole Tablets I.P. 400 mg") == ["albendazole"]


def test_vitamin_letters_survive():
    assert ing.extract_ingredients("Vitamin B Complex with Vitamin C Capsules") == ["vitamin b complex", "vitamin c"]


def test_match_tracked_by_base_name_and_misspelling():
    patents = {
        "amlodipine_besylate": SimpleNamespace(api_name="Amlodipine Besylate"),
        "paracetamol": SimpleNamespace(api_name="Paracetamol"),
    }
    idx = ing.tracked_index(patents)
    assert ing.match_tracked("amlodipine", idx) == "amlodipine_besylate"
    assert ing.match_tracked("paracetmol", idx) == "paracetamol"
    assert ing.match_tracked("aspirin", idx) is None
