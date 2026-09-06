"""Data-driven tenant registry tests (manufacturer/tenants.py).

The registry used to be a one-entry tuple; it is now curated entries plus
every company in ``nsq:ontology:companies``. These tests pin the parts that
are easy to break:

  * curated tenants keep their pinned keys and are never duplicated by the
    ontology entry with the same ontology_key (existing sign-ins stay valid);
  * ontology keys become URL-safe registry keys;
  * a Redis failure degrades to the curated registry and is NOT cached, so
    the first call after Redis returns picks up the real list;
  * Tenant.raw_names carries the spellings a key absorbed — the signal that
    the normalizer merged two different companies.

No Redis required: company_ontology.load_ontology is stubbed. tenants.py
imports it lazily inside all_tenants(), so stubbing the source module is
enough.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "manufacturer"))
sys.path.insert(0, str(REPO / "shared"))

FAKE_ONTOLOGY = {
    "regent ajanta": {
        "canonical_name": "Regent Ajanta Biotech", "city": "Haridwar",
        "aliases": ["Regent Ajanta Biotech Ltd"],
    },
    "unicure": {
        "canonical_name": "Unicure India Limited", "city": "Noida",
        "aliases": ["Unicure India Limited", "Unicure India Ltd", "Unicure India Ltd."],
    },
    # A real over-collapse from the CDSCO data: two unrelated firms, one key.
    "j": {
        "canonical_name": "J. M. Laboratories", "city": "",
        "aliases": ["J. M. Laboratories", "J.P Industries"],
    },
    "marc lifesciences": {
        "canonical_name": "Marc Lifesciences", "city": "Vadodara",
        "aliases": ["Marc Lifesciences"],
    },
    "": {"canonical_name": "", "city": "", "aliases": []},  # junk row, must be skipped
}


@pytest.fixture()
def tenants(monkeypatch):
    import company_ontology
    import tenants as tenants_mod

    monkeypatch.setattr(company_ontology, "load_ontology", lambda *a, **k: FAKE_ONTOLOGY)
    tenants_mod._cache = None
    yield tenants_mod
    tenants_mod._cache = None


def test_ontology_entries_become_tenants(tenants):
    ts = tenants.all_tenants()
    # curated + 3 valid ontology keys; the empty key is dropped.
    assert len(ts) == 4, [t.key for t in ts]
    assert {"unicure", "j", "marc-lifesciences"} <= {t.key for t in ts}


def test_curated_wins_and_is_not_duplicated(tenants):
    ts = tenants.all_tenants()
    assert ts[0].key == "regent-ajanta-biotech"
    assert sum(1 for t in ts if t.ontology_key == "regent ajanta") == 1


def test_lookup_by_curated_and_dynamic_key(tenants):
    assert tenants.get_tenant("regent-ajanta-biotech").canonical == "Regent Ajanta Biotech"
    assert tenants.get_tenant("marc-lifesciences").ontology_key == "marc lifesciences"
    assert tenants.get_tenant("nope") is None
    assert tenants.get_tenant("") is None


def test_merged_raw_names_are_preserved(tenants):
    j = tenants.get_tenant("j")
    assert j.raw_names == ("J. M. Laboratories", "J.P Industries")
    assert j.city == "—"  # missing city renders as a dash, not blank


def test_env_override_and_fallback(tenants, monkeypatch):
    monkeypatch.setenv("NSQ_TENANT", "unicure")
    assert tenants.get_active_tenant().key == "unicure"
    monkeypatch.setenv("NSQ_TENANT", "does-not-exist")
    assert tenants.get_active_tenant().key == "regent-ajanta-biotech"


def test_redis_failure_degrades_without_caching(tenants, monkeypatch):
    import company_ontology

    def boom(*a, **k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(company_ontology, "load_ontology", boom)
    tenants._cache = None
    assert tenants.all_tenants() == tenants.CURATED
    assert tenants._cache is None, "a Redis failure must not be cached for the full TTL"

    monkeypatch.setattr(company_ontology, "load_ontology", lambda *a, **k: FAKE_ONTOLOGY)
    assert len(tenants.all_tenants()) == 4, "recovers as soon as Redis is back"
