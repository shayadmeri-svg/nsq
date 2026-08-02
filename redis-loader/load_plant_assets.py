"""One-time seed loader for the CDMO plant asset registry.

Reads data/plant_assets_seed.json and writes each asset as a Redis HASH under
the cdmo:plant:<asset_id> keyspace. Independent of nsq:* data.

Usage:
    just load-plant-assets
    # or directly:
    redis-loader/.venv/bin/python redis-loader/load_plant_assets.py \
        --input data/plant_assets_seed.json --redis-url "$REDIS_URL" --flush
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine" / "shared"))

from intelligence_models import PlantAsset
from intelligence_store import save_plant_asset


def load(input_path: Path, redis_url: str, flush: bool) -> None:
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    assets = seed.get("assets", [])
    print(f"Read {len(assets)} plant assets from {input_path}")

    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()

    if flush:
        for key in r.scan_iter("cdmo:plant:*"):
            r.delete(key)
        print("Flushed existing cdmo:plant:* keys.")

    loaded = 0
    for raw in assets:
        asset = PlantAsset(**raw)
        save_plant_asset(asset, client=r)
        loaded += 1

    print(f"Loaded {loaded} plant assets into cdmo:plant:*")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/plant_assets_seed.json"), help="Seed JSON file.")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", ""), help="Redis URL.")
    parser.add_argument("--flush", action="store_true", help="Clear existing cdmo:plant:* keys before loading.")
    args = parser.parse_args()

    if not args.redis_url:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)

    load(args.input, args.redis_url, args.flush)


if __name__ == "__main__":
    main()
