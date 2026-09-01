"""Company-name ontology backed by Redis.

The analytics app extracts company information from each row's
'Manufactured By' free-text. We want to:

  1.  Produce a *canonical* company name per row (e.g. "Cipla Ltd." and
      "Cipla Limited" should resolve to the same entity).
  2.  Persist that canonical name + city/state/website across container
      restarts so the ontology grows over time, not just within one
      Streamlit session.
  3.  Never duplicate an entity that already exists — if a new raw name
      fuzzy-matches an existing canonical entry above a threshold, reuse
      the existing one and just record the raw name as an alias.

Redis layout (all under the `nsq:` family so `just clean` flushes them
alongside the record data — this is intentional; the ontology can be
rebuilt by re-running the analytics app over a fresh dataset):

  nsq:ontology:companies  -> HASH  {normalized_key -> JSON company record}
  nsq:ontology:meta       -> HASH  {entry_count, last_updated, version}

A "company record" is a JSON blob with this shape:

  {
    "canonical_name": "Cipla Limited",
    "city":           "Mumbai",
    "state":          "Maharashtra",
    "website":        "https://www.cipla.com",
    "aliases":        ["Cipla Ltd", "CIPLA LIMITED", "Cipla Limited, Mumbai"],
    "sources":        17
  }

Fuzzy matching: tries `rapidfuzz` first (faster, more accurate), falls
back to a token-set Jaccard similarity if rapidfuzz isn't installed.
Threshold is tunable via FUZZY_THRESHOLD (default 0.85).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

import redis

# Lazy import — rapidfuzz is in analytics/requirements.txt but this
# module is in shared/ and could be loaded from anywhere. Fall back
# gracefully if it isn't installed.
try:
    from rapidfuzz import fuzz  # type: ignore
    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    _HAS_RAPIDFUZZ = False


FUZZY_THRESHOLD = float(os.environ.get("NSQ_FUZZY_THRESHOLD", "0.85"))
COMPANY_HASH_KEY = "nsq:ontology:companies"
META_HASH_KEY = "nsq:ontology:meta"
PRODUCT_HASH_KEY = "nsq:ontology:products"
PRODUCT_META_HASH_KEY = "nsq:ontology:products:meta"
ONTOLOGY_VERSION = 1

# Token blacklist that frequently appears in 'Manufactured By' lines but
# is never part of the company name itself.
_TOKEN_NOISE = {
    "ltd", "limited", "pvt", "private", "pvt.", "pvt ltd", "private limited",
    "india", "indian", "pharmaceuticals", "pharma", "pharmaceutical",
    # Generic industry / sector descriptor tokens that appear as suffixes on
    # many unrelated manufacturers. Dropping them both prevents a single
    # generic token (e.g. "healthcare", "biotech", "industries") from
    # magnetizing unrelated companies via the fuzzy match, and lets genuine
    # same-brand variants ("Unicure Remedies" / "Unicure") collapse to an
    # exact normalized-key match instead of relying on fuzzy similarity.
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


# Legal-form tokens that terminate the company name in normalize: once one
# of these appears after the brand, the rest of the line is a legal suffix
# plus an address tail (e.g. "Jackson Laboratories Pvt. Ltd. Majitha
# Road" -> "jackson") and is dropped, so same-company variants with
# different address tails don't fragment into separate canonical groups
# under token_sort_ratio.
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
# redis-loader/load_csv_redis.py _ADDRESS_START.
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


def get_redis_client(url: str | None = None) -> redis.Redis:
    url = url or os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError(
            "REDIS_URL is not set. The company-ontology helpers need a "
            "Redis connection (see .env.example)."
        )
    return redis.from_url(url, decode_responses=True)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_company_name(raw: str) -> str:
    """Return a stable, comparable form of a company name.

    Steps: lowercase, strip accents, drop punctuation, drop the legal-
    suffix / location noise tokens, collapse whitespace, strip leading
    numbers (e.g. plot numbers that the parser didn't catch).
    """
    if not raw:
        return ""
    s = _strip_accents(str(raw).lower())
    # Replace any non-alphanumeric run with a single space.
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
        # and binning unrelated manufacturers together.
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
    """Additional lookup keys beyond the strict normalize() output.

    We also index the first two tokens, since many company records differ
    only by trailing legal-suffix noise.
    """
    parts = name.split()
    keys = {name}
    if len(parts) >= 2:
        keys.add(" ".join(parts[:2]))
    if len(parts) >= 3:
        keys.add(" ".join(parts[:3]))
    return [k for k in keys if k]


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------
def _similarity(a: str, b: str) -> float:
    """Return a similarity score in [0.0, 1.0]."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _HAS_RAPIDFUZZ:
        # token_sort_ratio is order-insensitive but, unlike token_set_ratio,
        # it is Levenshtein-based over the full sorted token string — so it
        # charges for extra/missing tokens instead of returning 1.0 whenever
        # one name's token set is a subset of the other's. That stops
        # distinct companies from collapsing together just because one name
        # is a short subset (e.g. "hindustan" vs "hindustan antibiotics") or
        # because they share a single generic industry token (e.g. both end
        # in "industries" / "healthcare").
        return float(fuzz.token_sort_ratio(a, b)) / 100.0
    # Fallback: Jaccard over token sets.
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


# ---------------------------------------------------------------------------
# Field extractors (city / state / website) from a free-text line
# ---------------------------------------------------------------------------
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


def extract_city(line: str) -> str:
    """Best-effort city extraction from a 'Manufactured By' line.

    Returns "" if no recognizable city token is present. The lookup is
    a simple substring scan; we pick the first city that appears in
    a recognized-city set.
    """
    if not line:
        return ""
    t = _strip_accents(str(line).lower())
    # Direct hit on a known city.
    for c in sorted(_CITY_HINTS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(c) + r"\b", t):
            return c.title()
    return ""


def extract_state(line: str) -> str:
    """Best-effort state extraction from a 'Manufactured By' line."""
    if not line:
        return ""
    t = _strip_accents(str(line).lower())
    for s in sorted(_STATE_TOKENS, key=len, reverse=True):
        if s in t:
            return s.title().replace("&", "and")
    return ""


def extract_website(line: str) -> str:
    """Extract the first http(s)/www URL from a 'Manufactured By' line."""
    if not line:
        return ""
    m = _URL_RE.search(str(line))
    if not m:
        return ""
    url = m.group(0).rstrip(".,);]")
    if url.lower().startswith("www."):
        url = "https://" + url
    return url


def extract_company_name(line: str) -> str:
    """Pull the leading company name out of a 'Manufactured By' line.

    The CDSCO convention is "<Company name>, <address…>" — the company
    name is the comma-separated segment up to the first comma (or the
    whole line if no comma is present).
    """
    if not line:
        return ""
    first = str(line).split(",", 1)[0].strip()
    return first


# ---------------------------------------------------------------------------
# Product-ontology normalization
# ---------------------------------------------------------------------------
# The CDSCO `Name of Product` column has many near-duplicate spellings
# for the same real product (e.g. `Telmisartan Tablets IP 40 mg` and
# `Telmisartan Tablets IP 40mg`). The product ontology canonicalizes
# these into stable keys + human-readable display names, parallel to
# the company ontology.
#
# Key shape (alphabetized active-ingredient tokens):
#   "Telmisartan Tablets IP 40 mg"        -> "telmisartan"
#   "Telmisartan & Amlodipine Tablets IP" -> "amlodipine telmisartan"
#   "Compound Sodium Lactate Injection"   -> "compound sodium lactate"
#
# Display name: a lightly-formatted version of the most-common alias
# (built from normalize_product() in analytics/app.py — this module
# only provides the key).
#
# Brand parentheticals like `(Telma 40)` are dropped from the key but
# kept in the `aliases` list. They are NOT findable via the canonical
# column — that's by design; users can search the raw Name of Product.

# Tokens that describe dosage form (dropped from the key)
_PRODUCT_FORM_TOKENS = {
    "tablets", "tablet", "tab", "tabs", "capsule", "caps", "caplet",
    "caplets", "cap", "injection", "inj", "syrup", "suspension", "susp",
    "ointment", "cream", "gel", "drops", "solution", "powder", "granules",
    "sachet", "bolus", "paint", "lotion", "spray", "patch", "lvp",
    "linctus", "mixture", "tonic", "emulsion", "elixir", "infusion",
    "irrigation", "dialysis", "aerosol", "nebuliser", "nebulizer",
    "suppository", "enema", "pellet", "implant", "gargle",
    "veterinary", "vet",
}

# Tokens that describe dose / strength / monograph (dropped from the key)
_PRODUCT_DOSE_MONO = {
    "mg", "ml", "mcg", "iu", "gm", "g", "meq", "mmol", "ng", "ug",
    "w", "v", "w/v", "w/w", "v/v",
    "ip", "bp", "usp", "nf", "nfi",
    "u", "i", "ii", "iii", "iv", "v",
    # Single-letter monograph fragments: when "I.P" splits into ["i", "p"],
    # "p" alone has no pharmaceutical meaning.
    "p", "b", "n", "f",
}

# Tokens used to combine multiple active ingredients
_PRODUCT_COMBO_TOKENS = {"&", "+", "and", "with", "combipack", "plus"}

# Explicit overrides for products that the normalizer can't disambiguate
# (e.g. Ringer's Lactate vs Compound Sodium Lactate). Each entry maps a
# raw alias -> the canonical key it should resolve to. Empty dict by
# default; populate as needed.
PRODUCT_CANONICAL_OVERRIDES: dict[str, str] = {}


def product_key(raw: str) -> str:
    """Return a stable, comparable key for a product name.

    Steps:
      1. Strip accents, lowercase.
      2. Drop parenthetical brand suffixes.
      3. Split digit-letter and letter-digit boundaries (40mg -> 40 mg).
      4. Replace non-alphanumeric runs with a single space.
      5. Drop form / dose / monograph / combo tokens.
      6. Drop pure-digit tokens (strengths like `40`, `12.5`).
      7. Drop monographs even with periods: `i.p` -> `i`, then dropped.
      8. Sort the remaining tokens alphabetically so word-order
         differences don't fragment the key.
      9. Apply any explicit PRODUCT_CANONICAL_OVERRIDES.
    """
    if not raw:
        return ""
    s = _strip_accents(str(raw).lower())
    # Drop parenthetical brand names: "(Telma 40)", "(CALXIA 500 )"
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    # Replace & and + with spaces before the alphanumeric filter, so
    # "A & B" and "A and B" both become "A B" rather than "a & b"
    s = re.sub(r"[&+]", " ", s)
    # Split digit-letter boundaries: "40mg" -> "40 mg", "5fu" -> "5 fu"
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s, flags=re.IGNORECASE)
    s = re.sub(r"([a-z])(\d)", r"\1 \2", s, flags=re.IGNORECASE)
    # Now strip the remaining non-alphanumeric (no periods this time
    # so "i.p" splits into "i" and "p" — both monographs).
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = []
    for tok in s.split():
        if tok in _PRODUCT_FORM_TOKENS:
            continue
        if tok in _PRODUCT_DOSE_MONO:
            continue
        if tok in _PRODUCT_COMBO_TOKENS:
            continue
        # Drop pure numbers (strengths) and pure decimals (12.5, 0.5)
        if re.fullmatch(r"\d+(\.\d+)?", tok):
            continue
        tokens.append(tok)
    key = " ".join(sorted(tokens)).strip()
    if key in PRODUCT_CANONICAL_OVERRIDES:
        return PRODUCT_CANONICAL_OVERRIDES[key]
    return key


