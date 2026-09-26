"""ClinicalTrials.gov (API v2) — trial pipeline per molecule.

For each molecule in data/generated/candidates.json (written by
build_universe.py) it asks four counts:

  total        all studies with the molecule as an intervention
  phase3plus   AREA[Phase](PHASE3 OR PHASE4)
  recent       started in the last 3 years
  india        with a site in India

Incremental: molecules refreshed within --max-age-days (default 7) are kept
from the previous run, and at most --limit molecules (default 120) are queried
per run, oldest first, so a daily schedule walks the whole universe weekly.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .common import Ctx, Unreachable, data_dir, http_get, now_iso, read_normalized, write_normalized

API = "https://clinicaltrials.gov/api/v2/studies"
META = {
    "title": "ClinicalTrials.gov",
    "publisher": "U.S. National Library of Medicine",
    "url": API,
    "page": "https://clinicaltrials.gov/data-api/api",
    "cadence": "daily, incremental (each molecule refreshed weekly)",
    "feeds": ["Trial counts", "Phase 3+ pipeline", "Recent trial momentum", "India trial sites"],
}


def _count(term: str, **extra: str) -> int:
    params = {"query.intr": term, "countTotal": "true", "pageSize": "1", "fields": "NCTId", **extra}
    raw = http_get(API, params=params, accept="application/json", timeout=60)
    return int(json.loads(raw.decode("utf-8")).get("totalCount") or 0)


def query_molecule(names: list[str]) -> dict[str, Any]:
    term = " OR ".join(sorted({n for n in names if n}))
    since = (date.today() - timedelta(days=3 * 365)).isoformat()
    return {
        "term": term,
        "total": _count(term),
        "phase3plus": _count(term, **{"filter.advanced": "AREA[Phase](PHASE3 OR PHASE4)"}),
        "recent": _count(term, **{"filter.advanced": f"AREA[StartDate]RANGE[{since},MAX]"}),
        "india": _count(term, **{"query.locn": "India"}),
        "fetched_at": now_iso(),
    }


def _candidates() -> list[dict[str, Any]]:
    p = data_dir() / "generated" / "candidates.json"
    if not p.exists():
        raise RuntimeError("No molecule candidates yet — run 'Build molecule universe' (build_universe.py) first.")
    return json.loads(p.read_text(encoding="utf-8"))


def run(ctx: Ctx) -> int:
    prev = (read_normalized("clinical_trials") or {}).get("data", {})
    if ctx.from_file:
        data = json.loads(ctx.from_file.read_text(encoding="utf-8"))
        data = data.get("data", data)
        write_normalized(ctx, META, data, len(data))
        return len(data)

    max_age = timedelta(days=int(ctx.options.get("max_age_days", 7)))
    limit = ctx.limit or int(ctx.options.get("limit", 120))
    now = datetime.now(timezone.utc)
    cands = _candidates()

    def age(key: str) -> float:
        f = (prev.get(key) or {}).get("fetched_at")
        if not f:
            return float("inf")
        return (now - datetime.fromisoformat(f)).total_seconds()

    due = [c for c in cands if ctx.force or age(c["key"]) > max_age.total_seconds()]
    due.sort(key=lambda c: -age(c["key"]))
    todo = due[:limit]
    ctx.log(f"{len(cands)} molecules, {len(due)} due, querying {len(todo)} this run")
    data = dict(prev)
    done = 0
    for c in todo:
        try:
            data[c["key"]] = query_molecule(c.get("names") or [c["key"]])
            done += 1
        except Unreachable:
            if done == 0:
                raise
            ctx.log(f"  stopped after {done}: ClinicalTrials.gov unreachable")
            break
        except Exception as exc:  # one bad term should not sink the run
            ctx.log(f"  {c['key']}: {exc}")
        if done % 20 == 0 and done:
            ctx.log(f"  {done}/{len(todo)}")
        time.sleep(float(ctx.options.get("sleep", 0.6)))
    keep = {c["key"] for c in cands}
    data = {k: v for k, v in data.items() if k in keep}
    write_normalized(ctx, META, data, len(data), extra={"queried_this_run": done, "due_remaining": max(0, len(due) - done)})
    return len(data)
