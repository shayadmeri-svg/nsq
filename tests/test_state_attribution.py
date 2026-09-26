"""Behavioral tests for canonical state attribution (extract_state).

extract_state answers "which Indian state did this manufacturer line come
from?" for the geographic heatmap. It layers:

  1. marketed-by truncation (the line's tail can be the MARKETER's
     address — its state must not win),
  2. strong state tokens (deterministic longest-first order; legacy
     spellings stay matchable but canonicalize on output),
  3. parenthesized/dotted abbreviations — (u.k.), (hp), H.P.-173025 —
     never the bare word 'uk' (United Kingdom, imported drugs),
  4. city -> state fallback, LATEST position in the line,
  5. weak tokens {delhi, goa} — they live inside road names and company
     names, so they only fire when nothing else matched.

Also pins the bin-key tripwire: _STATE_TOKENS and _CITY_HINTS feed
normalize_company_name's address truncation, so their membership is
FROZEN — any change here shifts Mfg_Bin_Key and invalidates the persisted
bins (see tests/test_ontology_lockstep.py).

Runnable both as `python tests/test_state_attribution.py` and via pytest.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED = REPO / "core"

# shared/ modules import each other by bare name (the services put shared/
# on sys.path), so import them the same way here.
sys.path.insert(0, str(SHARED))
import company_ontology  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rl", REPO / "redis-loader" / "load_csv_redis.py")
rl = importlib.util.module_from_spec(_spec)
sys.modules["rl"] = rl
_spec.loader.exec_module(rl)


# ---------------------------------------------------------------------------
# Layer-by-layer behavior
# ---------------------------------------------------------------------------

def test_canonicalizes_legacy_spellings():
    assert company_ontology.extract_state(
        "Uttaranchal Pharmaceuticals Pvt Ltd, Roorkee-Uttarakhand") == "Uttarakhand"
    assert company_ontology.extract_state(
        "Orissa Drugs & Chemicals Limited, Kolkata") == "Odisha"
    assert company_ontology.extract_state(
        "M/s XYZ, Pondicherry-605001") == "Puducherry"
    assert company_ontology.extract_state(
        "Alteus Remedies, Jammu & Kashmir") == "Jammu and Kashmir"
    assert company_ontology.extract_state(
        "M/s ABC, Jammu and Kashmir") == "Jammu and Kashmir"
    # never the .title() capital-And artifact of the old implementation
    assert "And Kashmir" not in company_ontology.extract_state(
        "Alteus Remedies, Jammu & Kashmir")


def test_deterministic_equal_length_tie():
    """uttaranchal/uttarakhand are equal-length; the sort tie must be
    alphabetical, not set-iteration order (the old bug made this line
    process-dependent)."""
    strong = company_ontology._STRONG_STATE_TOKENS
    i_uttarakhand = strong.index("uttarakhand")
    i_uttaranchal = strong.index("uttaranchal")
    assert i_uttarakhand < i_uttaranchal
    assert company_ontology.extract_state(
        "Uttaranchal Pharma, Roorkee, Uttarakhand") == "Uttarakhand"


def test_marketed_by_tail_does_not_win():
    # The marketer's address follows 'mfg. for' — the scan stops there.
    assert company_ontology.extract_state(
        "M/s ABC Pharma Ltd, Baddi. Mfg. for XYZ Ltd, Chandigarh") \
        == "Himachal Pradesh"
    # ...and 'mrk. by' / 'mkt. by' tails are cut too.
    assert company_ontology.extract_state(
        "M/s ABC Pharma Ltd, Baddi (H.P.) mrk. by XYZ, Chandigarh") \
        == "Himachal Pradesh"
    # A line that BEGINS with 'mfg.' must not be truncated to nothing
    # (the guard is start > 0).
    assert company_ontology.extract_state(
        "Mfg. at Solan, Himachal Pradesh") == "Himachal Pradesh"


def test_parenthesized_abbreviations():
    assert company_ontology.extract_state(
        "M/s Orchid Bio-Tech Limited, 65, Peerpura-Delhi Highway, "
        "Roorkee- 247667 (U.K.)") == "Uttarakhand"
    assert company_ontology.extract_state(
        "M/s Ponzi Pharma, Selaqui, Dehradun (UK)248197") == "Uttarakhand"
    assert company_ontology.extract_state(
        "M/s ABC Pharma, Bhiwadi (M.P.)-173025") == "Madhya Pradesh"
    assert company_ontology.extract_state(
        "XYZ Pharma, Nalagarh, H.P.-173025") == "Himachal Pradesh"
    assert company_ontology.extract_state(
        "XYZ Pharma, Nalagarh (hp)174103") == "Himachal Pradesh"
    assert company_ontology.extract_state(
        "ABC Ltd, Meerut (U.P.)-250001") == "Uttar Pradesh"


def test_bare_uk_is_never_uttarakhand():
    """33 'Manufactured By' lines are foreign (China etc.) — the bare word
    'uk' must not fire (it is the ISO code for the United Kingdom)."""
    assert company_ontology.extract_state(
        "Kukreja Pharmaceuticals, Mumbai") == "Maharashtra"  # 'uk' inside 'Kukreja'
    assert company_ontology.extract_state(
        "Reyoung (Shanghai) Medical, China.") == ""
    assert company_ontology.extract_state("Made in UK") == ""


def test_city_fallback_latest_position():
    # CDSCO addresses end with the plant city-PIN; road-name cities
    # precede it. 'Delhi' is only in the road name here.
    assert company_ontology.extract_state(
        "M/s Orchid Bio-Tech Limited, Roorkee bypass, Delhi Road, "
        "Manglour, Roorkee-247656") == "Uttarakhand"
    assert company_ontology.extract_state(
        "Alteus Remedies Pvt. Ltd., SIDCUL, Haridwar-249403") == "Uttarakhand"
    assert company_ontology.extract_state(
        "M/s Kotdwar Pharma, Kotdwar-246149") == "Uttarakhand"
    assert company_ontology.extract_state(
        "M/s HP Pharma, Baddi, Distt. Solan") == "Himachal Pradesh"
    # no city, no state -> empty (unchanged behavior)
    assert company_ontology.extract_state("Some Company Ltd, Plot 42") == ""


def test_weak_tokens_only_fire_when_nothing_else_matched():
    # 'Goa' is part of the company name; the plant is in Solan (HP).
    assert company_ontology.extract_state(
        "Goa Antibiotics & Pharmaceuticals Ltd, Solan (H.P.)-173205") \
        == "Himachal Pradesh"
    # genuine Delhi/Goa still resolve (city map / weak layer)
    assert company_ontology.extract_state(
        "Rani & Sons, 12/3 Shankar Road, New Delhi-110060") == "Delhi"
    assert company_ontology.extract_state(
        "Mapusa Industrial Estate, Goa 403528") == "Goa"


def test_canonical_state_name_bridge():
    """Display-side defense against stale persisted prod values."""
    f = company_ontology.canonical_state_name
    assert f("Uttaranchal") == "Uttarakhand"
    assert f("Orissa") == "Odisha"
    assert f("Pondicherry") == "Puducherry"
    assert f("Jammu And Kashmir") == "Jammu and Kashmir"
    assert f("Jammu & Kashmir") == "Jammu and Kashmir"
    assert f("The Government of NCT of Delhi") == "Delhi"
    # canonical + unknown values pass through
    assert f("Tamil Nadu") == "Tamil Nadu"
    assert f("Dadra and Nagar Haveli and Daman and Diu") == \
        "Dadra and Nagar Haveli and Daman and Diu"
    assert f("Somewhere") == "Somewhere"
    assert f("") == ""


def test_output_names_match_geojson_features():
    """The choropleth join key: every value extract_state can emit (the
    _STATE_CANONICAL image) except '' must be a NAME_1 feature of the
    committed LGD geojson."""
    geo_path = REPO / "analytics" / "india_states_slim.geojson"
    try:
        import json
        fc = json.loads(geo_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AssertionError(f"{geo_path} missing — run build_states_geojson.py")
    feature_names = {f["properties"]["NAME_1"] for f in fc["features"]}
    emitted = set(company_ontology._STATE_CANONICAL.values()) \
        | set(company_ontology._CITY_STATE)
    unjoinable = emitted - feature_names
    assert not unjoinable, (
        f"extract_state can emit values with no geojson feature: "
        f"{sorted(unjoinable)}")


def test_loader_extract_state_lockstep():
    """The loader's inlined _extract_state writes the persisted state —
    it must agree with the shared copy on every corpus line."""
    for line, expected in [
        ("Uttaranchal Pharmaceuticals Pvt Ltd, Roorkee-Uttarakhand", "Uttarakhand"),
        ("Alteus Remedies Pvt. Ltd., SIDCUL, Haridwar-249403", "Uttarakhand"),
        ("M/s ABC Pharma, Bhiwadi (M.P.)-173025", "Madhya Pradesh"),
        ("Kukreja Pharmaceuticals, Mumbai", "Maharashtra"),
        ("Reyoung (Shanghai) ... China.", ""),
    ]:
        assert rl._extract_state(line) == expected, f"loader drift on {line!r}"
        assert company_ontology.extract_state(line) == expected


# ---------------------------------------------------------------------------
# Bin-key tripwire — membership of these sets is FROZEN
# ---------------------------------------------------------------------------

FROZEN_STATE_TOKENS = {
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

FROZEN_CITY_HINTS = {
    "mumbai", "delhi", "bengaluru", "bangalore", "hyderabad", "ahmedabad",
    "chennai", "kolkata", "pune", "jaipur", "lucknow", "kanpur", "nagpur",
    "indore", "bhopal", "vadodara", "baroda", "surat", "rajkot", "noida",
    "greater noida", "gurugram", "gurgaon", "faridabad", "ghaziabad",
    "agra", "varanasi", "prayagraj", "allahabad", "meerut", "saharanpur",
    "haridwar", "roorkee", "dehradun", "rudrapur", "kashipur", "baddi",
    "solan", "nahan", "sirmaur", "kala amb", "parwanoo", "kangra", "una",
    "mandi", "subathu", "nalagarh", "dewas", "mandideep", "pithampur",
    "nashik", "aurangabad", "tarapur", "boisar", "palghar", "raigad",
    "thane", "mahalunge", "chakan", "bhavnagar", "mehsana", "kadi",
    "sanand", "mohali", "chandigarh", "ludhiana", "amritsar", "jalandhar",
    "patiala", "zirakpur", "sahnewal", "dera bassi", "karnal", "ambala",
    "manesar", "sonipat", "bhiwadi", "mysore", "mysuru", "mangalore",
    "hubli", "belgaum", "tumkur", "coimbatore", "madurai", "salem",
    "trichy", "hosur", "chengalpattu", "sriperumbudur", "secunderabad",
    "warangal", "visakhapatnam", "vijayawada", "guntur", "nellore",
    "kochi", "cochin", "trivandrum", "thiruvananthapuram", "kozhikode",
    "calicut", "jodhpur", "udaipur", "kota", "bikaner", "alwar", "howrah",
    "siliguri", "bhubaneswar", "cuttack", "patna", "gaya", "guwahati",
    "dispur", "gangtok", "panaji", "margao", "jammu", "srinagar", "kathua",
}


def test_state_token_and_city_hint_membership_is_frozen():
    """_STATE_TOKENS and _CITY_HINTS also feed normalize_company_name's
    address truncation — any membership change shifts Mfg_Bin_Key and
    invalidates every persisted bin. If this fires, the change must go in
    a NEW layer inside extract_state (like _CITY_STATE), never here.
    Also asserts the loader's inlined copies carry the same frozen sets.
    """
    for mod in (company_ontology, rl):
        st, ch = getattr(mod, "_STATE_TOKENS"), getattr(mod, "_CITY_HINTS")
        assert st == FROZEN_STATE_TOKENS, (
            f"{mod.__name__}._STATE_TOKENS changed: "
            f"added={sorted(set(st) - FROZEN_STATE_TOKENS)} "
            f"removed={sorted(FROZEN_STATE_TOKENS - set(st))}")
        assert ch == FROZEN_CITY_HINTS, (
            f"{mod.__name__}._CITY_HINTS changed: "
            f"added={sorted(set(ch) - FROZEN_CITY_HINTS)} "
            f"removed={sorted(FROZEN_CITY_HINTS - set(ch))}")


def test_city_state_map_never_feeds_normalize():
    """_CITY_STATE is an extract_state-only layer; if it ever leaks into
    normalize_company_name's truncation check, every _CITY_STATE city
    (kotdwar, paonta sahib, ...) starts truncating bin keys — drift."""
    import inspect
    src = inspect.getsource(company_ontology.normalize_company_name)
    assert "_CITY_STATE" not in src, (
        "normalize_company_name now consults _CITY_STATE — bin-key drift")
    # and the same for the loader's inlined _normalize
    src = inspect.getsource(rl._normalize)
    assert "_CITY_STATE" not in src, (
        "loader _normalize now consults _CITY_STATE — bin-key drift")


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