def load_product_ontology(client: redis.Redis | None = None) -> dict[str, dict[str, Any]]:
    """Read every product record out of Redis. Returns
    {canonical_key: record_dict}."""
    r = client or get_redis_client()
    raw = r.hgetall(PRODUCT_HASH_KEY)
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            continue
    return out


def _save_product(
    r: redis.Redis,
    ontology: dict[str, dict[str, Any]],
    key: str,
    record: dict[str, Any],
) -> None:
    ontology[key] = record
    r.hset(PRODUCT_HASH_KEY, mapping={key: json.dumps(record, ensure_ascii=False)})


def _write_product_meta(r: redis.Redis, count: int) -> None:
    r.hset(
        PRODUCT_META_HASH_KEY,
        mapping={
            "entry_count":  str(count),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "version":      str(ONTOLOGY_VERSION),
        },
    )


def _best_product_match(
    key: str,
    ontology: dict[str, dict[str, Any]],
) -> tuple[str, float]:
    """Return (best_key, best_score) for fuzzy match against the
    product ontology. Also scores each entry's aliases so a near-
    duplicate already-canonized under a slightly different key still
    hits."""
    best_key, best_score = "", 0.0
    for entry_key, rec in ontology.items():
        score = _similarity(key, entry_key)
        if score > best_score:
            best_score = score
            best_key = entry_key
        # Also try matching against the first 1-2 aliases (most common
        # raw names for that product). Keeps it cheap.
        for alias in (rec.get("aliases") or [])[:2]:
            akey = product_key(alias)
            if not akey:
                continue
            ascore = _similarity(key, akey)
            if ascore > best_score:
                best_score = ascore
                best_key = entry_key
    return best_key, best_score


