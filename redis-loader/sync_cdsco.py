"""Keep the cumulative CDSCO NSQ CSV current — no hand downloads.

1. If the cumulative CSV does not exist, rebuild it from the records already
   in Redis (e.g. after "Restore from snapshot"), so a fresh box or a clone
   without the gitignored CSV still has a source of truth.
2. Fetch the live CDSCO NSQ table (cdscoonline.gov.in/CDSCO/publicNsqDrugTable,
   which returns the latest notification month) — or read a saved JSON with
   --from-json — convert the rows to the CSV's columns, and append the ones
   not already present (same record_id as load_csv_redis.py uses).
3. Write the CSV atomically and save the raw download under data/raw/cdsco/.

Loading the CSV into Redis is left to load_csv_redis.py (the refresh job and
`just fetch-nsq` chain both).

Usage:
  python sync_cdsco.py --csv "../data/CDSCO ... .csv" --redis-url redis://localhost:6379/0
  python sync_cdsco.py --csv ... --bootstrap-only      # only rebuild a missing CSV
  python sync_cdsco.py --csv ... --from-json saved.json

Exit codes: 0 ok (including "nothing new"), 1 error, 2 CDSCO unreachable.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_csv_redis import CSV_TO_CDSCO, MONTH_MAP, _row_to_cdsco, record_id  # noqa: E402

CDSCO_URL = "https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable"
CDSCO_SOURCE = "https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug"
COLUMNS = list(CSV_TO_CDSCO.keys())  # Index, Name of Product, ..., Source
CDSCO_TO_CSV = {v: k for k, v in CSV_TO_CDSCO.items()}
_MONTH_TITLE = {v: k.title() for k, v in MONTH_MAP.items()}


def _month_title(raw: str) -> str:
    """'AUG-2026' / 'aug-2026' -> 'Aug-2026' (the CSV's spelling)."""
    raw = (raw or "").strip()
    parts = raw.split("-")
    if len(parts) == 2 and parts[0][:3].upper() in MONTH_MAP:
        return f"{parts[0][:3].title()}-{parts[1]}"
    return raw


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".csv.tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def rows_from_redis(redis_url: str) -> list[dict]:
    import redis

    r = redis.from_url(redis_url, decode_responses=True)
    ids = sorted(r.smembers("nsq:records"))
    out: list[dict] = []
    pipe = r.pipeline(transaction=False)
    for rid in ids:
        pipe.hgetall(f"nsq:record:{rid}")
    for rec in pipe.execute():
        if rec:
            out.append({CDSCO_TO_CSV[k]: v for k, v in rec.items() if k in CDSCO_TO_CSV})

    def _key(row):
        m = (row.get("Reporting Month & Year") or "").strip()
        parts = m.split("-")
        ym = f"{parts[1]}-{MONTH_MAP.get(parts[0][:3].upper(), '00')}" if len(parts) == 2 else m
        return (ym, row.get("Index") or "")

    out.sort(key=_key)
    return out


def rows_from_cdsco(payload: dict) -> list[dict]:
    rows = []
    for rec in payload.get("aaData") or []:
        row = {CDSCO_TO_CSV[k]: str(v if v is not None else "").strip() for k, v in rec.items() if k in CDSCO_TO_CSV}
        row["Reporting Month & Year"] = _month_title(row.get("Reporting Month & Year", ""))
        row.setdefault("Source", CDSCO_SOURCE)
        if not row.get("Source"):
            row["Source"] = CDSCO_SOURCE
        if row.get("Name of Product"):
            rows.append(row)
    return rows


def fetch(url: str, timeout: int) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (nsq-platform sync)", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", required=True, type=Path, help="Cumulative CSV (created if missing).")
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL"), help="Redis to rebuild a missing CSV from.")
    ap.add_argument("--url", default=CDSCO_URL)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--from-json", type=Path, help="Use a saved CDSCO JSON instead of fetching.")
    ap.add_argument("--raw-dir", type=Path, default=None, help="Where to keep raw downloads (default data/raw/cdsco).")
    ap.add_argument("--bootstrap-only", action="store_true", help="Only rebuild a missing CSV from Redis.")
    args = ap.parse_args()

    # 1. Make sure the cumulative CSV exists.
    if args.csv.exists():
        rows = read_csv(args.csv)
        print(f"cumulative CSV: {args.csv.name} — {len(rows):,} rows")
    else:
        if not args.redis_url:
            print(f"ERROR: {args.csv} not found and no --redis-url/REDIS_URL to rebuild it from.", file=sys.stderr)
            return 1
        rows = rows_from_redis(args.redis_url)
        if not rows:
            print("ERROR: CSV missing and Redis has no NSQ records. Run 'Restore from snapshot' or 'Pull from Upstash' first.", file=sys.stderr)
            return 1
        write_csv(args.csv, rows)
        print(f"rebuilt {args.csv.name} from Redis — {len(rows):,} rows")
    if args.bootstrap_only:
        return 0

    # 2. Get the latest CDSCO month.
    raw_dir = args.raw_dir or (args.csv.parent / "raw" / "cdsco")
    if args.from_json:
        payload = json.loads(args.from_json.read_text(encoding="utf-8"))
        print(f"read {args.from_json}")
    else:
        print(f"fetching {args.url}")
        try:
            payload = fetch(args.url, args.timeout)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"CDSCO unreachable: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"CDSCO returned non-JSON: {exc}", file=sys.stderr)
            return 1
        raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (raw_dir / f"publicNsqDrugTable-{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    fetched = rows_from_cdsco(payload)
    months = sorted({r.get("Reporting Month & Year", "") for r in fetched})
    print(f"CDSCO rows: {len(fetched):,} for {', '.join(months) or '—'}")

    # 3. Append the new ones.
    seen = {record_id(_row_to_cdsco(r)) for r in rows}
    next_index = len(rows) + 1
    added = 0
    for r in fetched:
        rid = record_id(_row_to_cdsco(r))
        if rid in seen:
            continue
        seen.add(rid)
        r["Index"] = str(next_index)
        next_index += 1
        rows.append(r)
        added += 1
    if added:
        write_csv(args.csv, rows)
    print(f"added {added:,} new alert(s); cumulative CSV now {len(rows):,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
