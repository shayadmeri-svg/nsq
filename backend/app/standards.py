"""Pharmacopoeial standards for an organisation's products, from every connected pharmacopoeia, each read on its own terms.

For each molecule in the organisation's CDSCO alerts (single-ingredient and combinations):

    India     Indian Pharmacopoeia        data/sources/ip.json — the standard CDSCO tests the product against
    Europe    European Pharmacopoeia      EDQM Knowledge Database: monograph, status, dated revisions (pharmacopoeia.py)
    Japan     Japanese Pharmacopoeia      data/sources/jp.json (MHLW English version)
    WHO       International Pharmacopoeia data/sources/ph_int.json
    US        FDA Dissolution Methods     data/sources/fda_dissolution.json, and FDA's 2018 guidance where it refers to it

Every monograph is shown as its source states it (assay range, dissolution test and Q, disintegration, IP's related
substances); then each source's immediate-release tablet limits are compared with the IP's: stricter, looser, the same,
or not directly comparable (a higher Q at a later time). Ph. Eur. limits are in the paid text and never compared.
Each country's insights are computed here: what matters for India is not what matters for an export market.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Optional

from . import data, limits, pharmacopoeia, signals

REGIONS = [
    {"id": "ip", "country": "India", "code": "IN", "label": "Indian Pharmacopoeia", "short": "IP",
     "role": "The standard CDSCO tests your products against: a medicine sold in India must meet its IP monograph where one "
             "exists, and another country's official pharmacopoeia where the IP has none (Drugs and Cosmetics Act, 1940, Second Schedule)."},
    {"id": "ph_eur", "country": "Europe", "code": "EU", "label": "European Pharmacopoeia", "short": "Ph. Eur.",
     "role": "Binding across the member states of the European Pharmacopoeia Convention, the EU included: the standard for "
             "exports to Europe and for a Certificate of Suitability (CEP). Its limits are in the paid text; tracked here: each "
             "monograph's status and EDQM's dated revisions."},
    {"id": "jp", "country": "Japan", "code": "JP", "label": "Japanese Pharmacopoeia", "short": "JP",
     "role": "Japan's official standard (MHLW): what an export to Japan is tested against, and a second official reference "
             "where the IP has no monograph."},
    {"id": "ph_int", "country": "WHO", "code": "WHO", "label": "The International Pharmacopoeia", "short": "Ph. Int.",
     "role": "WHO's pharmacopoeia, written for countries without their own and accepted in WHO prequalification: the "
             "reference for donor-funded and UN tenders and for many markets in Africa and South-East Asia."},
    {"id": "fda", "country": "United States", "code": "US", "label": "FDA Dissolution Methods Database", "short": "FDA",
     "role": "The dissolution test FDA recommends for a US generic (ANDA) where the USP has none. The USP–NF itself is "
             "subscription-only and not connected: a row that says \"Refer to USP\" means the USP monograph holds the method."},
]
_FILE = {"ip": "ip", "jp": "jp", "ph_int": "ph_int", "fda": "fda_dissolution"}
_SOLID_ORAL = re.compile(r"tablet|capsule", re.I)
# a CDSCO failure category → the monograph test that sets its limit
_TEST = {"Assay / Content": "assay", "Dissolution": "dissolution", "Related Substances": "related_substances", "Disintegration": "disintegration"}


def _short(text: Optional[str], n: int = 320) -> Optional[str]:
    """The sentence that states the limit: JP's dissolution paragraph goes on to the sample preparation."""
    if not text:
        return text
    s = re.split(r"(?<=%)\.\s|(?<=\.)\s(?=Start the test|Separately|Withdraw|Perform the test)", text, maxsplit=1)[0]
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _monograph(src: str, m: dict[str, Any], issues: dict[str, list[str]]) -> dict[str, Any]:
    d, a, dis, rs = (m.get("dissolution") or {}), (m.get("assay") or {}), (m.get("disintegration") or {}), (m.get("related_substances") or {})
    ref = m.get("reference") or {}
    return {
        "title": m.get("title"), "form": m.get("form"), "combination": bool(m.get("combination")), "ingredients": m.get("ingredients") or [],
        "url": m.get("url"), "id": m.get("id"),
        "reference": ({"edition": ref.get("edition") or m.get("edition"), "volume": ref.get("volume"), "page": ref.get("page")} if ref
                      else {"page": m.get("page"), "supplement": m.get("supplement")} if src == "jp" else None),
        "strengths_mg": m.get("usual_strengths_mg"),
        "assay": {"lo": a.get("lo"), "hi": a.get("hi"), "text": a.get("text")} if a else None,
        "dissolution": {**{k: d.get(k) for k in ("apparatus", "rpm", "medium", "ph", "volume_ml", "time_min", "q_pct", "each_unit_min_pct")},
                        "text": _short(d.get("text"))} if d else None,
        "disintegration": {"max_min": dis.get("max_min"), "text": dis.get("text")} if dis else None,
        "related_substances": rs.get("text") if rs else None,
        "verified": m.get("verified") if src == "ip" else None,
        "issues": [x for x in issues.get(m.get("title") or "", []) if not x.startswith("not verified")] if src == "ip" else [],
    }


