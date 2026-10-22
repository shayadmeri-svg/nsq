"""Pharmacopoeial limits for a molecule's immediate-release tablet: each value from the first source that has it.

    1. Indian Pharmacopoeia      data/sources/ip.json, when IPC's data is licensed and imported (same shape as
                                 ph_int.json); until then the product's own IP limits are entered per product in
                                 Plant setup (Eurveda Connect)
    2. International Pharmacopoeia (WHO)   tablet / capsule monographs: assay limits, dissolution test and Q
    3. Japanese Pharmacopoeia (MHLW, English)   the same, for the JP's tablet / capsule monographs
    4. FDA Dissolution Methods Database    the dissolution method (medium, volume, speed, sampling times); where it refers
                                 the product to FDA's 2018 guidance, that guidance's standard test and Q = 80% in 30 min
    5. Default                   the generic values the twin starts from, marked as such

Alongside, the European Pharmacopoeia monograph for the substance (EDQM Knowledge Database: number, status,
revisions in progress) — Ph. Eur. limits themselves are in the paid text, so they are never a value here.
Every value carries its source, the sentence it came from where there is one, and the source's licence.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import pharmacopoeia

# the twin's defaults (chem.process_twin.SPECS): what is left when no source gives a value
DEFAULTS = {"assay_lo": 95.0, "assay_hi": 105.0, "q_pct": 75.0, "q_time_min": 45.0, "dt_max_min": 15.0}

SOURCES = {
    "ip": {"label": "Indian Pharmacopoeia", "url": "https://www.iponline.ipc.gov.in/", "licence": "IPC licence"},
    "ph_int": {"label": "The International Pharmacopoeia (WHO)", "url": "https://digicollections.net/phint/",
               "licence": "CC BY-NC-SA 3.0 IGO"},
    "jp": {"label": "The Japanese Pharmacopoeia (MHLW)", "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000066597.html",
           "licence": "Public Data License 1.0 (Japan); values extracted by Eurveda"},
    "fda": {"label": "FDA Dissolution Methods Database", "url": "https://www.accessdata.fda.gov/scripts/cder/dissolution/index.cfm",
            "licence": "US public domain"},
    "default": {"label": "Default (generic)", "url": None, "licence": None},
}
# FDA guidance (August 2018) "Dissolution Testing and Acceptance Criteria for Immediate-Release Solid Oral Dosage Form
# Drug Products Containing High Solubility Drug Substances" — what the Dissolution Methods Database means by
# "Refer to FDA's Dissolution Guidance, 2018" (sections IV and V of the guidance).
FDA_2018 = {"volume_ml": 500.0, "ph": 1.2, "rpm": 50.0, "apparatus": "paddle", "medium": "0.1 N HCl", "q_pct": 80.0, "q_time_min": 30.0,
            "url": "https://www.fda.gov/media/92988/download",
            "text": "Paddle method (USP apparatus 2), 50 rpm, 500 mL of 0.1N HCl, no surfactant, 37 °C (or basket, 100 rpm); "
                    "for IR products containing a high solubility drug substance the dissolution criterion is Q = 80% in 30 minutes.",
            "note": "FDA's database refers this product to its 2018 guidance for high-solubility drugs"}
_IR_FORMS = ("tablets", "film-coated tablets", "dispersible tablets", "soluble tablets", "chewable tablets", "capsules", "hard capsules")


def _monograph(source: str, key: str) -> Optional[dict[str, Any]]:
    """The source's single-ingredient immediate-release tablet monograph (capsules if no tablet), or None."""
    from .lab import _source_rec

    rec = _source_rec(source, key) or {}
    mons = [m for m in rec.get("monographs") or [] if not m.get("combination") and m.get("form") in _IR_FORMS]
    # the plain tablet first; among equals (a source may hold two texts, e.g. a renamed salt) the one stating most
    mons.sort(key=lambda m: (_IR_FORMS.index(m["form"]), not (m.get("dissolution") or {}).get("q_pct"), not m.get("assay")))
    return mons[0] if mons else None


