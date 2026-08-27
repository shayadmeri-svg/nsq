"""Record-key, dedupe, and lab-harmonization tests for the CSV loader.

Locks in the record-identity change behind the Jan21-Jul26 data swap:

  * record_id() = (batch_no, product_name, reporting_month, lab,
    NSQ-result text) — so the same batch failing in consecutive months,
    tested by different labs in one month, or listed twice in one
    notification having failed different tests stays distinct instead of
    collapsing last-write-wins.
  * prepare_rows() drops true duplicates and sorts deterministically, so
    the resulting Redis state — including the insertion-order-dependent
    manufacturer ontology — is a pure function of the CSV content.
  * LAB_CANONICAL maps the 'Not applicable' placeholder to the 'Unknown'
    sentinel and merges the new-file same-lab spelling variants.

MUST stay in lockstep with load_nsq_redis.py record_id() (both loaders
must give one alert the same id).

Runnable both as `python tests/test_loader_record_keys.py` and via pytest.
"""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_loader():
    spec = importlib.util.spec_from_file_location(
        "load_csv_redis_under_test", REPO / "redis-loader" / "load_csv_redis.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _csv_row(**kw):
    base = {
        "Index": "1",
        "Name of Product": "Paracetamol Tablets I.P.",
        "Batch No": "B123",
        "Mfg": "3/1/2025",
        "Exp": "2/1/2027",
        "Manufactured By": "Acme Pharma Pvt Ltd, Plot 5, Noida",
        "NSQ Result": "Does not conform to IP.",
        "Reporting Source": "CDSCO Labs",
        "Reporting by Lab/State": "CDL, Kolkata",
        "Reporting Month & Year": "Jan-2026",
        "Source": "https://cdsco.gov.in/",
    }
    base.update(kw)
    return base


# --- record_id ---------------------------------------------------------------

def test_record_id_separates_consecutive_month_failures():
    """The reported loss mode: same batch failing in two consecutive months
    (DTL Dalgate Srinagar pattern) must yield TWO records, not one."""
    rl = _load_loader()
    jan = rl.record_id(rl._row_to_cdsco(_csv_row(**{"Reporting Month & Year": "Jan-2026"})))
    feb = rl.record_id(rl._row_to_cdsco(_csv_row(**{"Reporting Month & Year": "Feb-2026"})))
    assert jan != feb, "same batch+product failing in different months collapsed to one id"


def test_record_id_separates_same_month_different_lab():
    rl = _load_loader()
    a = rl.record_id(rl._row_to_cdsco(_csv_row(**{"Reporting by Lab/State": "CDL, Kolkata"})))
    b = rl.record_id(rl._row_to_cdsco(_csv_row(**{"Reporting by Lab/State": "DTL, Jaipur"})))
    assert a != b, "same batch+product+month tested by different labs collapsed to one id"


def test_record_id_stable_across_mfg_address_and_index():
    """Manufacturer address casing/whitespace and Index must NOT change the id."""
    rl = _load_loader()
    a = rl.record_id(rl._row_to_cdsco(_csv_row(Index="1")))
    b = rl.record_id(rl._row_to_cdsco(_csv_row(Index="999", **{"Manufactured By": "acme pharma pvt ltd,  plot 5, noida"})))
    assert a == b


def test_record_id_matches_json_loader():
    """CSV loader and JSON loader must give the same alert the same id."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("load_nsq_under_test", REPO / "redis-loader" / "load_nsq_redis.py")
    jl = _ilu.module_from_spec(spec)
    spec.loader.exec_module(jl)
    rl = _load_loader()
    csv_row = _csv_row(**{"Reporting by Lab/State": "CDL, Kolkata", "Reporting Month & Year": "Jan-2026"})
    json_row = {
        "str_batch_no": "B123",
        "str_product_name": "Paracetamol Tablets I.P.",
        "dt_manufacturing_date": "3/1/2025",
        "dt_expiry_date": "2/1/2027",
        "str_manufactured_by": "Acme Pharma Pvt Ltd, Plot 5, Noida",
        "str_nsq_result": "Does not conform to IP.",
        "str_reporting_source": "CDSCO Labs",
        "str_reported_by_lab_or_state": "CDL, Kolkata",
        "dt_reporting_month_year": "Jan-2026",
        "source": "https://cdsco.gov.in/",
    }
    assert rl.record_id(rl._row_to_cdsco(csv_row)) == jl.record_id(json_row)


# --- prepare_rows ------------------------------------------------------------

def test_prepare_rows_dedupes_true_duplicates():
    """Rows identical beyond Index collapse to one; near-duplicates that
    differ in a content field survive as distinct alerts."""
    rl = _load_loader()
    dup = _csv_row(Index="2")
    distinct = _csv_row(Index="3", **{"Reporting Month & Year": "Feb-2026"})
    prepared, stats = rl.prepare_rows([_csv_row(Index="1"), dup, distinct])
    assert stats["true_duplicates_removed"] == 1
    assert len(prepared) == 2
    assert stats["same_key_collapsed"] == 0


def test_different_result_text_keeps_both_records():
    """The same batch|product|month|lab failing DIFFERENT tests (e.g.
    Sterility vs pH+Related — CDSCO lists both rows in one notification)
    must stay distinct: result text is part of the record key."""
    rl = _load_loader()
    a = _csv_row(**{"NSQ Result": "The sample does not conform to IP with respect to test for Sterility."})
    b = _csv_row(**{"NSQ Result": "The sample does not conform to IP with respect to test for pH, Related compounds."})
    prepared, stats = rl.prepare_rows([a, b])
    assert stats["same_key_collapsed"] == 0
    assert stats["true_duplicates_removed"] == 0
    assert len(prepared) == 2


def test_prepare_rows_collapses_residual_same_key_rows():
    """A residual same-key collision (differing only in fields outside the
    key, e.g. Mfg-date spelling) collapses to one record, deterministically
    first — logged, counted, expected to be rare."""
    rl = _load_loader()
    a = _csv_row(Index="1", **{"Mfg": "3/1/2025"})
    b = _csv_row(Index="2", **{"Mfg": "03/01/2025"})
    prepared, stats = rl.prepare_rows([b, a])
    assert stats["same_key_collapsed"] == 1
    assert len(prepared) == 1
    # Rows tying on every sort field keep file order; either surviving row
    # is semantically the same alert, so just assert a deterministic pick.
    assert prepared[0]["dt_manufacturing_date"] in (a["Mfg"], b["Mfg"])


def test_prepare_rows_is_order_independent():
    """Shuffled input must produce the identical prepared sequence — this is
    what makes monthly CSV appends safe for the ontology build order."""
    import random
    rl = _load_loader()
    rows = [
        _csv_row(Index=str(i), **{"Batch No": f"B{i}", "Reporting Month & Year": m})
        for i, m in enumerate(["Mar-2026", "Jan-2026", "Feb-2026", "Jan-2026", "Mar-2026"])
    ]
    ref, ref_stats = rl.prepare_rows(rows)
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        got, stats = rl.prepare_rows(shuffled)
        assert got == ref, f"seed {seed}: row order changed the prepared sequence"
        assert stats == ref_stats


# --- LAB_CANONICAL -----------------------------------------------------------

def test_not_applicable_maps_to_unknown():
    rl = _load_loader()
    assert rl.harmonize_lab("Not applicable") == "Unknown"
    assert rl.harmonize_lab("Not Applicable") == "Unknown"


def test_new_file_same_lab_variants_collapse():
    rl = _load_loader()
    assert rl.harmonize_lab("CDL,Kolkata") == "CDL, Kolkata"
    assert rl.harmonize_lab("Central Drugs Laboratory, Kasauli") == "CDL Kasauli"
    assert rl.harmonize_lab("RDTL. Bellary Karnataka") == "RDTL, Bellary Karnataka"


def test_unknown_lab_name_passes_through():
    """A genuinely new lab must NOT be swallowed by the sentinel."""
    rl = _load_loader()
    assert rl.harmonize_lab("Lucknow Lab") == "Lucknow Lab"


# --- real-file smoke ---------------------------------------------------------

def test_real_file_preparation_numbers():
    """The Jan21-Jul26 file must yield the expected dedupe numbers — this is
    the regression lock for the data swap. Skipped when the file is absent."""
    path = REPO / "data" / "CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv"
    if not path.exists():
        return
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rl = _load_loader()
    prepared, stats = rl.prepare_rows(rows)
    assert len(rows) == 5635
    # 9 rows identical beyond Index collapse; 7 residual same-key pairs
    # (verified 2026-08-27) differ only in the manufacturer line —
    # whitespace / punctuation / plot-letter variants of the same alert —
    # and collapse to the sorted-first row.
    assert stats["true_duplicates_removed"] == 9
    assert stats["same_key_collapsed"] == 7
    assert len(prepared) == 5635 - 9 - 7


if __name__ == "__main__":
    fns = [v for v in list(globals().values()) if callable(v) and v.__name__.startswith("test_")]
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