def _ip_issues() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for i in signals._load("ip").get("issues") or []:
        out[i.get("title") or ""].append(i.get("message") or "")
    return out


def _fda_rows(key: str) -> list[dict[str, Any]]:
    from .lab import _source_rec

    rows = _source_rec("fda_dissolution", key)
    rows = rows if isinstance(rows, list) else []
    keep = [r for r in rows if _SOLID_ORAL.search(r.get("dosage_form") or "")]
    return [{k: r.get(k) for k in ("drug", "dosage_form", "apparatus", "rpm", "medium", "volume_ml", "times_min", "times_text", "updated", "combination")}
            | {"refers_to": "USP" if re.search(r"refer to usp", r.get("medium") or "", re.I)
               else "FDA 2018 guidance" if re.search(r"dissolution guidance", r.get("medium") or "", re.I) else None}
            for r in sorted(keep, key=lambda r: (bool(r.get("combination")), r.get("dosage_form") or ""))]


def _limits_row(src: str, key: str) -> Optional[dict[str, Any]]:
    """The source's immediate-release tablet (or capsule) limits, as compared across sources."""
    if src == "fda":
        from .lab import fda_method

        meth = fda_method(key)
        if not meth:
            return None
        if not meth.get("volume_ml") and re.search(r"dissolution guidance,?\s*2018", meth.get("medium") or "", re.I):
            g = limits.FDA_2018  # the database refers the product to the 2018 guidance: its standard test and Q
            return {"source": "fda", "monograph": "FDA 2018 guidance (high-solubility IR)", "assay_lo": None, "assay_hi": None,
                    **{f: g[f] for f in ("q_pct", "q_time_min", "medium", "ph", "rpm", "apparatus", "volume_ml")}}
        if not meth.get("volume_ml"):
            return None  # "Refer to USP": the method is in the USP monograph
        return {"source": "fda", "monograph": f"FDA Dissolution Methods Database ({meth.get('dosage_form')})", "assay_lo": None,
                "assay_hi": None, "q_pct": None, "q_time_min": None, **{f: meth.get(f) for f in ("medium", "ph", "rpm", "apparatus", "volume_ml")}}
    m = limits._monograph(src, key)
    if not m:
        return None
    a, d = m.get("assay") or {}, m.get("dissolution") or {}
    return {"source": src, "monograph": m.get("title"), "assay_lo": a.get("lo"), "assay_hi": a.get("hi"),
            "q_pct": d.get("q_pct") if d.get("q_pct") is not None else d.get("each_unit_min_pct"), "q_time_min": d.get("time_min"),
            **{f: d.get(f) for f in ("medium", "ph", "rpm", "apparatus", "volume_ml")}}


def _vs(o: Optional[float], o2: Optional[float], ip: Optional[float], ip2: Optional[float], higher_first_is_stricter: bool) -> Optional[str]:
    """Compare two (value, time-or-upper) pairs: dissolution (Q higher and time no later = stricter) or assay (narrower = stricter)."""
    if None in (o, o2, ip, ip2):
        return None
    if (o, o2) == (ip, ip2):
        return "same"
    if higher_first_is_stricter:  # dissolution: (Q, time)
        if o >= ip and o2 <= ip2:
            return "stricter"
        if o <= ip and o2 >= ip2:
            return "looser"
        return "different"
    if o >= ip and o2 <= ip2:  # assay: (lo, hi) inside IP's range
        return "stricter"
    if o <= ip and o2 >= ip2:
        return "looser"
    return "different"


def _method_differs(o: dict[str, Any], ip: dict[str, Any]) -> list[str]:
    out = []
    if o.get("ph") is not None and ip.get("ph") is not None and abs(float(o["ph"]) - float(ip["ph"])) >= 0.3:
        out.append(f"medium pH {o['ph']:g} vs {ip['ph']:g}")
    if o.get("rpm") and ip.get("rpm") and float(o["rpm"]) != float(ip["rpm"]):
        out.append(f"{o['rpm']:g} vs {ip['rpm']:g} rpm")
    if o.get("apparatus") and ip.get("apparatus") and str(o["apparatus"]).split()[0].lower() not in str(ip["apparatus"]).lower() \
            and str(ip["apparatus"]).split()[0].lower() not in str(o["apparatus"]).lower():
        out.append(f"{o['apparatus']} vs {ip['apparatus']}")
    if o.get("volume_ml") and ip.get("volume_ml") and float(o["volume_ml"]) != float(ip["volume_ml"]):
        out.append(f"{o['volume_ml']:g} vs {ip['volume_ml']:g} mL")
    return out


