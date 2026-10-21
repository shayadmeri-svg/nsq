"""EDQM Knowledge Database: the European Pharmacopoeia monograph behind each molecule, and how it has changed.

The Knowledge Database is EDQM's free public lookup (no monograph text — that is the paid Ph. Eur.). For each
molecule in data/generated/candidates.json it searches by name, keeps the monographs whose English name is the
molecule or one of its salts, and for each keeps:

    number, name, status, last published (supplement / issue), ongoing revision (state, Pharmeuropa issue,
    EDQM's description of what is being revised), ICH Q4B interchangeability, pharmacopoeial harmonisation,
    reference standards (CRS) on sale, and the revision history: per supplement / issue, which sections changed
    and EDQM's one-line description of the change.

Implementation dates come from EDQM's published schedule (SCHEDULE below, transcribed from the PDF linked there):
from the 13th Edition each issue is published at least nine months before it applies, so a revision in an issue
whose date is still ahead is an *upcoming* change. Issues before 13.1 carry no date here (the schedule document
does not list them); they are shown by number only.

Pages are cached under data/raw/edqm_kd/ for 30 days and fetched at most two a second.
"""

from __future__ import annotations

import html as _html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

from .common import Ctx, Unreachable, http_get, now_iso, read_normalized, write_normalized
from .pubchem import _targets

BASE = "https://extranet.edqm.eu"
META = {
    "title": "EDQM Knowledge Database (Ph. Eur. monographs)",
    "publisher": "European Directorate for the Quality of Medicines & HealthCare (Council of Europe)",
    "url": f"{BASE}/publications/recherches_sw.shtml",
    "page": f"{BASE}/publications/recherches_sw.shtml",
    "cadence": "weekly, incremental (each molecule refreshed every 30 days)",
    "feeds": ["Ph. Eur. monograph status and ongoing revisions", "Revision history per supplement / issue", "Upcoming changes with implementation dates"],
}
SCHEDULE_SOURCE = {
    "label": "EDQM — European Pharmacopoeia publication schedule, 13th–15th Editions (2025)",
    "url": "https://www.edqm.eu/documents/52006/2305027/European+Pharmacopoeia+-+Publication+schedule.pdf/6097d4d8-88a9-bf58-4a30-d17a20f4836f",
    "note": "Publication dates depend on Ph. Eur. Commission sessions and may change. From Issue 13.1 texts are published at least nine months before implementation.",
}
# issue: (Commission session, publication month, implementation date) — transcribed from SCHEDULE_SOURCE
SCHEDULE = {
    "13.1": ("183 / November 2025", "2026-04", "2027-01-01"), "13.2": ("184 / March 2026", "2026-07", "2027-04-01"),
    "13.3": ("185 / June 2026", "2026-10", "2027-07-01"), "14.1": ("186 / November 2026", "2027-04", "2028-01-01"),
    "14.2": ("187 / March 2027", "2027-07", "2028-04-01"), "14.3": ("188 / June 2027", "2027-10", "2028-07-01"),
    "15.1": ("189 / November 2027", "2028-04", "2029-01-01"), "15.2": ("190 / March 2028", "2028-07", "2029-04-01"),
    "15.3": ("191 / June 2028", "2028-10", "2029-07-01"),
}
_SALTS = r"\b(hcl|hbr|besylate|mesylate|tosylate|hydrochloride|dihydrochloride|hydrobromide|sodium|potassium|calcium|magnesium|besilate|mesilate|maleate|fumarate|tartrate|" \
         r"succinate|citrate|sulfate|sulphate|phosphate|acetate|monohydrate|dihydrate|trihydrate|hemihydrate|sesquihydrate|anhydrous|" \
         r"hyclate|bromide|chloride|nitrate|lactate|gluconate|tosilate|camsilate|dipropionate|propionate|valerate|" \
         r"medoxomil|axetil|proxetil|pivoxil|disodium|and|for|injection|tablets|capsules|oral|solution|suspension)\b|\(.*?\)|,"


def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _get(ctx: Ctx, path: str, cache_name: str) -> str:
    dest = ctx.raw_dir / cache_name
    if dest.exists() and not ctx.force and (time.time() - dest.stat().st_mtime) < 30 * 86400:
        return dest.read_text(encoding="utf-8", errors="replace")
    raw = http_get(f"{BASE}{path}", timeout=60, retries=1).decode("utf-8", errors="replace")
    time.sleep(float(ctx.options.get("sleep", 0.5)))
    dest.write_text(raw, encoding="utf-8")
    return raw


def search(ctx: Ctx, name: str) -> list[tuple[str, str]]:
    h = _get(ctx, f"/4DLink1/4DCGI/Query_SW?vSelectName=1&vContains=1&vtsubName={quote(name)}&SWTP=1&OK=Search",
             f"q_{re.sub(r'[^a-z0-9]+', '_', name.lower())}.html")
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", h, flags=re.S):
        c = [_clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.S)]
        if len(c) >= 2 and c[0].isdigit():
            out.append((c[0], c[1]))
    return out


def _base(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(_SALTS, " ", name.lower())).strip()


def parse_detail(h: str) -> dict[str, Any]:
    """Label / value pairs, row by row (labels sit inside nested <b>/<span>/<font> tags)."""
    fields: dict[str, str] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, flags=re.S):
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        while cells and not cells[0]:  # some rows start with an empty spacer cell
            cells = cells[1:]
        if len(cells) >= 2 and cells[0] and cells[0] not in fields:
            fields[cells[0]] = cells[1]
    crs = re.findall(r"crs\.edqm\.eu/db/4DCGI/View=(\w+)", h)
    revising = (fields.get("On-going") or "").lower().startswith("revision")
    return {"status": fields.get("Status"), "last_published": fields.get("Last published in English"),
            "pharmeuropa": fields.get("Pharmeuropa") or None, "revision_in_progress": revising,
            "revision_state": fields.get("State of work") if revising else None,
            "revision": (fields.get("Description") or None) if revising else None, "ich_q4b": fields.get("Interchangeable (ICH_Q4B)"),
            "harmonised": fields.get("Pharmacopoeial harmonisation"), "reference_standards": len(set(crs))}


