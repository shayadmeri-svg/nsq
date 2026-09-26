"""Real ICH guideline registry + Q4B pharmacopeial-harmonisation context.

Sourced from the live ICH guidelines database API
(https://database.ich.org/api/v1/guidelines) on 2026-08-18 and baked here as a
curated, cited dataset so the analytics app reads real cited ICH references at
import time — never the network at render time. Every entry carries the real
ICH document PDF URL (database.ich.org/sites/default/files/...pdf, which
returns 200 application/pdf — verified) and the retrieval date, so the
ich_guideline authority tier is traceable, not asserted.

Why baked and not live-fetched: analytics is an offline CSV app; a network
dependency at import would break the read-only investigation flow and make the
rigour gate depend on an external service's uptime. Baking the already-fetched,
dated data preserves the citation (PDF URL + retrieved_at) while keeping the
app hermetic. Re-running the API query refreshes this file with a new
retrieved_at.

Why this data is relevant to the NSQ analytics engine:

  1. ICH GUIDELINE REGISTRY — the Q-series guidelines the GMP / pharmacopeial
     intelligence section is conceptually rooted in (Q1A stability, Q2
     analytical validation, Q6A specifications, Q7 GMP for APIs, Q8
     pharmaceutical development / QbD, Q9 quality risk management, Q10
     pharmaceutical quality system). ich_prov_cited(code) returns an ich_prov
     carrying the real PDF URL, upgrading a bare "ICH Q9(R1)" string to a
     traceable citation. This is the cited factory for the ich_guideline tier.

  2. Q4B PHARMACOPEIAL HARMONISATION — ICH Q4B evaluates and recommends
     pharmacopoeial *general chapters* for use across the ICH regions. The Q4B
     annexes each declare ONE general chapter interchangeable across the ICH
     regions (EU / US / JP): Annex 7(R2) is the Dissolution Test general chapter,
     Annex 5 the Disintegration Test, Annex 6 Uniformity of Dosage Units, etc.

     This is directly relevant to Idea 4's cross-pharmacopeia diff, and the
     honest scope note matters: Q4B harmonises the *general chapter* (the
     apparatus definitions and general procedure), NOT the product-specific
     monograph conditions (medium, pH, rpm, Q, timepoints) that diff_drug
     compares — those are set per-monograph by each pharmacopeia. Nor does Q4B
     apply to IP (India is not a Q4B party). So an NSQ_RELEVANT difference in a
     product-specific dissolution condition is OUTSIDE Q4B's harmonisation
     scope and remains genuinely market-specific. surfacing that scope
     explicitly prevents a reader from wrongly assuming ICH harmonisation
     covers the differences this engine exists to find.

No-fabrication contract: only the Q4B annex that maps to a diff section we
actually compare is surfaced (dissolution -> Annex 7(R2)). Assay and impurity
sections map to NO Q4B annex — there is no Q4B harmonisation of HPLC assay or
impurity methods — so they carry an honest None, never a defaulted claim. The
per-region implementation status the API returns (Implemented / In the process
of implementation / Not yet implemented, per ICH party) is NOT baked here: the
API exposes ~18 parties per annex without reliably attributable names, so
mapping a status to a specific region would be uncited attribution. That
deliberate omission is the no-fabrication gate applied to ICH data.
"""

from __future__ import annotations

from dataclasses import dataclass

from gmp_knowledge import AUTHORITY_TIER_ICH, Provenance

# Retrieval date for every citation below — the day the database.ich.org
# guidelines API was queried for this dataset. Update when re-fetching.
RETRIEVED_AT = "2026-08-18"

# Source API for every citation (the live, citable ICH guidelines database).
ICH_API_URL = "https://database.ich.org/api/v1/guidelines"


