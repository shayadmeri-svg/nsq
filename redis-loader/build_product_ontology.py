"""One-shot seed: build the product ontology from the CSV in advance.

The analytics app grows the product ontology lazily at first render
(via `resolve_or_create_product()` in `shared/company_ontology.py`).
For a 2,800-row dataset that means ~2,800 per-row Redis HSETs during
the first cache miss — slow over Upstash TLS. This script reads the
CSV in one pass, batches ontology writes into a single pipeline, and
pre-fills `nsq:ontology:products` so the dashboard renders instantly.

Idempotent: re-running just bumps `sources` counts and adds new
aliases. The analytics app's lazy path will continue to add any
product names that appear in future datasets.

Usage:
    just build-product-ontology
    # or directly:
    redis-loader/.venv/bin/python redis-loader/build_product_ontology.py \\
        --input "../data/data Jan25_May26.csv"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# Make the shared/ module importable so we can reuse the resolver.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

import company_ontology  # noqa: E402
import redis  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="CSV file to seed from.")
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", ""),
        help="redis://... or rediss://... URL. Defaults to $REDIS_URL.",
    )
    args = parser.parse_args()

    if not args.redis_url:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Read {len(rows)} rows from {args.input}")

    r = redis.from_url(args.redis_url, decode_responses=True)
    r.ping()

    # Load the existing ontology once into memory so resolve_or_create
    # doesn't have to HGETALL the whole HASH per row.
    existing = r.hgetall(company_ontology.PRODUCT_HASH_KEY)
    cache: dict[str, dict] = {}
    for k, v in existing.items():
        try:
            cache[k] = json.loads(v)
        except json.JSONDecodeError:
            continue
    print(f"Loaded {len(cache)} existing ontology entries")

    new_or_updated: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        raw = (row.get("Name of Product") or "").strip()
        if not raw:
            skipped += 1
            continue
        key = company_ontology.product_key(raw)
        if not key:
            skipped += 1
            continue
        # 1. Exact match in cache
        if key in cache:
            rec = cache[key]
            if raw not in rec.get("aliases", []):
                rec.setdefault("aliases", []).append(raw)
            rec["sources"] = int(rec.get("sources", 0)) + 1
            new_or_updated[key] = rec
            continue
        # 2. Fuzzy match (caller-side loop, since the resolver is per-call)
        thr = company_ontology.FUZZY_THRESHOLD
        best_key, best_score = company_ontology._best_product_match(key, cache)
        if best_key and best_score >= thr:
            rec = cache[best_key]
            if raw not in rec.get("aliases", []):
                rec.setdefault("aliases", []).append(raw)
            rec["sources"] = int(rec.get("sources", 0)) + 1
            new_or_updated[best_key] = rec
            continue
        # 3. New entity
        new_rec = {
            "canonical_name": raw,
            "canonical_key":  key,
            "aliases":        [raw],
            "sources":        1,
        }
        cache[key] = new_rec
        new_or_updated[key] = new_rec

    # Single-pipeline flush
    pipe = r.pipeline()
    for k, rec in new_or_updated.items():
        pipe.hset(
            company_ontology.PRODUCT_HASH_KEY,
            mapping={k: json.dumps(rec, ensure_ascii=False)},
        )
    pipe.hset(
        company_ontology.PRODUCT_META_HASH_KEY,
        mapping={
            "entry_count":  str(len(cache)),
            "last_updated": company_ontology.datetime.now(company_ontology.timezone.utc).isoformat(),
            "version":      str(company_ontology.ONTOLOGY_VERSION),
        },
    )
    pipe.execute()

    print(
        f"Seeded {len(new_or_updated)} updated entries "
        f"(total {len(cache)} in ontology). "
        f"Skipped {skipped} empty rows."
    )


if __name__ == "__main__":
    main()
