"""Load the Jan25_May26.csv (or any similarly-shaped CSV) into Redis.

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
# same (batch_no, product_name) pair produces the same record_id whether
# the data came from JSON or CSV.
# ---------------------------------------------------------------------------
def record_id(row: dict) -> str:
    key = f"{row.get('str_batch_no', '')}|{row.get('str_product_name', '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


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
# (otherwise the original string is lost). The chosen canonicals are
# the most common spelling for each lab.
LAB_CANONICAL = {
    "CDL, Kolkata": [
        "CDL, Kolkata",
        "CDL Kolkata",
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
    "u", "s", "u.s.", "u.k.", "uk", "us",
    "eou", "ehtp", "stp", "sez", "epip", "sidcul",
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
    tokens = [t for t in s.split() if t not in _TOKEN_NOISE and not t.isdigit()]
    return " ".join(tokens).strip()


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
        return float(_fuzz.token_set_ratio(a, b)) / 100.0
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

    # 2. Alias key (first 2/3 tokens of an existing entry)
    for key in _alias_keys(norm):
        if key in ontology_cache:
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

    if dry_run:
        # Print the first 3 records' augmented form and exit.
        for r in rows[:3]:
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
    for i, raw in enumerate(rows):
        cdsco = _row_to_cdsco(raw)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Load data/data Jan25_May26.csv (or similar) into Redis.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to the CSV file.")
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
        help="Read the first 3 rows, print what would be written, exit.",
    )
    args = parser.parse_args()

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
