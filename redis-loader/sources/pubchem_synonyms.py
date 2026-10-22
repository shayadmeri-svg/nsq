"""PubChem synonyms of every tracked molecule: the other names official documents use for it.

Pharmacopoeias and regulators name the same molecule differently — INN ("acetylsalicylic acid"), USAN ("aspirin"),
BAN, JAN, Latin ("acidum acetylsalicylicum"), chemical ("2-acetoxybenzoic acid") — and core/identity.py resolves any
of them to the tracked molecule through this list. For each molecule's PubChem compound (pubchem.json) it keeps the
names PubChem ranks first, without registry numbers, database codes or very short tokens.

    data: {molecule_key: {"cid": int, "synonyms": [str, …], "fetched_at": iso}}

One request per molecule, at most five a second (PubChem's limit); each molecule refreshed every 60 days.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .common import Ctx, Unreachable, http_get, now_iso, read_normalized, write_normalized

URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
META = {
    "title": "PubChem synonyms",
    "publisher": "NCBI / NIH",
    "url": "https://pubchem.ncbi.nlm.nih.gov/",
    "page": "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest",
    "cadence": "monthly (each molecule refreshed every 60 days)",
    "feeds": ["Molecule names across sources (core/identity.py): INN, USAN, BAN, JAN, Latin and chemical names"],
}
KEEP = 50  # PubChem lists the most used names first; brand names and codes follow far down

_CODE = re.compile(r"^[A-Z0-9]{2,}[-\s]?\d|^\d(?![,\d]*-[a-z(])|^[A-Z]{2,}\d|unii|chebi|chembl|dtxsid|nsc\s?\d|^cas|^ec\s|^schembl|^bdbm|^akos|^mfcd|^hy-|^cs-|"
                   r"^ncgc|^smr\d|^bspbio|^kbio|^spectrum|^prestwick|^lopac|^tocris|^zinc|^db\d|^d\d{5}|^c\d{5}|^hsdb|^ccris|^brn|^ai3-|^wln",
                   re.I)


def keep_name(s: str) -> bool:
    s = s.strip()
    if len(s) < 4 or len(s) > 80 or _CODE.search(s):
        return False
    letters = sum(c.isalpha() for c in s)
    return letters >= 0.6 * len(s.replace(" ", ""))


def run(ctx: Ctx) -> int:
    from .pubchem import _targets

    pub = (read_normalized("pubchem") or {}).get("data", {})
    prev = (read_normalized("pubchem_synonyms") or {}).get("data", {})
    now = datetime.now(timezone.utc)

    def stale(key: str) -> bool:
        f = (prev.get(key) or {}).get("fetched_at")
        return ctx.force or not f or (now - datetime.fromisoformat(f)) > timedelta(days=60)

    todo = [t["key"] for t in _targets() if (pub.get(t["key"]) or {}).get("cid") and stale(t["key"])]
    ctx.log(f"{len(todo)} molecules to look up")
    data, done = dict(prev), 0
    for key in todo[: ctx.limit or 400]:
        cid = pub[key]["cid"]
        try:
            raw = json.loads(http_get(URL.format(cid=cid), timeout=30, retries=2))
        except Unreachable:
            if done == 0:
                raise
            ctx.log(f"  stopped after {done}: PubChem unreachable")
            break
        except Exception as exc:  # one molecule must not stop the rest
            ctx.log(f"  {key}: {exc}")
            continue
        names = ((raw.get("InformationList") or {}).get("Information") or [{}])[0].get("Synonym") or []
        syn = list(dict.fromkeys(n.strip() for n in names[:400] if keep_name(n)))[:KEEP]
        data[key] = {"cid": cid, "synonyms": syn, "fetched_at": now_iso()}
        done += 1
        time.sleep(0.4)
    write_normalized(ctx, META, data, len(data), extra={"queried_this_run": done})
    return len(data)
