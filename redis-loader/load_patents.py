"""One-time seed loader for the CDMO patent intelligence registry.

Reads data/patent_seed.json and writes each molecule as a Redis HASH under
the cdmo:patent:<molecule_key> keyspace. The keyspace is independent of the
existing nsq:* data so the loader is safe to run alongside the NSQ loaders.

Usage:
    just load-patents
    # or directly:
    redis-loader/.venv/bin/python redis-loader/load_patents.py \
        --input data/patent_seed.json --redis-url "$REDIS_URL" --flush
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine" / "shared"))

from intelligence_models import PatentEntry, PatentIntelligence
from intelligence_store import save_patent


def _parse_month(v: str | None) -> date | None:
    from datetime import date as _date

    if not v:
        return None
    if isinstance(v, str) and v.count("-") == 1:
        year, month = v.split("-")
        return _date(int(year), int(month), 1)
    if isinstance(v, str):
        return _date.fromisoformat(v)
    return None


def _parse_patent_entry(raw: dict) -> PatentEntry:
    expiry_raw = raw.get("expiry_date")
    expiry = _parse_month(expiry_raw) if expiry_raw else None
    return PatentEntry(
        description=raw.get("description", ""),
        expiry_date=expiry,
        jurisdiction=raw.get("jurisdiction", "global"),
        risk_level=raw.get("risk_level", "medium"),
    )


def _parse_geo_coverage(raw: dict):
    from intelligence_models import GeoCoverage

    return GeoCoverage(
        country_code=raw.get("country_code", ""),
        country_name=raw.get("country_name", ""),
        market_status=raw.get("market_status", "patented"),
        loe_date=_parse_month(raw.get("loe_date")),
        export_eligible=bool(raw.get("export_eligible", False)),
        patent_barrier=raw.get("patent_barrier", "none"),
        notes=raw.get("notes", ""),
    )


def load(input_path: Path, redis_url: str, flush: bool) -> None:
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    molecules = seed.get("molecules", [])
    print(f"Read {len(molecules)} molecules from {input_path}")

    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()

    if flush:
        for key in r.scan_iter("cdmo:patent:*"):
            r.delete(key)
        print("Flushed existing cdmo:patent:* keys.")

    loaded = 0
    for raw in molecules:
        entry = PatentIntelligence(
            molecule_key=raw["molecule_key"],
            brand_name=raw["brand_name"],
            api_name=raw["api_name"],
            therapeutic_area=raw["therapeutic_area"],
            originator=raw["originator"],
            estimated_loe_us=_parse_month(raw.get("estimated_loe_us")),
            estimated_loe_eu=_parse_month(raw.get("estimated_loe_eu")),
            estimated_loe_in=_parse_month(raw.get("estimated_loe_in")),
            market_size_usd_bn=raw.get("market_size_usd_bn"),
            formulation_patents=[_parse_patent_entry(p) for p in raw.get("formulation_patents", [])],
            process_patents=[_parse_patent_entry(p) for p in raw.get("process_patents", [])],
            secondary_patents=[_parse_patent_entry(p) for p in raw.get("secondary_patents", [])],
            geo_coverage=[_parse_geo_coverage(g) for g in raw.get("geo_coverage", [])],
            fto_risk=raw.get("fto_risk", "medium"),
            notes=raw.get("notes", ""),
            source_url=raw.get("source_url", ""),
        )
        save_patent(entry, client=r)
        loaded += 1

    print(f"Loaded {loaded} patent records into cdmo:patent:*")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/patent_seed.json"), help="Seed JSON file.")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", ""), help="Redis URL.")
    parser.add_argument("--flush", action="store_true", help="Clear existing cdmo:patent:* keys before loading.")
    args = parser.parse_args()

    if not args.redis_url:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)

    load(args.input, args.redis_url, args.flush)


if __name__ == "__main__":
    main()
