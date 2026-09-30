"""PubChem: chemical structure and measured properties per molecule.

For each molecule in data/generated/candidates.json (and the lab seed list) it
looks up the compound by name (PUG REST) and stores the CID, SMILES, InChIKey,
formula, XLogP3 and TPSA, plus experimental melting points from the compound's
PUG View "Melting Point" section (median of the values given in °C or °F).

It also keeps the compound's experimental "Solubility" (water only),
"Dissociation Constants" (pKa) and "LogP" entries from PUG View, each with
the raw text and the citation PubChem gives for it (Record.Reference:
SourceName + URL, matched by ReferenceNumber), under `exp`:

    exp = {"solubility_water_mg_ml": {value, t_c, text, source, url} | None,
           "solubility_texts": [{text, source, url}],   # qualitative / other solvents, kept for reading
           "pka": [{value, kind: "acid" | "base" | None, text, source, url}],
           "logp": {value, text, source, url} | None}

Entries fetched before this existed simply have no `exp`.

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
    "feeds": ["Chemical structures (SMILES)", "XLogP3", "Experimental melting points",
              "Experimental water solubility, pKa and log P (with citations)", "Lab models"],
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


# --- experimental properties from PUG View (solubility, pKa, log P) -------------------------------

def references(doc: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """ReferenceNumber -> {source, url} from a PUG View record."""
    rec = doc.get("Record", doc) if isinstance(doc, dict) else {}
    out = {}
    for r in rec.get("Reference") or []:
        if r.get("ReferenceNumber") is not None:
            out[int(r["ReferenceNumber"])] = {"source": r.get("SourceName") or r.get("Name"), "url": r.get("URL")}
    return out


def information(doc: dict[str, Any], heading: Optional[str] = None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(Information, citation) pairs under a TOC heading (anywhere in the record)."""
    refs = references(doc)
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def walk(node: Any, inside: bool) -> None:
        if isinstance(node, dict):
            here = inside or heading is None or node.get("TOCHeading") == heading
            if here and "Information" in node:
                for info in node["Information"]:
                    out.append((info, refs.get(int(info.get("ReferenceNumber", -1)), {"source": None, "url": None})))
            for k in ("Section", "Record"):
                if k in node:
                    walk(node[k], here)
        elif isinstance(node, list):
            for x in node:
                walk(x, inside)

    walk(doc, False)
    return out


def _text(info: dict[str, Any]) -> str:
    v = info.get("Value") or {}
    parts = [s.get("String", "") for s in v.get("StringWithMarkup") or []]
    if v.get("Number") is not None:
        nums = " ".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v["Number"])
        parts.append(f"{nums} {v.get('Unit') or ''}".strip())
    return " ".join(p for p in parts if p).strip()


_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(?:(?:[x×*]|X)\s*10\s*\^?\s*([+\-−]?\s*\d+)|[eE]([+\-]?\d+))?"
_OTHER_SOLVENT = re.compile(
    r"\b(ethanol|alcohol|methanol|acetone|chloroform|ether|benzene|toluene|hexane|heptane|dmso|dimethyl|octanol|"
    r"glycerol|propylene|oil|acid|alkali|hydroxide|naoh|hcl|buffer|ph\s*\d|acetonitrile|dichloromethane|"
    r"ethyl acetate|pyridine|isopropanol|propanol|butanol|dioxane|carbon tetrachloride|solvents?)\b", re.I)
_TEMP_C = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°|deg\.?|degrees?)\s*C\b", re.I)
# unit -> factor to mg/mL
_UNITS = [
    (r"(?:µ|u|mc|micro)g\s*/\s*L", 1e-6), (r"(?:µ|u|mc|micro)g\s*/\s*mL", 1e-3), (r"mg\s*/\s*L", 1e-3),
    (r"g\s*/\s*L", 1.0), (r"mg\s*/\s*mL", 1.0), (r"mg\s*/\s*(?:100\s*mL|dL)", 1e-2), (r"g\s*/\s*100\s*(?:mL|g|cc)", 10.0),
    (r"g\s*/\s*mL", 1000.0), (r"mg\s*/\s*cc", 1.0), (r"ppm", 1e-3),
]


def _num(m: re.Match, i: int = 1) -> float:
    v = float(m.group(i).replace(",", ""))
    exp = m.group(i + 1) or m.group(i + 2)
    if exp:
        v *= 10 ** int(exp.replace(" ", "").replace("−", "-"))
    return v


def parse_water_solubility(text: str) -> Optional[dict[str, Any]]:
    """mg/mL (and temperature, if stated) from one PubChem solubility string; None if it isn't a
    quantitative water value (other solvents, buffers, qualitative terms only)."""
    t = " ".join(text.replace("\u00a0", " ").split())
    clauses = [c.strip() for c in re.split(r";|\.\s+(?=[A-Z])", t) if c.strip()]
    water = [c for c in clauses if re.search(r"\bwater\b|\bH2O\b", c, re.I)]
    cands = water or [c for c in clauses if not _OTHER_SOLVENT.search(c)]
    for c in cands:
        # "In water, X" is fine; "in water and ethanol" or "in pH 7 buffer" is not
        if _OTHER_SOLVENT.search(c):
            continue
        temp = _TEMP_C.search(c)
        t_c = float(temp.group(1)) if temp else None
        m = re.search(r"1\s*g\s+(?:dissolves\s+)?in\s+(?:about\s+|approx\.?\s+|approximately\s+|ca\.?\s+)?" + _NUM
                      + r"\s*(?:mL|ml|cc)\b", c, re.I)
        if m:
            return {"value": 1000.0 / _num(m), "t_c": t_c}
        for pat, factor in _UNITS:
            m = re.search(_NUM + r"\s*" + pat + r"(?![A-Za-z])", c, re.I)
            if m:
                return {"value": _num(m) * factor, "t_c": t_c}
    return None


