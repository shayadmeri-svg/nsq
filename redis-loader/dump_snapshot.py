"""Dump the runtime-needed Redis keyspace to a local snapshot file.

The deployed services read live data from the Upstash Redis, whose free
plan has a monthly command quota. When the quota is exhausted mid-month,
every Redis command raises redis.RedisError. The snapshot written here is
the fallback tier the services serve in that case (see shared/nsq_redis.py):
a faithful gzipped-JSON mirror of the runtime keyspace, so production
shows data as of the last refresh instead of an empty dashboard.

Snapshot layout (see shared/nsq_redis.py::load_snapshot):

  {
    "schema_version": 1,
    "generated_at": <nsq:meta loaded_at, else wall clock>,
    "source":       "<sanitized host + label — never the URL/password>",
    "sections": {
      "record_ids":  sorted(nsq:records),
      "records":     {rid: verbatim HGETALL nsq:record:<rid>},
      "predictions": {rid: verbatim HGETALL nsq:prediction:<rid>},
      "meta":        verbatim HGETALL nsq:meta,
      "by_month":    {month: sorted SMEMBERS nsq:by_month:<month>},
      "ontology_companies":      verbatim HGETALL nsq:ontology:companies,
      "ontology_companies_meta": verbatim HGETALL nsq:ontology:meta,
      "ontology_products":       verbatim HGETALL nsq:ontology:products,
      "ontology_products_meta":  verbatim HGETALL nsq:ontology:products:meta,
      "geo": {"geo:india_states": {"payload": ..., "encoding": ..., "meta": ...}}
    }
  }

Every value is stored exactly as Redis returns it, so the readers reuse
the same parsing as the live path — no schema translation to get wrong.
Output is byte-deterministic for identical Redis state (sorted keys,
generated_at from nsq:meta, gzip mtime=0), keeping git diffs clean.

Usage (justfile wraps this — `just snapshot` / `just snapshot-prod`):
  python dump_snapshot.py --redis-url "$REDIS_URL" \
      --output ../data/nsq_snapshot.json.gz --source-label prod
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis

SCHEMA_VERSION = 1
DEFAULT_OUTPUT = "../data/nsq_snapshot.json.gz"
GEO_KEY = "geo:india_states"

# Section name -> the section it needs record ids for (pipelined together).
ALL_SECTIONS = [
    "records", "predictions", "meta", "by_month",
    "ontology_companies", "ontology_products", "geo",
]


def _sanitize_source(redis_url: str, label: str) -> str:
    """Host + label only. Upstash URLs embed the password, so never let
    the URL (or any credential) near the snapshot."""
    no_creds = re.sub(r"(?<=://)[^@/]+(?=@)", "***:***", redis_url)
    m = re.search(r"://(?:[^@/]+@)?([^:/]+)", no_creds)
    host = m.group(1) if m else "unknown-host"
    return f"{host} ({label})"


def dump_sections(r: redis.Redis, sections: list[str]) -> dict:
    """Read the requested sections out of a live client and return the
    snapshot envelope. Pure read — no writes, no deletes."""
    out: dict = {}

    # records + predictions share the same rid list; one pipeline for
    # both halves the command count (matters on a quota-metered plan).
    need_records = "records" in sections
    need_predictions = "predictions" in sections
    id_list: list[str] = []
    if need_records or need_predictions:
        id_list = sorted(r.smembers("nsq:records"))
        pipe = r.pipeline()
        record_rows = prediction_rows = None
        if need_records:
            for rid in id_list:
                pipe.hgetall(f"nsq:record:{rid}")
        if need_predictions:
            for rid in id_list:
                pipe.hgetall(f"nsq:prediction:{rid}")
        rows = pipe.execute()
        if need_records:
            record_rows = rows[: len(id_list)]
            rows = rows[len(id_list):]
        if need_predictions:
            prediction_rows = rows
        if need_records:
            out["record_ids"] = id_list
            out["records"] = {rid: row for rid, row in zip(id_list, record_rows)
                              if row is not None}
        if need_predictions:
            out["predictions"] = {rid: row for rid, row in zip(id_list, prediction_rows)
                                 if row}

    if "meta" in sections:
        out["meta"] = r.hgetall("nsq:meta") or {}

    if "by_month" in sections:
        by_month: dict[str, list[str]] = {}
        for key in sorted(r.scan_iter("nsq:by_month:*")):
            by_month[key.removeprefix("nsq:by_month:")] = sorted(r.smembers(key))
        out["by_month"] = by_month

    if "ontology_companies" in sections:
        out["ontology_companies"] = r.hgetall("nsq:ontology:companies") or {}
        out["ontology_companies_meta"] = r.hgetall("nsq:ontology:meta") or {}

    if "ontology_products" in sections:
        out["ontology_products"] = r.hgetall("nsq:ontology:products") or {}
        out["ontology_products_meta"] = r.hgetall("nsq:ontology:products:meta") or {}

    if "geo" in sections:
        payload = r.get(GEO_KEY)
        if payload is None:
            out["geo"] = {}
        else:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            geo_meta = r.hgetall(f"{GEO_KEY}:meta") or {}
            out["geo"] = {GEO_KEY: {
                "payload": payload,
                "encoding": geo_meta.get("encoding", "gzip+base64"),
                "meta": geo_meta,
            }}

    # generated_at from nsq:meta when available: the meta's loaded_at is a
    # pure function of the data, so identical Redis state -> identical
    # snapshot bytes. Wall clock only when meta wasn't dumped/is absent.
    generated_at = (out.get("meta") or {}).get("loaded_at") or \
        datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "sections": out,
    }


def write_snapshot(snapshot: dict, output: Path) -> None:
    """Write the snapshot as deterministic gzipped JSON (sorted keys,
    gzip mtime=0) via tmp + os.replace, so readers never see a torn file."""
    data = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_bytes(gzip.compress(data, mtime=0))
    os.replace(tmp, output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump the runtime Redis keyspace to a local snapshot file.")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL"),
                        help="Redis connection string (default: $REDIS_URL).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output path (default: {DEFAULT_OUTPUT}).")
    parser.add_argument("--sections", default=",".join(ALL_SECTIONS),
                        help=f"Comma-separated sections (default: all of {ALL_SECTIONS}).")
    parser.add_argument("--source-label", default="dev",
                        help="Label recorded in the snapshot's source field (e.g. prod).")
    args = parser.parse_args()

    if not args.redis_url:
        sys.exit("No --redis-url and no $REDIS_URL set — refusing to guess.")
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    unknown = [s for s in sections if s not in ALL_SECTIONS]
    if unknown:
        sys.exit(f"Unknown section(s): {unknown}. Valid: {ALL_SECTIONS}")

    r = redis.from_url(args.redis_url, decode_responses=True)
    snapshot = dump_sections(r, sections)
    snapshot["source"] = _sanitize_source(args.redis_url, args.source_label)

    output = Path(args.output)
    write_snapshot(snapshot, output)

    sec = snapshot["sections"]
    print(f"Snapshot written to {output} "
          f"({output.stat().st_size:,} bytes gzipped) "
          f"generated_at={snapshot['generated_at']}")
    for name, value in sec.items():
        count = len(value) if isinstance(value, (dict, list)) else 1
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()