@dataclass
class ICHGuideline:
    """One ICH guideline as a cited, traceable reference."""
    code: str            # "Q9(R1)", "Q4B Annex 7(R2)"
    title: str           # the ICH short title (e.g. "Quality Risk Management")
    step_4_date: str     # ICH Step 4 adoption date (the guideline version date)
    pdf_url: str         # real database.ich.org document PDF (returns 200)
    retrieved_at: str    # when this reference was pulled from the ICH API

    @property
    def provenance(self) -> Provenance:
        """An ich_prov (ich_guideline tier) carrying the real PDF URL +
        retrieval date — the cited form of an ICH guideline claim, traceable to
        the document. Built directly so retrieved_at is set, not mutated on."""
        return Provenance(
            authority_tier=AUTHORITY_TIER_ICH,
            source_type="ich_guideline",
            source_ref=self.code,
            retrieved_at=self.retrieved_at,
            reference_url=self.pdf_url,
            notes=f"ICH {self.code}; {self.title}; Step 4 {self.step_4_date}; "
                  f"retrieved {self.retrieved_at} from {ICH_API_URL}",
        )


# Real per-guideline facts lifted from the database.ich.org guidelines API
# (entityInfo/bundleInfo/code/shortTitle/stepDate.step_4 + the "Guideline" PDF in
# the files field). Titles are the ICH shortTitle verbatim. step_4_date is the
# ICH Step 4 adoption date. pdf_url is the primary Guideline document PDF.
# Every pdf_url below was verified to return 200 application/pdf on 2026-08-18.
ICH_GUIDELINE_RAW: dict[str, dict] = {
    "Q1A(R2)": dict(title="Stability Testing of New Drug Substances and Products", step_4_date="2003-02-06", pdf_url="https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf"),
    "Q2(R2)": dict(title="Revision of Q2(R1) Analytical Validation", step_4_date="2023-11-01", pdf_url="https://database.ich.org/sites/default/files/ICH_Q2%28R2%29_Guideline_2023_1130_ErrorCorrection_2025.pdf"),
    "Q6A": dict(title="Specifications : Test Procedures and Acceptance Criteria for New Drug Substances and New Drug Products: Chemical Substances", step_4_date="1999-10-06", pdf_url="https://database.ich.org/sites/default/files/Q6A%20Guideline.pdf"),
    "Q7": dict(title="Good Manufacturing Practice Guide for Active Pharmaceutical Ingredients", step_4_date="2000-11-10", pdf_url="https://database.ich.org/sites/default/files/Q7%20Guideline.pdf"),
    "Q8(R2)": dict(title="Pharmaceutical Development", step_4_date="2009-08-01", pdf_url="https://database.ich.org/sites/default/files/Q8%28R2%29%20Guideline.pdf"),
    "Q9(R1)": dict(title="Quality Risk Management", step_4_date="2023-01-18", pdf_url="https://database.ich.org/sites/default/files/ICH_Q9%28R1%29_Guideline_Step4_2025_0115_0.pdf"),
    "Q10": dict(title="Pharmaceutical Quality System", step_4_date="2008-06-04", pdf_url="https://database.ich.org/sites/default/files/Q10%20Guideline.pdf"),
    "Q4B": dict(title="Evaluation and Recommendation of Pharmacopoeial Texts for Use in the ICH Regions", step_4_date="2007-11-01", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Guideline.pdf"),
    "Q4B(R1)": dict(title="Evaluation and Recommendation of Pharmacopoeial Texts for Use in the ICH Regions", step_4_date="2024-06-05", pdf_url="https://database.ich.org/sites/default/files/ICH_Q4B%28R1%29_Guideline_2024_0605.pdf"),
    "Q4B Annex 1(R1)": dict(title="Residue on Ignition/Sulphated Ash General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%201%28R1%29%20Guideline.pdf"),
    "Q4B Annex 2(R1)": dict(title="Test for Extractable Volume of Parenteral Preparations General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%202%28R1%29%20Guideline.pdf"),
    "Q4B Annex 3(R1)": dict(title="Test for Particulate Contamination: Sub-Visible Particles General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%203%28R1%29%20Guideline.pdf"),
    "Q4B Annex 4A(R1)": dict(title="Microbiological Examination of Non-Sterile Products: Microbial Enumeration Tests General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex4A%28R1%29%20Guideline.pdf"),
    "Q4B Annex 4B(R1)": dict(title="Microbiological Examination of Non-Sterile Products: Tests for Specified Micro-Organisms General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex4B%28R1%29%20Guideline.pdf"),
    "Q4B Annex 4C(R1)": dict(title="Microbiological Examination of Non-Sterile Products: Acceptance Criteria for Pharmaceutical Preparations and Substances for Pharmaceutical Use General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex4C%28R1%29%20Guideline.pdf"),
    "Q4B Annex 5(R1)": dict(title="Disintegration Test General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%205%28R1%29%20Guideline.pdf"),
    "Q4B Annex 6": dict(title="Uniformity of Dosage Units General Chapter", step_4_date="2013-11-13", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%206%20Guideline.pdf"),
    "Q4B Annex 7(R2)": dict(title="Dissolution Test General Chapter", step_4_date="2010-11-11", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%207%20%28R2%29%20Guideline.pdf"),
    "Q4B Annex 8(R1)": dict(title="Sterility Test General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%208%28R1%29%20Guideline.pdf"),
    "Q4B Annex 9(R1)": dict(title="Tablet Friability General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%209%28R1%29%20Guideline.pdf"),
    "Q4B Annex 10(R1)": dict(title="Polyacrylamide Gel Electrophoresis General Chapter", step_4_date="2010-09-27", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%2010%28R1%29%20Guideline.pdf"),
    "Q4B Annex 11": dict(title="Capillary Electrophoresis General Chapter", step_4_date="2010-06-09", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%2011%20Guideline.pdf"),
    "Q4B Annex 12": dict(title="Analytical Sieving General Chapter", step_4_date="2010-06-09", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%2012%20Guideline.pdf"),
    "Q4B Annex 13": dict(title="Bulk Density and Tapped Density of Powders General Chapter", step_4_date="2012-06-07", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%2013%20Guideline.pdf"),
    "Q4B Annex 14": dict(title="Bacterial Endotoxins Test General Chapter", step_4_date="2012-10-18", pdf_url="https://database.ich.org/sites/default/files/Q4B%20Annex%2014%20Guideline.pdf"),
}


# The built registry: code -> ICHGuideline (with the cited PDF URL + retrieval).
ICH_GUIDELINE_REGISTRY: dict[str, ICHGuideline] = {
    code: ICHGuideline(
        code=code,
        title=raw["title"],
        step_4_date=raw["step_4_date"],
        pdf_url=raw["pdf_url"],
        retrieved_at=RETRIEVED_AT,
    )
    for code, raw in ICH_GUIDELINE_RAW.items()
}

# The Q4B annexes in numeric order (the pharmacopeial general chapters ICH has
# evaluated for interchangeability across the ICH regions). Q4B + Q4B(R1) are
# the parent guideline; the annexes are the per-chapter recommendations.
_Q4B_ANNEX_ORDER = [
    "Q4B Annex 1(R1)", "Q4B Annex 2(R1)", "Q4B Annex 3(R1)",
    "Q4B Annex 4A(R1)", "Q4B Annex 4B(R1)", "Q4B Annex 4C(R1)",
    "Q4B Annex 5(R1)", "Q4B Annex 6", "Q4B Annex 7(R2)", "Q4B Annex 8(R1)",
    "Q4B Annex 9(R1)", "Q4B Annex 10(R1)", "Q4B Annex 11", "Q4B Annex 12",
    "Q4B Annex 13", "Q4B Annex 14",
]
Q4B_ANNEXES: list[ICHGuideline] = [ICH_GUIDELINE_REGISTRY[c] for c in _Q4B_ANNEX_ORDER]


# Map a diff section to the Q4B annex that harmonises its general chapter, if
# any. Idea 4 compares three sections — dissolution / assay / impurities. Only
# dissolution has a Q4B annex (Annex 7(R2) — the Dissolution Test general
# chapter). Assay (HPLC/UV) and impurity methods have NO Q4B annex: ICH has not
# harmonised product-specific assay or impurity general chapters, so they carry
# an honest None — never a defaulted harmonisation claim.
_SECTION_TO_Q4B_ANNEX = {
    "dissolution": "Q4B Annex 7(R2)",
}


def q4b_annex_for_section(section: str) -> ICHGuideline | None:
    """The Q4B annex that harmonises the general chapter a diff section belongs
    to, or None where ICH has not harmonised that chapter (assay, impurities).
    This is the honest scope boundary: only dissolution maps to a Q4B annex."""
    code = _SECTION_TO_Q4B_ANNEX.get(section)
    if code is None:
        return None
    return ICH_GUIDELINE_REGISTRY.get(code)


def harmonisation_note(section: str) -> str | None:
    """The human-readable ICH Q4B scope note for a diff section, or None where
    no Q4B annex applies. The note states exactly what Q4B harmonises (the
    general chapter across ICH regions) and what it does NOT (the product-
    specific monograph conditions compared here, and IP) — so a reader cannot
    mistake ICH harmonisation for coverage of the differences we surface."""
    annex = q4b_annex_for_section(section)
    if annex is None:
        return None
    if section == "dissolution":
        return (
            f"ICH {annex.code} ({annex.title}) harmonises the general "
            "dissolution *chapter* (apparatus definitions) across the ICH "
            "regions (EU/US/JP). The product-specific conditions compared here "
            "(medium, pH, rpm, Q, timepoints) are set per-monograph by each "
            "pharmacopeia and are OUTSIDE Q4B scope; IP is not a Q4B party. "
            "NSQ_RELEVANT differences therefore remain market-specific."
        )
    # Future sections that gain a Q4B annex would add their own note here.
    return f"ICH {annex.code} ({annex.title}) — Q4B harmonisation applies."


def ich_prov_cited(code: str, notes: str = "") -> Provenance:
    """Return an ich_prov at the ich_guideline tier carrying the REAL ICH PDF
    URL + retrieval date for the given guideline code — the cited, traceable
    form of an ICH guideline claim. Falls back to a bare ich_prov (empty url)
    for codes not in the registry, so an unknown code is still honest (no
    fabricated URL), just not yet traced. Every code in the registry resolves
    to a verified 200 application/pdf on database.ich.org."""
    gl = ICH_GUIDELINE_REGISTRY.get(code)
    if gl is None:
        # Unknown code: honest empty URL (no fabricated link), still at the
        # ich_guideline tier so the claim is visible but untraced. Built
        # directly because ich_prov() does not accept a notes kwarg.
        return Provenance(
            authority_tier=AUTHORITY_TIER_ICH,
            source_type="ich_guideline",
            source_ref=code,
            reference_url="",
            notes=notes,
        )
    base_notes = (
        f"ICH {gl.code}; {gl.title}; Step 4 {gl.step_4_date}; "
        f"retrieved {RETRIEVED_AT} from {ICH_API_URL}"
    )
    return Provenance(
        authority_tier=AUTHORITY_TIER_ICH,
        source_type="ich_guideline",
        source_ref=gl.code,
        retrieved_at=RETRIEVED_AT,
        reference_url=gl.pdf_url,
        notes=f"{base_notes} | {notes}" if notes else base_notes,
    )


def stamp_ich_harmonisation() -> dict[str, int]:
    """Attach the cited ICH Q4B harmonisation provenance to each catalog
    molecule's pharmacopeial diff context. Every catalog molecule has a
    dissolution section, so each carries the Q4B Annex 7(R2) cited provenance —
    the ICH general-chapter harmonisation context for its dissolution
    comparison. Populates the previously-empty ich_guideline audit tier with
    real, traceable claims (URL + retrieved_at).

    References gmp_knowledge.PRODUCT_CATALOG dynamically so the stamp always
    targets the currently-loaded gmp_knowledge module (tests reload
    gmp_knowledge per-case; a static top-level binding would stamp a stale
    instance — same fix as us_regulatory_data.stamp_us_regulatory_data)."""
    import gmp_knowledge
    annex = ICH_GUIDELINE_REGISTRY["Q4B Annex 7(R2)"]
    stamped = 0
    for molecule_id in gmp_knowledge.PRODUCT_CATALOG:
        gmp_knowledge.PRODUCT_CATALOG[molecule_id].ich_harmonisation_prov = annex.provenance
        stamped += 1
    return {"ich_harmonisation_stamped": stamped}


# Stamp at import so the ich_guideline audit tier is populated by the time the
# app / tests read PRODUCT_CATALOG (mirrors us_regulatory_data).
stamp_ich_harmonisation()