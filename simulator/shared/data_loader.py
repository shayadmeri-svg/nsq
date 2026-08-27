"""Shared data loading and preprocessing for the analytics app.

This module separates the data-pipeline logic from the Streamlit UI so that
both `analytics/app.py` (the full dashboard) and `analytics/landing.py` (the
animated home page) can load the same enriched NSQ DataFrame without
duplicating code.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

import nsq_redis
from company_ontology import (
    extract_city,
    extract_company_name,
    extract_state,
    extract_website,
    load_ontology,
    load_product_ontology,
    normalize_company_name,
    product_key,
    resolve_or_create,
    resolve_or_create_product,
)

# ---------------------------------------------------------------------------
# Research profiles for the handful of active ingredients we have real
# patent / formulation / GMP / pharmacopeia context for. Every other
# product falls through to a "Generic monograph" stub so the column
# stays populated instead of NaN.
# ---------------------------------------------------------------------------
RESEARCH_PROFILES: dict[str, dict[str, str]] = {
    "paracetamol": {
        "patent_link": "US9219104B2 (Stable Paracetamol Compaction)",
        "formulation": "Wet granulation with PVP K30 binder; crospovidone disintegrant",
        "gmp": "Granule LOD 1.5–2.5%; main compression 10–16 kN",
        "patent_status": "Composition-of-matter expired; formulation patents active",
        "eu_phr": "Ph. Eur. monograph 0049 (Paracetamol) — UV 249 nm; Paddle 50 RPM in water, NLT 80% (Q) in 45 min; Imp. K max 0.15%",
        "ip_2026": "IP 2026 monographs: HPLC C18, MeOH/H2O/AcOH (70:30:1), 1.0 mL/min; USP-2 50 RPM pH 5.8 buffer, NLT 80% in 30 min",
    },
    "metformin": {
        "patent_link": "US6610324 (Swellable Hydrophilic Metformin Matrix)",
        "formulation": "Wet granulation; HPMC K100M 28% swellable matrix; Na-CMC 8%",
        "gmp": "Granulation water 8–12 L; fluid bed drying 30–50 min at 60 °C",
        "patent_status": "API off-patent; ER formulation patents region-specific",
        "eu_phr": "Ph. Eur. monograph 0004 (Metformin HCl) — LC vs reference; Apparatus 1 100 RPM pH 6.8; total impurities max 0.1%",
        "ip_2026": "IP 2026: UV 233 nm; USP-1 100 RPM pH 6.8; 1 h 20–40%, 3 h 45–65%, 8 h NLT 85%; dicyandiamide max 0.02%",
    },
    "atorvastatin": {
        "patent_link": "US5686104 (Atorvastatin Calcium Buffering System)",
        "formulation": "Wet granulation; CaCO3 alkalizer 6% to prevent acid-catalyzed lactonization",
        "gmp": "Spray rate 40–80 g/min; drying end-point 1.5% LOD",
        "patent_status": "Substantially expired in most jurisdictions; crystalline form patents lapsed",
        "eu_phr": "Ph. Eur. monograph 2191 (Atorvastatin Calcium Trihydrate) — LC at UV 244 nm; Paddle 75 RPM pH 6.8; NLT 75% in 30 min; unspecified degradants max 0.15%",
        "ip_2026": "IP 2026: HPLC C18 with MeCN/THF/H2O/NH4OAc; Apparatus 2 75 RPM pH 6.8, NLT 75% in 30 min; lactone RS max 0.3%",
    },
    "amoxicillin": {
        "patent_link": "US4497947 (Stable Amoxicillin Trihydrate)",
        "formulation": "Wet granulation with MCC diluent; colloidal silica glidant",
        "gmp": "RH < 40% throughout processing; LDPE-aluminium blister",
        "patent_status": "Composition-of-matter expired (1990s); formulation patents region-specific",
        "eu_phr": "Ph. Eur. monograph 0260 (Amoxicillin Trihydrate) — LC; Paddle 75 RPM in water, NLT 80% (Q) in 30 min; total impurities max 1.5%",
        "ip_2026": "IP 2026 monographs: HPLC C18 phosphate buffer/ACN; Apparatus 2 75 RPM; related substances NMT 1.0%",
    },
}


def _first_api_match(text: str) -> str | None:
    """Return the first active-ingredient key whose token appears in `text`."""
    for api in RESEARCH_PROFILES:
        if api in text:
            return api
    return None


# Dosage-form taxonomy. `Form type` is the single keyword pass over the
# product name (fine-grained, 9 values incl. a vet/specialty tier checked
# first). `Form` is a deterministic rollup of `Form type` (coarse, 5
# buckets) — never derived from independent keywords, so the two columns
# can never disagree.
_VET_SPECIALTY_TOKENS = [
    "veterinary", "vet ", "bolus", "pour-on", "pour on",
    "otic", "ophthalmic", "eye drop", "ear drop", "inhaler",
    "nebulizer", "nebulisation", "transdermal", "patch",
    "gargle", "paint", "lotion", "shampoo",
    "infusion", "large volume parenteral", "lvp",
    "irrigation", "dialysis", "rectal", "enema", "suppository",
    "pellet", "implant", "gel", "jelly", "foam", "aerosol",
    "nasal", "spray",
]

_FORM_TYPE_TO_FORM = {
    "Tablet": "Oral tablets",
    "Capsule": "Oral tablets",
    "Syrup/Suspension": "Oral suspensions, syrups & drops",
    "Drops": "Oral suspensions, syrups & drops",
    "Injection": "Injectables",
    "Speciality/Vet": "Speciality & vet formulations",
    "Ointment/Cream": "Other",
    "Powder/Granules": "Other",
    "Other": "Other",
}


def _infer_form_type(text: str) -> str:
    """Fine-grained dosage form from a product name.

    Vet/specialty tokens are checked FIRST so e.g. 'eye drop'/'ear drop'
    land in Speciality/Vet rather than falling through to Drops. Order
    matters: vet_specialty must precede the 'drops' substring.
    """
    t = str(text or "").lower()
    if any(k in t for k in _VET_SPECIALTY_TOKENS):
        return "Speciality/Vet"
    if "tablet" in t:
        return "Tablet"
    if "capsule" in t:
        return "Capsule"
    if "syrup" in t or "suspension" in t:
        return "Syrup/Suspension"
    if "injection" in t or "injectable" in t:
        return "Injection"
    if "ointment" in t or "cream" in t:
        return "Ointment/Cream"
    if "drops" in t:
        return "Drops"
    if "powder" in t or "granules" in t:
        return "Powder/Granules"
    return "Other"


def _generic_research(row) -> str:
    """Fallback scientific context when no curated profile matches."""
    name = row.get("Name of Product") or "Unknown product"
    return (
        f"Patent link: search WIPO / USPTO / IPO for '{name}' (no curated profile) | "
        f"Formulation: standard oral solid unit-dose monograph; review SmPC for excipient precedents | "
        f"GMP: ICH Q7/Q9 risk-based; typical LOD 2–3%, compression 10–14 kN | "
        f"Patent status: API likely off-patent if listed in WHO essential medicines"
    )


def _generic_regulatory() -> str:
    return (
        "Eu. Phr.: consult the relevant Ph. Eur. monograph for the active substance; "
        "if not monographed, follow Ph. Eur. general chapter 2.9.3 (dissolution) and 2.9.6 (uniformity) | "
        "I.P. 2026: consult Indian Pharmacopoeia 2026 monograph; "
        "if not monographed, follow IP general chapters for the dosage form"
    )


def normalize_product(name) -> str:
    """Cosmetically harmonize a raw product name for display/grouping.

    Whitespace cleanup, split digit-letter boundaries, and case-fold the
    common pharmacopeial / strength abbreviations. Module-level so the
    product-ontology fallback can reuse it without Redis.
    """
    if pd.isna(name):
        return ""
    s = str(name)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = []
    for tok in s.split(" "):
        upper = tok.upper()
        if upper in {"IP", "BP", "USP", "NF", "NFI", "HCL", "HBR", "EC", "SR", "IP.", "BP.", "W/V", "W/W", "V/V", "MG", "ML", "GM", "MCG", "IU"}:
            tokens.append(upper.rstrip("."))
        else:
            tokens.append(tok.capitalize())
    return " ".join(tokens)


def _load_predictions_from_redis() -> dict:
    """Read every nsq:prediction:<id> HASH out of Redis.

    Returns {record_id: {field: value, ...}}. Returns {} if Redis is
    unreachable or the predictions haven't been populated (e.g. the
    dataset was loaded without --augment). The CSV loader writes
    `source_row` (the CSV Index) so the analytics app can join the
    predictions back to the DataFrame.
    """
    try:
        client = nsq_redis.get_redis_client()
    except Exception:
        return {}
    try:
        ids = client.smembers("nsq:records")
    except Exception:
        return {}
    if not ids:
        return {}
    try:
        pipe = client.pipeline()
        for rid in ids:
            pipe.hgetall(f"nsq:prediction:{rid}")
        rows = pipe.execute()
    except Exception:
        return {}
    out: dict = {}
    for rid, row in zip(ids, rows):
        if not row:
            continue
        # Join key: the Redis record id (nsq:record:<rid> and
        # nsq:prediction:<rid> share the same rid). The CDSCO `index` field
        # and the CSV `source_row` are NOT stable across mixed data loads
        # (a live CDSCO fetch and a CSV load produce colliding index
        # numbers), which mis-attributes manufacturers. The rid is the only
        # key guaranteed to match a record to its own prediction.
        join_key = rid
        out[join_key] = {
            "Mfg_Company": row.get("raw_company", ""),
            "Mfg_Company_Canonical": row.get("canonical", ""),
            # Deterministic bin re-derived from the RAW company name (a pure
            # function of the name via normalize_company_name), NOT trusted
            # from the upstream `canonical`/`ontology_key` fields. This is the
            # analytics-side second line of defense: even if a stale or
            # contaminated canonical persists in Redis, grouping on
            # Mfg_Bin_Key keeps unrelated manufacturers in separate bins. See
            # app._mfg_label, which trusts the upstream canonical as a DISPLAY
            # label only when it normalizes to this same bin.
            "Mfg_Bin_Key": normalize_company_name(row.get("raw_company", "")),
            "Mfg_City": row.get("city", ""),
            "Mfg_State_Ontology": row.get("state", ""),
            "Mfg_Website": row.get("website", ""),
            "Mfg_Ontology_Key": row.get("ontology_key", ""),
        }
    return out


def _derive_company_fields(line: str) -> pd.Series:
    """Row-level wrapper around the company-ontology resolver."""
    raw = "" if line is None else str(line)
    raw_company = extract_company_name(raw)
    city = extract_city(raw)
    state = extract_state(raw)
    website = extract_website(raw)

    canonical = ""
    key = ""
    try:
        key, record, _created = resolve_or_create(raw_company, raw)
        canonical = record.get("canonical_name", "") if record else ""
        if record:
            if not city and record.get("city"):
                city = record["city"]
            if not website and record.get("website"):
                website = record["website"]
            if not state and record.get("state"):
                state = record["state"]
    except Exception:
        # Redis/ontology unreachable: fall back to the extracted company
        # name and its normalized form so the canonical + ontology-key
        # columns are never blank offline (stable grouping still works).
        canonical = raw_company
        key = normalize_company_name(raw_company)

    return pd.Series({
        "Mfg_Company": raw_company,
        "Mfg_Company_Canonical": canonical,
        # Deterministic bin re-derived from the raw name (see the note in
        # _load_predictions_from_redis). Offline path: key already holds
        # normalize_company_name(raw_company) on the Redis-unreachable branch.
        "Mfg_Bin_Key": normalize_company_name(raw_company),
        "Mfg_City": city,
        "Mfg_Website": website,
        "Mfg_Ontology_Key": key,
    })


# show_spinner=False is load-bearing: this cached call sits ABOVE the
# st.tabs(...) declaration in app.py. With the default show_spinner=True a
# spinner widget is inserted into the element tree on a cache MISS (cold
# load) and removed on every cache HIT (e.g. a radio/slider change). That
# appear/disappear above the tab container unmounts Streamlit's React Tab
# component, which holds the active-tab index only in frontend state — so
# it resets to the first tab on every widget change (Streamlit #13341).
# Suppressing the spinner keeps the element count above st.tabs invariant
# across reruns. Do not re-enable without also moving st.tabs above this
# call or backing the tab selection with session_state.
@st.cache_data(ttl=300, show_spinner=False)
def load_and_preprocess_data() -> pd.DataFrame:
    """Fetch NSQ data from Redis or CSV and return an enriched DataFrame."""
    # Load dataset from Redis (populated by redis-loader/load_nsq_redis.py)
    df = nsq_redis.load_dataframe()

    # 1. Derive harmonized failure category from NSQ Result.
    if ("Failure_Category" not in df.columns
            or "Failure_Category_Primary" not in df.columns):
        _CAT_PATTERNS: list[tuple[str, str]] = [
            ("Sterility / Microbial", r"\b(sterility|sterillity|microbial contamination|total aerobic (viable|microbial) count|total fungal count|total yeast and mould count|total viable count|total microbial count)\b"),
            ("Bacterial Endotoxin", r"\b(bacterial endotoxin|bet endotoxin|endotoxins?|bet)\b"),
            ("Dissolution", r"\bdissolution\b"),
            ("Disintegration", r"\b(disintegration|fines? of dispersion|fineness)\b"),
            ("Assay / Content", r"\b(assay|\bcontent(?! uniformity of weight)|content uniformity|uniformity of content|contents of)\b"),
            ("Description / Appearance", r"\b(description|appearance|clarity and colour|descriptive part|matter insoluble in alcohol|fineness residue|suspended matter|sedimentation|colour\b|cleanliness)\b"),
            ("Particulate Matter", r"\b(particulate matter|particulate)\b"),
            ("Uniformity of Weight", r"\b(uniformity of weight|uniformity)\b"),
            ("Weight per ml / Density", r"\b(weight per ml|specific gravity|density)\b"),
            ("Hardness / Friability", r"\b(hardness|friabilit|brittle tablets?|soft tablet|crumb)\b"),
            ("pH", r"\bp\s*h\b"),
            ("Labelling", r"\b(labelling|labeling|incorrect label|not mentioned on the label|label claim|strips?\s+as required)\b"),
            ("Misbranded", r"\bmisbrand"),
            ("Identification", r"\bidentification\b"),
            ("Related Substances", r"(related substance|impurit|degradant|degradation product|loss on drying)"),
            ("Heavy Metals", r"\b(heavy metal|lead|cadmium|arsenic|mercury)\b"),
        ]

        def _categorize(text: str) -> tuple[str, str]:
            t = str(text or "").lower()
            hits: list[str] = []
            for name, pat in _CAT_PATTERNS:
                if re.search(pat, t, re.IGNORECASE):
                    if name not in hits:
                        hits.append(name)
            if not hits:
                return "", "Uncategorized"
            return " | ".join(hits), hits[0]

        nsq_text = df["NSQ Result"].fillna("").astype(str)
        categorized = nsq_text.apply(_categorize)
        df["Failure_Category"] = categorized.apply(lambda x: x[0])
        df["Failure_Category_Primary"] = categorized.apply(lambda x: x[1])

    # 2. Derive Form type (fine-grained) from product name if missing.
    if "Form type" not in df.columns:
        df["Form type"] = df["Name of Product"].fillna("").astype(str).apply(_infer_form_type)

    # 3. Derive Form (coarse user-facing taxonomy) as a deterministic
    # rollup of Form type — never from independent keywords, so the two
    # columns stay consistent.
    if "Form" not in df.columns:
        df["Form"] = df["Form type"].map(_FORM_TYPE_TO_FORM).fillna("Other")

    # 4. (removed) Indication — redundant with Drug type (step 6 below);
    #    no filter or chart consumed it. Therapeutic classification is
    #    now single-sourced from Drug type.

    # 5. Derive Research enrichment bundle from product name.
    if "Scientific context research" not in df.columns:
        def derive_research(row):
            t = str(row.get("Name of Product") or "").lower()
            profile = RESEARCH_PROFILES.get(_first_api_match(t))
            if profile is None:
                return pd.Series({
                    "Scientific context research": _generic_research(row),
                    "Regulatory guidelines research": _generic_regulatory(),
                })
            return pd.Series({
                "Scientific context research": (
                    f"Patent link: {profile['patent_link']} | "
                    f"Formulation: {profile['formulation']} | "
                    f"GMP: {profile['gmp']} | "
                    f"Patent status: {profile['patent_status']}"
                ),
                "Regulatory guidelines research": (
                    f"Eu. Phr.: {profile['eu_phr']} | "
                    f"I.P. 2026: {profile['ip_2026']}"
                ),
            })

        df[["Scientific context research", "Regulatory guidelines research"]] = (
            df[["Name of Product", "NSQ Result"]].fillna("").apply(derive_research, axis=1)
        )

    # 6. Derive Drug type (therapeutic category) heuristically if missing
    if "Drug type" not in df.columns:
        def infer_drug_type(text):
            t = str(text).lower()
            antibiotics = ["amoxycillin", "amoxicillin", "ciprofloxacin", "ofloxacin", "azithromycin", "cefixime", "cephalexin", "metronidazole", "doxycycline"]
            analgesics = ["paracetamol", "diclofenac", "ibuprofen", "aspirin", "tramadol", "aceclofenac"]
            vitamins = ["vitamin", "multivitamin", "iron", "folic", "calcium", "zinc"]
            cardiac = ["amlodipine", "telmisartan", "losartan", "atenolol", "metoprolol", "ramipril", "atorvastatin"]
            antidiabetic = ["metformin", "glimepiride", "glipizide", "insulin", "vildagliptin"]
            antacid = ["omeprazole", "pantoprazole", "rabeprazole", "ranitidine", "esomeprazole"]
            respiratory = ["salbutamol", "ambroxol", "guaiphenesin", "terbutaline", "dextromethorphan", "phenylephrine", "chlorpheniramine", "montelukast", "levocetirizine"]
            if any(k in t for k in antibiotics):
                return "Antibiotic"
            if any(k in t for k in analgesics):
                return "Analgesic/Antipyretic"
            if any(k in t for k in vitamins):
                return "Vitamin/Nutritional"
            if any(k in t for k in cardiac):
                return "Cardiovascular"
            if any(k in t for k in antidiabetic):
                return "Antidiabetic"
            if any(k in t for k in antacid):
                return "Antacid/Antiulcer"
            if any(k in t for k in respiratory):
                return "Respiratory"
            return "Other / Unclassified"
        df["Drug type"] = df["Name of Product"].apply(infer_drug_type)

    # 7. (removed) Recall Class — was a hardcoded "Unclassified" placeholder
    #    with no source data. If a future CDSCO export ships a real recall /
    #    risk-class column, add a real derivation then.

    # 8. Identify Dissolution Failures
    text_search_space = df[["Failure_Category", "NSQ Result", "Name of Product"]].fillna("").astype(str)
    df["Is_Dissolution"] = (
        df["Failure_Category"].fillna("").str.contains(r"\bDissolution\b", regex=True)
        | df["NSQ Result"].fillna("").str.contains("dissolution", case=False, regex=False)
        | df["Name of Product"].fillna("").str.contains("dissolution", case=False, regex=False)
    )

    # 9. Parse Date Features. (Year_Month_Str removed — it was a copy of
    #    Reporting Month & Year; Parsed_Date covers typed usage.)
    df["Parsed_Date"] = pd.to_datetime(df["Reporting Month & Year"], format="%b-%Y", errors="coerce")

    # 10. Extract Indian State from "Manufactured By". State extraction is
    # consolidated in company_ontology.extract_state (state-name match then
    # city -> state map); it returns "" for no match. Step 11 overrides
    # this with the ontology state when a Redis prediction is available.
    df["Mfg_State"] = df["Manufactured By"].apply(extract_state)

    # 11. Read pre-computed predictions from Redis if available.
    needed_cols = ("Mfg_Company", "Mfg_Company_Canonical", "Mfg_City",
                   "Mfg_State_Ontology", "Mfg_Website", "Mfg_Ontology_Key")
    if not all(c in df.columns for c in needed_cols):
        predictions = _load_predictions_from_redis()
        if predictions:
            pred_df = pd.DataFrame.from_dict(predictions, orient="index")
            pred_df.index = pred_df.index.astype(str)
            # Join on the Redis record id — the stable key shared by
            # nsq:record:<rid> and nsq:prediction:<rid>. The CDSCO `index`
            # field is not stable across mixed data loads (see
            # _load_predictions_from_redis).
            if "record_id" in df.columns:
                df["__join_key"] = df["record_id"].astype(str)
            elif "index" in df.columns:
                df["__join_key"] = df["index"].astype(str)
            else:
                df["__join_key"] = df.index.astype(str)
            joined = df[["__join_key"]].join(pred_df, on="__join_key").drop(columns=["__join_key"])
            if "Mfg_State_Ontology" in joined.columns:
                df["Mfg_State"] = (
                    joined["Mfg_State_Ontology"]
                    .where(joined["Mfg_State_Ontology"].fillna("") != "", df["Mfg_State"])
                    .fillna(df["Mfg_State"])
                    .values
                )
            for col in needed_cols:
                if col in joined.columns and col not in df.columns:
                    df[col] = joined[col].fillna("").values
        if not all(c in df.columns for c in needed_cols[:4]):
            for c in needed_cols:
                if c not in df.columns:
                    df[c] = ""
        if "Mfg_Company" not in df.columns or df["Mfg_Company"].isna().any() or (df["Mfg_Company"] == "").any():
            mask = df.get("Mfg_Company", pd.Series(dtype=str)).fillna("") == "" if "Mfg_Company" in df.columns else pd.Series([True] * len(df))
            if mask.any():
                derived = df.loc[mask, "Manufactured By"].apply(_derive_company_fields)
                for col in derived.columns:
                    if col not in df.columns:
                        df[col] = ""
                    df.loc[mask, col] = derived[col].values

    # 12. Resolve company / city / website from the 'Manufactured By' free text.
    if (
        "Mfg_Company" not in df.columns
        or "Mfg_Company_Canonical" not in df.columns
        or "Mfg_City" not in df.columns
        or "Mfg_Website" not in df.columns
    ):
        df[["Mfg_Company", "Mfg_Company_Canonical", "Mfg_City", "Mfg_Website", "Mfg_Ontology_Key"]] = (
            df["Manufactured By"].apply(_derive_company_fields)
        )

    # 13. Harmonize product names for grouping.
    df["Product_Name_Norm"] = df["Name of Product"].apply(normalize_product)

    # 14. Resolve each product to a canonical entry in the product ontology.
    if "Product_Name_Canonical" not in df.columns or "Product_Ontology_Key" not in df.columns:
        def _resolve_product_batch():
            product_names = df["Name of Product"].fillna("").astype(str)
            canonical_col: list[str] = [""] * len(product_names)
            key_col: list[str] = [""] * len(product_names)

            try:
                r = nsq_redis.get_redis_client()
                cache = load_product_ontology(r)
            except Exception:
                # Redis/ontology unreachable: fall back to a locally
                # computed key + normalized display name so these columns
                # are never blank for the whole DataFrame offline. Mirrors
                # landing.py's _product_group_key fallback.
                for idx, raw in enumerate(product_names):
                    key_col[idx] = product_key(raw)
                    canonical_col[idx] = normalize_product(raw)
                return canonical_col, key_col

            dirty_keys: set[str] = set()

            for idx, raw in enumerate(product_names):
                try:
                    key, record, _created = resolve_or_create_product(
                        raw,
                        client=r,
                        ontology_cache=cache,
                        flush=False,
                    )
                    canonical = record.get("canonical_name", "") if record else ""
                    key_col[idx] = key
                    canonical_col[idx] = canonical
                    if key:
                        dirty_keys.add(key)
                except Exception:
                    key_col[idx] = product_key(raw)
                    canonical_col[idx] = normalize_product(raw)

            if dirty_keys:
                try:
                    pipe = r.pipeline(transaction=False)
                    for key in dirty_keys:
                        rec = cache.get(key)
                        if rec is None:
                            continue
                        pipe.hset(
                            "nsq:ontology:products",
                            mapping={key: json.dumps(rec, ensure_ascii=False)},
                        )
                    pipe.hset(
                        "nsq:ontology:products:meta",
                        mapping={
                            "entry_count": str(len(cache)),
                            "last_updated": datetime.now(timezone.utc).isoformat(),
                            "version": "1",
                        },
                    )
                    pipe.execute()
                except Exception:
                    pass

            return canonical_col, key_col

        canonical_col, key_col = _resolve_product_batch()
        df = df.copy()
        df["Product_Name_Canonical"] = canonical_col
        df["Product_Ontology_Key"] = key_col

    return df


def fuzzy_search_products(df: pd.DataFrame, query: str, threshold: int = 70) -> list[tuple[int, int, str]]:
    """Fuzzy-match `query` against every distinct product name in `df`."""
    try:
        from rapidfuzz import fuzz  # type: ignore
        _has_rapidfuzz = True
    except ImportError:  # pragma: no cover
        _has_rapidfuzz = False

    if not query or not query.strip():
        return []

    corpus = df[["Name of Product"]].fillna("").astype(str).copy()
    corpus["__idx"] = corpus.index
    corpus = corpus.drop_duplicates(subset=["Name of Product"], keep="first")

    q = query.strip().lower()
    hits: list[tuple[int, int, str]] = []
    for _, row in corpus.iterrows():
        name = row["Name of Product"]
        if not name:
            continue
        if _has_rapidfuzz:
            score = int(fuzz.token_set_ratio(q, name.lower()))
        else:
            sa, sb = set(q.split()), set(name.lower().split())
            if not sa or not sb:
                continue
            score = int(round(100 * len(sa & sb) / len(sa | sb)))
        if q in name.lower() or score >= threshold:
            hits.append((int(row["__idx"]), score, name))

    hits.sort(key=lambda t: (-t[1], t[2]))
    return hits
