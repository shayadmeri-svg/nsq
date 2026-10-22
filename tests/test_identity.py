"""core/identity.py: every way a source can name a tracked molecule resolves to it, and says how."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import identity  # noqa: E402

TARGETS = [{"key": "aspirin", "names": ["Aspirin"]}, {"key": "paracetamol", "names": ["Paracetamol"]},
           {"key": "atorvastatin_calcium", "names": ["Atorvastatin Calcium"]}, {"key": "telmisartan", "names": ["Telmisartan"]},
           {"key": "cyclosporine", "names": ["Cyclosporine"]}]
SYN = {"aspirin": ["aspirin", "ACETYLSALICYLIC ACID", "2-Acetoxybenzoic acid", "Acidum acetylsalicylicum", "Ecotrin"],
       "telmisartan": ["Telmisartan", "Micardis", "Ecotrin"]}  # a synonym two molecules share proves nothing
R = identity.Resolver(TARGETS, SYN)


def test_methods():
    assert R.resolve("Aspirin") == identity.Match("aspirin", "exact", "Aspirin")
    assert R.resolve("Atorvastatin Calcium Trihydrate").key == "atorvastatin_calcium"
    assert R.resolve("Atorvastatin").method == "salt"
    assert R.resolve("Acetaminophen").key == "paracetamol" and R.resolve("Acetaminophen").method == "inn_usan"  # USAN → INN
    assert R.resolve("Ciclosporin").key == "cyclosporine"  # INN → USAN
    for name in ("Acetylsalicylic Acid", "2-acetoxybenzoic acid", "Acidum acetylsalicylicum"):
        assert R.resolve(name).key == "aspirin", name
    assert R.resolve("Telmisarten").method == "fuzzy"


def test_ambiguous_and_unknown_names_do_not_map():
    assert R.resolve("Ecotrin") is None
    assert R.resolve("Allopurinol") is None


def test_coverage_counts_and_lists_what_is_missing():
    c = identity.coverage(R, ["Acetylsalicylic Acid", "Paracetamol", "Allopurinol", "Paracetamol"])
    assert (c["entries"], c["mapped"]) == (3, 2) and c["unmapped"] == ["Allopurinol"]
    assert c["by_method"]["synonym"] == 1 and c["by_method"]["exact"] == 1
    assert set(c["tracked_missing"]) == {"atorvastatin_calcium", "telmisartan", "cyclosporine"}
