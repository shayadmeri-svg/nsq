"""Provenance gate + structural tests for analytics/shared/gmp_knowledge.py.

The provenance layer is the rigour gate: every structured claim in
PRODUCT_CATALOG (ParamSpec corridor, TestingGuidelines ip2026/ph_eur, Excipient
rationale, Drug-level patent/optimal_process/common_alerts/vigibase_risks) and
every SOLUTION_BANK mitigation carries a Provenance with an authority_tier, or
is explicitly None and must not be rendered as authoritative.

These tests make the gate a CI failure rather than a silent citation gap:

  - test_provenance_audit_no_none      — the program-wide gate (zero
                                         None-provenance claims across 17 drugs)
  - test_authority_tier_vocab          — no typo / unknown tiers
  - test_monograph_refs_not_fabricated — no monograph number invented that is
                                         not already present in the source string
  - test_mitigation_return_type        — mitigations_for returns list[Mitigation]
                                         with the ICH Q9 fallback at ich_guideline
  - test_mitigation_text_unchanged     — the migration wrapped, never altered,
                                         the curated SOLUTION_BANK text
  - test_vigibase_cohort_honesty       — vigibase_risks are named-as-cohort but
                                         uncited (TODO), never silently grounded
  - test_generic_standards_provenance  — the uncurated fallback carries tier
  - test_uncited_count_visible         — citation debt is auditable, not hidden

Runnable both as `python tests/test_gmp_provenance.py` and via pytest.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GMP = REPO / "analytics" / "shared" / "gmp_knowledge.py"
SHARED = REPO / "analytics" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))


def _load():
    # Register the module in sys.modules BEFORE exec_module — on Python 3.9 with
    # `from __future__ import annotations`, dataclass field evaluation during
    # exec otherwise fails with "'NoneType' object has no attribute '__dict__'".
    spec = importlib.util.spec_from_file_location("gmp_knowledge", GMP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gmp_knowledge"] = mod
    spec.loader.exec_module(mod)
    # Re-run the post-default stamps against this freshly-loaded instance. The
    # optional stamped fields (orange_book, ich_harmonisation_prov) default to
    # None; without re-stamping they stay None and the gate counts them as
    # None-provenance. The stamp functions resolve gmp_knowledge.PRODUCT_CATALOG
    # dynamically from sys.modules, so the re-stamp targets this fresh module.
    import ich_registry, us_regulatory_data  # noqa: E402
    us_regulatory_data.stamp_us_regulatory_data()
    ich_registry.stamp_ich_harmonisation()
    return mod


# ---------------------------------------------------------------------------


def test_provenance_audit_no_none():
    """The program-wide gate: zero None-provenance claims across all 17 drugs."""
    g = _load()
    assert len(g.PRODUCT_CATALOG) == 17
    audit = g.provenance_audit()
    assert audit["None-provenance"] == 0, (
        f"gate open: {audit['None-provenance']} claim(s) have no provenance — "
        f"every structured claim must carry a Provenance. audit={audit}"
    )


def test_authority_tier_vocab():
    """Every attached Provenance.authority_tier is in AUTHORITY_TIER_ORDER."""
    g = _load()
    valid = set(g.AUTHORITY_TIER_ORDER)
    bad: list[str] = []

    def check(p):
        if p is None:
            bad.append("None provenance")
        elif p.authority_tier not in valid:
            bad.append(f"unknown tier {p.authority_tier!r}")

    for drug in g.PRODUCT_CATALOG.values():
        check(drug.patent_prov)
        check(drug.optimal_process_prov)
        check(drug.common_alerts_prov)
        check(drug.vigibase_risks_prov)
        for spec in drug.ideal_parameters.values():
            check(spec.provenance)
        for exc in drug.ideal_excipients:
            check(exc.provenance)
        check(drug.ip2026.provenance)
        check(drug.ph_eur.provenance)
    assert not bad, f"invalid provenance tiers: {bad}"


def test_monograph_refs_not_fabricated():
    """No monograph number appears in a TestingGuidelines provenance that is not
    already present in the existing ip2026/ph_eur section strings. Locks the
    no-fabrication principle at the citation level — the migration only lifts
    numbers already embedded in the curated text (e.g. amoxicillin Ph. Eur.
    monograph 0260), never invents one."""
    g = _load()
    for drug in g.PRODUCT_CATALOG.values():
        for tg, label in ((drug.ip2026, "ip2026"), (drug.ph_eur, "ph_eur")):
            prov = tg.provenance
            assert prov is not None
            if prov.authority_tier != g.AUTHORITY_TIER_MONOGRAPH:
                continue
            blob = f"{tg.assay} {tg.dissolution} {tg.impurities}"
            # Only digits that follow the word "monograph" in source_ref are a
            # claimed monograph number (the pharmacopeia edition year in
            # "IP 2026 ..." is the edition name, not a monograph number).
            claimed = set(re.findall(r"monograph\s+(\d+)", prov.source_ref, re.IGNORECASE))
            if not claimed:
                continue  # TODO ref — no number claimed, nothing to fabricate
            present = set(re.findall(r"monograph\s+(\d+)", blob, re.IGNORECASE))
            invented = claimed - present
            assert not invented, (
                f"fabricated monograph number for {drug.id}.{label}: "
                f"{invented} not in source string {blob!r}"
            )
    # Spot-check: amoxicillin Ph. Eur. lifts 0260 (already in the source string).
    amo = g.PRODUCT_CATALOG["amoxicillin"]
    assert amo.ph_eur.provenance.source_ref == "Ph. Eur. monograph 0260 (Amoxicillin)"
    # Spot-check: a 16-simulator drug without an embedded number stays TODO.
    pc = g.PRODUCT_CATALOG["paracetamol"]
    assert "TODO" in pc.ip2026.provenance.source_ref
    assert "TODO" in pc.ph_eur.provenance.source_ref


def test_mitigation_return_type():
    """mitigations_for returns list[Mitigation]; the fallback is ICH-guideline."""
    g = _load()
    m = g.mitigations_for("Dissolution")
    assert isinstance(m, list) and m, "expected a non-empty list"
    assert all(isinstance(x, g.Mitigation) for x in m)
    assert all(hasattr(x, "text") and hasattr(x, "provenance") for x in m)
    # Fallback for an unknown category is the ICH Q9 action at ich_guideline tier.
    fb = g.mitigations_for("NonexistentCategoryXYZ")
    assert isinstance(fb, list) and fb, "fallback must be non-empty"
    assert fb[0].provenance.authority_tier == g.AUTHORITY_TIER_ICH


def test_mitigation_text_unchanged():
    """Wrapping SOLUTION_BANK strings into Mitigation never altered the curated
    text — the migration is additive (provenance), not editorial."""
    g = _load()
    for category, raw_strings in g.SOLUTION_BANK.items():
        wrapped = g.mitigations_for(category)
        assert [w.text for w in wrapped] == list(raw_strings), (
            f"mitigation text drift for {category!r}"
        )


def test_vigibase_cohort_honesty():
    """vigibase_risks is named as a VigiBase cohort signal but currently carries
    no query id / retrieval date / count — it must be at the empirical_cohort
    tier with a TODO note, never silently presented as a grounded cohort. The
    one drug with no vigibase_risks (amoxicillin) is honestly uncited."""
    g = _load()
    for drug in g.PRODUCT_CATALOG.values():
        prov = drug.vigibase_risks_prov
        assert prov is not None
        if drug.vigibase_risks:
            assert prov.authority_tier == g.AUTHORITY_TIER_COHORT, drug.id
            assert "TODO" in (prov.notes or ""), (
                f"{drug.id}: vigibase cohort claim lacks a TODO citation marker"
            )
        else:
            # amoxicillin has no vigibase_risks → honestly uncited, not cohort.
            assert prov.authority_tier == g.AUTHORITY_TIER_UNCITED, drug.id


def test_generic_standards_provenance():
    g = _load()
    gp = g.GENERIC_STANDARDS_PROVENANCE
    assert set(gp) >= {"scientific", "regulatory"}
    assert gp["regulatory"].authority_tier == g.AUTHORITY_TIER_ICH
    assert gp["scientific"].authority_tier == g.AUTHORITY_TIER_EXPERT


def test_uncited_count_visible():
    """Citation debt is auditable: the audit names the 'uncited' tier and is
    callable so the team can track it as real sources are added over time."""
    g = _load()
    audit = g.provenance_audit()
    assert "uncited" in audit, "audit must expose the uncited (TODO) count"
    # Amoxicillin's empty common_alerts + empty vigibase_risks are honestly uncited.
    assert audit["uncited"] >= 1
    # The gate is closed even with visible citation debt.
    assert audit["None-provenance"] == 0


def test_factory_tier_contract():
    """Each factory helper stamps the tier it claims to — a wrong-tier factory
    would silently mislabel every claim built through it."""
    g = _load()
    assert g.monograph_prov("IP 2026", "x").authority_tier == g.AUTHORITY_TIER_MONOGRAPH
    assert g.ich_prov("ICH Q9(R1)").authority_tier == g.AUTHORITY_TIER_ICH
    assert g.patent_prov("US 1").authority_tier == g.AUTHORITY_TIER_PATENT
    assert g.cohort_prov("q1", "", 12).authority_tier == g.AUTHORITY_TIER_COHORT
    assert g.expert_prov().authority_tier == g.AUTHORITY_TIER_EXPERT
    assert g.uncited_prov().authority_tier == g.AUTHORITY_TIER_UNCITED


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