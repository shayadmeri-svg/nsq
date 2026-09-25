"""Tests for redis-loader/pull_upstash.py — the Upstash -> in-server Redis
copy that keeps the services off the Upstash command quota.

Pins: every key type round-trips byte-for-byte; nsq:*/geo:* are mirrored
(stale local keys deleted); cdmo seeds are upserted while server-local
runtime keys (portfolios, complexity, user-created plants) survive;
--only-if-empty costs zero upstream commands; an empty upstream is
refused rather than wiping the target; --dry-run writes nothing.

Uses fakeredis (skipped if absent). Runnable via pytest.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

fakeredis = pytest.importorskip("fakeredis")

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "pull_upstash", REPO / "redis-loader" / "pull_upstash.py")
pull_upstash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pull_upstash)


def _client():
    # Separate FakeServer per client == two independent Redis instances.
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=False)


@pytest.fixture
def upstream():
    r = _client()
    for rid in ("a1", "b2"):
        r.hset(f"nsq:record:{rid}", mapping={"str_product_name": f"P-{rid}"})
        r.hset(f"nsq:prediction:{rid}", mapping={"state": "Uttarakhand"})
    r.sadd("nsq:records", "a1", "b2")
    r.sadd("nsq:by_month:2026-07", "a1")
    r.hset("nsq:meta", mapping={"total_records": "2"})
    r.hset("nsq:ontology:companies", mapping={"acme": '{"canonical_name": "Acme"}'})
    r.set("nsq:frame:enriched", b"\x00binary\xffframe")
    r.set("geo:india_states", "H4sIAAAA")
    r.hset("geo:india_states:meta", mapping={"encoding": "gzip+base64"})
    r.rpush("nsq:some_list", "x", "y")
    r.zadd("nsq:some_zset", {"m": 1.5})
    r.hset("cdmo:patent:atorvastatin", mapping={"molecule_key": "atorvastatin"})
    r.hset("cdmo:plant:P1", mapping={"asset_id": "P1", "name": "Upstream name"})
    r.hset("cdmo:portfolio:upstream-only", mapping={"x": "1"})  # never copied
    return r


def _dump(r, pattern="*"):
    out = {}
    for k in r.scan_iter(match=pattern):
        t = r.type(k).decode()
        v = {"hash": r.hgetall, "set": r.smembers, "string": r.get,
             "list": lambda k: r.lrange(k, 0, -1),
             "zset": lambda k: r.zrange(k, 0, -1, withscores=True)}[t](k)
        out[k] = (t, v)
    return out


def test_copies_every_type_verbatim(upstream):
    target = _client()
    stats = pull_upstash.pull(upstream, target, log=lambda *_: None)
    assert _dump(target, "nsq:*") == _dump(upstream, "nsq:*")
    assert _dump(target, "geo:*") == _dump(upstream, "geo:*")
    assert target.get("nsq:frame:enriched") == b"\x00binary\xffframe"
    assert stats["target_records"] == 2


def test_mirror_deletes_stale_but_keeps_server_local(upstream):
    target = _client()
    target.hset("nsq:record:old", mapping={"x": "1"})          # dropped upstream
    target.sadd("nsq:by_month:2019-01", "old")
    target.hset("cdmo:portfolio:mine", mapping={"id": "mine"})  # runtime data
    target.hset("cdmo:complexity:atorvastatin", mapping={"x": "1"})
    target.hset("cdmo:plant:USER1", mapping={"asset_id": "USER1"})  # created on box
    target.hset("cdmo:plant:P1", mapping={"asset_id": "P1", "name": "Local edit"})

    stats = pull_upstash.pull(upstream, target, log=lambda *_: None)

    assert not target.exists("nsq:record:old", "nsq:by_month:2019-01")
    assert stats["stale_deleted"] == 2
    assert target.exists("cdmo:portfolio:mine", "cdmo:complexity:atorvastatin",
                         "cdmo:plant:USER1") == 3
    assert target.hget("cdmo:plant:P1", "name") == b"Upstream name"  # seed wins
    assert not target.exists("cdmo:portfolio:upstream-only")


def test_only_if_empty_skips_without_touching_upstream(upstream):
    target = _client()
    target.sadd("nsq:records", "already")

    class Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"upstream touched: {name}")

    with pytest.raises(SystemExit) as exc:
        pull_upstash.pull(Exploding(), target, only_if_empty=True, log=lambda *_: None)
    assert exc.value.code == pull_upstash.EXIT_SKIPPED
    assert target.smembers("nsq:records") == {b"already"}


def test_only_if_empty_seeds_an_empty_target(upstream):
    target = _client()
    pull_upstash.pull(upstream, target, only_if_empty=True, log=lambda *_: None)
    assert target.scard("nsq:records") == 2


def test_refuses_empty_upstream():
    target = _client()
    target.sadd("nsq:records", "keep-me")
    with pytest.raises(SystemExit) as exc:
        pull_upstash.pull(_client(), target, log=lambda *_: None)
    assert exc.value.code == 1
    assert target.smembers("nsq:records") == {b"keep-me"}


def test_dry_run_writes_nothing(upstream):
    target = _client()
    target.hset("nsq:record:old", mapping={"x": "1"})
    stats = pull_upstash.pull(upstream, target, dry_run=True, log=lambda *_: None)
    assert stats["stale_deleted"] == 1
    assert _dump(target) == {b"nsq:record:old": ("hash", {b"x": b"1"})}


def test_upstream_failure_leaves_target_untouched(upstream, monkeypatch):
    import redis
    target = _client()
    target.sadd("nsq:records", "keep-me")

    def quota(*_a, **_k):
        raise redis.exceptions.ResponseError("max requests limit exceeded")
    monkeypatch.setattr(pull_upstash, "read_values", quota)
    with pytest.raises(redis.RedisError):
        pull_upstash.pull(upstream, target, log=lambda *_: None)
    assert target.smembers("nsq:records") == {b"keep-me"}


def test_main_refuses_same_source_and_target():
    assert pull_upstash.main(["--source", "redis://x:6379/0",
                              "--target", "redis://x:6379/0"]) == 1
