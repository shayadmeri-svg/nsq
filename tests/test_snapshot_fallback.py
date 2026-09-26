"""Tests for the Redis-quota local-snapshot fallback tier.

When the Upstash monthly command quota is exhausted, every Redis command
raises ``redis.exceptions.ResponseError`` (a ``redis.RedisError``
subclass). The services then serve a local snapshot
(``data/nsq_snapshot.json.gz``, written by redis-loader/dump_snapshot.py)
instead of an empty dashboard.

These tests pin, with no Redis required:
  1. The dump roundtrip — ``dump_sections`` + ``write_snapshot`` produce
     a verbatim, reloadable mirror of the keyspace.
  2. The fallback tiers — a quota-exhausted client serves records,
     predictions, ontologies and geojson from the snapshot.
  3. The negative path — snapshot missing keeps today's behavior (empty
     frame / ``{}`` / CSV fallback), no new crash.

Integration test (roundtrip against the real dev Redis) skips when
Redis is unreachable — mirrors test_data_loader_uncached.py.

Runnable both as ``python tests/test_snapshot_fallback.py`` and via pytest.
"""

from __future__ import annotations

import base64
import fnmatch
import gzip
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
import redis

REPO = Path(__file__).resolve().parent.parent
SHARED = REPO / "core"
LOADER = REPO / "redis-loader"

# shared/ modules import each other by bare name (the services put shared/
# on sys.path), so import them the same way here.
sys.path.insert(0, str(SHARED))
import company_ontology  # noqa: E402
import nsq_redis  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "dump_snapshot", LOADER / "dump_snapshot.py")
dump_snapshot = importlib.util.module_from_spec(_spec)
sys.modules["dump_snapshot"] = dump_snapshot
_spec.loader.exec_module(dump_snapshot)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakePipeline:
    def __init__(self, store: "FakeRedis"):
        self._store = store
        self._ops: list[str] = []

    def hgetall(self, key: str) -> None:
        self._ops.append(key)

    def execute(self) -> list:
        out = [dict(self._store.hashes.get(k, {})) for k in self._ops]
        self._ops = []
        return out


class FakeRedis:
    """Dict-backed stand-in for the slices of redis.Redis the dump uses."""

    def __init__(self, hashes=None, sets=None, strings=None):
        self.hashes = hashes or {}
        self.sets = sets or {}
        self.strings = strings or {}

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def get(self, key):
        return self.strings.get(key)

    def scan_iter(self, pattern):
        keys = set(self.hashes) | set(self.sets) | set(self.strings)
        return sorted(k for k in keys if fnmatch.fnmatch(k, pattern))

    def pipeline(self):
        return FakePipeline(self)


class QuotaExceededClient:
    """Every command raises the way Upstash does when the monthly
    command quota is exhausted."""

    def _raise(self, *args, **kwargs):
        raise redis.exceptions.ResponseError("Monthly quota exceeded")

    smembers = hgetall = get = scan_iter = pipeline = _raise


def _fake_store() -> FakeRedis:
    """A small but faithful copy of the keyspace load_csv_redis.py writes."""
    geo = {"type": "FeatureCollection", "features": [{"properties": {"NAME_1": "Bihar"}}]}
    geo_b64 = base64.b64encode(gzip.compress(json.dumps(geo).encode("utf-8"))).decode("ascii")
    return FakeRedis(
        hashes={
            "nsq:record:rid-b": {
                "str_product_name": "Paracetamol 500mg Tablet",
                "str_batch_no": "PB2", "str_nsq_result": "Not of Standard Quality",
                "dt_reporting_month_year": "2025-02", "index": "2",
            },
            "nsq:record:rid-a": {
                "str_product_name": "Cetirizine 10mg Tablet",
                "str_batch_no": "PA1", "str_nsq_result": "Not of Standard Quality",
                "dt_reporting_month_year": "2025-01", "index": "1",
            },
            "nsq:prediction:rid-a": {
                "raw_company": "Cipla Ltd.", "canonical": "Cipla Limited",
                "city": "Mumbai", "state": "Maharashtra",
                "website": "https://www.cipla.com", "ontology_key": "cipla-limited",
            },
            "nsq:meta": {"total_records": "2", "loaded_at": "2025-03-01T00:00:00+00:00"},
            "nsq:ontology:companies": {
                "cipla-limited": json.dumps({
                    "canonical_name": "Cipla Limited", "city": "Mumbai",
                    "state": "Maharashtra", "aliases": ["Cipla Ltd."], "sources": 1,
                }),
            },
            "nsq:ontology:meta": {"entry_count": "1"},
            "nsq:ontology:products": {
                "paracetamol-500mg-tablet": json.dumps({"canonical_name": "Paracetamol 500mg Tablet"}),
            },
            "nsq:ontology:products:meta": {"entry_count": "1"},
            "geo:india_states:meta": {
                "encoding": "gzip+base64", "size_bytes": "42",
                "loaded_at": "2025-03-01T00:00:00+00:00",
            },
        },
        sets={
            "nsq:records": {"rid-a", "rid-b"},
            "nsq:by_month:2025-01": {"rid-a"},
            "nsq:by_month:2025-02": {"rid-b"},
        },
        strings={"geo:india_states": geo_b64},
    )


