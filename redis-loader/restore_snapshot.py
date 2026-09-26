"""Restore the runtime Redis keyspace from a local snapshot file.

The inverse of dump_snapshot.py. Use it to seed the in-server Redis when
Upstash is unreachable (quota exhausted, network down) or on a dev box with
no Upstash credentials:

  python restore_snapshot.py --input ../data/nsq_snapshot.json.gz \
      --redis-url redis://localhost:6379/0 [--flush]

Only the keys the snapshot carries are written (nsq:*, geo:*). cdmo:* keys
and anything else are left alone. --flush first deletes nsq:* and geo:* so
the result mirrors the snapshot exactly.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys

import redis


def _chunks(items, n=500):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def restore(snapshot: dict, r: redis.Redis, flush: bool = False) -> dict:
    sec = snapshot.get("sections") or {}
    if flush:
        for pattern in ("nsq:*", "geo:*"):
            keys = list(r.scan_iter(match=pattern, count=1000))
            for chunk in _chunks(keys):
                r.delete(*chunk)

    counts = {"records": 0, "predictions": 0, "months": 0}
    records = sec.get("records") or {}
    for chunk in _chunks(list(records.items())):
        pipe = r.pipeline(transaction=False)
        for rid, fields in chunk:
            if fields:
                pipe.hset(f"nsq:record:{rid}", mapping=fields)
        pipe.execute()
    counts["records"] = len(records)

    ids = sec.get("record_ids") or list(records)
    for chunk in _chunks(ids):
        r.sadd("nsq:records", *chunk)

    preds = sec.get("predictions") or {}
    for chunk in _chunks(list(preds.items())):
        pipe = r.pipeline(transaction=False)
        for rid, fields in chunk:
            if fields:
                pipe.hset(f"nsq:prediction:{rid}", mapping=fields)
        pipe.execute()
    counts["predictions"] = len(preds)

    for month, members in (sec.get("by_month") or {}).items():
        if members:
            r.sadd(f"nsq:by_month:{month}", *members)
    counts["months"] = len(sec.get("by_month") or {})

    for key, name in (
        ("meta", "nsq:meta"),
        ("ontology_companies", "nsq:ontology:companies"),
        ("ontology_companies_meta", "nsq:ontology:meta"),
        ("ontology_products", "nsq:ontology:products"),
        ("ontology_products_meta", "nsq:ontology:products:meta"),
    ):
        mapping = sec.get(key) or {}
        if mapping:
            r.hset(name, mapping=mapping)

    for geo_key, g in (sec.get("geo") or {}).items():
        if g.get("payload") is not None:
            r.set(geo_key, g["payload"])
        meta = dict(g.get("meta") or {})
        if g.get("encoding") and "encoding" not in meta:
            meta["encoding"] = g["encoding"]
        if meta:
            r.hset(f"{geo_key}:meta", mapping=meta)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input", default="../data/nsq_snapshot.json.gz")
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL"))
    ap.add_argument("--flush", action="store_true")
    args = ap.parse_args()
    if not args.redis_url:
        print("ERROR: --redis-url or REDIS_URL required", file=sys.stderr)
        return 1
    with gzip.open(args.input, "rt", encoding="utf-8") as fh:
        snap = json.load(fh)
    r = redis.from_url(args.redis_url, decode_responses=True)
    r.ping()
    counts = restore(snap, r, flush=args.flush)
    print(f"restored from {args.input} (generated {snap.get('generated_at')}): {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
