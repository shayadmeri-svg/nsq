"""The org Pharmacopoeia page's comparison with the IP: stricter, looser, the same, or not comparable."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "core"))

from app.standards import _method_differs, _vs  # noqa: E402


def test_dissolution_verdicts():
    assert _vs(85, 30, 75, 30, True) == "stricter"  # JP telmisartan vs IP
    assert _vs(70, 45, 80, 30, True) == "looser"
    assert _vs(80, 45, 75, 30, True) == "different"  # higher Q but later: not directly comparable
    assert _vs(80, 30, 80, 30, True) == "same"
    assert _vs(None, 30, 80, 30, True) is None


def test_assay_verdicts():
    assert _vs(95, 105, 90, 110, False) == "stricter"
    assert _vs(90, 110, 95, 105, False) == "looser"
    assert _vs(93, 104, 95, 105, False) == "different"  # lower floor, tighter ceiling


def test_method_differences():
    ip = {"ph": 7.5, "rpm": 75.0, "apparatus": "paddle", "volume_ml": 900.0}
    assert _method_differs({"ph": 6.8, "rpm": 50.0, "apparatus": "Paddle", "volume_ml": 900.0}, ip) == ["medium pH 6.8 vs 7.5", "50 vs 75 rpm"]
    assert _method_differs({"apparatus": "II (Paddle)"}, ip) == []