@pytest.fixture
def snapshot_path(tmp_path, monkeypatch):
    """Dump the fake store to a tmp snapshot and point NSQ_SNAPSHOT at it.
    A fresh tmp path per test also avoids the load_snapshot memo bleeding
    between tests (it re-reads whenever path/mtime/size change)."""
    path = tmp_path / "nsq_snapshot.json.gz"
    snapshot = dump_snapshot.dump_sections(_fake_store(), list(dump_snapshot.ALL_SECTIONS))
    dump_snapshot.write_snapshot(snapshot, path)
    monkeypatch.setenv("NSQ_SNAPSHOT", str(path))
    return path


# ---------------------------------------------------------------------------
# 1. Dump roundtrip (no Redis required)
# ---------------------------------------------------------------------------

def test_dump_roundtrip_verbatim(snapshot_path):
    with gzip.open(snapshot_path, "rt", encoding="utf-8") as f:
        snap = json.load(f)

    assert snap["schema_version"] == dump_snapshot.SCHEMA_VERSION
    # generated_at comes from nsq:meta's loaded_at -> byte-deterministic dumps
    assert snap["generated_at"] == "2025-03-01T00:00:00+00:00"
    sec = snap["sections"]
    assert sec["record_ids"] == ["rid-a", "rid-b"]  # sorted
    assert sec["records"]["rid-a"]["str_product_name"] == "Cetirizine 10mg Tablet"
    assert sec["predictions"]["rid-a"]["canonical"] == "Cipla Limited"
    assert sec["meta"]["total_records"] == "2"
    assert sec["by_month"] == {"2025-01": ["rid-a"], "2025-02": ["rid-b"]}
    # Ontology values stay raw JSON strings, exactly as Redis returns them
    assert json.loads(sec["ontology_companies"]["cipla-limited"])["city"] == "Mumbai"
    assert json.loads(sec["ontology_products"]["paracetamol-500mg-tablet"])["canonical_name"] == \
        "Paracetamol 500mg Tablet"
    geo_entry = sec["geo"]["geo:india_states"]
    assert geo_entry["encoding"] == "gzip+base64"
    assert json.loads(gzip.decompress(base64.b64decode(geo_entry["payload"])))["type"] == \
        "FeatureCollection"


def test_dump_is_byte_deterministic(tmp_path):
    snapshot = dump_snapshot.dump_sections(_fake_store(), list(dump_snapshot.ALL_SECTIONS))
    a, b = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    dump_snapshot.write_snapshot(snapshot, a)
    dump_snapshot.write_snapshot(dump_snapshot.dump_sections(
        _fake_store(), list(dump_snapshot.ALL_SECTIONS)), b)
    assert a.read_bytes() == b.read_bytes()


def test_dump_never_leaks_credentials():
    source = dump_snapshot._sanitize_source(
        "rediss://default:SEKRIT@relaxed-yak-123.upstash.io:6379", "prod")
    assert "SEKRIT" not in source
    assert source == "relaxed-yak-123.upstash.io (prod)"


# ---------------------------------------------------------------------------
# 2. Fallback tiers with a quota-exhausted client
# ---------------------------------------------------------------------------

def test_load_dataframe_serves_snapshot_on_quota_error(snapshot_path, caplog):
    with caplog.at_level("WARNING", logger="nsq_redis"):
        df = nsq_redis.load_dataframe(client=QuotaExceededClient())
    assert not df.empty
    assert list(df["record_id"]) == ["rid-a", "rid-b"]
    assert "Name of Product" in df.columns
    assert df.loc[df.record_id == "rid-a", "Name of Product"].iloc[0] == \
        "Cetirizine 10mg Tablet"
    assert "Redis unavailable" in caplog.text


def test_load_predictions_serves_snapshot_on_quota_error(snapshot_path):
    preds = nsq_redis.load_predictions(client=QuotaExceededClient())
    assert set(preds) == {"rid-a"}
    assert preds["rid-a"]["raw_company"] == "Cipla Ltd."
    # A live-Redis shape pin: raw loader field names, no Mfg_* renames here
    assert "canonical" in preds["rid-a"]


def test_load_meta_serves_snapshot_on_quota_error(snapshot_path):
    assert nsq_redis.load_meta(client=QuotaExceededClient())["total_records"] == "2"


def test_load_geojson_serves_snapshot_on_quota_error(snapshot_path, monkeypatch):
    # load_geojson builds its own client from REDIS_URL — point it at a
    # dead port so the command raises ConnectionError (a RedisError).
    monkeypatch.setenv("REDIS_URL", "redis://localhost:9")
    geo = nsq_redis.load_geojson()
    assert geo is not None
    assert geo["type"] == "FeatureCollection"
    assert geo["features"][0]["properties"]["NAME_1"] == "Bihar"


