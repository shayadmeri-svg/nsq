"""Real FDA Orange Book data for the Idea 4 US regulatory axis.

Sourced live from the openFDA Orange Book endpoint
(https://api.fda.gov/drug/orangebook.json) on 2026-08-18 and baked here as a
curated, cited dataset so the analytics app reads real cited data at import
time — never the network at render time. Each record carries a registry_prov
at the regulatory_registry authority tier with the real openFDA query URL and
the retrieval date, so the provenance is traceable, not asserted.

Why baked and not live-fetched in the app: analytics is an offline CSV app; a
network dependency at import would break the read-only investigation flow and
make the rigour gate depend on an external service's uptime. Baking the
already-fetched, dated data preserves the citation (URL + retrieved_at) while
keeping the app hermetic. Re-running the fetch (see us_regulatory_fetch.py
pattern) refreshes this file with a new retrieved_at.

Coverage: 16/17 catalog molecules. vildagliptin is NOT FDA-approved in the US
(no Orange Book entry — the openFDA query 404s), so it is honestly None, never
faked. amoxicillin, which had no simulator regulatory passport, DOES have real
FDA Orange Book data (NDA N050754, TE=AB) and is included here.

The USP compendial *method* text (apparatus/medium/limits) is NOT in this file:
USP-NF is subscription-gated. The USP method axis (drug.usp) stays None until a
real USP-NF (or FDA Product-Specific Guidance dissolution) source is wired —
honest absence, not a placeholder. The Orange Book TE codes / RLD below are the
real, citable US regulatory data for the axis.
"""

from __future__ import annotations

from gmp_knowledge import (
    OrangeBookRecord,
    registry_prov,
)

# Retrieval date for every citation below — the day the openFDA Orange Book
# endpoint was queried for this dataset. Update this when re-fetching.
RETRIEVED_AT = "2026-08-18"