def _val(value: Any, source: str, mono: Optional[dict[str, Any]] = None, text: Optional[str] = None, note: Optional[str] = None) -> dict[str, Any]:
    return {"value": value, "source": source, **SOURCES[source], "monograph": (mono or {}).get("title"),
            "url": (mono or {}).get("url") or SOURCES[source]["url"], "text": text, "note": note}


def resolve(key: str) -> dict[str, Any]:
    """{fields: {assay_lo, assay_hi, q_pct, q_time_min, volume_ml, ph, rpm, apparatus, medium, times_min, dt_max_min},
    chain: [{source, status, monograph}], ph_eur: [...]} — each field {value, source, label, url, text, note, licence}."""
    from .lab import fda_method

    fields: dict[str, dict[str, Any]] = {}
    chain = []

    def take(name: str, value: Any, source: str, mono=None, text=None, note=None) -> None:
        if value not in (None, "", []) and name not in fields:
            fields[name] = _val(value, source, mono, text, note)

    for src in ("ip", "ph_int", "jp"):
        mono = _monograph(src, key)
        status = "used" if mono else ("not imported" if src == "ip" else "no monograph")
        chain.append({"source": src, **SOURCES[src], "status": status, "monograph": (mono or {}).get("title"), "url": (mono or {}).get("url") or SOURCES[src]["url"]})
        if not mono:
            continue
        a = mono.get("assay") or {}
        take("assay_lo", a.get("lo"), src, mono, a.get("text"))
        take("assay_hi", a.get("hi"), src, mono, a.get("text"))
        d = mono.get("dissolution") or {}
        if d.get("q_pct") is not None:
            take("q_pct", d["q_pct"], src, mono, d.get("text"))
        elif d.get("each_unit_min_pct") is not None:
            take("q_pct", d["each_unit_min_pct"], src, mono, d.get("text"),
                 note="the monograph sets a minimum for each unit (older wording, with a 12-unit retest), used here as Q")
        take("q_time_min", d.get("time_min"), src, mono, d.get("text"))
        if d.get("conditions_given") and d.get("ph") is not None:  # the medium as one set, never mixed with another method's
            for f in ("volume_ml", "ph", "rpm", "apparatus", "medium"):
                take(f, d.get(f), src, mono, d.get("text"))
        elif d and "q_pct" not in fields:
            fields.setdefault("_dissolution_required", _val(True, src, mono, d.get("text"),
                                                            note="the monograph requires a dissolution test but states no conditions"))
        dis = mono.get("disintegration") or {}
        take("dt_max_min", dis.get("max_min"), src, mono, dis.get("text"))

    meth = fda_method(key)
    referred = bool(meth and not meth.get("volume_ml") and re.search(r"dissolution guidance,?\s*2018", meth.get("medium") or "", re.I))
    if referred:  # FDA's database refers this product to its 2018 guidance: that guidance's standard test and Q apply
        g = FDA_2018
        for f in ("volume_ml", "ph", "rpm", "apparatus", "medium"):
            take(f, g[f], "fda", text=g["text"], note=g["note"])
        take("q_pct", g["q_pct"], "fda", text=g["text"], note=g["note"])
        take("q_time_min", g["q_time_min"], "fda", text=g["text"], note=g["note"])
        for f in ("volume_ml", "ph", "rpm", "apparatus", "medium", "q_pct", "q_time_min"):
            if fields.get(f, {}).get("source") == "fda":
                fields[f]["url"] = g["url"]
    meth = meth if meth and meth.get("volume_ml") else None  # other rows that only say "Refer to USP" carry no method
    chain.append({"source": "fda", **SOURCES["fda"], "status": "used (2018 guidance)" if referred else "used" if meth else "no method",
                  "monograph": (meth or {}).get("dosage_form"), "url": SOURCES["fda"]["url"]})
    if meth:
        text = f"{meth.get('dosage_form')}: {meth.get('apparatus')} {meth.get('rpm_text') or ''} rpm, {meth.get('medium')}, {meth.get('volume_text')} mL, sampling {meth.get('times_text')} min"
        for f in ("volume_ml", "ph", "rpm", "medium", "times_min"):
            take(f, meth.get(f), "fda", text=text)
        take("apparatus", meth.get("apparatus"), "fda", text=text)

    for f, v in DEFAULTS.items():
        take(f, v, "default", note="generic value: no pharmacopoeia in the chain gives one for this molecule")
    chain.append({"source": "default", **SOURCES["default"], "status": "fallback", "monograph": None, "url": None})

    ph_eur = [{"number": m.get("number"), "name": m.get("name"), "status": m.get("status"), "last_published": m.get("last_published"),
               "revision": m.get("revision") if m.get("revision_in_progress") else None, "url": m.get("url")}
              for m in pharmacopoeia.monographs_for(key)]
    return {"key": key, "fields": fields, "chain": chain, "ph_eur": ph_eur,
            "ph_eur_note": "European Pharmacopoeia limits are in the paid text; shown here: the monograph, its status and revisions in progress (EDQM Knowledge Database)."}


