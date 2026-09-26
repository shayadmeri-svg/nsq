"""Fetch one public data source and write its normalised file.

  python fetch_source.py orange_book
  python fetch_source.py ema --from-file ~/Downloads/medicines.json
  python fetch_source.py clinical_trials --limit 50
  python fetch_source.py all                 # every source, keep going on errors
  python fetch_source.py --list

Exit codes: 0 ok, 1 error, 2 source unreachable, 3 unchanged since last fetch
(for 'all': 0 if at least one source succeeded or was unchanged).
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from sources import SOURCES, Ctx  # noqa: E402
from sources.common import (EXIT_ERROR, EXIT_OK, EXIT_UNCHANGED, EXIT_UNREACHABLE, NotFound, NotModified,  # noqa: E402
                            Unreachable, now_iso, update_manifest)


def run_one(name: str, args) -> int:
    spec = SOURCES[name]
    ctx = Ctx(name=name, from_file=Path(args.from_file).expanduser() if args.from_file else None,
              force=args.force, limit=args.limit, options={})
    print(f"▸ {spec['title']} ({spec['publisher']})", flush=True)
    t0 = time.time()
    update_manifest(name, last_attempt=now_iso())
    try:
        n = spec["run"](ctx)
    except NotModified:
        print("  unchanged since the last download", flush=True)
        update_manifest(name, status="unchanged", last_checked=now_iso(), error="")
        return EXIT_UNCHANGED
    except NotFound as exc:
        print(f"  NOT FOUND — the publisher moved or renamed the file: {exc}", file=sys.stderr, flush=True)
        print("  Download it by hand and run this source with the uploaded file (Admin → Pipelines).", file=sys.stderr, flush=True)
        update_manifest(name, status="error", error=f"Not found: {exc}"[:500])
        return EXIT_ERROR
    except Unreachable as exc:
        print(f"  UNREACHABLE: {exc}", file=sys.stderr, flush=True)
        update_manifest(name, status="unreachable", error=str(exc)[:500])
        return EXIT_UNREACHABLE
    except Exception as exc:
        traceback.print_exc()
        update_manifest(name, status="error", error=f"{type(exc).__name__}: {exc}"[:500])
        return EXIT_ERROR
    secs = round(time.time() - t0, 1)
    update_manifest(name, status="ok", last_success=now_iso(), records=n, seconds=secs, error="",
                    mode="file" if ctx.from_file else "download")
    print(f"  ok · {n:,} records · {secs}s", flush=True)
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", nargs="?", help="Source key, or 'all'.")
    ap.add_argument("--from-file", help="Parse a file you downloaded instead of fetching.")
    ap.add_argument("--force", action="store_true", help="Ignore HTTP caching / refresh everything.")
    ap.add_argument("--limit", type=int, help="Per-run cap (clinical_trials).")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list or not args.source:
        for k, v in SOURCES.items():
            print(f"{k:20s} {v['title']} — {v['cadence']}")
        return EXIT_OK
    if args.source == "all":
        if args.from_file:
            print("--from-file needs a single source", file=sys.stderr)
            return EXIT_ERROR
        codes = {k: run_one(k, args) for k in SOURCES}
        print("\nsummary: " + ", ".join(f"{k}={ {0: 'ok', 1: 'error', 2: 'unreachable', 3: 'unchanged'}[c] }" for k, c in codes.items()))
        return EXIT_OK if any(c in (EXIT_OK, EXIT_UNCHANGED) for c in codes.values()) else EXIT_UNREACHABLE
    if args.source not in SOURCES:
        print(f"unknown source {args.source!r}; one of: {', '.join(SOURCES)}", file=sys.stderr)
        return EXIT_ERROR
    return run_one(args.source, args)


if __name__ == "__main__":
    sys.exit(main())