# Raw per-molecule facts lifted verbatim from the openFDA Orange Book query
# results (single-ingredient products; salt-form active ingredients matched
# on the base name, e.g. AMLODIPINE matches "AMLODIPINE BESYLATE"). te_codes is
# the set of Therapeutic Equivalence codes across single-ingredient products.
# Strengths have the openFDA "**Federal Register determination...**" marketing
# note stripped (it is not a strength value).
_ORANGE_BOOK_RAW: dict[str, dict] = {
    "amlodipine": dict(active_ingredient="AMLODIPINE", te_codes=["AB"], rld_applicant="CMP DEVELOPMENT LLC", rld_app_number="N214439", rld_approval_date="20220224", reference_standard=True, rld_dosage_form="SOLUTION", dosage_forms=["SOLUTION", "TABLET"], strengths=["2.5MG", "5MG", "10MG"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "amoxicillin": dict(active_ingredient="AMOXICILLIN", te_codes=["AB"], rld_applicant="US ANTIBIOTICS LLC", rld_app_number="N050754", rld_approval_date="19980710", reference_standard=True, rld_dosage_form="TABLET", dosage_forms=["CAPSULE", "FOR SUSPENSION", "TABLET", "TABLET, CHEWABLE", "TABLET, EXTENDED RELEASE"], strengths=["125MG", "125MG/5ML", "200MG", "200MG/5ML"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "atenolol": dict(active_ingredient="ATENOLOL", te_codes=["AB"], rld_applicant="ASTRAZENECA PHARMACEUTICALS LP", rld_app_number="N019058", rld_approval_date="19890913", reference_standard=True, rld_dosage_form="INJECTABLE", dosage_forms=["INJECTABLE", "TABLET"], strengths=["25MG", "50MG", "100MG", "0.5MG/ML"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "atorvastatin": dict(active_ingredient="ATORVASTATIN", te_codes=["AB"], rld_applicant="UPJOHN MANUFACTURING IRELAND UNLTD", rld_app_number="N020702", rld_approval_date="19961217", reference_standard=True, rld_dosage_form="TABLET", dosage_forms=["TABLET"], strengths=["10MG", "20MG", "40MG", "80MG"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "esomeprazole": dict(active_ingredient="ESOMEPRAZOLE", te_codes=["AB", "AP"], rld_applicant="DEXCEL PHARMA TECHNOLOGIES LTD", rld_app_number="N214278", rld_approval_date="20201020", reference_standard=True, rld_dosage_form="TABLET, ORALLY DISINTEGRATING, DELAYED RELEASE", dosage_forms=["CAPSULE, DELAYED RELEASE", "FOR SUSPENSION, DELAYED RELEASE", "INJECTABLE", "TABLET, DELAYED RELEASE"], strengths=["10MG", "20MG", "2.5MG", "40MG"], marketing_statuses=["DISCONTINUED", "HUMAN OTC DRUG", "HUMAN PRESCRIPTION DRUG"]),
    "glimepiride": dict(active_ingredient="GLIMEPIRIDE", te_codes=["AB"], rld_applicant="SANOFI AVENTIS US LLC", rld_app_number="N020496", rld_approval_date="19951130", reference_standard=True, rld_dosage_form="TABLET", dosage_forms=["TABLET"], strengths=["1MG", "2MG", "3MG", "4MG"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "losartan": dict(active_ingredient="LOSARTAN", te_codes=["AB"], rld_applicant="ORGANON LLC A SUB OF ORGANON AND CO", rld_app_number="N020386", rld_approval_date="19950414", reference_standard=True, rld_dosage_form="TABLET", dosage_forms=["SUSPENSION", "TABLET"], strengths=["25MG", "50MG", "100MG", "10MG/ML"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "metformin": dict(active_ingredient="METFORMIN", te_codes=["AB", "AB1", "AB2", "AB3"], rld_applicant="SUN PHARMACEUTICAL INDUSTRIES LTD", rld_app_number="N212595", rld_approval_date="20190829", reference_standard=True, rld_dosage_form="FOR SUSPENSION, EXTENDED RELEASE", dosage_forms=["FOR SUSPENSION, EXTENDED RELEASE", "SOLUTION", "TABLET", "TABLET, EXTENDED RELEASE"], strengths=["500MG", "750MG", "850MG", "1GM"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "pantoprazole": dict(active_ingredient="PANTOPRAZOLE", te_codes=["AB", "AP"], rld_applicant="BAXTER HEALTHCARE CORP", rld_app_number="N217512", rld_approval_date="20240214", reference_standard=True, rld_dosage_form="SOLUTION", dosage_forms=["FOR SUSPENSION, DELAYED RELEASE", "INJECTABLE", "POWDER", "SOLUTION", "TABLET, DELAYED RELEASE"], strengths=["20MG", "40MG", "80MG"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "paracetamol": dict(active_ingredient="ACETAMINOPHEN", te_codes=[], rld_applicant="KENVUE BRANDS LLC", rld_app_number="N019872", rld_approval_date="20010111", reference_standard=True, rld_dosage_form="TABLET, EXTENDED RELEASE", dosage_forms=["SOLUTION", "SUPPOSITORY", "TABLET, EXTENDED RELEASE"], strengths=["120MG", "650MG", "10MG/ML"], marketing_statuses=["DISCONTINUED", "HUMAN OTC DRUG"]),
    "rabeprazole": dict(active_ingredient="RABEPRAZOLE", te_codes=["AB"], rld_applicant="AYTU BIOSCIENCE INC", rld_app_number="N204736", rld_approval_date="20130326", reference_standard=True, rld_dosage_form="CAPSULE, DELAYED RELEASE", dosage_forms=["CAPSULE, DELAYED RELEASE", "TABLET, DELAYED RELEASE"], strengths=["5MG", "10MG", "20MG"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "ramipril": dict(active_ingredient="RAMIPRIL", te_codes=["AB"], rld_applicant="ROSEMONT PHARMACEUTICALS HOLDINGS INC", rld_app_number="N219757", rld_approval_date="20250723", reference_standard=True, rld_dosage_form="SOLUTION", dosage_forms=["CAPSULE", "SOLUTION", "TABLET"], strengths=["1.25MG", "2.5MG", "5MG", "10MG", "1MG/ML"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "rosuvastatin": dict(active_ingredient="ROSUVASTATIN", te_codes=["AB"], rld_applicant="ASTRAZENECA UK LTD", rld_app_number="N021366", rld_approval_date="20030812", reference_standard=False, rld_dosage_form="TABLET", dosage_forms=["TABLET"], strengths=["5MG", "10MG", "20MG", "40MG"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "sitagliptin": dict(active_ingredient="SITAGLIPTIN", te_codes=["AB"], rld_applicant="MERCK SHARP AND DOHME LLC", rld_app_number="N021995", rld_approval_date="20061016", reference_standard=True, rld_dosage_form="TABLET", dosage_forms=["SOLUTION", "TABLET"], strengths=["25MG", "50MG", "100MG"], marketing_statuses=["HUMAN PRESCRIPTION DRUG"]),
    "tamoxifen": dict(active_ingredient="TAMOXIFEN", te_codes=["AB"], rld_applicant="ASTRAZENECA PHARMACEUTICALS LP", rld_app_number="N017970", rld_approval_date=None, reference_standard=True, rld_dosage_form="TABLET", dosage_forms=["SOLUTION", "TABLET"], strengths=["10MG", "20MG", "2MG/ML"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    "telmisartan": dict(active_ingredient="TELMISARTAN", te_codes=["AB"], rld_applicant="BOEHRINGER INGELHEIM", rld_app_number="N020850", rld_approval_date="19981110", reference_standard=True, rld_dosage_form="TABLET", dosage_forms=["TABLET"], strengths=["20MG", "40MG", "80MG"], marketing_statuses=["DISCONTINUED", "HUMAN PRESCRIPTION DRUG"]),
    # vildagliptin: NOT FDA-approved in the US — the openFDA Orange Book query
    # 404s. Honestly absent (no entry here); drug.orange_book stays None.
}

# The openFDA query URL per active ingredient (the citation for every record).
def _query_url(active_ingredient: str) -> str:
    import urllib.parse
    q = urllib.parse.quote(f'products.active_ingredients.name:"{active_ingredient}"')
    return f"https://api.fda.gov/drug/orangebook.json?search={q}&limit=100"


def orange_book_for(molecule_id: str) -> OrangeBookRecord | None:
    """Build the real FDA Orange Book record for one catalog molecule, with a
    registry_prov carrying the real openFDA query URL + retrieval date. Returns
    None for molecules with no FDA Orange Book entry (vildagliptin)."""
    raw = _ORANGE_BOOK_RAW.get(molecule_id)
    if raw is None:
        return None
    url = _query_url(raw["active_ingredient"])
    te_str = ",".join(raw["te_codes"]) or "(none — OTC / not TE-coded)"
    prov = registry_prov(
        ref=f"FDA Orange Book {raw['rld_app_number']} ({raw['active_ingredient']})",
        url=url,
        retrieved_at=RETRIEVED_AT,
        notes=(
            f"openFDA /drug/orangebook.json, single-ingredient products; "
            f"TE codes={te_str}; RLD applicant={raw['rld_applicant']}; "
            f"retrieved {RETRIEVED_AT}"
        ),
    )
    return OrangeBookRecord(
        active_ingredient=raw["active_ingredient"],
        te_codes=list(raw["te_codes"]),
        rld_applicant=raw["rld_applicant"],
        rld_app_number=raw["rld_app_number"],
        rld_approval_date=raw["rld_approval_date"],
        reference_standard=raw["reference_standard"],
        rld_dosage_form=raw["rld_dosage_form"],
        dosage_forms=list(raw["dosage_forms"]),
        strengths=list(raw["strengths"]),
        marketing_statuses=list(raw["marketing_statuses"]),
        provenance=prov,
    )


def stamp_us_regulatory_data() -> dict[str, int]:
    """Attach the real FDA Orange Book record to each catalog molecule that has
    one. Called after _stamp_default_provenance(). Returns coverage counts for
    auditability. Leaves drug.usp None (USP-NF method text is subscription-gated
    — honest absence) and drug.orange_book None where there is no FDA entry.

    References gmp_knowledge.PRODUCT_CATALOG dynamically so the stamp always
    targets the currently-loaded gmp_knowledge module (tests reload
    gmp_knowledge per-case; a static top-level binding would stamp a stale
    instance)."""
    import gmp_knowledge
    stamped = 0
    absent = 0
    for molecule_id in gmp_knowledge.PRODUCT_CATALOG:
        rec = orange_book_for(molecule_id)
        gmp_knowledge.PRODUCT_CATALOG[molecule_id].orange_book = rec
        if rec is not None:
            stamped += 1
        else:
            absent += 1
    return {"orange_book_stamped": stamped, "orange_book_absent": absent}


stamp_us_regulatory_data()