def test_ontology_loaders_serve_snapshot_on_quota_error(snapshot_path, caplog):
    with caplog.at_level("WARNING", logger="company_ontology"):
        companies = company_ontology.load_ontology(client=QuotaExceededClient())
        products = company_ontology.load_product_ontology(client=QuotaExceededClient())
    assert companies["cipla-limited"]["canonical_name"] == "Cipla Limited"
    assert products["paracetamol-500mg-tablet"]["canonical_name"] == "Paracetamol 500mg Tablet"
    assert "local snapshot" in caplog.text


def test_ontology_loaders_serve_snapshot_without_redis_url(snapshot_path, monkeypatch):
    # REDIS_URL unset raises RuntimeError in get_redis_client BEFORE any
    # command runs — the snapshot must serve then too (this is the state
    # of a container whose .env lacks REDIS_URL).
    monkeypatch.delenv("REDIS_URL", raising=False)
    companies = company_ontology.load_ontology()
    products = company_ontology.load_product_ontology()
    assert companies["cipla-limited"]["canonical_name"] == "Cipla Limited"
    assert products["paracetamol-500mg-tablet"]["canonical_name"] == "Paracetamol 500mg Tablet"


# ---------------------------------------------------------------------------
# 3. Negative path — snapshot missing keeps today's behavior
# ---------------------------------------------------------------------------

def test_no_snapshot_no_crash(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("NSQ_SNAPSHOT", str(tmp_path / "does-not-exist.json.gz"))
    monkeypatch.setenv("NSQ_CSV", str(tmp_path / "does-not-exist.csv"))

    with caplog.at_level("WARNING", logger="nsq_redis"):
        df = nsq_redis.load_dataframe(client=QuotaExceededClient())
    assert df.empty
    assert nsq_redis.load_predictions(client=QuotaExceededClient()) == {}
    assert nsq_redis.load_meta(client=QuotaExceededClient()) == {}
    assert company_ontology.load_ontology(client=QuotaExceededClient()) == {}
    assert company_ontology.load_product_ontology(client=QuotaExceededClient()) == {}
    assert "Redis unavailable" in caplog.text


def test_csv_tier_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("NSQ_SNAPSHOT", str(tmp_path / "does-not-exist.json.gz"))
    csv_path = tmp_path / "mini.csv"
    csv_path.write_text(
        "Index,Name of Product,Batch No,Mfg,Exp,Manufactured By,"
        "NSQ Result,Reporting Source,Reporting by Lab/State,"
        "Reporting Month & Year,Source\n"
        "1,Cetirizine 10mg Tablet,PA1,2024-01,2025-01,Cipla Ltd.,"
        "Not of Standard Quality,CDSCO,Central Drug Laboratory,"
        "Jan 2025,csv\n"
    )
    monkeypatch.setenv("NSQ_CSV", str(csv_path))

    df = nsq_redis.load_dataframe(client=QuotaExceededClient())
    assert list(df["Name of Product"]) == ["Cetirizine 10mg Tablet"]


def test_snapshot_directory_is_ignored(tmp_path, monkeypatch):
    # Docker creates a DIRECTORY at a single-file bind mount's target when
    # the source file is missing on the host — the reader must treat that
    # as "no snapshot", not crash.
    monkeypatch.setenv("NSQ_SNAPSHOT", str(tmp_path / "mount_point"))
    (tmp_path / "mount_point").mkdir()
    assert nsq_redis.load_snapshot() is None


# ---------------------------------------------------------------------------
# Integration (real dev Redis) — skips when unreachable
# ---------------------------------------------------------------------------

def _redis_reachable() -> bool:
    url = os.environ.get("REDIS_URL")
    if not url:
        return False
    try:
        return bool(redis.from_url(url, decode_responses=True).ping())
    except Exception:
        return False


@pytest.mark.skipif(not _redis_reachable(), reason="dev Redis not reachable")
def test_dump_roundtrip_real_redis(tmp_path):
    r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    snapshot = dump_snapshot.dump_sections(r, list(dump_snapshot.ALL_SECTIONS))
    path = tmp_path / "real.json.gz"
    dump_snapshot.write_snapshot(snapshot, path)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        snap = json.load(f)
    sec = snap["sections"]
    # Self-consistency: every record id has a record, counts match live Redis
    live_ids = r.smembers("nsq:records")
    assert sorted(live_ids) == sec["record_ids"]
    for rid in sec["record_ids"]:
        assert sec["records"][rid] == r.hgetall(f"nsq:record:{rid}")


if __name__ == "__main__":
    # These tests are fixture-based (tmp_path / monkeypatch / caplog), so
    # the standalone entry point delegates to pytest rather than calling
    # the functions bare (which would bypass their fixtures).
    raise SystemExit(pytest.main([__file__, "-v"]))