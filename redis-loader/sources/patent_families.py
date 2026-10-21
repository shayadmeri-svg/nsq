"""Google Patents: the compound patent family behind each molecule, and its legal status country by country.

Anchors come from the FDA Orange Book, never from a hand list: for every molecule in the universe, the
patents the Orange Book flags as *drug substance* (up to 4, the ones expiring within the last 8 years or
later). For each anchor this fetches the Google Patents page and keeps:

    number, title, assignee, priority / filing date, US adjusted expiry, legal status, url

and, for the anchor with the earliest priority date (the compound patent), its family:

    international_filing   the PCT filing date (from the WO publication) — the date India, Brazil and
                           South Africa count their 20-year term from
    countries: {EP|JP|CA|AU|BR|MX|ZA|CN|KR|IN|GB: {number, status, expiration, url}}
                           each family member's own legal status page
    spcs: [{number, country, url}]  supplementary protection certificates listed in the family

core/patent_terms.py turns these facts into a per-market status with the statute it relied on.

Google Patents has no API; pages are cached under data/raw/patent_families/ for 30 days and fetched at most
one a second. Incremental: --limit molecules per run (default 40).
"""

from __future__ import annotations

import html as _html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .common import Ctx, Unreachable, data_dir, http_get, now_iso, read_normalized, write_normalized

META = {
    "title": "Google Patents (patent families)",
    "publisher": "Google (family and legal-status data from EPO DOCDB / INPADOC)",
    "url": "https://patents.google.com/",
    "page": "https://patents.google.com/",
    "cadence": "weekly, incremental (each family refreshed every 30 days)",
    "feeds": ["Compound patent titles", "Per-country patent status and expiry", "SPCs", "India / Brazil / South Africa term rule"],
}
TARGETS = ("EP", "JP", "CA", "AU", "BR", "MX", "ZA", "CN", "KR", "IN", "GB")
_SPC = re.compile(r"^(?:[A-Z]{2}\d{2,4}C\d{2,}|LUC\d+|HUS\d+|LTPA\d+|LTC\d+|DKCA\d+|DKCR\d+|NL3\d{5}|BE\d{4}C\d+|FR\d{2}C\d+)",
                  re.I)
_KIND_SPC = re.compile(r"I[12]$")


def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", s or "")).strip()


def page(ctx: Ctx, number: str) -> Optional[str]:
    """The Google Patents page for a publication number, from the 30-day cache or the web."""
    dest = ctx.raw_dir / f"{number}.html"
    if dest.exists() and not ctx.force and (time.time() - dest.stat().st_mtime) < 30 * 86400:
        return dest.read_text(encoding="utf-8", errors="replace")
    try:
        raw = http_get(f"https://patents.google.com/patent/{number}/en", timeout=60, retries=1)
    except Unreachable:
        raise
    except Exception:
        return None
    time.sleep(float(ctx.options.get("sleep", 1.0)))
    text = raw.decode("utf-8", errors="replace")
    if "itemprop" not in text:
        return None
    dest.write_text(text, encoding="utf-8")
    return text


def parse(number: str, h: str) -> dict[str, Any]:
    def first(rx: str) -> Optional[str]:
        m = re.search(rx, h, flags=re.S)
        return _clean(m.group(1)) if m else None

    countries = {}
    for code, pub in re.findall(r'itemprop="countryStatus".*?itemprop="countryCode">(\w+)</span>.*?itemprop="representativePublication">([^<]+)<',
                                h, flags=re.S):
        countries.setdefault(code, pub.strip())
    family = re.findall(r'itemprop="docdbFamily".*?itemprop="publicationNumber">([^<]+)<.*?itemprop="publicationDate">([^<]+)<', h, flags=re.S)
    spcs = [{"number": n.strip(), "country": n.strip()[:2], "date": d.strip(), "url": f"https://patents.google.com/patent/{n.strip()}/en"}
            for n, d in family if _SPC.match(n.strip()) or _KIND_SPC.search(n.strip())]
    spcs += [{"number": p, "country": c, "date": None, "url": f"https://patents.google.com/patent/{p}/en"}
             for c, p in countries.items() if (_SPC.match(p) or _KIND_SPC.search(p)) and p not in {s["number"] for s in spcs}]
    wo = next((p for c, p in countries.items() if c == "WO"), None) or next((n.strip() for n, _ in family if n.startswith("WO")), None)
    return {
        "number": number, "url": f"https://patents.google.com/patent/{number}/en",
        "title": first(r'itemprop="title"[^>]*>([^<]+)<'),
        "assignee": first(r'itemprop="assigneeOriginal"[^>]*>([^<]+)<'),
        "status": first(r'itemprop="status"[^>]*>([^<]+)<'),
        "expiration": first(r'itemprop="expiration"[^>]*datetime="([\d-]+)"'),
        "priority": first(r'itemprop="priorityDate"[^>]*datetime="([\d-]+)"'),
        "filing": first(r'itemprop="filingDate"[^>]*datetime="([\d-]+)"'),
        "countries": countries, "wo": wo, "spcs": spcs,
    }


def _us_number(no: str) -> str:
    """Orange Book patent number -> Google Patents publication number (kind code resolved by redirect).
    Reissues keep their prefix: RE47739 -> USRE47739. Pediatric-exclusivity rows ('*PED') are not patents."""
    no = (no or "").strip().upper()
    if "*" in no:
        return ""
    m = re.match(r"^(RE|PP|D)?0*(\d+)$", no)
    return f"US{m.group(1) or ''}{m.group(2)}" if m else ""


