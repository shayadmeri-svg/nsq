"""Copy the static NSQ dataset from the upstream (Upstash) Redis into the
in-server Redis the services actually read.

Why: the NSQ data changes once a month, but every service used to read it
straight from Upstash, whose free plan has a monthly command quota. The
compose stack now runs its own `redis` container; this script is the only
thing that talks to Upstash, and only when you ask it to (once per data
refresh, or on a fresh box via `deploy.sh`).

What is copied, by key pattern:

  MIRROR  nsq:*  geo:*
      Owned by the loaders. The target ends up identical to upstream:
      keys are overwritten, and local keys that no longer exist upstream
      (e.g. record ids dropped by a --flush reload) are deleted.

  UPSERT  cdmo:patent:*  cdmo:regulatory:*  cdmo:demand:*  cdmo:plant:*
      Seed data. Upstream keys overwrite local ones; nothing is deleted,
      so plants created on the server survive.

  NEVER   cdmo:portfolio:*  cdmo:complexity:*  (anything else)
      Written by the engine at runtime — server-local data.

Upstream cost: a handful of SCANs, one TYPE and one read per key
(~23k commands for the current ~11.5k keys). Nothing is written upstream.

Usage (normally via ./pull-upstash.sh, which runs this inside the
analytics image on the compose network):

    python pull_upstash.py [--only-if-empty] [--dry-run]
        [--source URL (default $UPSTREAM_REDIS_URL)]
        [--target URL (default $TARGET_REDIS_URL or redis://redis:6379/0)]

Exit codes: 0 copied, 10 skipped (--only-if-empty and target already
seeded), 1 usage/safety refusal, 2 upstream unavailable (e.g. quota).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urlsplit

import redis

MIRROR_PATTERNS = ("nsq:*", "geo:*")
UPSERT_PATTERNS = (
    "cdmo:patent:*", "cdmo:regulatory:*", "cdmo:demand:*", "cdmo:plant:*",
)
BATCH = 500
EXIT_SKIPPED = 10
EXIT_UPSTREAM_DOWN = 2


def _redact(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "?"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}{parts.path}"


def _chunks(seq, n=BATCH):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def scan_keys(r: redis.Redis, pattern: str) -> list[bytes]:
    return sorted(set(r.scan_iter(match=pattern, count=1000)))


def read_values(src: redis.Redis, keys: list[bytes]) -> dict[bytes, tuple[str, object]]:
    """{key: (type, value)} for every key, pipelined in batches: one TYPE
    pass, then one read per key chosen by type."""
    out: dict[bytes, tuple[str, object]] = {}
    for batch in _chunks(keys):
        pipe = src.pipeline(transaction=False)
        for k in batch:
            pipe.type(k)
        types = [t.decode() if isinstance(t, bytes) else t for t in pipe.execute()]

        pipe = src.pipeline(transaction=False)
        kept = []
        for k, t in zip(batch, types):
            if t == "hash":
                pipe.hgetall(k)
            elif t == "set":
                pipe.smembers(k)
            elif t == "string":
                pipe.get(k)
            elif t == "list":
                pipe.lrange(k, 0, -1)
            elif t == "zset":
                pipe.zrange(k, 0, -1, withscores=True)
            else:  # 'none' (expired mid-scan) or an unsupported type
                continue
            kept.append((k, t))
        for (k, t), v in zip(kept, pipe.execute()):
            out[k] = (t, v)
    return out


def write_values(dst: redis.Redis, values: dict[bytes, tuple[str, object]]) -> None:
    items = list(values.items())
    for batch in _chunks(items):
        pipe = dst.pipeline(transaction=True)
        for k, (t, v) in batch:
            pipe.delete(k)
            if t == "string":
                pipe.set(k, v)
            elif not v:
                continue  # empty collection == key absent
            elif t == "hash":
                pipe.hset(k, mapping=v)
            elif t == "set":
                pipe.sadd(k, *v)
            elif t == "list":
                pipe.rpush(k, *v)
            elif t == "zset":
                pipe.zadd(k, dict(v))
        pipe.execute()


def pull(src: redis.Redis, dst: redis.Redis, *, only_if_empty: bool = False,
         dry_run: bool = False, log=print) -> dict:
    """Copy upstream -> target. Returns stats. Raises SystemExit with the
    documented exit codes on refusal/skip."""
    if only_if_empty and dst.scard("nsq:records") > 0:
        log(f"target already seeded ({dst.scard('nsq:records')} records) — skipping.")
        raise SystemExit(EXIT_SKIPPED)

    t0 = time.monotonic()
    upstream_records = src.scard("nsq:records")
    if upstream_records == 0:
        log("REFUSING: upstream has 0 nsq:records — mirroring it would wipe "
            "the target. Seed the upstream Redis first.")
        raise SystemExit(1)

    mirror_keys = [k for p in MIRROR_PATTERNS for k in scan_keys(src, p)]
    upsert_keys = [k for p in UPSERT_PATTERNS for k in scan_keys(src, p)]
    stats = {"upstream_records": upstream_records,
             "mirror_keys": len(mirror_keys), "upsert_keys": len(upsert_keys),
             "stale_deleted": 0, "dry_run": dry_run}

    local_mirror = {k for p in MIRROR_PATTERNS for k in scan_keys(dst, p)}
    stale = sorted(local_mirror - set(mirror_keys))
    stats["stale_deleted"] = len(stale)

    if dry_run:
        log(f"dry run: would copy {len(mirror_keys)} mirrored + "
            f"{len(upsert_keys)} upserted keys, delete {len(stale)} stale.")
        return stats

    values = read_values(src, mirror_keys + upsert_keys)
    write_values(dst, values)
    for batch in _chunks(stale):
        dst.delete(*batch)

    got = dst.scard("nsq:records")
    if got != upstream_records:
        log(f"WARNING: target has {got} records, upstream {upstream_records}.")
    stats["target_records"] = got
    stats["seconds"] = round(time.monotonic() - t0, 1)
    log(f"copied {len(values)} keys ({len(mirror_keys)} nsq/geo, "
        f"{len(upsert_keys)} cdmo seeds), deleted {len(stale)} stale; "
        f"target now has {got} records. {stats['seconds']}s")
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=os.environ.get("UPSTREAM_REDIS_URL"))
    ap.add_argument("--target", default=os.environ.get(
        "TARGET_REDIS_URL", "redis://redis:6379/0"))
    ap.add_argument("--only-if-empty", action="store_true",
                    help="Do nothing if the target already has nsq:records.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.source:
        print("No upstream URL: pass --source or set UPSTREAM_REDIS_URL.", file=sys.stderr)
        return 1
    if args.source.rstrip("/") == args.target.rstrip("/"):
        print("REFUSING: source and target are the same Redis.", file=sys.stderr)
        return 1

    print(f"upstream: {_redact(args.source)}  ->  target: {_redact(args.target)}")
    src = redis.from_url(args.source, decode_responses=False)
    dst = redis.from_url(args.target, decode_responses=False)
    try:
        dst.ping()
    except redis.RedisError as exc:
        print(f"target Redis unreachable: {exc}", file=sys.stderr)
        return 1
    try:
        pull(src, dst, only_if_empty=args.only_if_empty, dry_run=args.dry_run)
    except SystemExit as exc:
        return int(exc.code or 0)
    except redis.RedisError as exc:
        print(f"upstream Redis unavailable ({type(exc).__name__}: {exc}). "
              "If this is Upstash, the monthly quota may be exhausted. "
              "Target left as it was.", file=sys.stderr)
        return EXIT_UPSTREAM_DOWN
    return 0


if __name__ == "__main__":
    sys.exit(main())
