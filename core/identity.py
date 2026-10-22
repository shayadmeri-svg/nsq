"""One answer to "which molecule is this name?", for every source.

Official documents name a molecule many ways: INN ("acetylsalicylic acid"), USAN ("aspirin"), BAN ("frusemide"),
Latin ("acidum acetylsalicylicum"), chemical ("2-acetoxybenzoic acid"), with a salt or hydrate ("atorvastatin calcium
trihydrate") or misspelt ("paracetmol"). Every source resolves its names here, against the tracked molecules, and
every match says how it was made:

    exact       a name the molecule is tracked under
    salt        the same name once salts, hydrates and dosage-form words are removed (ingredients.ingredient_key)
    inn_usan    the INN ↔ USAN pair (ingredients.USAN_SYNONYMS, both directions)
    synonym     one of the molecule's PubChem synonyms (data/sources/pubchem_synonyms.json)
    pubchem     an unknown name that PubChem resolves to the same parent compound (online; cached)
    fuzzy       a near spelling of a tracked name (≥ 90 similarity, same first letters, long names only)

A name that matches none is reported as unmapped — see coverage() — so the gap is measured, not guessed.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import ingredients as ing

METHODS = ("exact", "salt", "inn_usan", "synonym", "pubchem", "fuzzy")


@dataclass(frozen=True)
class Match:
    key: str
    method: str
    via: str  # the name or synonym that matched


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def tracked(data_dir: Path) -> list[dict[str, Any]]:
    """The tracked molecules and the names each is tracked under (candidates, molecules added in the app, seeds)."""
    out: dict[str, dict[str, Any]] = {}
    p = data_dir / "generated" / "candidates.json"
    if p.exists():
        for c in json.loads(p.read_text(encoding="utf-8")):
            out[c["key"]] = {"key": c["key"], "names": c.get("names") or [c["key"]]}
    entered = data_dir / "generated" / "molecules.json"
    if entered.exists():
        for m in json.loads(entered.read_text(encoding="utf-8")):
            if m.get("added"):
                v = m.get("values") or {}
                out.setdefault(m["key"], {"key": m["key"], "names": [v.get("api_name") or m["name"], *(v.get("aliases") or [])]})
    seed = data_dir / "structures_seed.json"
    if seed.exists():
        for k, v in json.loads(seed.read_text(encoding="utf-8")).get("molecules", {}).items():
            out.setdefault(k, {"key": k, "names": [v.get("name") or k]})
    return list(out.values())


class Resolver:
    def __init__(self, targets: list[dict[str, Any]], synonyms: Optional[dict[str, list[str]]] = None,
                 cids: Optional[dict[str, int]] = None, cid_cache: Optional[Path] = None):
        self.keys = [t["key"] for t in targets]
        self.cids = {k: c for k, c in (cids or {}).items() if c}
        self._by_cid = {c: k for k, c in self.cids.items()}
        self.cid_cache = cid_cache
        self._cid_memo: dict[str, Any] = json.loads(cid_cache.read_text(encoding="utf-8")) if cid_cache and cid_cache.exists() else {}
        exact: dict[str, str] = {}
        salt: dict[str, str] = {}
        for t in targets:
            names = [t["key"].replace("_", " "), *t["names"]]
            for n in names:
                exact.setdefault(_norm(n), t["key"])
                k = ing.ingredient_key(n)
                if k:
                    salt.setdefault(k, t["key"])
        self.exact, self.salt = exact, salt
        inn: dict[str, str] = {}
        for a, b in ing.USAN_SYNONYMS.items():  # both directions: a source may use either name
            for x, y in ((a, b), (b, a)):
                if y in salt and x not in salt:
                    inn.setdefault(x, salt[y])
        self.inn = inn
        syn: dict[str, set[str]] = {}
        for key, names in (synonyms or {}).items():
            for n in names:
                for form in {_norm(n), ing.ingredient_key(n)}:
                    if form:
                        syn.setdefault(form, set()).add(key)
        self.synonym = {s: next(iter(ks)) for s, ks in syn.items() if len(ks) == 1}  # a synonym two molecules share is no evidence

    # --- resolution -----------------------------------------------------------------------------------------------
    def resolve(self, name: str, online: bool = False) -> Optional[Match]:
        n, k = _norm(name), ing.ingredient_key(name or "")
        if not n:
            return None
        if n in self.exact:
            return Match(self.exact[n], "exact", name)
        if k and k in self.salt:
            return Match(self.salt[k], "salt", k)
        if k and k in self.inn:
            return Match(self.inn[k], "inn_usan", k)
        if k and k.split()[0] in self.inn and len(k.split()) > 1:
            return Match(self.inn[k.split()[0]], "inn_usan", k.split()[0])
        for form in (n, k):
            if form and form in self.synonym:
                return Match(self.synonym[form], "synonym", form)
        if online and self.cids:
            hit = self._pubchem(name)
            if hit:
                return hit
        return self._fuzzy(k)

    def _fuzzy(self, k: str) -> Optional[Match]:
        if not k or len(k) < 6:
            return None
        try:
            from rapidfuzz import fuzz, process
        except ImportError:  # pragma: no cover
            return None
        pool = [s for s in self.salt if s[:2] == k[:2] and abs(len(s) - len(k)) <= 3]
        hit = process.extractOne(k, pool, scorer=fuzz.ratio, score_cutoff=90) if pool else None
        return Match(self.salt[hit[0]], "fuzzy", hit[0]) if hit else None

    def _pubchem(self, name: str) -> Optional[Match]:
        """PubChem's compound for the name, and its parent (salt-free) compound, against the tracked compounds."""
        q = _norm(name)
        if q not in self._cid_memo:
            self._cid_memo[q] = _pubchem_cids(name)
            if self.cid_cache:
                self.cid_cache.parent.mkdir(parents=True, exist_ok=True)
                self.cid_cache.write_text(json.dumps(self._cid_memo), encoding="utf-8")
        for cid in self._cid_memo[q] or []:
            if cid in self._by_cid:
                return Match(self._by_cid[cid], "pubchem", f"CID {cid}")
        return None

    def search_names(self, key: str, synonyms: Optional[list[str]] = None, limit: int = 6) -> list[str]:
        """Names worth searching another database by: the tracked names, the INN/USAN pair, then the first synonyms."""
        out = [n for n, v in self.exact.items() if v == key] + [n for n, v in self.inn.items() if v == key]
        out += [s for s in (synonyms or [])[:20] if len(s.split()) <= 3]
        return list(dict.fromkeys(x.lower() for x in out if x))[:limit]


