"""Two answers built on Failure forensics, for a small or medium maker.

* portfolio(lines): "here are my products" -> for each, how the market fails it, how risky it is to make, and what to
  check. A product line is free text (generic name, strength, form; brand names are resolved through the NSQ product
  names that carry them).
* needed(): "needed and badly made" — products many makers keep failing, crossed with how much India needs them:
  NFHS disease burden (diabetes, blood pressure, anaemia, childhood diarrhoea / respiratory infection) and IDSP
  outbreaks. Every link between a condition and a medicine is listed in CONDITIONS, so the join can be checked.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

import pandas as pd

from . import forensics as fx
from . import insights, signals

MAX_LINES = 150

# ------------------------------------------------------------------------------------------ portfolio

_FORMS = [
    ("Injection", r"\binj|inject|\bvial|\bamp(oule)?s?\b|infusion|\biv\b|\bi\.v\b"),
    ("Capsule", r"\bcap(s|sule)?s?\b"),
    ("Syrup/Suspension", r"syrup|susp|oral (liquid|solution)|\bsyp\b|\bliquid\b|elixir"),
    ("Ointment/Cream", r"ointment|cream|\bgel\b|lotion|\boint\b"),
    ("Powder/Granules", r"powder|sachet|granule|\bdry syrup\b"),
    ("Drops", r"drops?\b"),
    ("Tablet", r"\btab(let)?s?\b|\bsr\b|\ber\b|\bdt\b|\bmr\b"),
]
_FORMS_RX = [(f, re.compile(rx, re.I)) for f, rx in _FORMS]
_NOISE = re.compile(r"\b\d+(\.\d+)?\s*(mg|mcg|µg|g|ml|iu|%|w/v|w/w)?\b|\b(ip|bp|usp|tablets?|capsules?|inj\w*|syrup|susp\w*|sr|er|dt|mr|oral)\b", re.I)


def _form_of(text: str) -> Optional[str]:
    return next((f for f, rx in _FORMS_RX if rx.search(text)), None)


def _resolve(text: str, d: pd.DataFrame) -> tuple[tuple[str, ...], str]:
    """(ingredient key tuple, how it was resolved). Brand names fall back to NSQ product names that contain them."""
    ings = tuple(sorted(insights.product_ingredients(text)))
    names = d["Name of Product"].astype(str).str.lower()
    stem = _NOISE.sub(" ", text.lower())
    stem = re.sub(r"[^a-z0-9+\- ]", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    # a parsed "ingredient" that no NSQ product contains is usually a brand ("Dolo 650" -> "dolo")
    if ings and not (d["_ings"] == ings).any() and stem and len(stem) >= 3:
        hit = d[names.str.contains(r"\b" + re.escape(stem) + r"\b", regex=True)]
        if len(hit):
            return hit["_ings"].value_counts().index[0], "brand"
    if ings:
        return ings, "name"
    if stem and len(stem) >= 3:
        hit = d[names.str.contains(r"\b" + re.escape(stem) + r"\b", regex=True)]
        if len(hit):
            return hit["_ings"].value_counts().index[0], "brand"
    return (), "none"


_hyp_cache: dict[str, dict[str, Any]] = {}


def _diagnosis(key: str) -> Optional[dict[str, Any]]:
    """Archetype, the leading root cause and its checks for one forensics group (cached per data load)."""
    hit = _hyp_cache.get(key)
    if hit is not None:
        return hit or None
    d = fx._frame()
    g = d[d["_group"] == key]
    if len(g) < fx.MIN_ALERTS:
        _hyp_cache[key] = {}
        return None
    s = fx._signals(g, fx._cache["base"])
    arch, headline = fx._archetype(s)
    hyps = fx._hypotheses(s, fx._chemistry(list(g["_ings"].iloc[0])), key.split("|", 1)[1])
    top = next((h for h in hyps if h["confidence"] == "strong"), hyps[0] if hyps else None)
    out = {"archetype": arch, "headline": headline, "dominant": s["dominant"], "dominant_share": s["dominant_share"],
           "early": s["early"], "late": s["late"], "class_wide": s["class_wide"], "maker_specific": s["maker_specific"],
           "cause": top["title"] if top else None, "checks": (top["checks"][:3] if top else []),
           "evidence": (top["evidence"][:2] if top else [])}
    _hyp_cache[key] = out
    return out


def _risk(n: int, recent: int, diag: Optional[dict[str, Any]]) -> tuple[str, str]:
    if n == 0:
        return "clear", "No NSQ alert for this product in the data"
    if diag:
        if diag["maker_specific"]:
            return "watch", "Failures come from a few plants — the formula itself is workable"
        if diag["class_wide"] and recent >= 5:
            return "high", "Many independent makers fail it, and still do"
        if recent >= 10 or diag["archetype"] in ("born", "ages", "aseptic"):
            return "high", "A known, recurring failure mode"
        return "watch", "Fails regularly across makers"
    if recent >= 3:
        return "watch", "A few recent failures — not enough to read a pattern"
    return "low", "Rarely fails"


def _vocab(d: pd.DataFrame) -> set[str]:
    v = fx._cache.get("vocab")
    if v is None:
        v = {i for t in d["_ings"].unique() for i in t}
        v |= {m for c in CONDITIONS.values() for m in c["meds"]}
        try:
            from . import data
            v |= set(data.cdmo()["patents"])
        except Exception:
            pass
        fx._cache["vocab"] = v
    return v


def _own(g: pd.DataFrame, same: pd.DataFrame, keys: set[str], cutoff: pd.Timestamp) -> dict[str, Any]:
    """One company's own NSQ record for this product (same form) and for these ingredients in any form."""
    mine = g[g["Mfg_Ontology_Key"].isin(keys)]
    any_form = same[same["Mfg_Ontology_Key"].isin(keys)]
    return {"alerts": int(len(mine)), "recent_24m": int((mine["Parsed_Date"] >= cutoff).sum()),
            "last": mine["Parsed_Date"].max().strftime("%Y-%m") if len(mine) and mine["Parsed_Date"].notna().any() else None,
            "tests": [t for t, _ in Counter(t for ts in mine["_tests"] for t in ts).most_common(2)],
            "other_forms": int(len(any_form) - len(mine)),
            "ids": [str(x) for x in mine.sort_values("Parsed_Date", ascending=False)["record_id"].head(3)]}


