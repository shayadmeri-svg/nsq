"""The International Pharmacopoeia (WHO): the tests and limits of each tablet and capsule monograph.

WHO publishes Ph. Int. free online (digicollections.net) under CC BY-NC-SA 3.0 IGO: it may be copied and adapted
for non-commercial use with attribution (commercial use needs a WHO licence: who.int/about/licensing). The library
is static — a table of contents and one file per text — so this reads the contents, picks the specific dosage-form
monographs of the tracked molecules (tablets, capsules and their variants) and, from each, the numbers the models
use, with the sentence each came from:

    assay      contains not less than X% and not more than Y% of the labelled amount
    dissolution  medium and its volume, apparatus, speed, sampling time, Q (or a test the monograph gives instead)
    disintegration  a time set in the monograph itself (else the general "Tablets" / "Capsules" text applies)
    uniformity  whether 5.1 Uniformity of content is required (else 5.2 Uniformity of mass)

    data: {ingredient_key: {"found": bool, "tracked": bool, "monographs": [{id, title, form, combination, ingredients,
                                                                         url, assay, dissolution, disintegration,
                                                                         uniformity_of_content}]},
           "_general": {"tablets": {...}, "capsules": {...}, "dissolution_acceptance": {...}}}

Every solid oral monograph is kept (about a hundred texts), keyed by ingredient — the tracked molecules' own keys
where they match — so a molecule that becomes tracked already has its limits.

Monograph files are cached under data/raw/ph_int/ for 30 days and fetched at most one a second.
"""

from __future__ import annotations

import html as _html
import json
import re
import time
from typing import Any, Optional

from .common import Ctx, Unreachable, data_dir, http_get, write_normalized

SITE = "https://digicollections.net/phint"
LICENCE = {"name": "CC BY-NC-SA 3.0 IGO", "url": "https://creativecommons.org/licenses/by-nc-sa/3.0/igo",
           "commercial": "https://www.who.int/about/licensing"}
META = {
    "title": "The International Pharmacopoeia (WHO)",
    "publisher": "World Health Organization",
    "url": f"{SITE}/",
    "page": f"{SITE}/",
    "cadence": "one edition a year; checked weekly (each monograph refreshed every 30 days)",
    "feeds": ["Assay and dissolution limits per tablet / capsule monograph (twin specifications, Lab dissolution)"],
    "licence": LICENCE["name"],
}

# solid oral forms, longest first so "chewable tablets" wins over "tablets"
FORMS = ("prolonged-release tablets", "modified-release tablets", "gastro-resistant tablets", "film-coated tablets",
         "dispersible tablets", "chewable tablets", "effervescent tablets", "orodispersible tablets", "soluble tablets",
         "tablets", "hard capsules", "soft capsules", "capsules")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _amd(raw: str) -> dict[str, Any]:
    """The library's files are AMD modules: define({...})."""
    raw = raw.lstrip("﻿")
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def edition(ctx: Ctx) -> str:
    """The current edition's folder (e.g. 202502), from the redirect in the library's landing page."""
    if ctx.options.get("edition"):
        return str(ctx.options["edition"])
    page = http_get(f"{SITE}/", timeout=60).decode("utf-8", errors="replace")
    found = re.findall(r"(\d{6})/index\.html", page)
    if not found:
        raise Unreachable("Ph. Int.: could not find the current edition on the landing page")
    return max(found)