def resolve_or_create_product(
    raw: str,
    client: redis.Redis | None = None,
    threshold: float | None = None,
    *,
    ontology_cache: dict[str, dict[str, Any]] | None = None,
    flush: bool = True,
) -> tuple[str, dict[str, Any], bool]:
    """Return (canonical_key, record, was_created).

    If the product's `product_key()` matches an existing ontology entry
    (above the fuzzy threshold), the existing record is reused and the
    raw name is appended to its `aliases`. Otherwise a new record is
    created. Mirrors `resolve_or_create` for companies.

    `ontology_cache` (optional): an in-memory dict of the product
    ontology. If supplied, the function uses it instead of issuing an
    `HGETALL` against Redis, and only writes back to Redis when
    `flush=True`. This is the recommended path for batch callers (e.g.
    a per-row `.apply()` over the dataset) — one HGETALL on entry,
    in-memory matches, then a single pipeline `HSET` at the end.
    """
    r = client or get_redis_client()
    if ontology_cache is None:
        ontology = load_product_ontology(r)
    else:
        ontology = ontology_cache
    thr = threshold if threshold is not None else FUZZY_THRESHOLD

    raw_clean = (raw or "").strip()
    key = product_key(raw_clean)
    if not key:
        return "", {
            "canonical_name": "",
            "canonical_key":  "",
            "aliases":        [],
            "sources":        0,
        }, False

    # 1. Direct hit on the key.
    if key in ontology:
        rec = ontology[key]
        if raw_clean and raw_clean not in rec.get("aliases", []):
            rec.setdefault("aliases", []).append(raw_clean)
            rec["sources"] = int(rec.get("sources", 0)) + 1
            if flush:
                _save_product(r, ontology, key, rec)
                _write_product_meta(r, len(ontology))
        return key, rec, False

    # 2. Fuzzy match against existing entries.
    best_key, best_score = _best_product_match(key, ontology)
    if best_key and best_score >= thr:
        rec = ontology[best_key]
        if raw_clean and raw_clean not in rec.get("aliases", []):
            rec.setdefault("aliases", []).append(raw_clean)
            rec["sources"] = int(rec.get("sources", 0)) + 1
            if flush:
                _save_product(r, ontology, best_key, rec)
                _write_product_meta(r, len(ontology))
        return best_key, rec, False

    # 3. New entity. canonical_name starts as the most-common-looking
    # raw form; the analytics app applies its own cosmetic
    # normalize_product() on display.
    new_rec = {
        "canonical_name": raw_clean,
        "canonical_key":  key,
        "aliases":        [raw_clean] if raw_clean else [],
        "sources":        1,
        "first_seen":     datetime.now(timezone.utc).isoformat(),
    }
    if flush:
        _save_product(r, ontology, key, new_rec)
        _write_product_meta(r, len(ontology))
    else:
        ontology[key] = new_rec
    return key, new_rec, True


