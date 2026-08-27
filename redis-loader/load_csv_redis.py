"""Load the cumulative NSQ CSV (e.g. 'CDSCO Not of Standard Quality (NSQ)
Jan 21-Jul 26.csv') into Redis.

The CSV is cumulative: new monthly CDSCO notifications are appended to it
and the whole dataset is reloaded with --flush (just reload-csv). Because
prepare_rows() sorts before building the ontology, the resulting Redis
state is a pure function of the CSV content — independent of row order —
so monthly appends cannot perturb existing manufacturer bins.

Record identity: one alert = (batch_no, product_name, reporting_month,
reporting lab). See record_id().

Same Redis layout as `load_nsq_redis.py` so analytics and simulator see
no schema change:

  nsq:record:<id>         -> HASH of one row
  nsq:records              -> SET of all record ids
  nsq:by_month:<YYYY-MM>   -> SET of record ids reported that month
  nsq:meta                 -> HASH: total_records, loaded_records,
                                    loaded_at, source_file

Plus, when --augment is on, for every record we also write:

  nsq:prediction:<id>      -> HASH of {canonical, raw_company, city,
                                      state, website, aliases,
                                      sources, augmented_at, source_row}
  nsq:ontology:companies   -> HASH of {normalized_key -> JSON record}
  nsq:ontology:meta        -> HASH: entry_count, last_updated, version

The augmentation runs the company-ontology pipeline on each row's
'Manufactured By' field. The same algorithm lives in
`shared/company_ontology.py`, but the loader inlines a self-contained
copy so the loader has no dependency on the shared/ tree (and the
loader is a one-shot batch job, not a long-running service, so drift
risk is much lower than the three existing service-side copies).

Field renames: the CSV uses legacy column names
('Name of Product', 'Batch No', 'Mfg', 'Exp', 'Manufactured By', etc.)
and the JSON loader writes 'str_*' / 'dt_*' keys. The two need to
look the same to the apps, so before hashing/writing we rename
CSV-style columns to CDSCO-style keys (the inverse of FIELD_MAP in
shared/nsq_redis.py). The downstream apps then apply FIELD_MAP again
to get the CSV column names back — net effect: zero change to the
apps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import redis


# ---------------------------------------------------------------------------
# Field renames (CSV column -> CDSCO API key)
# ---------------------------------------------------------------------------
# Kept in lockstep with FIELD_MAP in shared/nsq_redis.py so the apps see
# the same column names regardless of which loader populated Redis.
CSV_TO_CDSCO = {
    "Index":                    "index",
    "Name of Product":          "str_product_name",
    "Batch No":                 "str_batch_no",
    "Mfg":                      "dt_manufacturing_date",
    "Exp":                      "dt_expiry_date",
    "Manufactured By":          "str_manufactured_by",
    "NSQ Result":               "str_nsq_result",
    "Reporting Source":         "str_reporting_source",
    "Reporting by Lab/State":   "str_reported_by_lab_or_state",
    "Reporting Month & Year":   "dt_reporting_month_year",
    "Source":                   "source",
}

MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


# ---------------------------------------------------------------------------
# Hash + month helpers — imported-equivalent to load_nsq_redis.py so the
# same (batch_no, product_name, reporting_month, lab) tuple produces the
# same record_id whether the data came from JSON or CSV.
# ---------------------------------------------------------------------------
def record_id(row: dict) -> str:
    """Stable id for one NSQ alert.

    (batch_no, product_name) alone is NOT a natural key: the same batch
    legitimately fails in consecutive months (re-tested samples listed in
    successive CDSCO notifications), can be tested by different labs in
    the same month, and can be listed twice in ONE notification having
    failed DIFFERENT tests (e.g. Sterility vs pH+Related). Hashing only
    batch+product collapsed those distinct alerts into one record
    (last-write-wins) — 46 alerts were lost that way on the Jan25-Jun26
    dataset alone. The reporting month, the (harmonized) reporting lab,
    and the failing-test text are therefore part of the key; rows that
    remain identical under it are true duplicates of one alert.
    """
    month = normalize_month(row.get('dt_reporting_month_year')) or \
        (row.get('dt_reporting_month_year') or '').strip()
    key = "|".join([
        (row.get('str_batch_no') or '').strip(),
        (row.get('str_product_name') or '').strip(),
        month,
        (row.get('str_reported_by_lab_or_state') or '').strip(),
        (row.get('str_nsq_result') or '').strip(),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# Fields that identify the *content* of an alert, i.e. everything that
# matters once the record key (batch|product|month|lab) is fixed. Two
# prepared rows with the same key AND the same content signature are true
# duplicates (Index differs only); same key but different content means the
# source listed the same alert twice with slightly different text (typos,
# trailing spaces) — the first is kept, the rest counted as collapsed.
_CONTENT_FIELDS = (
    "str_product_name", "str_batch_no", "dt_manufacturing_date",
    "dt_expiry_date", "str_manufactured_by", "str_nsq_result",
    "str_reporting_source", "str_reported_by_lab_or_state",
    "dt_reporting_month_year", "source",
)


def content_signature(cdsco: dict) -> tuple:
    return tuple((cdsco.get(f) or "").strip() for f in _CONTENT_FIELDS)


def prepare_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """Deterministically prepare CSV rows for a Redis load.

    1. Rename CSV columns to CDSCO keys and harmonize labs (_row_to_cdsco).
    2. Sort by (month, batch, product, lab, mfg, result, source) so the
       ontology build order — and therefore every binning decision — is a
       pure function of the CSV *content*, not of the file's row order.
       Monthly appends to the cumulative CSV can land anywhere in the file
       without changing the resulting ontology.
    3. Drop true duplicates (identical content beyond Index).
    4. Collapse residual same-key rows (the key covers batch|product|month|
       lab|result, so a residual collision means the same alert listed twice
       differing only in e.g. Mfg/Exp spelling), keeping the first in
       sorted order. Logged, counted, and expected to be rare/zero.

    Returns (prepared_rows, stats).
    """
    cdsco_rows = [_row_to_cdsco(r) for r in rows]
    cdsco_rows.sort(key=lambda r: tuple(
        (r.get(f) or "").strip() for f in (
            "dt_reporting_month_year", "str_batch_no", "str_product_name",
            "str_reported_by_lab_or_state", "str_manufactured_by",
            "str_nsq_result", "str_reporting_source", "source",
        )
    ))

    stats = {"rows_in": len(rows), "true_duplicates_removed": 0,
             "same_key_collapsed": 0, "collapsed_samples": []}

    seen_content: set[tuple] = set()
    by_id: dict[str, dict] = {}
    prepared: list[dict] = []
    for r in cdsco_rows:
        sig = content_signature(r)
        if sig in seen_content:
            stats["true_duplicates_removed"] += 1
            continue
        seen_content.add(sig)
        rid = record_id(r)
        if rid in by_id:
            stats["same_key_collapsed"] += 1
            if len(stats["collapsed_samples"]) < 5:
                stats["collapsed_samples"].append({
                    "id": rid,
                    "kept": (by_id[rid].get("str_nsq_result") or "")[:60],
                    "dropped": (r.get("str_nsq_result") or "")[:60],
                })
            continue
        by_id[rid] = r
        prepared.append(r)
    return prepared, stats


def normalize_month(raw: str | None) -> str | None:
    """'Jan-2026' or 'JAN-2026' -> '2026-01'. Returns None if unparseable."""
    if not raw:
        return None
    parts = raw.strip().upper().split("-")
    if len(parts) != 2:
        return None
    mon, year = parts
    mon = MONTH_MAP.get(mon[:3])
    if not mon or not year.isdigit():
        return None
    return f"{year}-{mon}"


# ---------------------------------------------------------------------------
# Reporting-lab harmonization
# ---------------------------------------------------------------------------
# The CDSCO dataset has several labs spelled inconsistently across rows
# (with/without comma, with/without state suffix, etc.). Analytics'
# value_counts() and cross-tab heatmap would treat these as separate
# entities, splitting the same lab into two columns. Collapse the
# known variants to one canonical form per lab before writing to Redis.
#
# Important: the canonical name MUST be one of the observed variants
# (otherwise the original string is lost) — with one deliberate exception
# below: the non-lab placeholder 'Not applicable' is mapped to 'Unknown'.
# The chosen canonicals are the most common spelling for each lab.
LAB_CANONICAL = {
    # CDSCO lists this placeholder (20 rows in the Jan21-Jul26 file) when a
    # notification does not name a testing lab. It is not a lab; mapping it
    # to a sentinel keeps it out of the lab cross-tabs while preserving the
    # rows. Any future placeholder spelling should be added to this list.
    "Unknown": [
        "Not applicable",
        "Not Applicable",
        "N/A",
        "NA",
    ],
    "CDL, Kolkata": [
        "CDL, Kolkata",
        "CDL Kolkata",
        "CDL,Kolkata",
    ],
    "CDL Kasauli": [
        "CDL Kasauli",
        "Central Drugs Laboratory, Kasauli",
    ],
    "RDTL, Bellary Karnataka": [
        "RDTL, Bellary Karnataka",
        "RDTL. Bellary Karnataka",
    ],
    "DTL, Jaipur": [
        "DTL, Jaipur",
        "DTL Jaipur",
        "DTL,Jaipur (State Lab)",
        "DTL, Jaipur (State Lab)",
        "DTL,Jaipur(State Lab)",
    ],
    "CDTL, Mumbai": [
        "CDTL, Mumbai",
        "CDTL Mumbai",
        "CDTL-Mumbai",
    ],
    "DTL Thiruvananthapuram": [
        "DTL Thiruvananthapuram",
        "Drugs Testing Laboratory Thiruvananthapuram",
        "DTL Thiruvananthapuram,Kerala",
        "DTL, Thiruvananthapuram",
        "DTL, Thiruvananthapuram, Kerala",
    ],
    "RDTL, Chandigarh": [
        "RDTL, Chandigarh",
        "RDTL Chandigarh",
        "RDTL,Chandigarh",
    ],
    "RDTL, Guwahati": [
        "RDTL, Guwahati",
        "RDTL Guwahati",
        "RDTL,Guwahati",
    ],
    "DTL, Madurai-19": [
        "DTL Madurai",
        "DTL,Madurai",
        "DTL, Madurai-19",
        "Drugs Testing Laboratory, Madurai-19",
        "Drugs Testing Laboratory, Madurai -19",
    ],
}


def harmonize_lab(raw: str | None) -> str:
    """Collapse known reporting-lab spelling variants to one canonical form.

    Returns the input unchanged (after .strip()) if no canonical match.
    """
    if not raw:
        return ""
    s = raw.strip()
    for canonical, variants in LAB_CANONICAL.items():
        if s in variants:
            return canonical
    return s


# ---------------------------------------------------------------------------
# Inlined company-ontology logic
# ---------------------------------------------------------------------------
# This is a self-contained copy of the relevant bits of
# shared/company_ontology.py. Inlining avoids a sys.path hack in the
# loader and keeps the loader runnable as a standalone script. The
# logic MUST stay in lockstep with shared/company_ontology.py — see
# the `just sync-shared` recipe in the justfile to detect drift.

_TOKEN_NOISE = {
    "ltd", "limited", "pvt", "private", "pvt.", "pvt ltd", "private limited",
    "india", "indian", "pharmaceuticals", "pharma", "pharmaceutical",
    # Generic industry / sector descriptor suffixes. See the note in
    # shared/company_ontology.py _TOKEN_NOISE — MUST stay in lockstep.
    "remedies", "industries", "industry", "biotech", "biosciences", "bioscience",
    "healthcare", "therapeutics", "therapeutic", "enterprises", "enterprise",
    "nutrition", "nutraceuticals", "nutraceutical", "sciences", "science",
    "medical", "medicare", "wellness",
    "drug", "drugs", "formulations", "formulation", "labs", "laboratories",
    "laboratory", "mfg", "manufactured", "manufacturing", "company", "co",
    "incorporated", "inc", "corp", "corporation", "llp", "llc",
    "the", "and", "&", "of", "for", "by", "unit", "division", "div",
    "plot", "no", "no.", "survey", "khata", "khata no", "block", "sector",
    "phase", "industrial", "estate", "area", "road", "street", "lane",
    "post", "po", "distt", "district", "taluka", "taluk", "tehsil", "city",
    "state", "country", "pin", "pincode", "zip", "code", "pincode-",
    "regd", "regd.", "registered", "office", "head", "works",
    "iii", "ii", "iv", "v", "i", "vi",
    "gmbh", "ag", "sa", "plc", "pty", "kg",
    "u", "s", "m", "ms", "messrs", "u.s.", "u.k.", "uk", "us",
    "eou", "ehtp", "stp", "sez", "epip", "sidcul",
}


# Legal-form tokens that terminate the company name in _normalize: once
# one of these appears after the brand, the rest of the line is a legal
# suffix plus an address tail (e.g. "Jackson Laboratories Pvt. Ltd.
# Majitha Road" -> "jackson") and is dropped, so same-company variants
# with different address tails don't fragment into separate canonical
# groups under token_sort_ratio. MUST stay in lockstep with
# shared/company_ontology.py _LEGAL_STOP.
_LEGAL_STOP = {
    "ltd", "limited", "pvt", "private", "inc", "incorporated", "corp",
    "corporation", "llp", "llc", "company", "co", "gmbh", "ag", "sa",
    "plc", "pty", "kg",
}


# Structural address openers: tokens that, once the brand has started,
# unambiguously begin the address tail (plot/no/door/floor/road/complex/
# gidc/distt/near/...). Unlike city/state words these can't be enumerated
# by geography — but they're a small, stable vocabulary of address
# grammar, so a denylist-of-markers works. MUST stay in lockstep with
# shared/company_ontology.py _ADDRESS_START.
_ADDRESS_START = {
    # Plot / door / unit identifiers
    "plot", "no", "nos", "number", "door", "doorway", "flat", "apartment",
    "unit", "block", "shed", "shop", "khasra", "khata", "cts", "survey",
    "sy",
    # Floor / building structure
    "floor", "ground", "first", "second", "third", "fourth", "fifth",
    "basement", "loft", "building", "tower", "wing",
    # Roads / areas / complexes
    "road", "marg", "street", "lane", "nagar", "complex", "area",
    "estate", "zone",
    # Industrial-corporation estate markers (already in _TOKEN_NOISE, but
    # listed here too so they terminate the name rather than just skipping
    # and letting a following area name back in).
    "gidc", "midc", "sidcul", "epip", "ehtp", "stp", "sez", "sipcot",
    # District / village / locality
    "distt", "district", "taluka", "tehsil", "village", "mouza",
    # Directional / locator words
    "near", "opposite", "opp", "behind", "beside", "adjacent", "towards",
}

_STATE_TOKENS = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "delhi", "goa", "gujarat", "haryana", "himachal pradesh", "jammu and kashmir",
    "jammu & kashmir", "jharkhand", "karnataka", "kerala", "madhya pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha",
    "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana",
    "tripura", "uttar pradesh", "uttarakhand", "uttaranchal", "west bengal",
    "chandigarh", "puducherry", "pondicherry", "andaman and nicobar",
    "dadra and nagar haveli", "daman and diu", "lakshadweep", "ladakh",
    "the government of NCT of delhi",
}

_CITY_HINTS = {
    "mumbai", "delhi", "bengaluru", "bangalore", "hyderabad", "ahmedabad",
    "chennai", "kolkata", "pune", "jaipur", "lucknow", "kanpur", "nagpur",
    "indore", "bhopal", "vadodara", "baroda", "surat", "rajkot", "noida",
    "greater noida", "gurugram", "gurgaon", "faridabad", "ghaziabad",
    "lucknow", "kanpur", "agra", "varanasi", "prayagraj", "allahabad",
    "meerut", "saharanpur", "haridwar", "roorkee", "dehradun", "rudrapur",
    "kashipur", "baddi", "solan", "nahan", "sirmaur", "kala amb",
    "parwanoo", "kangra", "una", "mandi", "subathu", "nalagarh",
    "indore", "bhopal", "dewas", "mandideep", "pithampur",
    "nashik", "aurangabad", "tarapur", "boisar", "palghar", "raigad",
    "thane", "mahalunge", "chakan",
    "vadodara", "surat", "rajkot", "bhavnagar", "mehsana", "kadi", "sanand",
    "mohali", "chandigarh", "ludhiana", "amritsar", "jalandhar", "patiala",
    "zirakpur", "sahnewal", "dera bassi", "karnal", "ambala", "manesar",
    "sonipat", "bhiwadi", "mysore", "mysuru", "mangalore", "hubli",
    "belgaum", "tumkur", "coimbatore", "madurai", "salem", "trichy",
    "hosur", "chengalpattu", "sriperumbudur", "secunderabad", "warangal",
    "visakhapatnam", "vijayawada", "guntur", "nellore", "kochi", "cochin",
    "trivandrum", "thiruvananthapuram", "kozhikode", "calicut", "jodhpur",
    "udaipur", "kota", "bikaner", "alwar", "howrah", "siliguri",
    "bhubaneswar", "cuttack", "patna", "gaya", "guwahati", "dispur",
    "gangtok", "panaji", "margao", "jammu", "srinagar", "kathua",
}

_URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s,;\"'<>]+", re.IGNORECASE)

# Optional — only used if rapidfuzz is installed. Falling back to a
# slower token-Jaccard is fine for a 2,800-row dataset.
try:
    from rapidfuzz import fuzz as _fuzz  # type: ignore
    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    _HAS_RAPIDFUZZ = False


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize(raw: str) -> str:
    if not raw:
        return ""
    s = _strip_accents(str(raw).lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    cleaned = []
    for t in s.split():
        # A legal form (ltd/pvt/...) after the brand ends the name; the
        # rest of the line is suffix + address and must not leak into the
        # key, or same-company variants with different address tails
        # fragment into separate groups under token_sort_ratio.
        if cleaned and t in _LEGAL_STOP:
            break
        # Once the brand has started, the first address marker TERMINATES
        # the name — we break, not skip. Addresses never contain brand
        # tokens after they begin, so anything past this point (including
        # unrecognized area names like "bavia" / "thirumuruga" that no
        # city list can enumerate) must not re-enter the key. Skipping
        # individually is the old bug: it left a gap that a later
        # non-listed area word would slip through, contaminating the key
        # and binning unrelated manufacturers together. MUST stay in
        # lockstep with shared/company_ontology.py
        # normalize_company_name().
        if cleaned and (
            t in _ADDRESS_START
            or t in _CITY_HINTS
            or t in _STATE_TOKENS
            or any(c.isdigit() for c in t)
            or len(t) == 1
        ):
            break
        if t in _TOKEN_NOISE or t.isdigit():
            continue
        cleaned.append(t)
    return " ".join(cleaned).strip()


def _alias_keys(name: str) -> list[str]:
    parts = name.split()
    keys = {name}
    if len(parts) >= 2:
        keys.add(" ".join(parts[:2]))
    if len(parts) >= 3:
        keys.add(" ".join(parts[:3]))
    return [k for k in keys if k]


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _HAS_RAPIDFUZZ:
        # token_sort_ratio (not token_set_ratio): order-insensitive but
        # Levenshtein-based over the full sorted token string, so it charges
        # for extra/missing tokens instead of returning 1.0 whenever one
        # name's tokens are a subset of the other's. Stops distinct
        # companies from merging on a short-subset or shared-generic-token
        # match (e.g. "hindustan" vs "hindustan antibiotics", or two names
        # both ending in "industries"). MUST stay in lockstep with
        # shared/company_ontology.py _similarity().
        return float(_fuzz.token_sort_ratio(a, b)) / 100.0
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def _extract_city(line: str) -> str:
    if not line:
        return ""
    t = _strip_accents(str(line).lower())
    for c in sorted(_CITY_HINTS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(c) + r"\b", t):
            return c.title()
    return ""


def _extract_state(line: str) -> str:
    if not line:
        return ""
    t = _strip_accents(str(line).lower())
    for s in sorted(_STATE_TOKENS, key=len, reverse=True):
        if s in t:
            return s.title().replace("&", "and")
    return ""


def _extract_website(line: str) -> str:
    if not line:
        return ""
    m = _URL_RE.search(str(line))
    if not m:
        return ""
    url = m.group(0).rstrip(".,);]")
    if url.lower().startswith("www."):
        url = "https://" + url
    return url


def _extract_company(line: str) -> str:
    if not line:
        return ""
    return str(line).split(",", 1)[0].strip()


def _resolve_or_create(
    raw_company: str,
    raw_line: str,
    threshold: float,
    ontology_cache: dict,
    new_or_updated: dict,
) -> tuple[str, dict, bool]:
    """Inlined equivalent of company_ontology.resolve_or_create.

    The ontology is kept entirely in Redis (so the analytics app sees
    the same data it would have computed lazily):
      nsq:ontology:companies  HASH {normalized_key -> JSON record}
      nsq:ontology:meta       HASH {entry_count, last_updated, version}

    The caller is responsible for the single HGETALL on cold start
    (passing `ontology_cache` already loaded) AND for flushing
    `new_or_updated` back to Redis in the same pipeline as the records.
    This keeps round-trips to Upstash down to ~2 for the whole batch
    (HGETALL on cold start, pipeline.execute() at the end) regardless
    of how many rows we process.
    """
    raw = (raw_company or "").strip()
    norm = _normalize(raw)
    if not norm:
        return "", {
            "canonical_name": "", "city": "", "state": "",
            "website": "", "aliases": [], "sources": 0,
        }, False

    # 1. Exact normalized key
    if norm in ontology_cache:
        rec = ontology_cache[norm]
        if raw and raw not in rec.get("aliases", []):
            rec.setdefault("aliases", []).append(raw)
            rec["sources"] = int(rec.get("sources", 0)) + 1
            new_or_updated[norm] = rec
        return norm, rec, False

    # 2. Alias key (first 2/3 tokens of an existing entry). Gated by the
    # same similarity threshold as the fuzzy path (step 3): a prefix match
    # only merges when the normalized names are genuinely similar. Without
    # this gate the bin depended on insertion order — a later "Jackson
    # Pharma" (norm "jackson pharma") would merge into an existing
    # "jackson" key via the 2-token prefix at similarity ~0, binning
    # unrelated companies together. MUST stay in lockstep with
    # shared/company_ontology.py resolve_or_create.
    for key in _alias_keys(norm):
        if key in ontology_cache and _similarity(norm, key) >= threshold:
            rec = ontology_cache[key]
            if raw and raw not in rec.get("aliases", []):
                rec.setdefault("aliases", []).append(raw)
                rec["sources"] = int(rec.get("sources", 0)) + 1
                new_or_updated[key] = rec
            return key, rec, False

    # 3. Fuzzy match against all existing canonical names
    best_key, best_score = "", 0.0
    for key in ontology_cache:
        score = _similarity(norm, key)
        if score > best_score:
            best_score = score
            best_key = key
    if best_key and best_score >= threshold:
        rec = ontology_cache[best_key]
        if raw and raw not in rec.get("aliases", []):
            rec.setdefault("aliases", []).append(raw)
            rec["sources"] = int(rec.get("sources", 0)) + 1
        for fld, fn in (("city", _extract_city), ("state", _extract_state), ("website", _extract_website)):
            new_val = fn(raw_line)
            if new_val and not rec.get(fld):
                rec[fld] = new_val
        new_or_updated[best_key] = rec
        return best_key, rec, False

    # 4. New entity
    new_rec = {
        "canonical_name": raw,
        "city": _extract_city(raw_line),
        "state": _extract_state(raw_line),
        "website": _extract_website(raw_line),
        "aliases": [raw] if raw else [],
        "sources": 1,
    }
    ontology_cache[norm] = new_rec
    new_or_updated[norm] = new_rec
    return norm, new_rec, True


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
log = logging.getLogger("load_csv_redis")


def _coerce_str(v) -> str:
    if v is None:
        return ""
    return str(v)


def _row_to_cdsco(row: dict) -> dict:
    """Rename CSV columns to CDSCO keys; pass through unmapped fields as-is.

    Also harmonizes the reporting-lab field so the same lab with two
    spellings (e.g. 'CDL, Kolkata' and 'CDL Kolkata') collapses to a
    single canonical form before the row is hashed and written.
    """
    out = {}
    for k, v in row.items():
        cdsco_key = CSV_TO_CDSCO.get(k, k)
        val = _coerce_str(v).strip()
        if k == "Reporting by Lab/State":
            val = harmonize_lab(val)
        out[cdsco_key] = val
    return out


def load(
    input_path: Path,
    redis_url: str,
    flush: bool,
    augment: bool,
    dry_run: bool,
) -> None:
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print(f"No header in {input_path}", file=sys.stderr)
            sys.exit(1)
        rows = list(reader)

    print(f"Read {len(rows)} rows from {input_path}")

    prepared, prep_stats = prepare_rows(rows)
    print(
        f"Prepared {len(prepared)} records "
        f"({prep_stats['true_duplicates_removed']} true duplicates removed, "
        f"{prep_stats['same_key_collapsed']} same-key rows collapsed)."
    )
    for s in prep_stats["collapsed_samples"]:
        print(f"    collapsed {s['id']}: kept {s['kept']!r} / dropped {s['dropped']!r}")

    if dry_run:
        # Print the first 3 records' augmented form and exit.
        for r in prepared[:3]:
            cdsco = _row_to_cdsco(r)
            rid = record_id(cdsco)
            raw_company = _extract_company(cdsco.get("str_manufactured_by", ""))
            city = _extract_city(cdsco.get("str_manufactured_by", ""))
            state = _extract_state(cdsco.get("str_manufactured_by", ""))
            website = _extract_website(cdsco.get("str_manufactured_by", ""))
            print(json.dumps({
                "record_id": rid,
                "name": cdsco.get("str_product_name", "")[:60],
                "raw_company": raw_company,
                "city": city,
                "state": state,
                "website": website,
                "month": normalize_month(cdsco.get("dt_reporting_month_year")),
            }, ensure_ascii=False))
        return

    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()

    fuzzy_threshold = float(os.environ.get("NSQ_FUZZY_THRESHOLD", "0.85"))

    if flush:
        # nsq:* (records + by_month + ontology + prediction)
        ids = r.smembers("nsq:records")
        pipe = r.pipeline()
        for rid in ids:
            pipe.delete(f"nsq:record:{rid}")
            pipe.delete(f"nsq:prediction:{rid}")
        pipe.delete("nsq:records")
        for key in r.scan_iter("nsq:by_month:*"):
            pipe.delete(key)
        pipe.delete("nsq:ontology:companies")
        pipe.delete("nsq:ontology:meta")
        # The product ontology is additive/idempotent by design, but its
        # 'sources' counts inflate on every re-run over overlapping data.
        # Flushing it here (with reload-csv followed by
        # just build-product-ontology) makes the whole nsq:* state a pure
        # function of the CSV — the deterministic monthly-refresh path.
        pipe.delete("nsq:ontology:products")
        pipe.delete("nsq:ontology:products:meta")
        pipe.execute()
        print("Flushed existing nsq:* keys (records, predictions, ontology).")

    pipe = r.pipeline()
    loaded = 0
    augmented_ok = 0
    augmented_err = 0
    # One-time ontology cache + a deferred write set so we batch all
    # ontology HSETs into the single pipeline.execute() at the end.
    COMPANY_HASH_KEY = "nsq:ontology:companies"
    META_HASH_KEY = "nsq:ontology:meta"
    ontology_cache: dict = {}
    new_or_updated: dict = {}
    if augment:
        for k, v in r.hgetall(COMPANY_HASH_KEY).items():
            try:
                ontology_cache[k] = json.loads(v)
            except json.JSONDecodeError:
                continue
    for i, raw in enumerate(prepared):
        cdsco = raw
        rid = record_id(cdsco)

        # 1. Write the raw record.
        pipe.hset(
            f"nsq:record:{rid}",
            mapping={k: ("" if v is None else str(v)) for k, v in cdsco.items()},
        )
        pipe.sadd("nsq:records", rid)
        month = normalize_month(cdsco.get("dt_reporting_month_year"))
        if month:
            pipe.sadd(f"nsq:by_month:{month}", rid)

        # 2. Augment if requested.
        if augment:
            try:
                mfg_line = cdsco.get("str_manufactured_by", "")
                raw_company = _extract_company(mfg_line)
                # First-time companies create new ontology entries via
                # _resolve_or_create's write path; subsequent rows just
                # add aliases / sources.
                key, record, _created = _resolve_or_create(
                    raw_company, mfg_line, fuzzy_threshold,
                    ontology_cache, new_or_updated,
                )
                pred = {
                    "canonical":       record.get("canonical_name", ""),
                    "raw_company":     raw_company,
                    "city":            record.get("city", "") or _extract_city(mfg_line),
                    "state":           record.get("state", "") or _extract_state(mfg_line),
                    "website":         record.get("website", "") or _extract_website(mfg_line),
                    "aliases":         json.dumps(record.get("aliases", []), ensure_ascii=False),
                    "sources":         str(record.get("sources", 1)),
                    "augmented_at":    datetime.now(timezone.utc).isoformat(),
                    "source_row":      str(raw.get("Index", i + 1)),
                    "ontology_key":    key,
                }
                pipe.hset(f"nsq:prediction:{rid}", mapping=pred)
                augmented_ok += 1
            except Exception as exc:  # never let one bad row poison the load
                pipe.hset(
                    f"nsq:prediction:{rid}",
                    mapping={
                        "error":         str(exc)[:200],
                        "augmented_at":  datetime.now(timezone.utc).isoformat(),
                        "source_row":    str(raw.get("Index", i + 1)),
                    },
                )
                augmented_err += 1
                log.warning("row %d: augmentation failed: %s", i + 1, exc)

        loaded += 1

    # 3. nsq:meta — overwrite, do not flush (matches load_nsq_redis.py semantics).
    pipe.hset(
        "nsq:meta",
        mapping={
            "total_records":  str(len(rows)),
            "loaded_records": str(loaded),
            "true_duplicates_removed": str(prep_stats["true_duplicates_removed"]),
            "same_key_collapsed":      str(prep_stats["same_key_collapsed"]),
            "loaded_at":      datetime.now(timezone.utc).isoformat(),
            "source_file":    str(input_path),
            "augmented":      "1" if augment else "0",
        },
    )
    if augment:
        # Flush all deferred ontology writes + the meta in one pipeline.
        for k, rec in new_or_updated.items():
            pipe.hset(COMPANY_HASH_KEY, mapping={k: json.dumps(rec, ensure_ascii=False)})
        pipe.hset(
            META_HASH_KEY,
            mapping={
                "entry_count":  str(len(ontology_cache)),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "version":      "1",
            },
        )
    pipe.execute()

    print(
        f"Loaded {loaded} records into Redis. "
        f"Augmented: {augmented_ok} ok, {augmented_err} errors."
    )


def rebuild_ontology(r, *, dry_run: bool = False) -> dict:
    """Re-derive every nsq:ontology:companies record with the CURRENT
    _normalize, then re-stamp every nsq:prediction:<id> canonical field.

    For each existing company record, every alias is re-normalized:

      * If all aliases share ONE normalized key, the record is re-keyed to
        that key. This fixes stale keys left by older, looser normalizers
        (e.g. a record filed under "regent" when the current normalize
        yields "regent ajanta").

      * If aliases normalize to MORE than one distinct key, the record is
        SPLIT into one record per distinct key. This retroactively undoes
        contamination where unrelated manufacturers — e.g. "Regent Ajanta
        Biotech" and "Jackson Laboratories Pvt. Ltd., ... Amritsar" — had
        been binned together under a bridging key from a prior run.

      * Re-keyed records that collide (two old keys -> one new key) are
        merged (aliases unioned, city/state/website kept where non-empty).

    On a split, canonical_name/city/state/website are kept on the sub-record
    whose norm equals the OLD key (the original canonical owner) and blanked
    on the others, so a contaminated city is never copied onto an unrelated
    manufacturer. Every nsq:prediction:<id> is then re-stamped from the
    rebuilt ontology so the dashboard does not display stale canonicals.

    Returns a stats dict. With dry_run=True, Redis is read but not written.
    """
    company_hash = "nsq:ontology:companies"
    meta_hash = "nsq:ontology:meta"
    raw_ont = r.hgetall(company_hash)  # {key: json-str}, decode_responses=True

    new_ont: dict[str, dict] = {}
    stats = {
        "records_in": 0, "unchanged": 0, "rekeyed": 0,
        "split": 0, "split_groups": 0, "merged_collisions": 0,
        "records_out": 0, "predictions_seen": 0, "predictions_restamped": 0,
        "sample_splits": [],
    }

    def _add(norm: str, rec: dict) -> None:
        if norm in new_ont:
            ex = new_ont[norm]
            for a in rec.get("aliases", []):
                if a not in ex["aliases"]:
                    ex["aliases"].append(a)
            ex["sources"] = len(ex["aliases"])
            for fld in ("city", "state", "website"):
                if not ex.get(fld) and rec.get(fld):
                    ex[fld] = rec[fld]
            stats["merged_collisions"] += 1
        else:
            new_ont[norm] = {
                "canonical_name": rec.get("canonical_name", ""),
                "city": rec.get("city", ""),
                "state": rec.get("state", ""),
                "website": rec.get("website", ""),
                "aliases": list(rec.get("aliases", [])),
                "sources": int(rec.get("sources", len(rec.get("aliases", [])) or 1)),
            }

    for old_key, blob in raw_ont.items():
        stats["records_in"] += 1
        try:
            rec = json.loads(blob)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        aliases = list(rec.get("aliases") or [])
        cn = rec.get("canonical_name") or ""
        if cn and cn not in aliases:
            aliases.insert(0, cn)

        groups: dict[str, list[str]] = {}
        for a in aliases:
            n = _normalize(a)
            if not n:
                # Never drop data silently: fall back to the old key's norm.
                n = _normalize(old_key) or str(old_key)
            groups.setdefault(n, []).append(a)

        if not groups:
            stats["unchanged"] += 1
            _add(str(old_key), rec)
            continue

        if len(groups) == 1:
            nk, al = next(iter(groups.items()))
            _add(nk, {
                "canonical_name": al[0] if al else (cn or nk),
                "city": rec.get("city", ""),
                "state": rec.get("state", ""),
                "website": rec.get("website", ""),
                "aliases": al,
                "sources": len(al),
            })
            if nk == old_key:
                stats["unchanged"] += 1
            else:
                stats["rekeyed"] += 1
        else:
            stats["split"] += 1
            if len(stats["sample_splits"]) < 10:
                stats["sample_splits"].append({
                    "old_key": str(old_key),
                    "groups": {k: v for k, v in groups.items()},
                })
            for nk, al in groups.items():
                keep_geo = (nk == old_key)
                stats["split_groups"] += 1
                _add(nk, {
                    "canonical_name": al[0],
                    "city": rec.get("city", "") if keep_geo else "",
                    "state": rec.get("state", "") if keep_geo else "",
                    "website": rec.get("website", "") if keep_geo else "",
                    "aliases": al,
                    "sources": len(al),
                })

    stats["records_out"] = len(new_ont)

    # Re-stamp predictions from the rebuilt ontology so stale canonicals
    # do not surface in the dashboard.
    pipe = r.pipeline()
    restamp: dict = {}
    for key in r.scan_iter("nsq:prediction:*", count=1000):
        stats["predictions_seen"] += 1
        pred = r.hgetall(key)
        raw_company = pred.get("raw_company", "")
        norm = _normalize(raw_company)
        rec = new_ont.get(norm)
        if not rec:
            continue
        restamp[key] = {
            "canonical": rec.get("canonical_name", ""),
            "ontology_key": norm,
            "city": rec.get("city", ""),
            "state": rec.get("state", ""),
            "website": rec.get("website", ""),
            "aliases": json.dumps(rec.get("aliases", []), ensure_ascii=False),
            "sources": str(rec.get("sources", 1)),
        }
        stats["predictions_restamped"] += 1

    if dry_run:
        return stats

    pipe = r.pipeline()
    pipe.delete(company_hash)
    if new_ont:
        pipe.hset(company_hash, mapping={
            k: json.dumps(v, ensure_ascii=False) for k, v in new_ont.items()
        })
    pipe.hset(meta_hash, mapping={
        "entry_count": str(len(new_ont)),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "version": "1",
    })
    for key, mapping in restamp.items():
        pipe.hset(key, mapping=mapping)
    pipe.execute()
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Load data/data Jan25_May26.csv (or similar) into Redis.",
    )
    parser.add_argument("--input", required=False, type=Path, help="Path to the CSV file. Required unless --rebuild-ontology.")
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", ""),
        help="redis://... or rediss://... URL. Defaults to $REDIS_URL.",
    )
    parser.add_argument("--flush", action="store_true", help="Clear existing nsq:* keys before loading.")
    parser.add_argument(
        "--augment",
        default=None,
        help="Run the company-ontology augmentation (1/0/true/false). "
             "Defaults to the NSQ_AUGMENT env var (1 if unset).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read the first 3 rows, print what would be written, exit. "
             "With --rebuild-ontology, read Redis and report stats without writing.",
    )
    parser.add_argument(
        "--rebuild-ontology",
        action="store_true",
        help="Re-derive every nsq:ontology:companies record with the current "
             "normalizer: re-key stale records, split records whose aliases "
             "normalize to >1 key (undoes bin contamination), re-stamp "
             "nsq:prediction:<id> canonicals. Operates on Redis only; --input "
             "not required. Pair with --dry-run to preview.",
    )
    args = parser.parse_args()

    if args.rebuild_ontology:
        if not args.redis_url:
            print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
            sys.exit(1)
        r = redis.from_url(args.redis_url, decode_responses=True)
        stats = rebuild_ontology(r, dry_run=args.dry_run)
        mode = "DRY-RUN" if args.dry_run else "REBUILT"
        print(f"[{mode}] ontology: {stats['records_in']} in -> "
              f"{stats['records_out']} out "
              f"({stats['unchanged']} unchanged, {stats['rekeyed']} re-keyed, "
              f"{stats['split']} split into {stats['split_groups']} groups, "
              f"{stats['merged_collisions']} merged collisions).")
        print(f"[{mode}] predictions: {stats['predictions_seen']} seen, "
              f"{stats['predictions_restamped']} re-stamped.")
        if stats["sample_splits"]:
            print(f"[{mode}] sample splits (up to 10):")
            for s in stats["sample_splits"]:
                print(f"    {s['old_key']!r}  ->  {list(s['groups'].keys())}")
        return

    if not args.input:
        print("No --input given. Required for a CSV load (or use --rebuild-ontology).", file=sys.stderr)
        sys.exit(1)

    if not args.redis_url and not args.dry_run:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)

    if args.augment is None:
        env_val = os.environ.get("NSQ_AUGMENT", "1")
        augment = env_val.lower() in ("1", "true", "yes", "on")
    else:
        augment = str(args.augment).lower() in ("1", "true", "yes", "on")

    load(args.input, args.redis_url, args.flush, augment, args.dry_run)


if __name__ == "__main__":
    main()
