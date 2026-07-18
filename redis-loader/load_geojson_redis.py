"""Push a GeoJSON file into Redis as a single string key, so it doesn't
need to live in the repo as a checked-in file.

Redis layout:
  geo:india_states -> STRING (raw GeoJSON, gzip-compressed + base64 by default)
  geo:india_states:meta -> HASH: size_bytes, loaded_at, source_file

Usage:
    python load_geojson_redis.py --input ../analytics/india_states_slim.geojson \
        --redis-url "$REDIS_URL" --key geo:india_states
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis


def load(input_path: Path, redis_url: str, key: str, compress: bool) -> None:
    raw_text = input_path.read_text(encoding="utf-8")

    # Validate it's actually JSON/GeoJSON before pushing.
    try:
        json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"{input_path} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    r = redis.from_url(redis_url, decode_responses=False)
    r.ping()

    if compress:
        payload = base64.b64encode(gzip.compress(raw_text.encode("utf-8")))
        encoding = "gzip+base64"
    else:
        payload = raw_text.encode("utf-8")
        encoding = "raw"

    pipe = r.pipeline()
    pipe.set(key, payload)
    pipe.hset(
        f"{key}:meta",
        mapping={
            "size_bytes": str(len(raw_text.encode("utf-8"))),
            "stored_bytes": str(len(payload)),
            "encoding": encoding,
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "source_file": str(input_path),
        },
    )
    pipe.execute()

    print(f"Stored {input_path} ({len(raw_text):,} chars) in Redis at '{key}' (encoding={encoding}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Path to the .geojson file.")
    parser.add_argument("--key", default="geo:india_states", help="Redis key to store the payload under.")
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", ""),
        help="redis://... or rediss://... URL. Defaults to $REDIS_URL.",
    )
    parser.add_argument("--no-compress", action="store_true", help="Store raw JSON instead of gzip+base64.")
    args = parser.parse_args()

    if not args.redis_url:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    load(args.input, args.redis_url, args.key, compress=not args.no_compress)


if __name__ == "__main__":
    main()
