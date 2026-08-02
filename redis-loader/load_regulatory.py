"""One-time seed loader for the CDMO regulatory passport registry.

Reads data/regulatory_seed.json and writes each molecule as a Redis HASH under
the cdmo:regulatory:<molecule_key> keyspace. The keyspace is independent of the
existing nsq:* and cdmo:patent:* data so the loader is safe to run alongside
other CDMO loaders.

Usage:
    just load-regulatory
    # or directly:
    redis-loader/.venv/bin/python redis-loader/load_regulatory.py \
        --input data/regulatory_seed.json --redis-url "$REDIS_URL" --flush
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine" / "shared"))

from intelligence_models import RegulatoryPassport
from intelligence_store import save_regulatory


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, str) and v.count("-") == 2:
        return date.fromisoformat(v)
    if isinstance(v, str) and v.count("-") == 1:
        year, month = v.split("-")
        return date(int(year), int(month), 1)
    return None


def _parse_exclusivity(items):
    """Return exclusivity entries as dicts, parsing ISO dates into date objects."""
    out = []
    for raw in items:
        out.append(
            {
                "type": raw.get("type", ""),
                "expiry_date": _parse_date(raw.get("expiry_date")),
                "description": raw.get("description", ""),
            }
        )
    return out


def load(input_path: Path, redis_url: str, flush: bool) -> None:
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    passports = seed.get("passports", [])
    print(f"Read {len(passports)} regulatory passports from {input_path}")

    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()

    if flush:
        for key in r.scan_iter("cdmo:regulatory:*"):
            r.delete(key)
        print("Flushed existing cdmo:regulatory:* keys.")

    loaded = 0
    for raw in passports:
        passport = RegulatoryPassport(
            molecule_key=raw["molecule_key"],
            ip_2026_monograph=raw.get("ip_2026_monograph", ""),
            ph_eur_monograph=raw.get("ph_eur_monograph", ""),
            usp_monograph=raw.get("usp_monograph", ""),
            analytical_specs=raw.get("analytical_specs", []),
            stability_conditions=raw.get("stability_conditions", ""),
            bcs_class=raw.get("bcs_class", ""),
            rld=raw.get("rld", ""),
            rld_applicant=raw.get("rld_applicant", ""),
            te_code=raw.get("te_code", ""),
            te_rating=raw.get("te_rating", ""),
            dosage_form=raw.get("dosage_form", ""),
            strength=raw.get("strength", ""),
            exclusivity=_parse_exclusivity(raw.get("exclusivity", [])),
            bioequivalence_notes=raw.get("bioequivalence_notes", ""),
            readiness=raw.get("readiness", "partial"),
            source_url=raw.get("source_url", ""),
            notes=raw.get("notes", ""),
        )
        save_regulatory(passport, client=r)
        loaded += 1

    print(f"Loaded {loaded} regulatory passports into cdmo:regulatory:*")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/regulatory_seed.json"), help="Seed JSON file.")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", ""), help="Redis URL.")
    parser.add_argument("--flush", action="store_true", help="Clear existing cdmo:regulatory:* keys before loading.")
    args = parser.parse_args()

    if not args.redis_url:
        print("No Redis URL given. Set REDIS_URL or pass --redis-url.", file=sys.stderr)
        sys.exit(1)

    load(args.input, args.redis_url, args.flush)


if __name__ == "__main__":
    main()
