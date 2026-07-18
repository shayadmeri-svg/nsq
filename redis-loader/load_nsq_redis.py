"""Load CDSCO publicNsqDrugTable-shaped JSON into Redis.

Expects a local JSON file matching the DataTables response shape used
by https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable :

    {
      "iTotalDisplayRecords": <int>,
      "iTotalRecords": <int>,
      "aaData": [
        {
          "str_product_name": "...",
          "str_batch_no": "...",
          "dt_manufacturing_date": "...",
          "dt_expiry_date": "...",
          "str_manufactured_by": "...",
          "str_nsq_result": "...",
          "str_reporting_source": "...",
          "str_reported_by_lab_or_state": "...",
          "dt_reporting_month_year": "..."
        },
        ...
      ]
    }

This script does NOT fetch that JSON for you. Save the response body
(e.g. via your browser's network tab, or however you're permitted to
obtain it) to a local file and point --input at it.

Redis layout:
  nsq:record:<id>        -> HASH of one row (id = stable hash of batch_no+product_name)
  nsq:records             -> SET of all record ids (index)
  nsq:by_month:<YYYY-MM>  -> SET of record ids reported that month
  nsq:meta                -> HASH: total_records, loaded_at
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis


MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def record_id(row: dict) -> str:
    """Stable id: batch number + product name are the natural key."""
    key = f"{row.get('str_batch_no', '')}|{row.get('str_product_name', '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize_month(raw: str | None) -> str | None:
    """'MAY-2026' -> '2026-05'. Returns None if unparseable."""
    if not raw:
        return None
    parts = raw.strip().upper().split("-")
    if len(parts) != 2:
        return None
    mon, year = parts
    mon = MONTH_MAP.get(mon[:3])
    if not mon or not year.isdigit():
        return None
    return f"{year}-{mon}"


def load(input_path: Path, redis_url: str, flush: bool) -> None:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    rows = data.get("aaData", [])
    if not rows:
        print("No rows found under 'aaData' — nothing to load.", file=sys.stderr)
        sys.exit(1)

    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()

    if flush:
        ids = r.smembers("nsq:records")
        pipe = r.pipeline()
        for rid in ids:
            pipe.delete(f"nsq:record:{rid}")
        pipe.delete("nsq:records")
        for key in r.scan_iter("nsq:by_month:*"):
            pipe.delete(key)
        pipe.execute()

    pipe = r.pipeline()
    loaded = 0
    for row in rows:
        rid = record_id(row)
        pipe.hset(
            f"nsq:record:{rid}",
            mapping={k: ("" if v is None else str(v)) for k, v in row.items()},
        )
        pipe.sadd("nsq:records", rid)
        month = normalize_month(row.get("dt_reporting_month_year"))
        if month:
            pipe.sadd(f"nsq:by_month:{month}", rid)
        loaded += 1

    pipe.hset(
        "nsq:meta",
        mapping={
            "total_records": str(data.get("iTotalRecords", loaded)),
            "loaded_records": str(loaded),
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "source_file": str(input_path),
        },
    )
    pipe.execute()

    print(f"Loaded {loaded} records into Redis at key prefix 'nsq:'.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Path to the JSON file (aaData shape).")
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", ""),
        help="redis://... or rediss://... URL. Defaults to $REDIS_URL.",
    )
    parser.add_argument("--flush", action="store_true", help="Clear existing nsq:* keys before loading.")
    args = parser.parse_args()

    if not args.redis_url:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    load(args.input, args.redis_url, args.flush)


if __name__ == "__main__":
    main()
