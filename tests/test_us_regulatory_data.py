"""Real FDA Orange Book data tests (Idea 4 US regulatory axis).

These tests are the rigour gate for the USP/Orange Book addition: they make
the difference between *real, cited FDA data* and the *representative seed
placeholder* a CI failure. The seed in data/regulatory_seed.json stamped every
molecule with te_code='AB', te_rating='A', rld_applicant='Various generic
applicants' — uniform placeholder. Sourcing real data means these tests must
FAIL if the placeholder ever sneaks back in:

  - test_orange_book_coverage       — 16/17 molecules have a real record;
                                       vildagliptin is honestly None (not
                                       FDA-approved in the US)
  - test_real_citations              — every record is at regulatory_registry
                                       tier with a real openFDA URL + retrieval
                                       date + an application number in source_ref
  - test_no_placeholder_seed         — no record carries the seed's uniform
                                       'Various generic applicants' — the real
                                       pull replaced the placeholder
  - test_te_code_vocab               — every TE code is a real FDA code (or the
                                       list is empty for OTC / not-TE-coded)
  - test_provenance_gate             — every OB provenance is non-None and in
                                       AUTHORITY_TIER_ORDER; the program gate
                                       stays closed (0 None-provenance)
  - test_metformin_ab_subcodes       — metformin carries AB1/AB2/AB3: not all
                                       AB generics are therapeutically
                                       equivalent — a real NSQ-relevant signal,
                                       not the uniform 'AB' placeholder
  - test_audit_counts_registry       — provenance_audit reports 16
                                       regulatory_registry claims

Runnable both as `python tests/test_us_regulatory_data.py` and via pytest.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED = REPO / "analytics" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

# Valid FDA Orange Book Therapeutic Equivalence codes.
# A-rated (therapeutically equivalent): AA, AB (+ subscripted AB1..AB5 when
# multiple non-equivalent generics), AN, AO, AP, AT.
# B-rated (NOT therapeutically equivalent): BC, BD, BE, BN, BP, BR, BS, BT, BX.
_VALID_TE_CODES = {
    "AA", "AB", "AB1", "AB2", "AB3", "AB4", "AB5", "AN", "AO", "AP", "AT",
    "BC", "BD", "BE", "BN", "BP", "BR", "BS", "BT", "BX",
}


def _load():
    spec = importlib.util.spec_from_file_location("gmp_knowledge", SHARED / "gmp_knowledge.py")
    gmp = importlib.util.module_from_spec(spec)
    sys.modules["gmp_knowledge"] = gmp
    spec.loader.exec_module(gmp)
    # importing us_regulatory_data runs stamp_us_regulatory_data() at import,
    # but tests reload gmp_knowledge per-case, so re-stamp to target this
    # freshly-loaded instance (stamp resolves gmp_knowledge.PRODUCT_CATALOG
    # dynamically, so the re-stamp hits the current module).
    usd = importlib.import_module("us_regulatory_data")
    usd.stamp_us_regulatory_data()
    # Same pattern for the ICH Q4B harmonisation stamp: ich_harmonisation_prov
    # defaults to None and would otherwise count as None-provenance in the gate.
    ich = importlib.import_module("ich_registry")
    ich.stamp_ich_harmonisation()
    return gmp, usd


# ---------------------------------------------------------------------------


def test_orange_book_coverage():
    """16/17 catalog molecules have a real FDA Orange Book record; vildagliptin
    is honestly None (not FDA-approved in the US — the openFDA query 404s)."""
    gmp, _ = _load()
    assert len(gmp.PRODUCT_CATALOG) == 17
    present = [k for k, d in gmp.PRODUCT_CATALOG.items() if d.orange_book is not None]
    assert len(present) == 16, f"expected 16 OB records, got {len(present)}"
    assert gmp.PRODUCT_CATALOG["vildagliptin"].orange_book is None, (
        "vildagliptin must be honestly absent (not FDA-approved), not faked"
    )
    # amoxicillin had NO simulator passport but DOES have real FDA Orange Book
    # data — it must be covered here (the real pull closes a seed gap).
    assert gmp.PRODUCT_CATALOG["amoxicillin"].orange_book is not None


def test_real_citations():
    """Every Orange Book record carries a real, dated openFDA citation at the
    regulatory_registry tier — not the seed placeholder, not a bare claim."""
    gmp, _ = _load()
    for key, drug in gmp.PRODUCT_CATALOG.items():
        ob = drug.orange_book
        if ob is None:
            continue
        prov = ob.provenance
        assert prov is not None, f"{key}: OB record has no provenance"
        assert prov.authority_tier == gmp.AUTHORITY_TIER_REGISTRY, (
            f"{key}: OB provenance must be regulatory_registry, got {prov.authority_tier}"
        )
        assert prov.reference_url.startswith("https://api.fda.gov/drug/orangebook.json"), (
            f"{key}: OB citation must be a real openFDA Orange Book URL, got {prov.reference_url}"
        )
        assert prov.retrieved_at == "2026-08-18", (
            f"{key}: OB citation must carry the retrieval date, got {prov.retrieved_at!r}"
        )
        assert "N" in prov.source_ref and any(ch.isdigit() for ch in prov.source_ref), (
            f"{key}: OB source_ref must name the FDA application number, got {prov.source_ref!r}"
        )


def test_no_placeholder_seed():
    """The seed stamped every molecule with rld_applicant='Various generic
    applicants' (uniform placeholder). A real pull must NOT carry that — this
    test fails if the placeholder ever sneaks back in."""
    gmp, _ = _load()
    for key, drug in gmp.PRODUCT_CATALOG.items():
        ob = drug.orange_book
        if ob is None:
            continue
        assert ob.rld_applicant != "Various generic applicants", (
            f"{key}: rld_applicant is the seed placeholder, not real FDA data"
        )
        assert ob.rld_applicant and ob.rld_applicant != "", (
            f"{key}: rld_applicant empty — real pull must name a real applicant"
        )


def test_te_code_vocab():
    """Every TE code is a real FDA Orange Book code, or the list is empty
    (OTC / not TE-coded, e.g. acetaminophen). No invented codes."""
    gmp, _ = _load()
    for key, drug in gmp.PRODUCT_CATALOG.items():
        ob = drug.orange_book
        if ob is None:
            continue
        for code in ob.te_codes:
            assert code in _VALID_TE_CODES, (
                f"{key}: TE code {code!r} is not a known FDA Orange Book code"
            )


def test_provenance_gate():
    """Every OB provenance is non-None and in AUTHORITY_TIER_ORDER, and the
    program-wide gate stays closed (0 None-provenance) with the new tier."""
    gmp, _ = _load()
    valid = set(gmp.AUTHORITY_TIER_ORDER)
    for key, drug in gmp.PRODUCT_CATALOG.items():
        ob = drug.orange_book
        if ob is None:
            continue
        assert ob.provenance is not None, f"{key}: OB provenance is None"
        assert ob.provenance.authority_tier in valid, (
            f"{key}: OB tier {ob.provenance.authority_tier!r} not in vocab"
        )
    audit = gmp.provenance_audit()
    assert audit["None-provenance"] == 0, f"gate open: {audit}"
    assert audit["regulatory_registry"] == 16, (
        f"expected 16 registry claims, audit={audit}"
    )


def test_metformin_ab_subcodes():
    """Metformin carries AB1/AB2/AB3 — FDA's signal that not all AB-rated
    metformin generics are therapeutically equivalent to each other. This is a
    genuine NSQ-relevant fact (substitution risk) that the uniform seed
    placeholder ('AB' for everyone) erased. The real pull must surface it."""
    gmp, _ = _load()
    ob = gmp.PRODUCT_CATALOG["metformin"].orange_book
    assert ob is not None
    assert {"AB", "AB1", "AB2", "AB3"} <= set(ob.te_codes), (
        f"metformin should carry AB + AB1/AB2/AB3, got {ob.te_codes}"
    )


def test_audit_counts_registry():
    """provenance_audit exposes the regulatory_registry tier and counts 16 —
    the new real-data claims are auditable, not hidden."""
    gmp, _ = _load()
    audit = gmp.provenance_audit()
    assert "regulatory_registry" in audit
    assert audit["regulatory_registry"] == 16


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