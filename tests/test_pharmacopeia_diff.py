"""Cross-pharmacopeia structured diff tests (Idea 4).

The no-fabrication principle is the gate for Idea 4, made a CI failure here:

  - test_no_fabrication_gate  — every LOW/NONE-confidence PharmacopeialMethod
                                built across the catalog has ALL numeric
                                fields None (no value invented on sparse text)
  - test_parse_paracetamol    — the regex lifts the real IP 2026 dissolution
                                string into the right structured numerics
  - test_diff_classification   — paracetamol is 3/3 NSQ_RELEVANT (the real
                                signal), with the right rationale fields
  - test_incomparable_honesty — a sparse side is INCOMPARABLE, never a silent
                                equivalence claim
  - test_equivalence_proven   — METHOD_EQUIVALENT requires both sides parsed
                                and matching; it is never the default
  - test_usp_seam_absent      — the USP axis is honestly None today (the
                                simulator passport seam), never faked present
  - test_coverage_matrix      — 17x3 matrix, USP column absent, IP/Ph.Eur full

Runnable both as `python tests/test_pharmacopeia_diff.py` and via pytest.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED = REPO / "analytics" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))


def _load():
    # Register gmp_knowledge before exec (Python 3.9 + PEP 563 dataclass fix,
    # same as test_gmp_provenance), then load the sibling parser + diff.
    spec = importlib.util.spec_from_file_location("gmp_knowledge", SHARED / "gmp_knowledge.py")
    gmp = importlib.util.module_from_spec(spec)
    sys.modules["gmp_knowledge"] = gmp
    spec.loader.exec_module(gmp)

    pmp = importlib.import_module("pharmacopeia_methods")
    pdf = importlib.import_module("pharmacopeia_diff")
    return gmp, pmp, pdf


# ---------------------------------------------------------------------------


def test_no_fabrication_gate():
    """Every PharmacopeialMethod built across the 17-drug catalog with
    LOW or NONE confidence has ALL numeric fields None. A sparse compendial
    string must never yield an invented numeric — None means 'not in the
    source', and the diff must read that as INCOMPARABLE, not equivalence."""
    gmp, pmp, pdf = _load()
    bad: list[str] = []
    for key, drug in gmp.PRODUCT_CATALOG.items():
        for diff in pdf.diff_drug(drug):
            for pharm, method in diff.methods.items():
                if method is None:
                    continue
                if method.parse_confidence in (gmp.CONFIDENCE_LOW, gmp.CONFIDENCE_NONE):
                    if not pmp.numeric_fields_are_none(method):
                        bad.append(f"{key}.{pharm.value}.{method.section} "
                                   f"conf={method.parse_confidence} "
                                   f"ph={method.medium_ph} rpm={method.rpm} "
                                   f"q={method.q_limit_pct} "
                                   f"imp={method.impurity_limit_pct}")
    assert not bad, (
        f"no-fabrication gate open: {len(bad)} sparse method(s) carry a "
        f"numeric field that was not in the source string: {bad[:3]}"
    )


def test_parse_paracetamol():
    """The regex lifts the real IP 2026 paracetamol dissolution string into
    the right structured numerics — apparatus, RPM, medium, pH, Q, timepoint."""
    gmp, pmp, pdf = _load()
    raw = ("USP Apparatus 2 (Paddle) at 50 RPM; Medium: 900 mL Phosphate Buffer "
           "pH 5.8; Limit: NLT 80% dissolved in 30 minutes.")
    m = pmp.parse_method(gmp.Pharmacopeia.IP2026, "dissolution", raw)
    assert m.parse_confidence == gmp.CONFIDENCE_HIGH
    assert m.apparatus == "Apparatus 2"
    assert m.rpm == 50.0
    assert m.medium == "Phosphate Buffer"
    assert m.medium_ph == 5.8
    assert m.q_limit_pct == 80.0
    assert len(m.timepoints) == 1 and m.timepoints[0].time_min == 30.0
    assert m.timepoints[0].q_limit_pct == 80.0
    # Ph. Eur. paracetamol dissolution: paddle, water, no pH, 45 min, 80%.
    raw2 = "Paddle Apparatus at 50 RPM; Medium: Water; Limit: NLT 80% (Q) in 45 minutes."
    m2 = pmp.parse_method(gmp.Pharmacopeia.PH_EUR, "dissolution", raw2)
    assert m2.apparatus == "paddle"
    assert m2.medium == "Water"
    assert m2.medium_ph is None
    assert m2.q_limit_pct == 80.0
    assert m2.timepoints[0].time_min == 45.0