def twin_specs(lim: dict[str, Any]) -> dict[str, float]:
    """The twin's specification overrides from resolved limits (sources only; defaults are the twin's own)."""
    f = lim["fields"]
    return {k: float(f[k]["value"]) for k in ("assay_lo", "assay_hi", "q_pct", "q_time_min", "dt_max_min")
            if k in f and f[k]["source"] != "default"}


def spec_basis(lim: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The twin's SPEC_BASIS entries that a pharmacopoeia now supplies, worded as the twin shows them."""
    f, out = lim["fields"], {}
    if f.get("assay_lo", {}).get("source") not in (None, "default"):
        a = f["assay_lo"]
        out["assay"] = {"kind": "source", "text": f"{f['assay_lo']['value']:g}–{f['assay_hi']['value']:g}% of label claim: {a['label']}, {a['monograph']}",
                        "url": a["url"], "licence": a.get("licence")}
    if f.get("q_pct", {}).get("source") not in (None, "default"):
        q, t = f["q_pct"], f.get("q_time_min", {})
        out["dissolution"] = {"kind": "source", "text": f"Q = {q['value']:g}% at {t.get('value', 45):g} min: {q['label']}, {q['monograph']}"
                                                        + (f" ({q['note']})" if q.get("note") else ""),
                              "url": q["url"], "licence": q.get("licence")}
    return out


def method(lim: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The dissolution method the models run (medium, volume, pH, speed, sampling) — from the first source in the
    chain that states one — or None when only defaults are left."""
    f = lim["fields"]
    src = (f.get("volume_ml") or {}).get("source")
    if src in (None, "default"):
        return None
    v = {k: (f.get(k) or {}).get("value") for k in ("volume_ml", "ph", "rpm", "apparatus", "medium", "times_min")}
    if src == "fda":
        label = (f"FDA 2018 guidance (high-solubility IR): paddle 50 rpm, 500 mL 0.1 N HCl, Q 80% at 30 min" if f["volume_ml"].get("note")
                 else f"FDA method: {f['volume_ml']['text']}")
    else:
        label = (f"{f['volume_ml']['label']}, {f['volume_ml']['monograph']}: {v['apparatus'] or ''} {v['rpm'] or '?':g} rpm, "
                 f"{v['volume_ml']:g} mL of {v['medium']}") if isinstance(v["rpm"], (int, float)) else f"{f['volume_ml']['label']}, {f['volume_ml']['monograph']}"
    if not v["times_min"] and "q_time_min" in f:
        v["times_min"] = [f["q_time_min"]["value"]]
    return {**v, "source": src, "label": label, "url": f["volume_ml"]["url"], "licence": f["volume_ml"].get("licence")}
