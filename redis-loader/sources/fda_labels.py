"""FDA drug labels (openFDA): excipients and pharmacokinetics per molecule, quoted from the label.

For each molecule in data/generated/candidates.json it finds single-ingredient prescription labels on
openFDA (generic name equal to the molecule, not a combination), preferring the reference product's own
label (an NDA) over generics (ANDAs), and keeps from up to three labels:

    set_id, brand, manufacturer, application_number, effective_time, DailyMed url
    inactive_ingredients   the label's own list ("Inactive ingredients: ..."), per label — real excipients
    pk                     numbers the label states, each with the sentence it came from:
                           half_life_h, vd_l (or vd_l_kg), f_pct, tmax_h, cl_l_h

Nothing is filled in: a value the label does not state is absent. The Lab uses these for the
bioequivalence model's PK inputs; Investigate shows the excipients next to the NSQ failures.

Incremental: entries younger than 60 days are kept; at most --limit (default 120) per run.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import quote

from .common import Ctx, Unreachable, http_get, now_iso, read_normalized, write_normalized
from .pubchem import _targets

BASE = "https://api.fda.gov/drug/label.json"
META = {
    "title": "FDA drug labels (openFDA)",
    "publisher": "U.S. Food and Drug Administration",
    "url": BASE,
    "page": "https://open.fda.gov/apis/drug/label/",
    "cadence": "weekly, incremental (each molecule refreshed every 60 days)",
    "feeds": ["Excipients of marketed products", "Half-life, volume of distribution, bioavailability, Tmax (BE model)"],
}
_NUM = r"(\d+(?:\.\d+)?)"
_RANGE = rf"{_NUM}\s*(?:(?:to|-|–|and)\s*{_NUM}\s*)?"
_TIME_UNIT = r"(hours?|hrs?|h|minutes?|min|days?)\b"
PATTERNS = {
    "half_life": re.compile(rf"half-?\s?life[^.;]{{0,90}}?{_RANGE}{_TIME_UNIT}", re.I),
    "vd": re.compile(rf"volume of distribution[^.;]{{0,90}}?{_RANGE}(L/kg|liters?/kg|litres?/kg|L|liters?|litres?)\b", re.I),
    "f": re.compile(rf"(?:absolute|oral|systemic)?\s*bioavailability[^.;]{{0,70}}?{_RANGE}%", re.I),
    "tmax": re.compile(rf"(?:peak|maximum|T\s?max|C\s?max)[^.;]{{0,80}}?(?:reached|achieved|occur\w*|attained|observed|within|at)[^.;]{{0,30}}?{_RANGE}{_TIME_UNIT}", re.I),
    "cl": re.compile(rf"(?:total|plasma|systemic|apparent|oral)?\s*clearance[^.;]{{0,70}}?{_RANGE}(mL/min/kg|L/h/kg|L/hr/kg|mL/min|L/h|L/hr)\b", re.I),
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])", re.sub(r"\s+", " ", text or "")) if s.strip()]


def _hours(v: float, unit: str) -> float:
    u = unit.lower()
    return v / 60 if u.startswith("min") else v * 24 if u.startswith("day") else v


def _mid(m: re.Match) -> float:
    a = float(m.group(1))
    b = float(m.group(2)) if m.group(2) else None
    return (a + b) / 2 if b else a


def parse_pk(text: str) -> dict[str, Any]:
    """Numbers stated in a label's pharmacokinetics section, each with its sentence (first match wins)."""
    out: dict[str, Any] = {}
    for s in _sentences(text):
        if "half_life_h" not in out and (m := PATTERNS["half_life"].search(s)):
            v = _hours(_mid(m), m.group(3))
            if 0.05 <= v <= 2000:
                out["half_life_h"] = {"value": round(v, 3), "text": s[:400]}
        if "vd_l" not in out and "vd_l_kg" not in out and (m := PATTERNS["vd"].search(s)):
            unit = m.group(3).lower()
            key = "vd_l_kg" if "/kg" in unit else "vd_l"
            out[key] = {"value": round(_mid(m), 3), "text": s[:400]}
        if "f_pct" not in out and (m := PATTERNS["f"].search(s)):
            v = _mid(m)
            if 0 < v <= 100 and "reduc" not in s[:m.start()].lower()[-40:]:
                out["f_pct"] = {"value": round(v, 1), "text": s[:400]}
        if "tmax_h" not in out and (m := PATTERNS["tmax"].search(s)):
            v = _hours(_mid(m), m.group(3))
            if 0.05 <= v <= 48:
                out["tmax_h"] = {"value": round(v, 3), "text": s[:400]}
        if "cl" not in out and (m := PATTERNS["cl"].search(s)):
            out["cl"] = {"value": round(_mid(m), 3), "unit": m.group(3), "text": s[:400]}
    return out


_INACTIVE = re.compile(r"inactive ingredients?(?: (?:are|include|consist of))?[^:]{0,60}:\s*(.+?)(?:\.\s+[A-Z]|$)", re.I)


