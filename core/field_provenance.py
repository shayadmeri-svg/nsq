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
        "present": "Per molecule and market: US from the FDA Orange/Purple Book and EU from EMA when the scheduled source sync matched the molecule (each date then carries its own source icon); otherwise the curated estimate. Blank means treated as off-patent.",
        "gap": "EU SPCs and national (non-central) authorisations are not covered; India has no patent API, so India is derived from US/EU status or left as the estimate.",
    },
    "geo_coverage": {
        "label": "Country patent status",
        "status": "estimate",
        "present": "US and EU rows follow the sourced LOE dates when available; the other countries keep the curated template.",
        "gap": "Per-country patent/SPC data (e.g. EPO OPS) is not wired.",
    },
    "fto_risk": {
        "label": "Freedom-to-operate risk",
        "status": "estimate",
        "present": "Derived from the Orange Book when matched (compound patent or >1 y exclusivity ⇒ high; formulation/method patents only ⇒ medium; none ⇒ low); otherwise hand-assigned in the seed.",
        "gap": "A real FTO view needs patent claims analysis per market; no automated source.",
    },
    "patents": {
        "label": "Patent list",
        "status": "estimate",
        "present": "US patents in force from the Orange Book patent file (drug substance, drug product, method of use) when the molecule is matched; other markets from the curated seed.",
        "gap": "Process patents are not listed in the Orange Book; non-US patents are not sourced.",
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
        "present": "ClinicalTrials.gov v2 counts per molecule (total, phase 3+, started in 3 years, India sites), refreshed weekly by the source sync; the curated seed value until a molecule has been queried.",
        "gap": "Counts are keyword matches on the intervention; they are not deduplicated by indication.",
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
        "present": "Active ANDAs for single-ingredient products in the Orange Book (licensed biosimilars from the Purple Book) when matched; otherwise the hand-entered count.",
        "gap": "Combination products and discontinued ANDAs are not counted.",
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
        "status": "sourced",
        "present": "The Orange Book data files, fetched on a schedule (Admin → Pipelines). The older openFDA snapshot in code is still used by the process pages.",
        "gap": "FDA updates the data files monthly.",
    },
    "nsq_alerts": {
        "label": "CDSCO NSQ alerts",
        "status": "sourced",
        "present": "CDSCO Not-of-Standard-Quality notifications: the cumulative CSV, checked daily against the live CDSCO table (Admin → Pipelines).",
        "gap": "Historical months can only be backfilled if CDSCO's month filter answers; the bundled CSV covers Jan 2021 – Jul 2026.",
    },
}


def provenance() -> dict[str, dict[str, Any]]:
    return FIELD_PROVENANCE
