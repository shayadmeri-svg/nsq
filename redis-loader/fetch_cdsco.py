"""Fetch the live CDSCO NSQ drug table and save it as local JSON.

Hits https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable directly (it's a
plain GET returning the same DataTables-shaped JSON that load_nsq_redis.py
expects — see that file's docstring for the shape).

Usage:
    python fetch_cdsco.py --output data/publicNsqDrugTable.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CDSCO_URL = "https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable"


def fetch(url: str, timeout: int) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (nsq-platform fetcher)"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=CDSCO_URL, help="Endpoint to fetch (default: CDSCO public NSQ table).")
    parser.add_argument("--output", required=True, type=Path, help="Where to write the JSON.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    args = parser.parse_args()

    try:
        data = fetch(args.url, args.timeout)
    except (HTTPError, URLError) as exc:
        print(f"Failed to fetch {args.url}: {exc}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Response from {args.url} was not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    rows = data.get("aaData", [])
    if not rows:
        print("Fetched response but 'aaData' was empty — refusing to overwrite existing file.", file=sys.stderr)
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fetched {len(rows)} records -> {args.output}")


if __name__ == "__main__":
    main()