def parse_inactive(rec: dict[str, Any]) -> list[str]:
    texts = (rec.get("inactive_ingredient") or []) + (rec.get("description") or [])
    for t in texts:
        t = re.sub(r"\s+", " ", t)
        m = _INACTIVE.search(t) or (re.match(r"(?:INACTIVE INGREDIENTS?:?\s*)?(.+)", t, re.I) if t in (rec.get("inactive_ingredient") or []) else None)
        if not m:
            continue
        body = re.sub(r"\b(?:and|or)\b", ",", m.group(1))
        items = [re.sub(r"^\W+|\W+$", "", x).strip() for x in body.split(",")]
        items = [x for x in items if 2 < len(x) < 60 and not re.search(r"\d+\s*mg\b", x, re.I)]
        if items:
            return list(dict.fromkeys(i.lower() for i in items))[:30]
    return []


def _search(field: str, name: str, limit: int = 25) -> list[dict[str, Any]]:
    q = f'{field}:"{name}"'
    try:
        d = json.loads(http_get(f"{BASE}?search={quote(q)}&limit={limit}", accept="application/json", timeout=60).decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    return d.get("results") or []


def lookup(names: list[str]) -> dict[str, Any]:
    def single(r: dict[str, Any], target: str) -> bool:
        """One active ingredient: the molecule itself or one of its salts ('DICLOFENAC SODIUM'), never a combination."""
        g = [x.upper() for x in (r.get("openfda") or {}).get("generic_name") or []]
        return len(g) == 1 and (g[0] == target or (g[0].startswith(target + " ") and not re.search(r"\bAND\b|,|/", g[0])))

    def rank(r: dict[str, Any]) -> tuple:
        o = r.get("openfda") or {}
        return (str((o.get("route") or [""])[0]).upper() != "ORAL", not str((o.get("application_number") or [""])[0]).startswith("NDA"),
                not r.get("pharmacokinetics"), -int(r.get("effective_time") or 0))

    for n in names:
        target = n.strip().upper()
        rows = [r for r in _search("openfda.generic_name", target, limit=50) if single(r, target)]
        if not rows:
            continue
        rows.sort(key=rank)
        labels = []
        for r in rows[:3]:
            o = r.get("openfda") or {}
            labels.append({
                "set_id": r.get("set_id"), "brand": (o.get("brand_name") or [""])[0], "manufacturer": (o.get("manufacturer_name") or [""])[0],
                "application_number": (o.get("application_number") or [""])[0], "effective_time": r.get("effective_time"),
                "route": (o.get("route") or [""])[0], "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={r.get('set_id')}",
                "inactive_ingredients": parse_inactive(r),
                "pk": parse_pk(" ".join((r.get("pharmacokinetics") or []) + (r.get("clinical_pharmacology") or []))),
            })
        pk = next((lab["pk"] for lab in labels if lab["pk"]), {})
        pk_from = next((lab for lab in labels if lab["pk"]), None)
        return {"found": True, "query": target, "labels": labels, "pk": pk,
                "pk_label": {k: pk_from[k] for k in ("brand", "manufacturer", "application_number", "url")} if pk_from else None,
                "fetched_at": now_iso()}
    return {"found": False, "query": names[0] if names else "", "fetched_at": now_iso()}


def run(ctx: Ctx) -> int:
    prev = (read_normalized("fda_labels") or {}).get("data", {})
    if ctx.from_file:
        data = json.loads(ctx.from_file.read_text(encoding="utf-8"))
        data = data.get("data", data)
        write_normalized(ctx, META, data, len(data))
        return len(data)
    max_age = timedelta(days=int(ctx.options.get("max_age_days", 60)))
    limit = ctx.limit or int(ctx.options.get("limit", 120))
    now = datetime.now(timezone.utc)

    def age(key: str) -> float:
        f = (prev.get(key) or {}).get("fetched_at")
        return (now - datetime.fromisoformat(f)).total_seconds() if f else float("inf")

    import ingredients as ing  # core/

    targets = _targets()
    due = [t for t in targets if t["key"] not in prev] if ctx.options.get("missing_only") else \
        sorted([t for t in targets if ctx.force or age(t["key"]) > max_age.total_seconds()], key=lambda t: -age(t["key"]))
    todo = due[:limit]
    ctx.log(f"{len(targets)} molecules, {len(due)} due, looking up {len(todo)} this run")
    data, done = dict(prev), 0
    for i, t in enumerate(todo, 1):
        names = list(dict.fromkeys([*t["names"], *(ing.us_name(ing.ingredient_key(n)) for n in t["names"])]))
        try:
            r = lookup([n for n in names if n])
            data[t["key"]] = r
            done += 1
            if r["found"]:
                lab = r["labels"][0]
                ctx.log(f"  [{i}/{len(todo)}] {t['key']}: {lab['brand']} ({lab['application_number']}) · "
                        f"{len(lab['inactive_ingredients'])} excipients · PK {', '.join(r['pk']) or 'none stated'}")
            else:
                ctx.log(f"  [{i}/{len(todo)}] {t['key']}: no single-ingredient US label")
        except Unreachable:
            if done == 0:
                raise
            ctx.log(f"  stopped after {done}: openFDA unreachable")
            break
        except Exception as exc:
            ctx.log(f"  {t['key']}: {exc}")
        time.sleep(float(ctx.options.get("sleep", 0.3)))  # openFDA: 240 requests/min without a key
    write_normalized(ctx, META, data, sum(1 for v in data.values() if v.get("found")), extra={"queried_this_run": done})
    return len(data)
