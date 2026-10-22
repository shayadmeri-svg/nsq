#!/usr/bin/env python3
"""Merge extracted Indian Pharmacopoeia monograph rows (JSONL) into data/ip_seed.json, cleaning them on the way.

    python redis-loader/ip_import.py extract.jsonl            # report only
    python redis-loader/ip_import.py extract.jsonl --write    # merge into data/ip_seed.json

Each input line is one monograph as an extraction step produced it (title, form, ingredients, reference, assay,
dissolution, usual_strengths_mg, _review, or _error). What this does, so a bad reading never reaches the models:

    - drops rows the extraction could not read (_error), and rows whose "title" is a fragment (Tablets, release and …)
    - moves release words out of ingredient names (Bupropion Hydrochloride Extended-release → form prolonged-release)
    - one entry per monograph: alternative titles of the same monograph (Acetaminophen/Paracetamol Tablets, a salt and
      its base) become other_names
    - blanks values outside a plausible range (an assay range that is not around 100%, 0.1 rpm, 0.9 mL …) and says so in
      `review`; normalises the medium's OCR spelling and derives its pH where the medium fixes it
    - never touches an entry already in the seed (hand-entered or verified ones stay as they are)
    - runs every result through sources/ip.check (data/IP_SEED_GUIDE.md) and leaves out anything that still fails

The seed's licence and verification rules apply: these values are an OCR extraction and stay unverified until someone
checks them against the edition (data/IP_SEED_GUIDE.md rule 12).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "core"))

import ingredients as ing  # noqa: E402
from sources import ip  # noqa: E402

SEED = HERE.parent / "data" / "ip_seed.json"
FRAGMENT = {"tablets", "capsules", "sublingual", "disintegrating", "prolonged-release", "extended-release", "release",
            "hydrochloride", "and", "fumarate", "maleate", "medoxomil", "sulphate", "disoproxil", "paediatric",
            "mouth", "chewable", "sustained-release"}
RELEASE = [(r"\s+(extended|prolonged|sustained)-release$", "prolonged-release"), (r"\s+gastro-resistant$", "gastro-resistant"),
           (r"\s+sublingual$", "sublingual")]
LEADING_FORM = {"dispersible": "dispersible tablets", "soluble": "soluble tablets", "effervescent": "effervescent tablets"}
RPM_OK = (25, 150)


def _clean_medium(m: Optional[str]) -> Optional[str]:
    if not m:
        return None
    m = re.split(r"\s{3,}|[■|\\\"]|\s-\s", m)[0]                      # OCR noise after the medium
    m = re.sub(r"(\d)\s*[.,:;]\s*[I1l]\s*M", r"\1.1 M", m)               # 0.IM, 0. IM, 0:1 M → 0.1 M
    m = re.sub(r"0\s*[.,]\s*0\s*[I1lO]\s*M", "0.01 M", m)               # 0.0IM, 0.01M → 0.01 M
    m = re.sub(r"(\d)M(?=[a-z])", r"\1 M ", m)                          # 0.1Mhydrochloric → 0.1 M hydrochloric
    m = re.sub(r"M(hydrochloric|sodium|potassium|phosphate|acetate)", r"M \1", m)
    m = re.sub(r"buffer\s*pH", "buffer pH", m)
    m = re.sub(r"\b(waler|wafer|wate\?|watez|warer)\b", "water", m)
    m = re.sub(r"hydrochlori(?:c|de)\s*'?\s*acid", "hydrochloric acid", m)
    m = re.sub(r"\s+", " ", m).strip(" ,.;:'\"!^")
    return m or None


def _medium_ph(m: Optional[str], given: Optional[float]) -> Optional[float]:
    if given is not None and 1.0 <= given <= 8.0:
        return given
    if not m:
        return None
    s = m.lower()
    p = re.search(r"ph\s*(\d+(?:\.\d+)?)", s)
    if p and 1.0 <= float(p.group(1)) <= 8.0:
        return float(p.group(1))
    if re.match(r"^0\.1 m hydrochloric acid$", s) or "gastric" in s:
        return 1.2
    if re.match(r"^0\.01 m hydrochloric acid$", s):
        return 2.0
    if re.match(r"^0\.001 m hydrochloric acid$", s):
        return 3.0
    if "intestinal" in s:
        return 6.8
    return None


def normalise(r: dict[str, Any]) -> tuple[Optional[dict[str, Any]], list[str]]:
    """(entry or None, notes) for one extracted row."""
    notes: list[str] = []
    title = re.sub(r"\s+", " ", r.get("title") or "").strip()
    first = title.split(" ")[0].lower() if title else ""
    if "_error" in r or not title or first in FRAGMENT or not re.match(r"^[A-Z(]|^[a-z]-|^[A-Z]-", title):
        return None, [r.get("_error") or "title is a fragment"]
    form = (r.get("form") or "").lower()
    ingr = [i.strip() for i in r.get("ingredients") or [] if i and i.strip()]
    if ingr and ingr[0].lower().split(" ")[0] in LEADING_FORM:          # "Dispersible Ampicillin" → Ampicillin
        form = LEADING_FORM[ingr[0].lower().split(" ")[0]]
        ingr[0] = " ".join(ingr[0].split(" ")[1:])
    for i, name in enumerate(ingr):                                     # "… Extended-release" in an ingredient name
        for rx, kind in RELEASE:
            if re.search(rx, name, re.I):
                ingr[i] = re.sub(rx, "", name, flags=re.I)
                base = "capsules" if "capsule" in form else "tablets"
                form = f"{kind} {base}" if kind != "sublingual" else "sublingual tablets"
    if not ingr or any(not re.search(r"[a-z]{3}", i.lower()) for i in ingr):
        return None, ["no ingredient name"]
    key = ing.molecule_key_for(ingr[0])
    ref = dict(r.get("reference") or {})
    if not (ref.get("edition") and ref.get("volume") and ref.get("page")):
        return None, ["no reference"]
    e: dict[str, Any] = {"title": title, "form": form, "ingredients": ingr, "combination": len(ingr) > 1, "reference": ref}

    st = sorted({float(x) for x in r.get("usual_strengths_mg") or [] if isinstance(x, (int, float)) and x > 0.05})
    if st:
        e["usual_strengths_mg"] = [int(x) if x == int(x) else x for x in st]

    a = r.get("assay") or {}
    lo, hi = a.get("lo"), a.get("hi")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        if 85 <= lo < 100 <= hi <= 130:
            e["assay"] = {"lo": float(lo), "hi": float(hi), "text": f"Assay {lo:g}–{hi:g}% of the stated amount ({ref['edition']}, {title})"}
        else:
            notes.append(f"assay {lo:g}–{hi:g} is not a limit around the labelled amount: left out (enter by hand)")

    d = r.get("dissolution")
    if d:
        dd: dict[str, Any] = {}
        app = d.get("apparatus")
        if app in ip.APPARATUS:
            dd["apparatus"] = app
            dd["apparatus_ip"] = d.get("apparatus_ip") or ("Apparatus No. 1 (Basket), IP 2.5.2" if app == "basket" else "Apparatus No. 2 (Paddle), IP 2.5.2")
        for f, (lo_, hi_) in (("volume_ml", (100, 4000)), ("rpm", RPM_OK), ("time_min", (5, 1440)), ("q_pct", (40, 100))):
            v = d.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if lo_ <= v <= hi_:
                    dd[f] = float(v)
                else:
                    notes.append(f"dissolution {f} {v:g} is outside {lo_}–{hi_}: left out (OCR)")
        med = _clean_medium(d.get("medium"))
        if med:
            dd["medium"] = med
        ph = _medium_ph(med, d.get("ph"))
        if ph is not None:
            dd["ph"] = ph
        if any(k in dd for k in ("q_pct", "volume_ml", "rpm", "time_min")):
            dd["conditions_given"] = all(k in dd for k in ("volume_ml", "rpm", "time_min"))
            if dd.get("q_pct") is not None:
                cond = ", ".join(x for x in (dd.get("apparatus"), dd.get("volume_ml") and f"{dd['volume_ml']:g} mL", med,
                                             dd.get("rpm") and f"{dd['rpm']:g} rpm", dd.get("time_min") and f"{dd['time_min']:g} min") if x)
                dd["text"] = f"{cond}; Q not less than {dd['q_pct']:g}% ({ref['edition']}, {title})"
            e["dissolution"] = dd
    e["review"] = [x for x in (r.get("_review") or []) if x] + notes
    return e, notes


_resolver = None


def molecule(name: str) -> str:
    """The molecule a name stands for: the tracked one when the name resolves (Acetaminophen → paracetamol), else its key."""
    global _resolver
    if _resolver is None:
        import identity  # core/

        _resolver = identity.load(HERE.parent / "data")
    m = _resolver.resolve(name)
    return m.key if m else ing.molecule_key_for(name)


def group_key(e: dict[str, Any]) -> tuple:
    first_page = re.match(r"\d+", str(e["reference"]["page"]))  # "3197–3198" and "3197" are the same monograph
    return (molecule(e["ingredients"][0]), e["form"], first_page.group(0) if first_page else e["reference"]["page"], e["combination"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("jsonl", type=Path)
    ap.add_argument("--write", action="store_true", help="merge into data/ip_seed.json (otherwise report only)")
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in args.jsonl.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    have_titles = {m["title"].lower() for v in seed["molecules"].values() for m in v.get("monographs") or []}
    have_groups = {group_key(m) for v in seed["molecules"].values() for m in v.get("monographs") or []}

    why: Counter = Counter()
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        e, notes = normalise(r)
        if e is None:
            why[(notes[0] if notes else "unreadable").split(" at printed")[0].split(" not located")[0]] += 1
            continue
        if e["title"].lower() in have_titles or group_key(e) in have_groups:
            why["already in the seed (kept as entered)"] += 1
            continue
        groups[group_key(e)].append(e)

    added: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failed = []
    for g, es in groups.items():
        # the reading with most values stands for the monograph; the other titles are its alternative names
        es.sort(key=lambda x: (-len(x.get("dissolution") or {}), -("assay" in x), len(x["title"])))
        best = dict(es[0])
        others = sorted({x["title"] for x in es[1:]} - {best["title"]})
        if others:
            best["other_names"] = others
        key = molecule(best["ingredients"][0])
        errs, _ = ip.check(key, best)
        if errs:
            failed.append((best["title"], errs))
            continue
        added[key].append(best)

    n_mono = sum(len(v) for v in added.values())
    print(f"{len(rows)} rows → {n_mono} monographs for {len(added)} molecules"
          f" ({sum(len(es) for es in groups.values()) - len(groups)} alternative titles folded in)")
    for k, v in why.most_common():
        print(f"  skipped {v:4} · {k}")
    for t, errs in failed:
        print(f"  failed checks · {t}: {'; '.join(errs)}")
    q = sum(1 for v in added.values() for m in v if (m.get("dissolution") or {}).get("q_pct") is not None)
    a = sum(1 for v in added.values() for m in v if m.get("assay"))
    c = sum(1 for v in added.values() for m in v if (m.get("dissolution") or {}).get("conditions_given"))
    print(f"  with assay limits {a} · with Q {q} · with full dissolution conditions {c}")
    if args.write:
        for key, mons in added.items():
            seed["molecules"].setdefault(key, {"monographs": []})["monographs"].extend(mons)
        seed["molecules"] = dict(sorted(seed["molecules"].items()))
        SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {SEED.relative_to(HERE.parent)}: {len(seed['molecules'])} molecules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
