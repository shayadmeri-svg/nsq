"""ChEMBL: first approval year, development phase, molecule type and WHO ATC class per molecule.

For each molecule in data/generated/candidates.json it finds the ChEMBL record — by the PubChem InChIKey
when PubChem has the structure (exact), else by preferred name — and climbs to the parent compound (a salt's
record carries no approval year; its parent does). It keeps:

    chembl_id, pref_name, first_approval (year, earliest approval anywhere as ChEMBL records it), max_phase,
    molecule_type (Small molecule / Protein / Antibody / ...), oral / parenteral / topical flags,
    atc: [{code, level1..level4 descriptions}], url

These replace two hand-made inputs: the therapeutic area (was a name-suffix guess, now the WHO ATC class)
and the patent age rule's approval year (core/patent_terms.py).

Incremental like PubChem: entries younger than 60 days are kept; at most --limit (default 120) per run.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import quote

from .common import Ctx, Unreachable, http_get, now_iso, read_normalized, write_normalized
from .pubchem import _targets

BASE = "https://www.ebi.ac.uk/chembl/api/data"
META = {
    "title": "ChEMBL",
    "publisher": "EMBL-EBI",
    "url": BASE,
    "page": "https://www.ebi.ac.uk/chembl/",
    "licence": "CC BY-SA 3.0",
    "cadence": "weekly, incremental (each molecule refreshed every 60 days)",
    "feeds": ["First approval year (patent age rule)", "WHO ATC therapeutic class", "Molecule type"],
}
_FIELDS = ("molecule_chembl_id", "pref_name", "first_approval", "max_phase", "molecule_type", "oral", "parenteral", "topical",
           "atc_classifications", "molecule_hierarchy", "black_box_warning", "withdrawn_flag")
_atc_cache: dict[str, dict[str, Any]] = {}


def _get(path: str) -> dict[str, Any]:
    return json.loads(http_get(f"{BASE}/{path}", accept="application/json", timeout=60).decode("utf-8"))


def _by_inchikey(ik: str) -> Optional[dict[str, Any]]:
    d = _get(f"molecule.json?molecule_structures__standard_inchi_key={quote(ik)}&limit=1")
    rows = d.get("molecules") or []
    return rows[0] if rows else None


def _by_name(name: str) -> Optional[dict[str, Any]]:
    d = _get(f"molecule.json?pref_name__iexact={quote(name)}&limit=1")
    rows = d.get("molecules") or []
    if rows:
        return rows[0]
    d = _get(f"molecule/search.json?q={quote(name)}&limit=5")
    rows = [m for m in d.get("molecules") or [] if m.get("max_phase") not in (None, "")]
    rows.sort(key=lambda m: -float(m.get("max_phase") or 0))
    return rows[0] if rows else None


def _parent(m: dict[str, Any]) -> dict[str, Any]:
    pid = (m.get("molecule_hierarchy") or {}).get("parent_chembl_id")
    if pid and pid != m.get("molecule_chembl_id"):
        try:
            return _get(f"molecule/{pid}.json")
        except HTTPError:
            return m
    return m


def _atc(code: str) -> dict[str, Any]:
    if code not in _atc_cache:
        try:
            d = _get(f"atc_class/{code}.json")
        except HTTPError:
            d = {}
        _atc_cache[code] = {"code": code, **{f"level{i}": d.get(f"level{i}_description") for i in range(1, 5)}}
    return _atc_cache[code]


def _score(m: dict[str, Any]) -> tuple:
    """Prefer the approved medicine record: an approval year, phase 4, an ATC code."""
    return (bool(m.get("first_approval")), float(m.get("max_phase") or 0), bool(m.get("atc_classifications")))


def lookup(names: list[str], inchikey: Optional[str]) -> dict[str, Any]:
    cands: list[tuple[dict[str, Any], str]] = []
    if inchikey:
        hit = _by_inchikey(inchikey)
        if hit:
            cands.append((_parent(hit), "InChIKey (PubChem structure)"))
    if not cands or not _score(cands[0][0])[0]:
        # a stereo-variant or salt record carries no approval: the name finds the medicine itself
        for n in names:
            hit = _by_name(n)
            if hit:
                cands.append((_parent(hit), f"name '{n}'"))
                break
    if not cands:
        return {"found": False, "query": names[0] if names else "", "fetched_at": now_iso()}
    m, how = max(cands, key=lambda c: _score(c[0]))
    salt = m
    first = m.get("first_approval")
    codes = list(dict.fromkeys((m.get("atc_classifications") or []) + (salt.get("atc_classifications") or [])))[:4]
    return {"found": True, "matched_by": how, "chembl_id": m.get("molecule_chembl_id"), "pref_name": m.get("pref_name"),
            "salt_chembl_id": salt.get("molecule_chembl_id") if salt is not m else None,
            "first_approval": int(first) if first else None, "max_phase": float(m.get("max_phase") or 0) or None,
            "molecule_type": m.get("molecule_type"), "oral": m.get("oral"), "parenteral": m.get("parenteral"), "topical": m.get("topical"),
            "black_box_warning": bool(int(m.get("black_box_warning") or 0)), "withdrawn": bool(m.get("withdrawn_flag")),
            "atc": [_atc(c) for c in codes],
            "url": f"https://www.ebi.ac.uk/chembl/explore/compound/{m.get('molecule_chembl_id')}", "fetched_at": now_iso()}


def run(ctx: Ctx) -> int:
    prev = (read_normalized("chembl") or {}).get("data", {})
    pubchem = (read_normalized("pubchem") or {}).get("data", {})
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

    targets = _targets()
    if ctx.options.get("missing_only"):
        due = [t for t in targets if t["key"] not in prev]
    else:
        due = sorted([t for t in targets if ctx.force or age(t["key"]) > max_age.total_seconds()], key=lambda t: -age(t["key"]))
    todo = due[:limit]
    ctx.log(f"{len(targets)} molecules, {len(due)} due, looking up {len(todo)} this run")
    data, done = dict(prev), 0
    for i, t in enumerate(todo, 1):
        try:
            ik = (pubchem.get(t["key"]) or {}).get("inchikey")
            r = lookup(t["names"], ik)
            data[t["key"]] = r
            done += 1
            ctx.log(f"  [{i}/{len(todo)}] {t['key']}: " + (f"{r['chembl_id']} · first approval {r['first_approval']} · "
                                                         f"{', '.join(a['code'] for a in r['atc']) or 'no ATC'} · by {r['matched_by']}"
                                                         if r["found"] else "not in ChEMBL"))
        except Unreachable:
            if done == 0:
                raise
            ctx.log(f"  stopped after {done}: ChEMBL unreachable")
            break
        except Exception as exc:
            ctx.log(f"  {t['key']}: {exc}")
        time.sleep(float(ctx.options.get("sleep", 0.2)))
    write_normalized(ctx, META, data, sum(1 for v in data.values() if v.get("found")),
                     extra={"queried_this_run": done, "due_remaining": max(0, len(due) - done), "licence": META["licence"]})
    return len(data)