def _pubchem_cids(name: str) -> list[int]:
    """CIDs PubChem gives for a name, plus each one's parent compound (so a salt's name reaches the free base)."""
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    def get(url: str) -> Any:
        try:
            with urlopen(Request(url, headers={"User-Agent": "Eurveda/identity"}), timeout=20) as r:
                return json.loads(r.read())
        except (HTTPError, URLError, TimeoutError, ValueError):
            return None
        finally:
            time.sleep(0.25)  # PubChem: at most 5 requests a second

    base = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    d = get(f"{base}/compound/name/{quote(name)}/cids/JSON")
    cids = ((d or {}).get("IdentifierList") or {}).get("CID") or []
    out = list(cids[:3])
    for cid in cids[:3]:
        p = get(f"{base}/compound/cid/{cid}/cids/JSON?cids_type=parent")
        out += ((p or {}).get("IdentifierList") or {}).get("CID") or []
    return list(dict.fromkeys(out))


_cache: dict[str, tuple[float, Resolver]] = {}


def load(data_dir: Path) -> Resolver:
    """The resolver over the tracked molecules, rebuilt when the data files change."""
    files = [data_dir / "generated" / "candidates.json", data_dir / "generated" / "molecules.json", data_dir / "structures_seed.json",
             data_dir / "sources" / "pubchem_synonyms.json", data_dir / "sources" / "pubchem.json"]
    stamp = sum(f.stat().st_mtime for f in files if f.exists())
    hit = _cache.get(str(data_dir))
    if hit and hit[0] == stamp:
        return hit[1]

    def src(name: str) -> dict[str, Any]:
        p = data_dir / "sources" / f"{name}.json"
        return (json.loads(p.read_text(encoding="utf-8")).get("data") or {}) if p.exists() else {}

    syn = {k: v.get("synonyms") or [] for k, v in src("pubchem_synonyms").items()}
    cids = {k: v.get("cid") for k, v in src("pubchem").items() if isinstance(v, dict)}
    r = Resolver(tracked(data_dir), syn, cids, cid_cache=data_dir / "generated" / "name_cids.json")
    _cache[str(data_dir)] = (stamp, r)
    return r


def coverage(resolver: Resolver, names: Iterable[str], online: bool = False, solid_oral: Optional[set[str]] = None) -> dict[str, Any]:
    """How a source's entry names map: per method, the names that map to no tracked molecule, and which tracked
    molecules the source covers. Stored in each source's file as "coverage" and read by the admin coverage report."""
    by_method: dict[str, int] = {m: 0 for m in METHODS}
    unmapped: list[str] = []
    covered: dict[str, list[str]] = {}
    seen = list(dict.fromkeys(n for n in names if n))
    for n in seen:
        m = resolver.resolve(n, online=online)
        if m:
            by_method[m.method] += 1
            covered.setdefault(m.key, []).append(n)
        else:
            unmapped.append(n)
    return {"entries": len(seen), "mapped": len(seen) - len(unmapped), "by_method": by_method, "unmapped": sorted(unmapped),
            "tracked_total": len(resolver.keys), "tracked_covered": sorted(covered),
            "tracked_missing": sorted(set(resolver.keys) - set(covered)),
            "matches": {k: v[:3] for k, v in sorted(covered.items())}}