def parse_pka(text: str) -> list[dict[str, Any]]:
    """pKa values (with acid/base kind when the text says) from one PubChem string."""
    out = []
    for seg in re.split(r";|,\s*(?=pKa)", text):
        for m in re.finditer(r"pKa\s*\d?\s*(?:\([^)]*\))?\s*(?:=|:|of|is|~|≈)?\s*(-?\d+(?:\.\d+)?)", seg, re.I):
            v = float(m.group(1))
            if not -3 <= v <= 16:
                continue
            tail = seg[m.end():m.end() + 60].lower() + " " + seg[:m.start()].lower()
            kind = None
            if re.search(r"conjugate acid|amine|amino|basic|\bbase\b|pyridin|imidazol|piperazin|protonated|nh\+|guanid|amidin", tail):
                kind = "base"
            elif re.search(r"carboxyl|acidic|\bacid\b|phenol|cooh|sulfonamide|tetrazol|enol|hydroxyl", tail):
                kind = "acid"
            out.append({"value": v, "kind": kind})
    if not out:  # a bare number under the "Dissociation Constants" heading
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:\(([^)]*)\))?\s*", text)
        if m and -3 <= float(m.group(1)) <= 16:
            note = (m.group(2) or "").lower()
            kind = "base" if re.search(r"conjugate acid|amine|base", note) else "acid" if re.search(r"acid|carboxyl|phenol", note) else None
            out.append({"value": float(m.group(1)), "kind": kind})
    return out


def parse_logp(text: str) -> Optional[float]:
    m = re.search(r"log\s*(?:K\s*ow|Kow|P|Pow|D)?\s*(?:\(octanol[^)]*\))?\s*(?:=|:|of|is)?\s*(-?\d+(?:\.\d+)?)", text, re.I)
    if m:
        v = float(m.group(1))
        return v if -8 <= v <= 12 else None
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:\((?:log\s*K\s*ow|log\s*P)[^)]*\))?\s*", text, re.I)
    return float(m.group(1)) if m and -8 <= float(m.group(1)) <= 12 else None


def experimental(docs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Parse PUG View documents for the headings Solubility / Dissociation Constants / LogP."""
    sol, texts, pkas, logp = [], [], [], None
    for info, ref in information(docs.get("Solubility") or {}, "Solubility"):
        text = _text(info)
        if not text:
            continue
        got = parse_water_solubility(text)
        if got and got["value"] > 0:
            sol.append({**got, "value": float(f"{got['value']:.4g}"), "text": text, **ref})
        else:
            texts.append({"text": text, **ref})
    for info, ref in information(docs.get("Dissociation Constants") or {}, "Dissociation Constants"):
        text = _text(info)
        for p in parse_pka(text) if text else []:
            pkas.append({**p, "text": text, **ref})
    for info, ref in information(docs.get("LogP") or {}, "LogP"):
        text = _text(info)
        v = parse_logp(text) if text else None
        if v is not None and logp is None:
            logp = {"value": v, "text": text, **ref}
    # prefer a value stated at 20-30 °C, else the first one
    best = next((s for s in sol if s["t_c"] is not None and 20 <= s["t_c"] <= 30), sol[0] if sol else None)
    return {"solubility_water_mg_ml": best, "solubility_all": sol[:6], "solubility_texts": texts[:6], "pka": pkas[:6], "logp": logp}


def experimental_for(cid: int) -> dict[str, Any]:
    docs = {}
    for heading in ("Solubility", "Dissociation Constants", "LogP"):
        try:
            docs[heading] = _json(f"{BASE}/pug_view/data/compound/{cid}/JSON?heading={quote(heading)}")
        except HTTPError as exc:
            if exc.code not in (400, 404):  # 404: no such section for this compound
                raise
    return experimental(docs)


def lookup(names: list[str]) -> dict[str, Any]:
    for n in names:
        p = properties(n)
        if p:
            cid = int(p["CID"])
            smiles = p.get("SMILES") or p.get("IsomericSMILES") or p.get("ConnectivitySMILES") or p.get("CanonicalSMILES")
            mp, mps = melting_point(cid)
            exp = experimental_for(cid)
            return {"found": True, "query": n, "cid": cid, "smiles": smiles, "inchikey": p.get("InChIKey"),
                    "formula": p.get("MolecularFormula"), "mw": float(p["MolecularWeight"]) if p.get("MolecularWeight") else None,
                    "xlogp": p.get("XLogP"), "tpsa": p.get("TPSA"), "iupac": p.get("IUPACName"), "mp_c": mp, "mp_values": mps,
                    "exp": exp,
                    "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}", "fetched_at": now_iso()}
    return {"found": False, "query": names[0] if names else "", "fetched_at": now_iso()}


def _targets() -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    p = data_dir() / "generated" / "candidates.json"
    if p.exists():
        for c in json.loads(p.read_text(encoding="utf-8")):
            out[c["key"]] = {"key": c["key"], "names": c.get("names") or [c["key"]]}
    entered = data_dir() / "generated" / "molecules.json"
    if entered.exists():
        for m in json.loads(entered.read_text(encoding="utf-8")):
            if m.get("added"):
                v = m.get("values") or {}
                out.setdefault(m["key"], {"key": m["key"], "names": [v.get("api_name") or m["name"], *(v.get("aliases") or [])]})
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