def _get(ctx: Ctx, ed: str, doc: str) -> dict[str, Any]:
    dest = ctx.raw_dir / ed / f"{doc}.js"
    if dest.exists() and not ctx.force and (time.time() - dest.stat().st_mtime) < 30 * 86400:
        return _amd(dest.read_text(encoding="utf-8"))
    raw = http_get(f"{SITE}/{ed}/data/b/b.{doc}.js", timeout=60, retries=1).decode("utf-8", errors="replace")
    time.sleep(float(ctx.options.get("sleep", 1.0)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw, encoding="utf-8")
    return _amd(raw)


def contents(toc: dict[str, Any]) -> list[tuple[str, str]]:
    """(id, plain title) of every text in the table of contents."""
    out: list[tuple[str, str]] = []

    def walk(n: dict[str, Any]) -> None:
        if n.get("id"):
            out.append((n["id"], _clean(n.get("t", ""))))
        for c in n.get("c") or []:
            walk(c)

    walk(toc)
    return out


def split_title(title: str) -> Optional[tuple[list[str], str]]:
    """'Amoxicillin and clavulanic acid tablets (Amoxicillini …)' → (['Amoxicillin', 'clavulanic acid'], 'tablets');
    None when it is not a solid oral form."""
    name = re.sub(r"\s*\(.*$", "", title).strip()
    low = name.lower()
    for form in FORMS:
        if low.endswith(" " + form):
            head = name[: -len(form)].strip()
            parts = [p.strip() for p in re.split(r",\s*|\s+and\s+", head) if p.strip()]
            return parts, form
    return None


_NUM = r"(\d+(?:\.\d+)?)"


def parse_assay(text: str) -> Optional[dict[str, Any]]:
    m = re.search(rf"contain[s]? not less than {_NUM}\s*%\s*and not more than {_NUM}\s*%[^.]*?(?:stated on the label|labelled|label claim)[^.]*\.",
                  text, re.I)
    if not m:
        return None
    return {"lo": float(m.group(1)), "hi": float(m.group(2)), "text": m.group(0)}


def _section(text: str, heading: str) -> Optional[str]:
    """The paragraph that starts with `heading.` up to the next 'Heading.' of the monograph's own tests."""
    m = re.search(rf"\b{heading}\.\s", text)
    if not m:
        return None
    rest = text[m.start():]
    nxt = re.search(r"\.\s(?:Related substances|Assay|Identity tests?|Uniformity of content|Disintegration|"
                    r"Dissolution|Water|Loss on drying|Definition|Impurities|Storage|Labelling|Additional information|\d-[A-Z][a-z]+)\.\s",
                    rest[len(heading) + 2:])
    return rest[: len(heading) + 2 + nxt.start() + 1] if nxt else rest[:3000]


def medium_ph(medium: str) -> Optional[float]:
    """pH of a dissolution medium as Ph. Int. names it, where it says (buffer pH x) or it is a standard HCl strength."""
    m = re.search(r"pH\s*\(?\s*" + _NUM, medium, re.I)
    if m:
        return float(m.group(1))
    if re.search(r"hydrochloric acid\s*\(~\s*(?:3\.65|4)\s*g/l\)|hydrochloric acid\s*\(0\.1\s*mol/l\)", medium, re.I):
        return 1.2  # ~0.1 mol/L HCl
    if re.search(r"hydrochloric acid\s*\(~\s*0\.365\s*g/l\)|hydrochloric acid\s*\(0\.01\s*mol/l\)", medium, re.I):
        return 2.0
    return None


def parse_dissolution(text: str) -> Optional[dict[str, Any]]:
    sec = _section(text, "Dissolution") or _section(text, "Dissolution test")
    if not sec:
        return None
    out: dict[str, Any] = {"text": sec[:1500]}
    # "using as the dissolution medium 900 mL of X and rotating …" or "using 900 mL of X as the dissolution medium …"
    med = (re.search(r"dissolution medium,?\s*(\d+)\s*ml of (.+?)(?:,? and rotating|,? rotating|;|\.\s)", sec, re.I)
           or re.search(r"using\s*(\d+)\s*ml of (.+?)\s*as the dissolution medium", sec, re.I))
    if med:
        out["volume_ml"] = float(med.group(1))
        out["medium"] = med.group(2).strip()
        out["ph"] = medium_ph(out["medium"])
    app = re.search(r"rotat(?:ing|e) the (paddle|basket) at\s*(\d+)\s*revolutions per minute", sec, re.I)
    if app:
        out["apparatus"], out["rpm"] = app.group(1).lower(), float(app.group(2))
    t = re.search(r"At\s*(\d+)\s*minutes", sec)
    if t:
        out["time_min"] = float(t.group(1))
    q = re.search(r"not less than\s*" + _NUM + r"\s*%\s*\(Q\)", sec, re.I)
    if q:
        out["q_pct"] = float(q.group(1))
    each = re.search(r"amount in solution for each (?:tablet|capsule) is not less than\s*" + _NUM + r"\s*%", sec, re.I)
    if each:  # older wording: a minimum for every unit (with a 12-unit retest), not a Q
        out["each_unit_min_pct"] = float(each.group(1))
    # some monographs only require the test (5.5) and give no conditions of their own
    out["conditions_given"] = any(k in out for k in ("volume_ml", "rpm", "time_min"))
    if "either test a or test b" in sec.lower() or re.search(r"\bTest B\b", sec):
        out["alternatives"] = True
    return out


def parse_disintegration(text: str) -> Optional[dict[str, Any]]:
    sec = _section(text, "Disintegration")
    if not sec:
        return None
    m = re.search(r"(\d+)\s*minutes", sec)
    return {"max_min": float(m.group(1)) if m else None, "text": sec[:600]}


def parse_monograph(doc_id: str, title: str, body_html: str, ed: str) -> dict[str, Any]:
    text = _clean(body_html)
    parts, form = split_title(title) or ([], "")
    return {"id": doc_id, "title": title, "form": form, "ingredients": parts, "combination": len(parts) > 1,
            "url": f"{SITE}/{ed}/index.html#d/b.{doc_id}",
            "assay": parse_assay(text), "dissolution": parse_dissolution(text), "disintegration": parse_disintegration(text),
            "uniformity_of_content": "5.1 Uniformity of content" in text or "Uniformity of content." in text}


def parse_general(body_html: str) -> dict[str, Any]:
    """The general dosage-form text: the default disintegration time for uncoated units."""
    text = _clean(body_html)
    m = re.search(r"Operate the apparatus for\s*(\d+)\s*minutes", text)
    return {"disintegration_max_min": float(m.group(1)) if m else None,
            "text": (m and text[max(0, m.start() - 200): m.end() + 120]) or None}


def parse_acceptance(body_html: str) -> dict[str, Any]:
    """5.5's acceptance table for conventional-release forms (stages S1–S3 around the monograph's Q)."""
    text = _clean(body_html)
    m = re.search(r"Table 1 Level Samples tested Acceptance criteria (.*?)(?= Sustained-release| Delayed-release|$)", text)
    return {"stages_text": m.group(1)[:900] if m else None}


def _summary(m: dict[str, Any]) -> str:
    d = m["dissolution"] or {}
    out = m["title"].split(" (")[0]
    if m["assay"]:
        out += f" · assay {m['assay']['lo']:g}–{m['assay']['hi']:g}%"
    if d.get("q_pct"):
        out += f" · Q {d['q_pct']:g}% at {d.get('time_min', 0):g} min"
    elif d.get("each_unit_min_pct"):
        out += f" · each unit ≥ {d['each_unit_min_pct']:g}% at {d.get('time_min', 0):g} min"
    elif d:
        out += " · dissolution required (no conditions in the monograph)"
    return out


def run(ctx: Ctx) -> int:
    import identity  # core/
    import ingredients as ing  # core/

    if ctx.from_file:
        data = json.loads(ctx.from_file.read_text(encoding="utf-8"))
        data = data.get("data", data)
        write_normalized(ctx, META, data, sum(1 for k, v in data.items() if not k.startswith("_") and v.get("found")),
                         extra={"licence": LICENCE})
        return len(data)
    ed = edition(ctx)
    toc = _get(ctx, ed, "toc")
    items = contents(toc)
    resolver = identity.load(data_dir())
    targets = set(resolver.keys)
    hits: dict[str, list[tuple[str, str]]] = {}
    general: dict[str, str] = {}
    names: list[str] = []
    for doc_id, title in items:
        if title in ("Tablets", "Capsules") and doc_id.startswith("6.2."):
            general[title.lower()] = doc_id
            continue
        if title.startswith("5.5 Dissolution test"):
            general["dissolution_acceptance"] = doc_id
            continue
        if not doc_id.startswith("6.2.2."):
            continue
        st = split_title(title)
        if not st:
            continue
        names += st[0]
        for k in {(m.key if (m := resolver.resolve(p, online=True)) else ing.ingredient_key(p)) for p in st[0]}:
            hits.setdefault(k, []).append((doc_id, title))
    tracked = [k for k in hits if k in targets]
    ctx.log(f"Ph. Int. edition {ed}: {len(items)} texts; solid oral monographs for {len(hits)} ingredients "
            f"({len(tracked)} of {len(targets)} tracked molecules)")

    data: dict[str, Any] = {"_general": {}}
    for form, doc_id in general.items():
        body = _get(ctx, ed, doc_id).get("b", "")
        rec = parse_acceptance(body) if form == "dissolution_acceptance" else parse_general(body)
        data["_general"][form] = {"id": doc_id, "url": f"{SITE}/{ed}/index.html#d/b.{doc_id}", **rec}
    done = 0
    for key in sorted(hits, key=lambda k: (k not in targets, k)):  # tracked molecules first
        mons = []
        for doc_id, title in hits[key]:
            try:
                mons.append(parse_monograph(doc_id, title, _get(ctx, ed, doc_id).get("b", ""), ed))
                done += 1
            except Unreachable:
                if done == 0:
                    raise
                ctx.log(f"  stopped after {done}: digicollections unreachable")
                break
            except Exception as exc:  # one malformed text must not stop the rest
                ctx.log(f"  {key} {title}: {exc}")
        data[key] = {"found": bool(mons), "tracked": key in targets, "monographs": mons}
        if mons and key in targets:
            ctx.log(f"  {key}: " + "; ".join(_summary(m) for m in mons))
    found = sum(1 for k, v in data.items() if not k.startswith("_") and v["found"])
    cov = identity.coverage(resolver, names, online=True)
    ctx.log(f"coverage: {cov['mapped']}/{cov['entries']} ingredient names map to a tracked molecule "
            f"({', '.join(f'{k} {v}' for k, v in cov['by_method'].items() if v)}); tracked covered {len(cov['tracked_covered'])}/{cov['tracked_total']}")
    write_normalized(ctx, META, data, found, extra={"edition": ed, "licence": LICENCE, "coverage": cov})
    return found
