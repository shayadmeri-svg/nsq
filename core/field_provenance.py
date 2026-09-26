"""Where each displayed number comes from, and what is missing.

Every value the dashboards show that is NOT backed by a public source is
listed here with its status, what is present today, and the gap. The UI
renders a disclaimer icon next to these fields using this registry, so the
same text is used on every page.

status:
    sourced   — pulled from a cited public source (still shown with its as-of date)
    frozen    — pulled from a real source once, not refreshed automatically
    estimate  — hand-entered estimate with no public source
    inferred  — derived by a rule from other fields
"""

from __future__ import annotations

from typing import Any

SEED_AS_OF = "2026-08"

FIELD_PROVENANCE: dict[str, dict[str, Any]] = {
    # --- patents / market ----------------------------------------------------
    "market_size_usd_bn": {
        "label": "Market size",
        "status": "estimate",
        "present": f"Hand-entered global market estimate in the patent seed ({SEED_AS_OF}); round numbers, no source cited.",
        "gap": "No free public source for sales by molecule. Needs a licensed dataset (e.g. IQVIA) or company filings per originator.",
    },
    "loe": {
        "label": "Loss of exclusivity",
        "status": "estimate",
        "present": f"'Publicly reported estimates' typed into the patent seed ({SEED_AS_OF}). Blank means treated as off-patent.",
        "gap": "US dates can be sourced from the FDA Orange Book patent/exclusivity files and Purple Book; EU from EMA authorisation dates + SPC registers; India has no patent API.",
    },
    "geo_coverage": {
        "label": "Country patent status",
        "status": "estimate",
        "present": "Templated: each molecule has the same status in all 10 countries.",
        "gap": "Needs per-country patent/SPC data (EPO OPS for Europe, Orange Book for US); not yet wired.",
    },
    "fto_risk": {
        "label": "Freedom-to-operate risk",
        "status": "estimate",
        "present": "Hand-assigned low/medium/high in the patent seed.",
        "gap": "A real FTO view needs patent claims analysis per market; no automated source.",
    },
    "patents": {
        "label": "Patent list",
        "status": "estimate",
        "present": "Formulation/process/secondary patents typed for the 10 novel molecules only; generics have none listed.",
        "gap": "US patents are available from the Orange Book patent file; not yet wired.",
    },
    # --- demand ----------------------------------------------------------------
    "disease_prevalence": {
        "label": "Disease prevalence",
        "status": "estimate",
        "present": f"Hand-entered global and India prevalence (millions) in the demand seed ({SEED_AS_OF}).",
        "gap": "IHME Global Burden of Disease publishes prevalence, but only through a manual results tool; not automated.",
    },
    "trial_counts": {
        "label": "Clinical trial counts",
        "status": "estimate",
        "present": "Hand-entered totals in the demand seed; one record cites ClinicalTrials.gov.",
        "gap": "Can be sourced from the ClinicalTrials.gov v2 API; not yet wired.",
    },
    "buyer_activity_score": {
        "label": "Buyer activity",
        "status": "estimate",
        "present": "0–100 proxy score typed by hand; no underlying data.",
        "gap": "Would need tender data (GeM, CPPP, NHS/EU tenders) or distributor demand; no free API.",
    },
    "market_momentum_score": {
        "label": "Market momentum",
        "status": "estimate",
        "present": "0–100 proxy score typed by hand; no underlying data.",
        "gap": "Would need sales growth data (licensed) or tender volumes.",
    },
    "competitor_anda_count": {
        "label": "Generic competitors",
        "status": "estimate",
        "present": "Hand-entered ANDA count.",
        "gap": "Count of approved ANDAs per ingredient is available from the Orange Book products file; not yet wired.",
    },
    # --- plants ------------------------------------------------------------------
    "talent_depth": {
        "label": "Talent depth",
        "status": "estimate",
        "present": "0–100 scores per skill area typed for the demo plants; feeds the talent part of the fit score.",
        "gap": "No public source for a site's team depth; should be entered by the organisation.",
    },
    "capability_inferred": {
        "label": "Inferred capability",
        "status": "inferred",
        "present": "Implied by a dosage form the reference site states (e.g. tablets ⇒ compression), not evidenced.",
        "gap": "Confirm with the organisation or its equipment list.",
    },
    "certifications_claimed": {
        "label": "Claimed standards",
        "status": "estimate",
        "present": "The reference site says it conforms to these standards, but no certificate or inspection record was found.",
        "gap": "Check EudraGMDP (EU GMP), FDA inspection classification database, WHO PQ lists.",
    },
    # --- knowledge ------------------------------------------------------------------
    "orange_book": {
        "label": "FDA Orange Book record",
        "status": "frozen",
        "present": "Pulled from openFDA on 2026-08-18 for 16 molecules and stored in code.",
        "gap": "Not refreshed; a fetch job would re-pull it monthly.",
    },
    "nsq_alerts": {
        "label": "CDSCO NSQ alerts",
        "status": "sourced",
        "present": "CDSCO Not-of-Standard-Quality notifications, loaded from the cumulative CSV.",
        "gap": "The CSV is refreshed by hand; the live CDSCO endpoint is not yet wired.",
    },
}


def provenance() -> dict[str, dict[str, Any]]:
    return FIELD_PROVENANCE
