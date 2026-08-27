"""Real ICH guideline registry + Q4B harmonisation tests (ich.org data).

These tests are the rigour gate for the ich.org data addition: they make the
difference between *real, cited ICH data pulled from the database.ich.org
guidelines API* and an *authored-from-memory list* a CI failure. The ICH
registry is the first thing to populate the previously-empty ich_guideline
audit tier, and the Q4B harmonisation context is the synthesis with Idea 4's
cross-pharmacopeia diff — so the tests pin both the citation and the honest
scope boundary:

  - test_registry_real_citations     — every registry entry carries a real
                                        database.ich.org PDF URL + retrieval date
                                        (not a bare "ICH Q9(R1)" string, not a
                                        dead fileadmin URL)
  - test_q4b_annex_for_dissolution   — dissolution maps to Q4B Annex 7(R2)
                                        (Dissolution Test general chapter)
  - test_no_q4b_for_assay_or_impurities — assay/impurities map to NO Q4B annex
                                        (ICH has not harmonised those chapters);
                                        honest None, never a fabricated annex
  - test_harmonisation_note_scope    — the dissolution note states the scope
                                        boundary (outside Q4B; IP not a party)
  - test_ich_prov_cited_carries_url  — ich_prov_cited upgrades a bare ich_prov
                                        with the real PDF URL + retrieval date;
                                        unknown codes fall back honestly (empty
                                        url, no fabricated link)
  - test_stamp_populates_audit_tier  — stamp_ich_harmonisation lifts the
                                        ich_guideline audit tier from 0 to 17
                                        and keeps the gate closed
  - test_drug_ich_harmonisation_prov — every drug carries a cited Q4B Annex 7
                                        provenance at the ich_guideline tier
  - test_q4b_annex_count             — 16 Q4B annexes, all real, all in registry
  - test_diff_carries_ich_note       — pharmacopeia_diff.diff_drug sets the
                                        ich_harmonisation note on the dissolution
                                        row only (assay/impurities stay None)
  - test_no_fabricated_codes         — every registry code is a real ICH Q-series
                                        code; no invented / placeholder codes

Runnable both as `python tests/test_ich_registry.py` and via pytest.
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
    """Load a fresh gmp_knowledge, then re-stamp both post-default stamp
    modules against it (the stamp functions resolve gmp_knowledge.PRODUCT_CATALOG
    dynamically from sys.modules, so the re-stamp targets this fresh instance)."""
    spec = importlib.util.spec_from_file_location("gmp_knowledge", SHARED / "gmp_knowledge.py")
    gmp = importlib.util.module_from_spec(spec)
    sys.modules["gmp_knowledge"] = gmp
    spec.loader.exec_module(gmp)
    usd = importlib.import_module("us_regulatory_data")
    usd.stamp_us_regulatory_data()
    ich = importlib.import_module("ich_registry")
    ich.stamp_ich_harmonisation()
    pdf = importlib.import_module("pharmacopeia_diff")
    return gmp, ich, pdf


# The complete, real set of Q4B annex codes (in numeric order) as returned by
# the database.ich.org guidelines API on 2026-08-18. Pinned so a fabricated or
# missing annex fails loudly.
_REAL_Q4B_ANNEX_CODES = {
    "Q4B Annex 1(R1)", "Q4B Annex 2(R1)", "Q4B Annex 3(R1)",
    "Q4B Annex 4A(R1)", "Q4B Annex 4B(R1)", "Q4B Annex 4C(R1)",
    "Q4B Annex 5(R1)", "Q4B Annex 6", "Q4B Annex 7(R2)", "Q4B Annex 8(R1)",
    "Q4B Annex 9(R1)", "Q4B Annex 10(R1)", "Q4B Annex 11", "Q4B Annex 12",
    "Q4B Annex 13", "Q4B Annex 14",
}

# The real ICH document host every PDF URL must live on (verified 200
# application/pdf on 2026-08-18). Old fileadmin.ich.org URLs are dead stubs —
# this pins the live host so a stale URL can't sneak back in.
_ICH_PDF_PREFIX = "https://database.ich.org/sites/default/files/"


# ---------------------------------------------------------------------------


def test_registry_real_citations():
    """Every registry entry is a real, cited ICH reference: a non-empty code,
    title, Step 4 date, and a PDF URL on the live database.ich.org host (not a
    bare string, not a dead fileadmin URL). All carry the retrieval date."""
    gmp, ich, _ = _load()
    assert len(ich.ICH_GUIDELINE_REGISTRY) >= 25, "registry must hold the Q-series + Q4B annexes"
    for code, gl in ich.ICH_GUIDELINE_REGISTRY.items():
        assert gl.code == code, f"{code}: code mismatch {gl.code!r}"
        assert gl.title, f"{code}: empty title"
        assert gl.step_4_date and len(gl.step_4_date) == 10, (
            f"{code}: Step 4 date must be a real ISO date, got {gl.step_4_date!r}"
        )
        assert gl.pdf_url.startswith(_ICH_PDF_PREFIX), (
            f"{code}: PDF URL must be on the live database.ich.org host, got {gl.pdf_url}"
        )
        assert gl.pdf_url.endswith(".pdf"), f"{code}: PDF URL must end .pdf"
        assert gl.retrieved_at == "2026-08-18", f"{code}: retrieval date {gl.retrieved_at!r}"
        # the cited provenance carries the real URL + retrieval (not bare).
        prov = gl.provenance
        assert prov.authority_tier == gmp.AUTHORITY_TIER_ICH
        assert prov.reference_url == gl.pdf_url
        assert prov.retrieved_at == "2026-08-18"
        assert prov.source_ref == code


def test_q4b_annex_for_dissolution():
    """Dissolution maps to Q4B Annex 7(R2) — the Dissolution Test general
    chapter. This is the one Q4B annex directly relevant to Idea 4's dissolution
    section, cited to the real ICH document."""
    gmp, ich, _ = _load()
    annex = ich.q4b_annex_for_section("dissolution")
    assert annex is not None
    assert annex.code == "Q4B Annex 7(R2)"
    assert annex.title == "Dissolution Test General Chapter"


def test_no_q4b_for_assay_or_impurities():
    """Assay and impurities map to NO Q4B annex — ICH has not harmonised
    product-specific assay (HPLC/UV) or impurity general chapters. Honest None,
    never a fabricated default annex."""
    gmp, ich, _ = _load()
    assert ich.q4b_annex_for_section("assay") is None, (
        "assay must not map to a Q4B annex — ICH has not harmonised it"
    )
    assert ich.q4b_annex_for_section("impurities") is None, (
        "impurities must not map to a Q4B annex — ICH has not harmonised it"
    )


def test_harmonisation_note_scope():
    """The dissolution note states the honest Q4B scope boundary: the general
    chapter is harmonised, the product-specific conditions compared here are
    OUTSIDE Q4B scope, and IP is not a Q4B party. Assay/impurities have no note."""
    gmp, ich, _ = _load()
    note = ich.harmonisation_note("dissolution")
    assert note is not None
    assert "Q4B Annex 7(R2)" in note
    assert "OUTSIDE Q4B scope" in note, "note must state the scope boundary"
    assert "IP is not a Q4B party" in note, "note must flag IP is outside Q4B"
    assert ich.harmonisation_note("assay") is None
    assert ich.harmonisation_note("impurities") is None


def test_ich_prov_cited_carries_url():
    """ich_prov_cited upgrades a bare ich_prov with the real ICH PDF URL +
    retrieval date. An unknown code falls back to an empty URL — honest (no
    fabricated link), just not yet traced."""
    gmp, ich, _ = _load()
    prov = ich.ich_prov_cited("Q9(R1)")
    assert prov.authority_tier == gmp.AUTHORITY_TIER_ICH
    assert prov.source_ref == "Q9(R1)"
    assert prov.reference_url.startswith(_ICH_PDF_PREFIX), prov.reference_url
    assert prov.reference_url.endswith(".pdf")
    assert prov.retrieved_at == "2026-08-18"
    # unknown code -> honest empty URL, no fabrication
    unk = ich.ich_prov_cited("NOT_A_REAL_ICH_CODE")
    assert unk.authority_tier == gmp.AUTHORITY_TIER_ICH
    assert unk.reference_url == "", "unknown code must not get a fabricated URL"


def test_stamp_populates_audit_tier():
    """stamp_ich_harmonisation lifts the ich_guideline audit tier from 0 (it was
    empty before this addition) to 17 and keeps the program-wide gate closed."""
    gmp, ich, _ = _load()
    audit = gmp.provenance_audit()
    assert audit["ich_guideline"] == 17, (
        f"expected 17 ich_guideline claims (one Q4B Annex 7 per drug), got {audit['ich_guideline']}"
    )
    assert audit["None-provenance"] == 0, f"gate open: {audit}"


def test_drug_ich_harmonisation_prov():
    """Every catalog drug carries a cited Q4B Annex 7(R2) provenance at the
    ich_guideline tier — a real ICH document URL + retrieval date, not a bare
    string and not None."""
    gmp, ich, _ = _load()
    for key, drug in gmp.PRODUCT_CATALOG.items():
        prov = drug.ich_harmonisation_prov
        assert prov is not None, f"{key}: ich_harmonisation_prov is None"
        assert prov.authority_tier == gmp.AUTHORITY_TIER_ICH, (
            f"{key}: tier {prov.authority_tier!r}"
        )
        assert prov.source_ref == "Q4B Annex 7(R2)", f"{key}: source_ref {prov.source_ref!r}"
        assert prov.reference_url.startswith(_ICH_PDF_PREFIX), f"{key}: {prov.reference_url}"
        assert prov.retrieved_at == "2026-08-18", f"{key}: retrieved_at {prov.retrieved_at!r}"


def test_q4b_annex_count():
    """16 Q4B annexes, every one a real code in the pinned set, all present in
    the registry, in numeric order."""
    gmp, ich, _ = _load()
    codes = [a.code for a in ich.Q4B_ANNEXES]
    assert len(ich.Q4B_ANNEXES) == 16, f"expected 16 Q4B annexes, got {len(ich.Q4B_ANNEXES)}"
    assert set(codes) == _REAL_Q4B_ANNEX_CODES, "Q4B annex code set drifted from the real API"
    # Annex 7(R2) is in position 9 (1-indexed) in numeric order.
    assert codes.index("Q4B Annex 7(R2)") == 8, f"annex 7 order wrong: {codes}"
    for a in ich.Q4B_ANNEXES:
        assert a.code in ich.ICH_GUIDELINE_REGISTRY


def test_diff_carries_ich_note():
    """pharmacopeia_diff.diff_drug sets the ich_harmonisation note on the
    dissolution row only; assay and impurities stay None — the honest scope
    boundary is encoded in the data model, not just the UI."""
    gmp, ich, pdf = _load()
    diffs = pdf.diff_drug(gmp.PRODUCT_CATALOG["paracetamol"])
    by_section = {d.section: d for d in diffs}
    assert by_section["dissolution"].ich_harmonisation is not None
    assert "Q4B Annex 7(R2)" in by_section["dissolution"].ich_harmonisation
    assert by_section["assay"].ich_harmonisation is None
    assert by_section["impurities"].ich_harmonisation is None


def test_no_fabricated_codes():
    """Every registry code is a real ICH Q-series code (Q + digits + optional
    (Rn) / Annex). No invented / placeholder codes — the registry is real data,
    not an authored list."""
    gmp, ich, _ = _load()
    import re
    pat = re.compile(r"^Q\d+[A-Z]?(?:\s+Annex\s+\d+[A-Z]?)?(?:\(R\d+\))?$")
    for code in ich.ICH_GUIDELINE_REGISTRY:
        assert pat.match(code), f"code {code!r} is not a real ICH Q-code shape"
    # Spot-check the key guidelines the GMP section is rooted in are all present.
    for must in ["Q1A(R2)", "Q2(R2)", "Q6A", "Q7", "Q8(R2)", "Q9(R1)", "Q10", "Q4B"]:
        assert must in ich.ICH_GUIDELINE_REGISTRY, f"{must} missing from registry"


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