def test_diff_classification():
    """Paracetamol is 3/3 NSQ_RELEVANT — the real cross-pharmacopeia signal:
    HPLC vs UV assay, Apparatus-2/pH-5.8/30-min vs paddle/water/45-min
    dissolution, 0.1 vs 0.15 impurity limit."""
    gmp, pmp, pdf = _load()
    drug = gmp.PRODUCT_CATALOG["paracetamol"]
    diffs = pdf.diff_drug(drug)
    assert pdf.nsq_relevant_count(drug) == 3
    by_sec = {d.section: d for d in diffs}
    assert by_sec["assay"].significance == gmp.DIFF_NSQ_RELEVANT
    assert "detection" in by_sec["assay"].rationale
    assert by_sec["dissolution"].significance == gmp.DIFF_NSQ_RELEVANT
    assert "timepoint" in by_sec["dissolution"].rationale
    assert by_sec["impurities"].significance == gmp.DIFF_NSQ_RELEVANT
    assert "impurity_limit_pct" in by_sec["impurities"].rationale


def test_incomparable_honesty():
    """A side too sparse to compare is INCOMPARABLE — never a silent
    METHOD_EQUIVALENT. Amoxicillin's Ph. Eur. assay is a one-liner with no
    column/wavelength, so the assay diff must be INCOMPARABLE, not equivalent."""
    gmp, pmp, pdf = _load()
    drug = gmp.PRODUCT_CATALOG["amoxicillin"]
    by_sec = {d.section: d for d in pdf.diff_drug(drug)}
    # Amoxicillin assay Ph. Eur. is too sparse → INCOMPARABLE for assay.
    assert by_sec["assay"].significance == gmp.DIFF_INCOMPARABLE, (
        "a sparse side must be INCOMPARABLE, not silently equivalent"
    )
    # Dissolution (Apparatus 2 vs paddle) and impurities (1.0 vs 1.5) are real.
    assert by_sec["dissolution"].significance == gmp.DIFF_NSQ_RELEVANT
    assert by_sec["impurities"].significance == gmp.DIFF_NSQ_RELEVANT


def test_equivalence_proven():
    """METHOD_EQUIVALENT requires both sides parsed AND matching — it is
    never the default and never returned when one side is sparse."""
    gmp, pmp, pdf = _load()
    hi = pmp.parse_method(gmp.Pharmacopeia.IP2026, "impurities",
                          "Impurity K: Maximum 0.15%.")
    hi2 = pmp.parse_method(gmp.Pharmacopeia.PH_EUR, "impurities",
                           "Impurity K: Maximum 0.15%.")
    sig, _ = pdf._classify_pair("impurities", hi, hi2, "IP 2026", "Ph. Eur.")
    assert sig == gmp.DIFF_METHOD_EQUIVALENT
    # Same again but one side sparse → must NOT be equivalent.
    sparse = pmp.parse_method(gmp.Pharmacopeia.PH_EUR, "impurities", "USP monograph")
    sig2, _ = pdf._classify_pair("impurities", hi, sparse, "IP 2026", "Ph. Eur.")
    assert sig2 == gmp.DIFF_INCOMPARABLE


def test_usp_seam_absent():
    """The USP axis is honestly None for every drug today — analytics has no
    USP field, and the seam (simulator passport usp_monograph text via a future
    Redis adapter) is documented, not faked. No diff_drug USP method is present."""
    gmp, pmp, pdf = _load()
    for key, drug in gmp.PRODUCT_CATALOG.items():
        for diff in pdf.diff_drug(drug):
            usp = diff.methods[gmp.Pharmacopeia.USP]
            assert usp is None, f"{key}: USP method must be None today (seam), got {usp}"


def test_coverage_matrix():
    """17x3 coverage matrix: IP2026 and Ph.Eur are present for all 17; the
    USP column is absent (the seam) and surfaced honestly as present=False."""
    gmp, pmp, pdf = _load()
    cov = pdf.coverage_matrix(gmp.PRODUCT_CATALOG)
    assert len(cov) == len(gmp.PRODUCT_CATALOG)
    for key, row in cov.items():
        assert row[gmp.Pharmacopeia.IP2026].present, f"{key}: IP2026 should be present"
        assert row[gmp.Pharmacopeia.PH_EUR].present, f"{key}: Ph.Eur should be present"
        assert row[gmp.Pharmacopeia.USP].present is False, (
            f"{key}: USP must be absent today (seam), not silently present"
        )
        assert row[gmp.Pharmacopeia.USP].method is None


def test_significance_vocab():
    """Every MethodDiff.significance across the catalog is one of the three
    defined values — no typo / invented tier leaks into the UI."""
    gmp, pmp, pdf = _load()
    valid = {gmp.DIFF_NSQ_RELEVANT, gmp.DIFF_METHOD_EQUIVALENT, gmp.DIFF_INCOMPARABLE}
    seen = set()
    for drug in gmp.PRODUCT_CATALOG.values():
        for diff in pdf.diff_drug(drug):
            seen.add(diff.significance)
            assert diff.significance in valid
    # All three actually occur across the real catalog (else the classifier is
    # degenerate and one branch is untested by reality).
    assert seen == valid, f"significance values seen={seen}, expected all of {valid}"


if __name__ == "__main__":
    fns = [v for v in globals().values() if callable(v) and v.__name__.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)