def parse_history(h: str) -> list[dict[str, Any]]:
    """[{issue, kind (supplement|issue|edition), changes: [{section, text}]}], newest first as EDQM lists them."""
    out = []
    blocks = re.split(r"(?=<b>\s*(?:SUPPLEMENT|ISSUE|EDITION)\s)", h, flags=re.I)
    for b in blocks:
        m = re.match(r"<b>\s*(SUPPLEMENT|ISSUE|EDITION)\s+([\d.]+)\s*</b>", b, flags=re.I)
        if not m:
            continue
        body = b[m.end():]
        changes = []
        for sec, text in re.findall(r"<b>([^<]+)</b>\s*:?\s*(.*?)(?=<b>|</p>|$)", body, flags=re.S):
            t = _clean(text).lstrip(": ").strip()
            if _clean(sec) and t:
                changes.append({"section": _clean(sec), "text": t})
        if not changes:
            t = _clean(body).lstrip(": ").strip()
            if t:
                changes.append({"section": "", "text": t})
        out.append({"issue": m.group(2).strip(), "kind": m.group(1).lower(), "changes": changes[:12]})
    return out


def dated(entry: dict[str, Any], today: Optional[str] = None) -> dict[str, Any]:
    """Implementation date and status from the published schedule; issues before 13.1 are left undated."""
    today = today or datetime.now(timezone.utc).date().isoformat()
    s = SCHEDULE.get(entry["issue"])
    if not s:
        return {**entry, "implementation": None, "published": None, "state": "earlier"}
    return {**entry, "published": s[1], "implementation": s[2], "session": s[0],
            "state": "upcoming" if s[2] > today else "in_force"}


def lookup(ctx: Ctx, names: list[str]) -> dict[str, Any]:
    seen: dict[str, str] = {}
    for n in names:
        base = _base(n)
        if not base:
            continue
        for num, eng in search(ctx, base.split()[0]):
            if _base(eng) == base:  # the molecule itself or one of its salts / hydrates
                seen.setdefault(num, eng)
        if seen:
            break
    mons = []
    for num, eng in list(seen.items())[:5]:
        det = parse_detail(_get(ctx, f"/4DLink1/4DCGI/Web_View/mono/{num}", f"mono_{num}.html"))
        hist = [dated(e) for e in parse_history(_get(ctx, f"/4DLink1/Web_mono_hist?{num}", f"hist_{num}.html"))]
        mons.append({"number": num.zfill(5), "name": eng, **det, "history": hist,
                     "url": f"{BASE}/4DLink1/4DCGI/Web_View/mono/{num}", "history_url": f"{BASE}/4DLink1/Web_mono_hist?{num}"})
    return {"found": bool(mons), "query": names[0] if names else "", "monographs": mons, "fetched_at": now_iso()}


def run(ctx: Ctx) -> int:
    import ingredients as ing  # core/

    prev = (read_normalized("edqm_kd") or {}).get("data", {})
    if ctx.from_file:
        data = json.loads(ctx.from_file.read_text(encoding="utf-8"))
        data = data.get("data", data)
        write_normalized(ctx, META, data, len(data), extra={"schedule": SCHEDULE, "schedule_source": SCHEDULE_SOURCE})
        return len(data)
    limit = ctx.limit or int(ctx.options.get("limit", 200))
    now = datetime.now(timezone.utc)

    def stale(key: str) -> bool:
        f = (prev.get(key) or {}).get("fetched_at")
        return ctx.force or not f or (now - datetime.fromisoformat(f)) > timedelta(days=30)

    targets = _targets()
    due = [t for t in targets if t["key"] not in prev] if ctx.options.get("missing_only") else [t for t in targets if stale(t["key"])]
    todo = due[:limit]
    ctx.log(f"{len(targets)} molecules, {len(due)} due, looking up {len(todo)} this run")
    data, done = dict(prev), 0
    for i, t in enumerate(todo, 1):
        names = list(dict.fromkeys([*t["names"], *(ing.us_name(ing.ingredient_key(n)) for n in t["names"])]))
        try:
            r = lookup(ctx, [n for n in names if n])
            data[t["key"]] = r
            done += 1
            if r["found"]:
                up = [f"{m['number']} {e['issue']}" for m in r["monographs"] for e in m["history"] if e["state"] == "upcoming"]
                ctx.log(f"  [{i}/{len(todo)}] {t['key']}: " + ", ".join(f"{m['number']} {m['name']} ({m['status']}, last {m['last_published']})"
                                                               for m in r["monographs"]) + (f" · UPCOMING {', '.join(up)}" if up else ""))
            else:
                ctx.log(f"  [{i}/{len(todo)}] {t['key']}: no Ph. Eur. monograph")
        except Unreachable:
            if done == 0:
                raise
            ctx.log(f"  stopped after {done}: EDQM unreachable")
            break
        except Exception as exc:
            ctx.log(f"  {t['key']}: {exc}")
    write_normalized(ctx, META, data, sum(1 for v in data.values() if v.get("found")),
                     extra={"queried_this_run": done, "schedule": SCHEDULE, "schedule_source": SCHEDULE_SOURCE})
    return len(data)
