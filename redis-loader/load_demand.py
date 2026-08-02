"""One-time seed loader for the CDMO demand signal registry.

Reads data/demand_seed.json and writes each molecule as a Redis HASH under
the cdmo:demand:<molecule_key> keyspace. The keyspace is independent of the
existing nsq:* and cdmo:* data so the loader is safe to run alongside other
CDMO loaders.

Usage:
    just load-demand
    # or directly:
    redis-loader/.venv/bin/python redis-loader/load_demand.py \
        --input data/demand_seed.json --redis-url "$REDIS_URL" --flush
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine" / "shared"))

from intelligence_models import DemandProfile
from intelligence_store import save_demand


def _float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def _int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (ValueError, TypeError):
        return 0


def load(input_path: Path, redis_url: str, flush: bool) -> None:
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    profiles = seed.get("profiles", [])
    print(f"Read {len(profiles)} demand profiles from {input_path}")

    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()

    if flush:
        for key in r.scan_iter("cdmo:demand:*"):
            r.delete(key)
        print("Flushed existing cdmo:demand:* keys.")

    loaded = 0
    for raw in profiles:
        profile = DemandProfile(
            molecule_key=raw["molecule_key"],
            disease_area=raw.get("disease_area", ""),
            disease_prevalence_global_millions=_float(raw.get("disease_prevalence_global_millions")),
            disease_prevalence_india_millions=_float(raw.get("disease_prevalence_india_millions")),
            growth_trend=raw.get("growth_trend", "stable"),
            trial_count_total=_int(raw.get("trial_count_total")),
            trial_count_phase_3_plus=_int(raw.get("trial_count_phase_3_plus")),
            cluster=raw.get("cluster", ""),
            buyer_activity_score=_float(raw.get("buyer_activity_score")),
            competitor_anda_count=_int(raw.get("competitor_anda_count")),
            market_momentum_score=_float(raw.get("market_momentum_score")),
            notes=raw.get("notes", ""),
            source_url=raw.get("source_url", ""),
        )
        save_demand(profile, client=r)
        loaded += 1

    print(f"Loaded {loaded} demand profiles into cdmo:demand:*")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/demand_seed.json"), help="Seed JSON file.")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", ""), help="Redis URL.")
    parser.add_argument("--flush", action="store_true", help="Clear existing cdmo:demand:* keys before loading.")
    args = parser.parse_args()

    if not args.redis_url:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)

    load(args.input, args.redis_url, args.flush)


if __name__ == "__main__":
    main()