# ---------------------------------------------------------------------------
# Ontology CRUD
# ---------------------------------------------------------------------------
def load_ontology(client: redis.Redis | None = None) -> dict[str, dict[str, Any]]:
    """Read every company record out of Redis. Returns
    {normalized_key: record_dict}."""
    r = client or get_redis_client()
    raw = r.hgetall(COMPANY_HASH_KEY)
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            # Corrupt entry — skip rather than crash the whole load.
            continue
    return out


def _save_record(
    r: redis.Redis,
    ontology: dict[str, dict[str, Any]],
    key: str,
    record: dict[str, Any],
) -> None:
    ontology[key] = record
    # Use the mapping= form of hset — works across redis-py versions.
    r.hset(COMPANY_HASH_KEY, mapping={key: json.dumps(record, ensure_ascii=False)})


def _write_meta(r: redis.Redis, count: int) -> None:
    from datetime import datetime, timezone
    r.hset(
        META_HASH_KEY,
        mapping={
            "entry_count": str(count),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "version": str(ONTOLOGY_VERSION),
        },
    )


def resolve_or_create(
    raw_company: str,
    raw_line: str,
    client: redis.Redis | None = None,
    threshold: float | None = None,
) -> tuple[str, dict[str, Any], bool]:
    """Return (normalized_key, record, was_created).

    If the raw company name matches an existing ontology entry (above
    the fuzzy threshold), the existing record is reused and the raw
    name is appended to its `aliases`. Otherwise a new record is
    created from the city/state/website extracted from `raw_line` and
    persisted to Redis.
    """
    r = client or get_redis_client()
    ontology = load_ontology(r)
    thr = threshold if threshold is not None else FUZZY_THRESHOLD

    raw = (raw_company or "").strip()
    norm = normalize_company_name(raw)
    if not norm:
        return "", {
            "canonical_name": "",
            "city": "",
            "state": "",
            "website": "",
            "aliases": [],
            "sources": 0,
        }, False

    # Direct hit on normalized key.
    if norm in ontology:
        rec = ontology[norm]
        if raw and raw not in rec.get("aliases", []):
            rec.setdefault("aliases", []).append(raw)
            rec["sources"] = int(rec.get("sources", 0)) + 1
            _save_record(r, ontology, norm, rec)
            _write_meta(r, len(ontology))
        return norm, rec, False

    # Alias-key hit (first 2/3 tokens of an existing record). Gated by the
    # SAME similarity threshold as the fuzzy path below: a prefix match
    # only merges when the normalized names are genuinely similar. Without
    # this gate the bin depended on insertion order — a later "Jackson
    # Pharma" (norm "jackson pharma") would merge into an existing
    # "jackson" key via the 2-token prefix at similarity ~0, binning
    # unrelated companies together. The gate makes every merge route
    # require >= thr similarity, so the bin is a function of name
    # similarity, not which row arrived first.
    for key in _alias_keys(norm):
        if key in ontology and _similarity(norm, key) >= thr:
            rec = ontology[key]
            if raw and raw not in rec.get("aliases", []):
                rec.setdefault("aliases", []).append(raw)
                rec["sources"] = int(rec.get("sources", 0)) + 1
                _save_record(r, ontology, key, rec)
                _write_meta(r, len(ontology))
            return key, rec, False

    # Fuzzy match against all existing canonical names.
    best_key = ""
    best_score = 0.0
    for key, rec in ontology.items():
        score = _similarity(norm, key)
        if score > best_score:
            best_score = score
            best_key = key
    if best_key and best_score >= thr:
        rec = ontology[best_key]
        if raw and raw not in rec.get("aliases", []):
            rec.setdefault("aliases", []).append(raw)
            rec["sources"] = int(rec.get("sources", 0)) + 1
        # Backfill city/state/website if we now have a real value and
        # the existing record didn't.
        for fld in ("city", "state", "website"):
            new_val = {
                "city": extract_city(raw_line),
                "state": extract_state(raw_line),
                "website": extract_website(raw_line),
            }[fld]
            if new_val and not rec.get(fld):
                rec[fld] = new_val
        _save_record(r, ontology, best_key, rec)
        _write_meta(r, len(ontology))
        return best_key, rec, False

    # New entity.
    new_rec = {
        "canonical_name": raw,
        "city": extract_city(raw_line),
        "state": extract_state(raw_line),
        "website": extract_website(raw_line),
        "aliases": [raw] if raw else [],
        "sources": 1,
    }
    _save_record(r, ontology, norm, new_rec)
    _write_meta(r, len(ontology))
    return norm, new_rec, True