def compare(key: str) -> dict[str, Any]:
    """Each source's tablet limits beside the IP's, with a verdict per test."""
    rows = {s: _limits_row(s, key) for s in ("ip", "jp", "ph_int", "fda")}
    ip = rows["ip"]
    out = []
    for s, r in rows.items():
        if not r:
            continue
        if ip and s != "ip":
            r["dissolution_vs_ip"] = _vs(r["q_pct"], r["q_time_min"], ip["q_pct"], ip["q_time_min"], True)
            r["assay_vs_ip"] = _vs(r["assay_lo"], r["assay_hi"], ip["assay_lo"], ip["assay_hi"], False)
            r["method_vs_ip"] = _method_differs(r, ip)
        out.append(r)
    return {"rows": out, "has_ip": bool(ip)}


def _region_stats(rid: str, mols: list[dict[str, Any]]) -> dict[str, Any]:
    """The numbers and observations that matter for one country, from the organisation's molecules."""
    name = {m["key"]: m["name"] for m in mols}
    has = [m for m in mols if m["sources"][rid]["present"]]
    out: dict[str, Any] = {"with": len(has), "of": len(mols), "insights": []}
    ins = out["insights"]

    def add(tone: str, text: str, keys: list[str]) -> None:
        if keys:
            ins.append({"tone": tone, "text": text, "molecules": [name[k] for k in keys], "keys": keys})

    if rid == "ip":
        mons = [mo for m in has for mo in m["sources"]["ip"]["monographs"]]
        out["monographs"] = len(mons)
        out["unverified"] = sum(1 for mo in mons if not (mo.get("verified") or {}).get("by"))
        out["with_q"] = sum(1 for m in has if any((mo.get("dissolution") or {}).get("q_pct") is not None for mo in m["sources"]["ip"]["monographs"]))
        failed = []
        for m in has:
            primary = next((mo for mo in m["sources"]["ip"]["monographs"] if not mo["combination"]), m["sources"]["ip"]["monographs"][0])
            for f in m["your_failures"]:
                t = _TEST.get(f["name"])
                lim = primary.get(t) if t else None
                text = (lim.get("text") if isinstance(lim, dict) else lim) if lim else None
                if text:
                    failed.append({"molecule": m["name"], "key": m["key"], "test": f["name"], "count": f["count"], "limit": text, "monograph": primary["title"]})
        out["failed_against"] = sorted(failed, key=lambda x: -x["count"])
        add("rose", "No IP monograph: CDSCO holds these to another country's official pharmacopoeia — see Japan, WHO and the US.",
            [m["key"] for m in mols if not m["sources"]["ip"]["present"]])
        add("amber", "The IP entry states no Q: the models fall back to the next source in the chain for dissolution.",
            [m["key"] for m in has if not any((mo.get("dissolution") or {}).get("q_pct") is not None for mo in m["sources"]["ip"]["monographs"])])
    elif rid == "ph_eur":
        out["upcoming"] = sum(len(mo["upcoming"]) for m in has for mo in m["sources"]["ph_eur"]["monographs"])
        out["under_revision"] = sum(1 for m in has for mo in m["sources"]["ph_eur"]["monographs"] if mo["under_revision"])
        out["touching_failures"] = sum(1 for m in has if any(mo["touches_your_failures"] for mo in m["sources"]["ph_eur"]["monographs"]))
        add("rose", "A Ph. Eur. revision is published and applies on a future date.",
            [m["key"] for m in has if any(mo["upcoming"] for mo in m["sources"]["ph_eur"]["monographs"])])
        add("amber", "Under revision: a draft is out for comment in Pharmeuropa.",
            [m["key"] for m in has if any(mo["under_revision"] for mo in m["sources"]["ph_eur"]["monographs"])])
        add("indigo", "A revision touches a test these products have already failed in India.",
            [m["key"] for m in has if any(mo["touches_your_failures"] for mo in m["sources"]["ph_eur"]["monographs"])])
    else:
        rows = {m["key"]: next((r for r in m["compare"]["rows"] if r["source"] == rid), None) for m in mols}
        if rid == "fda":
            out["refer_usp"] = sum(1 for m in has if any(r["refers_to"] == "USP" for r in m["sources"]["fda"]["methods"]))
            add("rose", "FDA's 2018 guidance applies (Q 80% in 30 min, 500 mL 0.1 N HCl) and is stricter than the IP's Q.",
                [k for k, r in rows.items() if r and r.get("dissolution_vs_ip") == "stricter"])
            add("amber", "A US filing needs a different dissolution method from the IP's.",
                [k for k, r in rows.items() if r and r.get("method_vs_ip")])
            add("slate", "The method is in the USP monograph (not connected): FDA's database only refers to it.",
                [m["key"] for m in has if any(r["refers_to"] == "USP" for r in m["sources"]["fda"]["methods"]) and not rows[m["key"]]])
        else:
            short = next(r["short"] for r in REGIONS if r["id"] == rid)
            add("rose", f"{short} dissolution is stricter than the IP's: a batch that passes in India can fail here.",
                [k for k, r in rows.items() if r and r.get("dissolution_vs_ip") == "stricter"])
            add("rose", f"{short} assay range is narrower than the IP's.",
                [k for k, r in rows.items() if r and r.get("assay_vs_ip") == "stricter"])
            add("amber", f"{short} uses a different dissolution method (medium, speed or apparatus).",
                [k for k, r in rows.items() if r and r.get("method_vs_ip")])
            add("brand", f"A {short} monograph where the IP has none: the nearest official standard CDSCO can apply.",
                [m["key"] for m in has if not m["sources"]["ip"]["present"]])
            add("slate", f"{short} is looser than the IP on dissolution: the IP is the one to meet.",
                [k for k, r in rows.items() if r and r.get("dissolution_vs_ip") == "looser"])
    return out


