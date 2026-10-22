"""Indian Pharmacopoeia limits, from data/ip_seed.json: the first source in the limits chain (backend/app/limits.py).

IP is the standard CDSCO judges Indian products against. Its text is IPC's (paid, licensed), so it is not fetched:
the seed holds limits entered by hand — numbers and the monograph reference (edition, volume, page), no monograph
text — and grows by appending molecules (any molecule, tracked or not). Every entry is checked against the rules in
data/IP_SEED_GUIDE.md; one with an error is reported and not loaded. Each entry's molecule is resolved through core/identity.py like every other
source, and the run's coverage is stored with the data.

    data: {molecule_key: {"found": True, "monographs": [{title, form, ingredients, combination, reference, url,
                                                        assay, dissolution, related_substances, …}]}}
"""

from __future__ import annotations

import json
import re
from typing import Any

from .common import Ctx, data_dir, write_normalized

SEED = "ip_seed.json"
URL = "https://www.iponline.ipc.gov.in/"
META = {
    "title": "Indian Pharmacopoeia (limits entered from the licensed edition)",
    "publisher": "Indian Pharmacopoeia Commission",
    "url": URL,
    "page": URL,
    "cadence": "whenever data/ip_seed.json changes",
    "feeds": ["Assay, dissolution and impurity limits per monograph — first in the limits chain (twin, Lab, Coverage)"],
}


FORMS = {"tablets", "film-coated tablets", "dispersible tablets", "chewable tablets", "soluble tablets", "effervescent tablets",
         "orally disintegrating tablets", "sublingual tablets", "prolonged-release tablets", "modified-release tablets", "gastro-resistant tablets",
         "capsules", "hard capsules", "soft capsules", "prolonged-release capsules", "gastro-resistant capsules",
         "oral suspension", "oral solution", "syrup", "injection", "powder for injection", "eye drops", "cream", "ointment", "gel"}
APPARATUS = {"paddle", "basket", "flow-through cell", "reciprocating cylinder"}
# plausible ranges: a value outside is almost always a misread or a unit slip (data/IP_SEED_GUIDE.md rule 11)
RANGES = {"volume_ml": (100, 4000), "rpm": (25, 150), "time_min": (5, 1440), "q_pct": (40, 100), "each_unit_min_pct": (40, 100),
          "ph": (1.0, 8.0)}


def check(key: str, mon: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one monograph entry, against the rules in data/IP_SEED_GUIDE.md."""
    err, warn = [], []

    def num(v: Any) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    if not re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", key):
        err.append(f"key '{key}': lowercase INN, words joined by _")
    if not mon.get("title"):
        err.append("title missing")
    if mon.get("form") not in FORMS:
        err.append(f"form '{mon.get('form')}' is not one of the listed forms")
    ref = mon.get("reference") or {}
    for f in ("edition", "volume", "page"):
        if not ref.get(f):
            err.append(f"reference.{f} missing")
    ingr = mon.get("ingredients") or []
    if bool(mon.get("combination")) != (len(ingr) > 1):
        err.append("combination must be true exactly when there is more than one ingredient")
    a = mon.get("assay")
    if a is not None:
        if not (num(a.get("lo")) and num(a.get("hi"))):
            err.append("assay lo / hi must be numbers")
        elif not (50 <= a["lo"] < a["hi"] <= 150):
            err.append(f"assay {a['lo']}–{a['hi']}: lo must be below hi, both within 50–150%")
    d = mon.get("dissolution")
    if d is not None:
        if d.get("apparatus") is None:
            warn.append("dissolution.apparatus not entered")
        elif d["apparatus"] not in APPARATUS:
            err.append(f"dissolution.apparatus '{d['apparatus']}': one of {', '.join(sorted(APPARATUS))}")
        for f, (lo, hi) in RANGES.items():
            v = d.get(f)
            if v is None:
                continue
            if not num(v):
                err.append(f"dissolution.{f} must be a number, not {v!r}")
            elif not lo <= v <= hi:
                err.append(f"dissolution.{f} = {v} is outside {lo}–{hi}: check the reading")
        if d.get("q_pct") is None and d.get("each_unit_min_pct") is None:
            warn.append("dissolution has no Q")
        if d.get("ph") is None and "water" not in (d.get("medium") or "").lower():
            warn.append(f"dissolution.ph missing for medium '{d.get('medium')}'")
        given = all(d.get(f) is not None for f in ("volume_ml", "rpm", "time_min"))
        if bool(d.get("conditions_given")) != given:
            err.append("dissolution.conditions_given must be true exactly when volume_ml, rpm and time_min are all given")
        for i, v in enumerate(d.get("variants") or []):
            if not (num(v.get("time_min")) and num(v.get("q_pct"))):
                err.append(f"dissolution.variants[{i}] needs numeric time_min and q_pct")
    if not (mon.get("verified") or {}).get("by"):
        warn.append("not verified against the printed edition yet (add verified.by / on / against)")
    return err, warn


def run(ctx: Ctx) -> int:
    import identity  # core/

    path = ctx.from_file or data_dir() / SEED
    seed = json.loads(path.read_text(encoding="utf-8"))
    edition = seed.get("edition", "")
    resolver = identity.load(data_dir())
    data: dict[str, Any] = {}
    names = []
    issues: list[dict[str, Any]] = []
    for key, entry in (seed.get("molecules") or {}).items():
        m = resolver.resolve(key.replace("_", " "))
        target = m.key if m else key
        names.append(key.replace("_", " "))
        mons = []
        for mon in entry.get("monographs") or []:
            err, warn = check(key, mon)
            for level, msgs in (("error", err), ("warning", warn)):
                issues += [{"key": key, "title": mon.get("title"), "level": level, "message": x} for x in msgs]
                for x in msgs:
                    ctx.log(f"  {level.upper()} {key} / {mon.get('title')}: {x}")
            if not err:  # an entry with an error is reported, not loaded
                mons.append({**mon, "url": URL, "edition": (mon.get("reference") or {}).get("edition") or edition})
        if not mons:
            continue
        entry_ = data.setdefault(target, {"found": True, "tracked": bool(m), "monographs": []})  # two seed keys can name one molecule
        entry_["monographs"] += mons
        ctx.log(f"  {target}: " + "; ".join(f"{x['title']} ({x['reference'].get('edition')}, vol. {x['reference'].get('volume')}, "
                                             f"p. {x['reference'].get('page')})" for x in mons))
    cov = identity.coverage(resolver, names)
    errors = sum(1 for i in issues if i["level"] == "error")
    ctx.log(f"{len(data)} molecules loaded; {errors} errors, {len(issues) - errors} warnings (rules: data/IP_SEED_GUIDE.md)")
    write_normalized(ctx, META, data, len(data), extra={"edition": edition, "seed": SEED, "coverage": cov, "issues": issues,
                                                        "licence": {"name": "IPC — limits entered from a licensed copy"}})
    return len(data)