# Titles of later drug-substance patents (a salt, crystal form, formulation) rather than the compound itself.
_LATER_FORM = re.compile(r"\b(salt|crystal|crystalline|polymorph|solid form|amorphous|hydrate|solvate|formulation|composition|"
                         r"dosage|dosing|regimen|administration|tablet|capsule|process|preparation|method of treat|use of|uses? thereof)", re.I)


def _ob_index():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from build_universe import Sources  # the builder's own Orange Book matching, so the two agree

    return Sources()


def _targets() -> list[dict[str, Any]]:
    p = data_dir() / "generated" / "patents.json"
    if not p.exists():
        raise RuntimeError("No molecule universe yet: run 'Build molecule universe' first.")
    rows = json.loads(p.read_text(encoding="utf-8")).get("molecules", [])
    return [{"key": m["molecule_key"], "names": [m.get("api_name") or m["molecule_key"], *(m.get("aliases") or [])]} for m in rows]


def family_for(ctx: Ctx, ob_patents: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    cutoff = (date.today() - timedelta(days=8 * 365)).isoformat()
    subst = sorted([p for p in ob_patents if p.get("substance") and "*" not in (p.get("no") or "") and (p.get("expires") or "") >= cutoff],
                   key=lambda p: p.get("expires") or "")[:5]
    if not subst:
        return None
    anchors = []
    for p in subst:
        num = _us_number(p["no"])
        h = page(ctx, num)
        if not h:
            continue
        rec = parse(num, h)
        rec["ob_expires"] = p.get("expires")
        anchors.append(rec)
    if not anchors:
        return None
    # The compound patent: the earliest priority among the patents whose titles don't describe a later form.
    compound = [a for a in anchors if not _LATER_FORM.search(a.get("title") or "")]
    anchor = min(compound or anchors, key=lambda a: a.get("priority") or "9999")
    if compound and anchor.get("priority"):  # the compound family: same priority era as the anchor (continuations, PTE)
        y0 = int(anchor["priority"][:4])
        compound = [a for a in compound if a.get("priority") and int(a["priority"][:4]) <= y0 + 2]
    out: dict[str, Any] = {"anchor": {k: anchor.get(k) for k in ("number", "url", "title", "assignee", "status", "expiration",
                                                                  "priority", "filing", "ob_expires")},
                           "substance_patents": [{k: a.get(k) for k in ("number", "url", "title", "assignee", "priority", "filing",
                                                                         "expiration", "status", "ob_expires")} for a in anchors],
                           "spcs": anchor.get("spcs") or [], "countries": {}, "international_filing": None, "wo": anchor.get("wo"),
                           # False when every Orange Book drug-substance patent is a later form (salt, crystal, formulation):
                           # its family then says nothing about the molecule itself.
                           "anchor_is_compound": bool(compound),
                           # latest Orange Book expiry among the compound-type patents (one may carry a term extension)
                           "compound_expires": max((a.get("ob_expires") or "" for a in compound), default="") or None,
                           "compound_patents": [{k: a.get(k) for k in ("number", "title", "ob_expires", "url")} for a in compound]}
    if anchor.get("wo"):
        h = page(ctx, anchor["wo"])
        if h:
            out["international_filing"] = parse(anchor["wo"], h).get("filing")
    for code in TARGETS:
        pub = (anchor.get("countries") or {}).get(code)
        if not pub or _SPC.match(pub) or _KIND_SPC.search(pub):
            continue
        h = page(ctx, pub)
        if not h:
            continue
        m = parse(pub, h)
        out["countries"][code] = {"number": pub, "status": m.get("status"), "expiration": m.get("expiration"),
                                  "filing": m.get("filing"), "url": m["url"]}
    return out


def run(ctx: Ctx) -> int:
    prev = (read_normalized("patent_families") or {}).get("data", {})
    if ctx.from_file:
        data = json.loads(ctx.from_file.read_text(encoding="utf-8"))
        data = data.get("data", data)
        write_normalized(ctx, META, data, len(data))
        return len(data)
    src = _ob_index()
    limit = ctx.limit or int(ctx.options.get("limit", 40))
    now = datetime.now(timezone.utc)

    def stale(key: str) -> bool:
        f = (prev.get(key) or {}).get("fetched_at")
        return ctx.force or not f or (now - datetime.fromisoformat(f)) > timedelta(days=30)

    todo = []
    for t in _targets():
        ob = src.ob(t["names"])
        pats = (ob or {}).get("patents") or []
        if any(p.get("substance") for p in pats) and stale(t["key"]):
            todo.append((t, pats))
    ctx.log(f"{len(todo)} molecules with Orange Book drug-substance patents due; fetching {min(limit, len(todo))}")
    data, done = dict(prev), 0
    for i, (t, pats) in enumerate(todo[:limit], 1):
        try:
            fam = family_for(ctx, pats)
        except Unreachable:
            if done == 0:
                raise
            ctx.log(f"  stopped after {done}: Google Patents unreachable")
            break
        except Exception as exc:
            ctx.log(f"  {t['key']}: {exc}")
            continue
        if fam:
            data[t["key"]] = {**fam, "fetched_at": now_iso()}
            done += 1
            a = fam["anchor"]
            ctx.log(f"  [{i}] {t['key']}: {a['number']} '{(a.get('title') or '')[:60]}' priority {a.get('priority')} · "
                    f"PCT {fam.get('international_filing') or '—'} · {len(fam['countries'])} countries · {len(fam['spcs'])} SPCs")
    write_normalized(ctx, META, data, len(data), extra={"queried_this_run": done})
    return len(data)
