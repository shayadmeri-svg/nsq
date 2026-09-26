"""PubChem: chemical structure and measured properties per molecule.

For each molecule in data/generated/candidates.json (and the lab seed list) it
looks up the compound by name (PUG REST) and stores the CID, SMILES, InChIKey,
formula, XLogP3 and TPSA, plus experimental melting points from the compound's
PUG View "Melting Point" section (median of the values given in °C or °F).

The lab computes everything else (descriptors, solubility, BCS class, process
models) from these structures. Biologics have no small-molecule structure in
PubChem and are recorded as such.

Incremental: entries younger than --max-age-days (default 30) are kept; at most
--limit (default 80) molecules are queried per run.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import quote

from .common import Ctx, Unreachable, data_dir, http_get, now_iso, read_normalized, write_normalized

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest"
META = {
    "title": "PubChem",
    "publisher": "U.S. National Library of Medicine (NCBI)",
    "url": f"{BASE}/pug",
    "page": "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest",
    "cadence": "daily, incremental (each molecule refreshed monthly)",
    "feeds": ["Chemical structures (SMILES)", "XLogP3", "Experimental melting points", "Lab models"],
}
PROPS_NEW = "SMILES,ConnectivitySMILES,InChIKey,MolecularFormula,MolecularWeight,XLogP,TPSA,IUPACName"
PROPS_OLD = "IsomericSMILES,CanonicalSMILES,InChIKey,MolecularFormula,MolecularWeight,XLogP,TPSA,IUPACName"
_TEMP = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:-|to|–)?\s*(-?\d+(?:\.\d+)?)?\s*°?\s*(C|F)\b", re.I)


def _json(url: str) -> dict[str, Any]:
    return json.loads(http_get(url, accept="application/json", timeout=60).decode("utf-8"))


def properties(name: str) -> Optional[dict[str, Any]]:
    for props in (PROPS_NEW, PROPS_OLD):
        try:
            d = _json(f"{BASE}/pug/compound/name/{quote(name)}/property/{props}/JSON")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code == 400 and props == PROPS_NEW:  # a property name this PubChem version doesn't know
                continue
            raise
        rows = (d.get("PropertyTable") or {}).get("Properties") or []
        if rows:
            return rows[0]
    return None


def parse_melting_points(section: dict[str, Any]) -> list[float]:
    """All melting points (°C) mentioned in a PUG View 'Melting Point' section."""
    vals: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "Information" in node:
                for info in node["Information"]:
                    v = info.get("Value") or {}
                    if v.get("Number") and v.get("Unit") in ("°C", "deg C"):
                        vals.extend(float(x) for x in v["Number"])
                    for s in v.get("StringWithMarkup") or []:
                        m = _TEMP.search(s.get("String", ""))
                        if m:
                            lo = float(m.group(1))
                            hi = float(m.group(2)) if m.group(2) else lo
                            c = (lo + hi) / 2
                            if m.group(3).upper() == "F":
                                c = (c - 32) * 5 / 9
                            vals.append(c)
            for k in ("Section", "Record"):
                if k in node:
                    walk(node[k])
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(section)
    return [round(v, 1) for v in vals if -50 < v < 450]


def melting_point(cid: int) -> tuple[Optional[float], list[float]]:
    try:
        d = _json(f"{BASE}/pug_view/data/compound/{cid}/JSON?heading=Melting+Point")
    except HTTPError as exc:
        if exc.code in (400, 404):  # no melting point section
            return None, []
        raise
    vals = parse_melting_points(d)
    return (round(statistics.median(vals), 1) if vals else None), vals[:8]


def lookup(names: list[str]) -> dict[str, Any]:
    for n in names:
        p = properties(n)
        if p:
            cid = int(p["CID"])
            smiles = p.get("SMILES") or p.get("IsomericSMILES") or p.get("ConnectivitySMILES") or p.get("CanonicalSMILES")
            mp, mps = melting_point(cid)
            return {"found": True, "query": n, "cid": cid, "smiles": smiles, "inchikey": p.get("InChIKey"),
                    "formula": p.get("MolecularFormula"), "mw": float(p["MolecularWeight"]) if p.get("MolecularWeight") else None,
                    "xlogp": p.get("XLogP"), "tpsa": p.get("TPSA"), "iupac": p.get("IUPACName"), "mp_c": mp, "mp_values": mps,
                    "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}", "fetched_at": now_iso()}
    return {"found": False, "query": names[0] if names else "", "fetched_at": now_iso()}


def _targets() -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    p = data_dir() / "generated" / "candidates.json"
    if p.exists():
        for c in json.loads(p.read_text(encoding="utf-8")):
            out[c["key"]] = {"key": c["key"], "names": c.get("names") or [c["key"]]}
    seed = data_dir() / "structures_seed.json"
    if seed.exists():
        for k, v in json.loads(seed.read_text(encoding="utf-8")).get("molecules", {}).items():
            out.setdefault(k, {"key": k, "names": [v.get("name") or k]})
    if not out:
        raise RuntimeError("No molecules to look up yet: run 'Build molecule universe' first.")
    return list(out.values())


def run(ctx: Ctx) -> int:
    prev = (read_normalized("pubchem") or {}).get("data", {})
    if ctx.from_file:
        data = json.loads(ctx.from_file.read_text(encoding="utf-8"))
        data = data.get("data", data)
        write_normalized(ctx, META, data, len(data))
        return len(data)
    max_age = timedelta(days=int(ctx.options.get("max_age_days", 30)))
    limit = ctx.limit or int(ctx.options.get("limit", 80))
    now = datetime.now(timezone.utc)

    def age(key: str) -> float:
        f = (prev.get(key) or {}).get("fetched_at")
        return (now - datetime.fromisoformat(f)).total_seconds() if f else float("inf")

    targets = _targets()
    if ctx.options.get("missing_only"):
        due = [t for t in targets if t["key"] not in prev]
        if not due:
            ctx.log(f"{len(targets)} molecules, all already looked up")
            return sum(1 for v in prev.values() if v.get("found"))
    else:
        due = sorted([t for t in targets if ctx.force or age(t["key"]) > max_age.total_seconds()], key=lambda t: -age(t["key"]))
    todo = due[:limit]
    ctx.log(f"{len(targets)} molecules, {len(due)} due, looking up {len(todo)} this run")
    data, done = dict(prev), 0
    for i, t in enumerate(todo, 1):
        try:
            r = lookup(t["names"])
            data[t["key"]] = r
            done += 1
            ctx.log(f"  [{i}/{len(todo)}] {t['key']}: " + (f"CID {r['cid']}, {r['formula']}, mp {r['mp_c']} °C" if r["found"] else "not in PubChem (biologic or unknown name)"))
        except Unreachable:
            if done == 0:
                raise
            ctx.log(f"  stopped after {done}: PubChem unreachable")
            break
        except Exception as exc:
            ctx.log(f"  {t['key']}: {exc}")
        time.sleep(float(ctx.options.get("sleep", 0.35)))  # PubChem asks for <= 5 requests/s
    write_normalized(ctx, META, data, sum(1 for v in data.values() if v.get("found")),
                     extra={"queried_this_run": done, "due_remaining": max(0, len(due) - done)})
    return len(data)