def portfolio(lines: list[str], compare: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """compare = {"keys": [manufacturer ontology keys], "name": str} adds that company's own record per product."""
    d = fx._frame()
    keys = {k for k in (compare or {}).get("keys") or [] if k}
    if d.empty:
        return {"available": False}
    if fx._cache.get("hyp_key") != fx._cache.get("key"):
        _hyp_cache.clear()
        fx._cache["hyp_key"] = fx._cache.get("key")
    cutoff = d["Parsed_Date"].max() - pd.DateOffset(months=24)
    seen: set[str] = set()
    vocab = _vocab(d)
    rows = []
    for raw in lines[:MAX_LINES]:
        text = re.sub(r"\s+", " ", str(raw or "")).strip(" ,;\t")
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        ings, via = _resolve(text, d)
        form = _form_of(text)
        if not ings:
            rows.append({"input": text, "risk": "unknown", "why": "Couldn't recognise the ingredients — try the generic name"})
            continue
        if not all(i in vocab for i in ings):
            rows.append({"input": text, "risk": "unknown", "ingredients": list(ings),
                         "why": "No NSQ alert names this. If it's a brand, type the generic name; if it's a generic, it has no NSQ history"})
            continue
        same = d[d["_ings"] == ings]
        forms = same["_form"].value_counts()
        if form is None and len(forms):
            form = str(forms.index[0])  # no form given: the one the market fails most
        g = same[same["_form"] == form] if form else same
        key = "+".join(ings) + "|" + (form or "")
        n, recent = int(len(g)), int((g["Parsed_Date"] >= cutoff).sum())
        makers = int(g["Mfg_Ontology_Key"].dropna().nunique())
        diag = _diagnosis(key) if n >= fx.MIN_ALERTS else None
        risk, why = _risk(n, recent, diag)
        combos = d[d["_ings"].map(lambda t: t != ings and set(ings) <= set(t))]
        rows.append({
            "input": text, "via": via, "label": fx._label(key) if form else " + ".join(i.title() for i in ings),
            "ingredients": list(ings), "form": form, "form_given": _form_of(text) is not None,
            "key": key if diag else None, "alerts": n, "recent_24m": recent, "makers": makers,
            "last": g["Parsed_Date"].max().strftime("%Y-%m") if n and g["Parsed_Date"].notna().any() else None,
            "tests": [t for t, _ in Counter(t for ts in g["_tests"] for t in ts).most_common(3)],
            "risk": risk, "why": why, **({"diagnosis": diag} if diag else {}),
            "other_forms": [{"form": str(f), "alerts": int(c), "key": "+".join(ings) + "|" + str(f) if c >= fx.MIN_ALERTS else None}
                            for f, c in forms.items() if f != form][:4],
            "in_combinations": int(len(combos)),
            **({"own": _own(g, same, keys, cutoff)} if keys else {}),
        })
    order = {"high": 0, "watch": 1, "low": 2, "clear": 3, "unknown": 4}
    rows.sort(key=lambda r: (order[r["risk"]], -r.get("recent_24m", 0)))
    summary = Counter(r["risk"] for r in rows)
    checks = Counter(c for r in rows if r["risk"] == "high" for c in (r.get("diagnosis") or {}).get("checks", []))
    own_rows = [r for r in rows if r.get("own")]
    return {"available": True, "rows": rows, "summary": {k: summary.get(k, 0) for k in order},
            "compare": ({"name": (compare or {}).get("name") or ", ".join(sorted(keys)), "keys": sorted(keys),
                         "source": (compare or {}).get("source", "chosen"),
                         "products_failed": sum(1 for r in own_rows if r["own"]["alerts"]),
                         "alerts": sum(r["own"]["alerts"] for r in own_rows)} if keys else None),
            "period": {"first": d["Parsed_Date"].min().strftime("%Y-%m"), "last": d["Parsed_Date"].max().strftime("%Y-%m")},
            "common_checks": [{"check": c, "products": n} for c, n in checks.most_common(6) if n > 1],
            "note": "Risk reads how the whole market fails each product in CDSCO NSQ alerts. A company's own record is shown "
                    "only when one is chosen (or you sign in as an organisation). No form in a line means the form most often failed."}


def maker_products(mfr_key: str, limit: int = 60) -> list[str]:
    """Products a maker has been named for in NSQ alerts — a quick way to fill the portfolio box."""
    d = fx._frame()
    g = d[d["Mfg_Ontology_Key"] == mfr_key]
    out = []
    for key in g["_group"].value_counts().index[:limit]:
        out.append(fx._label(key).replace(" · ", " "))
    return out


# ------------------------------------------------------------------------------------------ needed and badly made

# condition -> NFHS indicators that measure its burden, IDSP diseases that signal it, and the medicines (ingredient
# stems, both spellings) whose demand it drives
CONDITIONS: dict[str, dict[str, Any]] = {
    "diabetes": {"label": "Diabetes", "nfhs": ["sugar_women", "sugar_men"], "idsp": [],
                 "meds": ["metformin", "glimepiride", "gliclazide", "glibenclamide", "sitagliptin", "vildagliptin", "teneligliptin",
                          "linagliptin", "dapagliflozin", "empagliflozin", "voglibose", "pioglitazone", "insulin"]},
    "hypertension": {"label": "Blood pressure & heart", "nfhs": ["bp_women", "bp_men"], "idsp": [],
                     "meds": ["telmisartan", "amlodipine", "losartan", "olmesartan", "metoprolol", "atenolol", "ramipril", "enalapril",
                              "hydrochlorothiazide", "chlorthalidone", "cilnidipine", "nifedipine", "bisoprolol", "candesartan",
                              "atorvastatin", "rosuvastatin", "clopidogrel", "aspirin"]},
    "anaemia": {"label": "Anaemia", "nfhs": ["anaemia_women", "anaemia_children"], "idsp": [],
                # Anaemia Mukt Bharat: iron-folic acid plus deworming with albendazole
                "meds": ["iron", "ferrous", "ferric", "folic acid", "cyanocobalamin", "methylcobalamin", "vitamin b12", "albendazole"]},
    "diarrhoea": {"label": "Diarrhoea & gut infections", "nfhs": ["diarrhoea_children"],
                  "idsp": ["Acute diarrhoeal disease", "Food poisoning", "Cholera", "Typhoid"],
                  "meds": ["oral rehydration", "zinc", "ofloxacin", "ornidazole", "metronidazole", "tinidazole", "norfloxacin",
                           "racecadotril", "ondansetron", "ciprofloxacin", "cefixime", "azithromycin", "ceftriaxone"]},
    "respiratory": {"label": "Respiratory infections & cough", "nfhs": ["ari_children"], "idsp": ["Influenza / ILI"],
                    "meds": ["amoxycillin", "amoxicillin", "clavulan", "azithromycin", "cefixime", "cefpodoxime", "salbutamol",
                             "levosalbutamol", "terbutaline", "ambroxol", "guaiphenesin", "montelukast", "cetirizine", "levocetirizine",
                             "chlorpheniramine", "dextromethorphan", "phenylephrine", "bromhexine"]},
    "fever": {"label": "Fever: dengue, chikungunya, malaria", "nfhs": [], "idsp": ["Dengue", "Chikungunya", "Fever (unknown)", "Malaria"],
              "meds": ["paracetamol", "artemether", "lumefantrine", "artesunate", "chloroquine", "primaquine"]},
}


def _matches(ings: tuple[str, ...], meds: list[str]) -> list[str]:
    return [i for i in ings if any(m in i or (len(i) >= 5 and i in m) for m in meds)]


def _nfhs_burden(ind: str) -> Optional[dict[str, Any]]:
    raw = signals._load("nfhs")
    rows = [r for r in raw.get("data") or [] if r["ind"] == ind]
    if not rows:
        return None
    rounds = sorted({r["round"] for r in rows})
    cur = rounds[-1]
    prev = rounds[-2] if len(rounds) > 1 else None
    india = {r["round"]: r["value"] for r in rows if r["level"] == "india"}
    st_cur = {r["state"]: r["value"] for r in rows if r["level"] == "state" and r["round"] == cur}
    st_prev = {r["state"]: r["value"] for r in rows if r["level"] == "state" and r["round"] == prev}
    states = sorted(({"state": s, "value": v, "change": round(v - st_prev[s], 1) if s in st_prev else None} for s, v in st_cur.items()),
                    key=lambda x: -x["value"])
    label = (raw.get("indicators") or {}).get(ind, {}).get("label", ind)
    return {"indicator": ind, "label": label, "round": cur, "previous_round": prev, "india": india.get(cur),
            "india_prev": india.get(prev) if prev else None,
            "change": round(india[cur] - india[prev], 1) if prev and cur in india and prev in india else None,
            "rising_states": sum(1 for s in states if (s["change"] or 0) > 0), "states_total": len(states),
            "top_states": states[:6]}


def _idsp(diseases: list[str]) -> Optional[dict[str, Any]]:
    if not diseases:
        return None
    o = signals.outbreaks(26)
    if not o.get("available"):
        return None
    hit = [b for b in o["by_disease"] if b["disease"] in diseases]
    if not hit:
        return {"outbreaks": 0, "cases": 0, "deaths": 0, "diseases": [], "weeks": len(o["weeks"])}
    raw = signals._load("idsp").get("data") or []
    keep = set(o["weeks"])
    st = Counter((r.get("state") or "Unknown") for r in raw if r.get("disease_key") in diseases and r.get("week") in keep)
    return {"outbreaks": sum(b["outbreaks"] for b in hit), "cases": sum(b["cases"] for b in hit), "deaths": sum(b["deaths"] for b in hit),
            "diseases": [{"disease": b["disease"], "outbreaks": b["outbreaks"], "cases": b["cases"]} for b in hit],
            "top_states": [{"state": s, "outbreaks": n} for s, n in st.most_common(6)], "weeks": len(o["weeks"]),
            "first_week": o["weeks"][0] if o["weeks"] else None, "last_week": o["weeks"][-1] if o["weeks"] else None}


def needed() -> dict[str, Any]:
    gs = fx._groups()
    if not gs:
        return {"available": False}
    d = fx._frame()
    cutoff = d["Parsed_Date"].max() - pd.DateOffset(months=24)
    recent = d[d["Parsed_Date"] >= cutoff]
    made_in = {k: Counter(v) for k, v in recent.groupby("_group")["Mfg_State_Ontology"].apply(lambda s: s.dropna().tolist()).items()}

    conds = []
    by_group: dict[str, list[str]] = {}
    for ck, c in CONDITIONS.items():
        burden = [b for b in (_nfhs_burden(i) for i in c["nfhs"]) if b]
        idsp = _idsp(c["idsp"])
        prods = []
        for g in gs:
            m = _matches(tuple(g["ingredients"]), c["meds"])
            if not m or g["maker_specific"] or g["archetype"] == "labelling" or g["recent_24m"] < 3:
                continue
            by_group.setdefault(g["key"], []).append(ck)
            prods.append({**{k: g[k] for k in ("key", "label", "archetype", "headline", "n", "recent_24m", "makers", "dominant",
                                               "dominant_share", "class_wide", "last")}, "linked_by": m,
                          "made_in": [{"state": s, "alerts": n} for s, n in made_in.get(g["key"], Counter()).most_common(3) if s]})
        prods.sort(key=lambda p: -(p["recent_24m"] * (1 + p["makers"] / 20)))
        conds.append({"key": ck, "label": c["label"], "burden": burden, "outbreaks": idsp, "medicines": c["meds"],
                      "products": prods, "recent_alerts": sum(p["recent_24m"] for p in prods),
                      "class_wide": sum(1 for p in prods if p["class_wide"])})
    conds.sort(key=lambda c: -c["recent_alerts"])

    # one ranked list: quality-gap strength x how many needs it serves
    ranked = []
    for g in gs:
        cks = by_group.get(g["key"])
        if not cks:
            continue
        gap = g["recent_24m"] * (1 + g["makers"] / 20)
        need = 0.0
        for ck in cks:
            c = next(x for x in conds if x["key"] == ck)
            need += max([b["india"] or 0 for b in c["burden"]] + [0]) / 10 + min((c["outbreaks"] or {}).get("outbreaks", 0), 300) / 100
        ranked.append({**{k: g[k] for k in ("key", "label", "archetype", "headline", "n", "recent_24m", "makers", "class_wide", "dominant")},
                       "conditions": [CONDITIONS[ck]["label"] for ck in cks], "gap_score": round(gap, 1),
                       "need_score": round(need, 1), "score": round(gap * (1 + need), 1),
                       "made_in": [{"state": s, "alerts": n} for s, n in made_in.get(g["key"], Counter()).most_common(3) if s]})
    ranked.sort(key=lambda r: -r["score"])
    return {"available": True, "conditions": conds, "ranked": ranked[:25],
            "window": {"from": cutoff.strftime("%Y-%m"), "to": d["Parsed_Date"].max().strftime("%Y-%m")},
            "sources": {"nfhs": signals._meta(signals._load("nfhs")), "idsp": signals._meta(signals._load("idsp"))},
            "note": "Burden: NFHS fact-sheet prevalence (latest round vs the one before). Outbreaks: IDSP/NCDC weekly reports, "
                    "last 26 weeks. The condition → medicine links are the usual first-line treatments listed on this page — "
                    "demand signals, not prescription volumes. Products that fail mainly at a few plants, or only on labelling, are "
                    "left out: their gap is a plant or a label, not the product."}
