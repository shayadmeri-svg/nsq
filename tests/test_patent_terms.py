"""core/patent_terms.py: every market status is sourced, derived by a cited statute, or unknown — never invented."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import patent_terms as pt  # noqa: E402

TODAY = date(2026, 10, 21)

# Semaglutide's compound family as Google Patents reports it (US8536122 / WO2006097537, filed 2006-03-20)
SEMAGLUTIDE = {
    "anchor": {"number": "US8536122", "url": "https://patents.google.com/patent/US8536122B2/en", "priority": "2005-03-18", "filing": "2006-03-20"},
    "international_filing": "2006-03-20",
    "countries": {
        "CA": {"number": "CA2601784C", "status": "Expired - Fee Related", "expiration": "2028-03-20", "url": "u"},
        "EP": {"number": "EP1863839B1", "status": "Expired - Lifetime", "expiration": None, "url": "u"},
        "JP": {"number": "JP5209463B2", "status": "Active", "expiration": "2028-07-01", "url": "u"},
    },
    "spcs": [{"number": "FR18C1017I2", "country": "FR", "url": "u"}, {"number": "NL300936I2", "country": "NL", "url": "u"}],
}


def test_india_from_international_filing_matches_the_real_expiry():
    # India: 20 years from the international filing date, no extension -> 2026-03-20, when generics launched
    s = pt.market_status("IN", today=TODAY, family=SEMAGLUTIDE, first_approval_year=2017)
    assert s.status == "off_patent" and s.basis == "derived"
    assert s.date == date(2026, 3, 20)
    assert "s. 53" in s.sources[0]["label"]


def test_india_before_expiry_is_an_upper_bound_not_a_claim():
    s = pt.market_status("IN", today=date(2025, 1, 1), family=SEMAGLUTIDE, first_approval_year=2017)
    assert s.status == "loe_pending" and s.basis == "derived"
    assert "Not confirmed" in s.note and s.date == date(2026, 3, 20)


def test_country_member_status_is_sourced():
    ca = pt.market_status("CA", today=TODAY, family=SEMAGLUTIDE, first_approval_year=2017)
    assert ca.status == "off_patent" and ca.basis == "sourced" and "Fee Related" in ca.note
    jp = pt.market_status("JP", today=TODAY, family=SEMAGLUTIDE, first_approval_year=2017)
    assert jp.status == "loe_pending" and jp.basis == "sourced" and jp.date == date(2028, 7, 1)


def test_lifetime_expiry_respects_term_extension_window():
    fam = {**SEMAGLUTIDE, "countries": {"JP": {"number": "JP5209463B2", "status": "Expired - Lifetime", "expiration": None,
                                               "filing": "2006-03-20", "url": "u"}}}
    jp = pt.market_status("JP", today=TODAY, family=fam, first_approval_year=2017)
    assert jp.status in ("loe_pending", "patented") and jp.basis == "derived" and jp.date == date(2031, 3, 20)


def test_uk_uses_the_european_patent():
    gb = pt.market_status("GB", today=TODAY, family=SEMAGLUTIDE, first_approval_year=2017, first_eu_authorisation=date(2018, 2, 8))
    assert gb.basis != "unknown"


def test_eu_spc_keeps_protection_after_the_patent_lapses():
    eu = pt.market_status("EU", today=TODAY, family=SEMAGLUTIDE, first_approval_year=2017, first_eu_authorisation=date(2018, 2, 8))
    # SPC ceiling: min(filing + 25 y, first EU authorisation + 15 y) = 2031-03-20
    assert eu.status in ("loe_pending", "patented") and eu.basis == "derived"
    assert eu.date == date(2031, 3, 20)


def test_old_molecule_is_off_patent_everywhere_by_age():
    for code in ("IN", "BR", "JP", "EU"):
        s = pt.market_status(code, today=TODAY, first_approval_year=1974)
        assert s.status == "off_patent" and s.basis == "derived", code


def test_unknown_is_unknown_not_patented():
    s = pt.market_status("IN", today=TODAY, family=None, first_approval_year=2015)
    assert s.status == "unknown" and s.basis == "unknown"


def test_us_generics_on_market_mean_open_even_with_product_patents():
    ob = {"anda_active": 22, "first_generic_approval": "1982-01-01", "last_substance_patent_expiry": "2026-12-08",
          "last_patent_expiry": "2026-12-08", "last_exclusivity_expiry": ""}
    s = pt.us_status(ob, today=TODAY, first_approval_year=1974)  # amoxicillin: a modified-release product patent
    assert s.status == "off_patent" and s.barrier == "formulation"
    assert "specific products" in s.note


def test_us_approved_generics_wait_for_the_compound_patent():
    ob = {"anda_active": 2, "first_generic_approval": "2019-12-23", "last_substance_patent_expiry": "2026-11-21",
          "last_patent_expiry": "2026-11-21", "last_exclusivity_expiry": ""}
    s = pt.us_status(ob, today=TODAY, first_approval_year=2012)  # apixaban
    assert s.status == "loe_pending" and s.date == date(2026, 11, 21)
    assert "launch waits" in s.note


def test_us_monograph_drug_without_orange_book_record():
    s = pt.us_status(None, today=TODAY, first_approval_year=1950)  # aspirin (OTC monograph)
    assert s.status == "off_patent" and s.basis == "derived"


def test_every_status_cites_something_unless_unknown():
    for s in (pt.market_status("IN", today=TODAY, family=SEMAGLUTIDE), pt.market_status("BR", today=TODAY, first_approval_year=1990)):
        assert s.basis == "unknown" or s.sources
