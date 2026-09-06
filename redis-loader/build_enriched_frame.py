#!/usr/bin/env python3
"""Pre-compute the enriched NSQ frame and store it in Redis.

WHY THIS EXISTS
---------------
`data_loader._load_and_preprocess()` is the expensive step in the whole
platform: it reads every nsq:record:*, joins the company ontology, and walks
all ~5,600 rows through `resolve_or_create_product()`, which fuzzy-matches
each product name. That used to run at page-render time inside Streamlit,
behind a 5-minute cache. Measured on the deployed t3.micro:

    first paint, cold cache .... 33.5 s
    first paint, warm cache .... 13.4 s
    (DOM itself was ready in 0.6 s — the wait was all this)

The enrichment is a pure function of the nsq:* keyspace, so it does not
belong in a render path at all. This script computes it once and writes it
to `nsq:frame:enriched` (gzipped parquet, base64) plus a meta hash. The apps
read it with a single GET.

WHEN TO RUN IT
--------------
After anything that changes nsq:record:* — `just reload-csv`,
`just refresh-csv`, a CDSCO fetch. `just refresh-csv` chains it for you.
Forgetting is safe but slow: the meta carries the record count it was built
from, and `load_enriched_frame()` returns None when that no longer matches,
so the apps fall back to computing rather than serving a stale frame.

USAGE
    just build-frame              # runs inside the analytics image
    # or, in an environment that has pandas + pyarrow + rapidfuzz:
    python3 build_enriched_frame.py --redis-url "$REDIS_URL"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# shared/ lives one level up; the analytics image ships it at /app/shared.
_HERE = Path(__file__).resolve().parent
for candidate in (_HERE.parent / "shared", Path("/app/shared")):
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))
        break

import data_loader  # noqa: E402
import nsq_redis  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL"),
                    help="Redis connection string (defaults to $REDIS_URL).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Build and report, but do not write to Redis.")
    args = ap.parse_args()

    if not args.redis_url:
        print("ERROR: no --redis-url and no $REDIS_URL set.", file=sys.stderr)
        return 2
    os.environ["REDIS_URL"] = args.redis_url

    client = nsq_redis.get_redis_client(args.redis_url)

    t0 = time.perf_counter()
    df = data_loader._load_and_preprocess()
    build_s = time.perf_counter() - t0

    if df.empty:
        print("ERROR: the enriched frame came back empty — is nsq:records "
              "populated? Nothing written.", file=sys.stderr)
        return 1

    print(f"built:   {len(df):,} rows x {len(df.columns)} cols in {build_s:.1f}s")

    if args.dry_run:
        print("dry-run: not written.")
        return 0

    t1 = time.perf_counter()
    meta = data_loader.save_enriched_frame(df, client=client)
    write_s = time.perf_counter() - t1

    stored_mb = int(meta["stored_bytes"]) / 1e6
    print(f"stored:  {stored_mb:.2f} MB at '{data_loader.ENRICHED_FRAME_KEY}' "
          f"in {write_s:.1f}s (record_count={meta['record_count']})")

    # Prove the round-trip works before declaring success — a frame that
    # cannot be read back is worse than none, because the apps would keep
    # silently falling back to the slow path.
    t2 = time.perf_counter()
    back = data_loader.load_enriched_frame(client=client)
    read_s = time.perf_counter() - t2
    if back is None or len(back) != len(df):
        print("ERROR: wrote the frame but could not read it back intact.",
              file=sys.stderr)
        return 1
    print(f"verify:  read back {len(back):,} rows in {read_s:.2f}s "
          f"(was {build_s:.1f}s to compute — {build_s / max(read_s, 0.01):.0f}x faster)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