def org_view(ontology_keys: list[str]) -> dict[str, Any]:
    from .insights import tracked_for, tracked_index

    eu = pharmacopoeia.org_tracker(ontology_keys)
    eu_rows = {r["key"]: r for r in eu["molecules"]}
    df = data.org_frame(ontology_keys)
    cats: dict[str, Counter] = defaultdict(Counter)
    prods: dict[str, Counter] = defaultdict(Counter)
    if not df.empty:
        index = tracked_index()
        for name, cat in zip(df["Name of Product"].astype(str), df["Failure_Category_Primary"].fillna("").astype(str)):
            for k in tracked_for(name, index):
                cats[k][cat] += 1
                prods[k][name] += 1
    from .lab import _source_rec

    issues = _ip_issues()
    mols = []
    for k in cats:
        p = data.cdmo()["patents"].get(k)
        srcs: dict[str, Any] = {}
        for s in ("ip", "jp", "ph_int"):
            rec = _source_rec(_FILE[s], k) or {}
            mons = [_monograph(s, m, issues) for m in rec.get("monographs") or []]
            mons.sort(key=lambda m: (m["combination"], m["form"] or ""))
            srcs[s] = {"present": bool(mons), "monographs": mons}
        fda = _fda_rows(k)
        srcs["fda"] = {"present": bool(fda), "methods": fda}
        pe = (eu_rows.get(k) or {}).get("monographs") or []
        srcs["ph_eur"] = {"present": bool(pe), "monographs": pe}
        lim = limits.resolve(k)["fields"]
        applies = {f: {"value": lim[f]["value"], "source": lim[f]["source"], "monograph": lim[f].get("monograph")}
                   for f in ("assay_lo", "assay_hi", "q_pct", "q_time_min", "medium") if f in lim}
        mols.append({"key": k, "name": p.api_name if p else k.replace("_", " ").title(), "alerts": sum(cats[k].values()),
                     "your_failures": [{"name": c, "count": n} for c, n in cats[k].most_common(5) if c],
                     "products": [n for n, _ in prods[k].most_common(3)], "sources": srcs, "compare": compare(k), "applies": applies})
    mols.sort(key=lambda m: -m["alerts"])
    regions = []
    for r in REGIONS:
        src = signals._load(_FILE.get(r["id"], "edqm_kd"))
        lic = src.get("licence")
        regions.append({**r, "source": {"title": src.get("title"), "url": src.get("url"), "retrieved_at": src.get("retrieved_at"),
                                        "edition": src.get("edition"), "licence": lic.get("name") if isinstance(lic, dict) else lic},
                        **_region_stats(r["id"], mols)})
    disagree = [m["key"] for m in mols if any(r.get("dissolution_vs_ip") == "stricter" or r.get("assay_vs_ip") == "stricter"
                                              for r in m["compare"]["rows"])]
    return {"regions": regions, "molecules": mols, "disagree": disagree,
            "ph_eur": {k: eu[k] for k in ("today", "upcoming", "schedule", "schedule_source", "source")},
            "scope": ("Molecules named in your CDSCO alerts. Each pharmacopoeia is shown as it states its limits; IP limits were "
                      "entered from the IP 2022 PDFs and are marked until checked against the printed edition. Ph. Eur. limits are "
                      "in the paid text and are not compared; the USP is not connected.")}
