"""Health & trade signals for the Playground: NFHS burden by district, IDSP outbreaks, UN Comtrade pharma trade.

Reads data/sources/{nfhs,idsp,comtrade}.json (written by redis-loader/sources/health_signals.py) and
re-reads a file only when it changes.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Optional

from .config import settings

_files: dict[str, tuple[float, dict[str, Any]]] = {}


def _load(name: str) -> dict[str, Any]:
    p = settings.data_dir / "sources" / f"{name}.json"
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    hit = _files.get(name)
    if hit and hit[0] == m:
        return hit[1]
    try:
        _files[name] = (m, json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}
    return _files[name][1]


def _meta(d: dict[str, Any]) -> Optional[dict[str, Any]]:
    return {k: d.get(k) for k in ("title", "publisher", "url", "retrieved_at", "records")} if d else None


def meta() -> dict[str, Any]:
    return {"nfhs": _meta(_load("nfhs")), "idsp": _meta(_load("idsp")), "comtrade": _meta(_load("comtrade"))}


# ------------------------------------------------------------------------------------------ NFHS

def nfhs(ind: str = "sugar_women", rnd: str = "", state: str = "") -> dict[str, Any]:
    d = _load("nfhs")
    rows = d.get("data") or []
    if not rows:
        return {"available": False}
    inds = d.get("indicators") or {}
    have = Counter(r["ind"] for r in rows)
    ind = ind if ind in have else (max(have, key=have.get) if have else ind)
    rounds = sorted({r["round"] for r in rows if r["ind"] == ind})  # e.g. blood sugar was not measured this way in NFHS-4
    rnd = rnd if rnd in rounds else rounds[-1]
    prev = next((r for r in reversed(rounds) if r < rnd), None)
    sel = [r for r in rows if r["ind"] == ind]

    def by(level: str, round_: Optional[str]) -> dict[tuple, float]:
        return {(r.get("state") or "", r.get("district") or ""): r["value"] for r in sel if r["level"] == level and r["round"] == round_}

    cur_d, prev_d = by("district", rnd), by("district", prev)
    cur_s, prev_s = by("state", rnd), by("state", prev)
    # states without a state-level row: mean of their districts (unweighted — marked as such)
    derived = set()
    for (st, _), _v in list(cur_d.items()):
        if st and (st, "") not in cur_s:
            vals = [v for (s2, _d), v in cur_d.items() if s2 == st]
            cur_s[(st, "")] = round(sum(vals) / len(vals), 1)
            derived.add(st)
    india = next((r["value"] for r in sel if r["level"] == "india" and r["round"] == rnd), None)
    dist = [{"state": st, "district": di, "value": v, "prev": prev_d.get((st, di)),
             "change": round(v - prev_d[(st, di)], 1) if (st, di) in prev_d else None}
            for (st, di), v in cur_d.items() if not state or st == state]
    dist.sort(key=lambda x: -x["value"])
    states = [{"name": st, "count": v, "prev": prev_s.get((st, "")), "change": round(v - prev_s[(st, "")], 1) if (st, "") in prev_s else None,
               "from_districts": st in derived} for (st, _), v in cur_s.items()]
    states.sort(key=lambda x: -x["count"])
    risers = sorted([x for x in dist if x["change"] is not None], key=lambda x: -x["change"])[:10]
    return {"available": True, "indicator": ind, "round": rnd, "previous_round": prev, "rounds": rounds,
            "indicators": [{"key": k, **inds.get(k, {"label": k, "group": ""}), "values": have.get(k, 0)} for k in inds if have.get(k)],
            "india": india, "states": states, "districts": dist[:300], "districts_total": len(dist), "risers": risers,
            "meta": _meta(d),
            "note": "NFHS fact-sheet percentages (survey estimates). Values in brackets in the fact sheets rest on 25–49 cases; "
                    "state values marked 'from districts' are unweighted district means where no state row was loaded."}


# ------------------------------------------------------------------------------------------ IDSP

def _tracked(names: list[str]) -> list[dict[str, str]]:
    try:
        import ingredients as ing

        from . import data

        pats = data.cdmo()["patents"]
        out = []
        for n in names:
            k = ing.ingredient_key(n)
            hit = k if k in pats else next((pk for pk in pats if pk.split()[0] == k.split()[0]), None) if k else None
            out.append({"name": n, "key": hit} if hit else {"name": n})
        return out
    except Exception:
        return [{"name": n} for n in names]


def outbreaks(weeks: int = 26, disease: str = "", state: str = "") -> dict[str, Any]:
    d = _load("idsp")
    rows = d.get("data") or []
    if not rows:
        return {"available": False}
    all_weeks = sorted({r["week"] for r in rows if r.get("week")})
    keep = set(all_weeks[-weeks:]) if all_weeks else set()
    sel = [r for r in rows if (not keep or r.get("week") in keep)]
    diseases = Counter(r["disease_key"] for r in sel)
    if disease:
        sel = [r for r in sel if r["disease_key"] == disease]
    if state:
        sel = [r for r in sel if (r.get("state") or "") == state]
    by_dis: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in sel:
        v = by_dis[r["disease_key"]]
        v[0] += 1
        v[1] += r.get("cases") or 0
        v[2] += r.get("deaths") or 0
    top = [k for k, _ in Counter({k: v[0] for k, v in by_dis.items()}).most_common(5)]
    wk = sorted({r["week"] for r in sel if r.get("week")})
    series = {"months": wk, "series": [{"name": k, "values": [sum(1 for r in sel if r["disease_key"] == k and r.get("week") == w) for w in wk]} for k in top]}
    st = Counter()
    for r in sel:
        st[r.get("state") or "Unknown"] += 1
    districts = Counter((r.get("state") or "", r.get("district") or "") for r in sel)
    meds = (d.get("diseases") or {})
    return {"available": True, "weeks": wk, "weeks_available": len(all_weeks), "diseases_all": [{"name": k, "count": v} for k, v in diseases.most_common()],
            "by_disease": [{"disease": k, "outbreaks": v[0], "cases": v[1], "deaths": v[2], "medicines": _tracked(meds.get(k, []))}
                           for k, v in sorted(by_dis.items(), key=lambda kv: -kv[1][0])],
            "series": series, "states": [{"name": k, "count": v} for k, v in st.most_common()],
            "districts": [{"state": s, "district": di, "outbreaks": n} for (s, di), n in districts.most_common(15)],
            "latest": sorted(sel, key=lambda r: (r.get("reported") or r.get("start") or ""), reverse=True)[:25],
            "meta": _meta(d),
            "note": "Outbreaks reported to IDSP by districts (events, not all cases). Medicines listed are the usual treatments — "
                    "demand signals, not prescriptions."}


# ------------------------------------------------------------------------------------------ Comtrade

def trade(hs: str = "", flow: str = "export") -> dict[str, Any]:
    d = _load("comtrade")
    rows = d.get("data") or []
    if not rows:
        return {"available": False}
    codes = d.get("hs") or {}
    years = sorted({r["year"] for r in rows})
    world = [r for r in rows if r["partner_code"] == 0]
    partners = [r for r in rows if r["partner_code"] != 0]
    # yearly totals by HS code and flow (World partner row; sum of partners when missing)
    tot: dict[tuple, float] = defaultdict(float)
    for r in world:
        tot[(r["hs"], r["flow"], r["year"])] = r["value_usd"]
    world_keys = {(w["hs"], w["flow"], w["year"]) for w in world}
    for r in partners:
        if (r["hs"], r["flow"], r["year"]) not in world_keys:
            tot[(r["hs"], r["flow"], r["year"])] += r["value_usd"]
    table = []
    for code, meta_ in codes.items():
        ex = [round(tot.get((code, "export", y), 0) / 1e6, 1) for y in years]
        im = [round(tot.get((code, "import", y), 0) / 1e6, 1) for y in years]
        table.append({"hs": code, **meta_, "exports_musd": ex, "imports_musd": im})
    sel_codes = [hs] if hs else list(codes)
    latest = max((y for y in years if any(r["year"] == y and r["flow"] == flow and r["hs"] in sel_codes for r in partners)), default=years[-1])
    part = Counter()
    for r in partners:
        if r["year"] == latest and r["flow"] == flow and r["hs"] in sel_codes:
            part[r["partner"]] += r["value_usd"]
    total_latest = sum(part.values()) or 1.0
    # API import dependence on China: share of India's imports of API codes coming from China, per year
    api = [c for c, m in codes.items() if m.get("group") == "api"]
    china = []
    for y in years:
        imp = [r for r in partners if r["year"] == y and r["flow"] == "import" and r["hs"] in api]
        t = sum(r["value_usd"] for r in imp)
        cn = sum(r["value_usd"] for r in imp if r.get("partner_iso") == "CHN" or r.get("partner_code") == 156)
        china.append({"year": y, "share_pct": round(100 * cn / t, 1) if t else None, "imports_musd": round(t / 1e6, 1)})
    return {"available": True, "years": years, "codes": table, "flow": flow, "hs": hs, "latest_year": latest,
            "partners": [{"name": k, "count": round(v / 1e6, 1), "share_pct": round(100 * v / total_latest, 1)} for k, v in part.most_common(15)],
            "china_api_share": china, "mode": d.get("mode"), "meta": _meta(d),
            "note": "US$ million, as reported by India (exports FOB, imports CIF). HS codes are product classes — 3004 is all dosed "
                    "medicines, 2941 all antibiotics — not single molecules."}


# ------------------------------------------------------------------------------------------ Open Reaction Database

_EQUIPMENT = {
    "hydrogenation": "Hydrogenator / pressure reactor rated for H₂, catalyst filtration, flameproof (zone 1) area",
    "cryogenic": "Cryogenic reactor (−20 to −90 °C) with liquid-nitrogen or thermal-fluid chilling",
    "high_temperature": "Hot-oil heated reactor (≥ 150 °C)",
    "pressure": "Pressure-rated reactor (> 2 bar)",
    "organometallic": "Moisture-free, nitrogen-blanketed reactors; pyrophoric reagent handling",
    "hazardous": "Containment and quench systems for azide / cyanide / phosgene / hydride reagents",
    "pd_coupling": "Metal scavenging and ICH Q3D residual-palladium testing",
    "chlorinated_solvent": "Chlorinated-solvent recovery and emission control",
}


def synthesis(key: str) -> dict[str, Any]:
    d = _load("ord")
    rows = d.get("data") or {}
    if not rows:
        return {"available": False}
    m = rows.get(key)
    labels = d.get("needs") or {}
    if not m:
        return {"available": True, "found": False, "meta": _meta(d)}
    return {"available": True, "found": True, **m,
            "needs": [{"key": k, "label": labels.get(k, k), "equipment": _EQUIPMENT.get(k), **v} for k, v in (m.get("needs") or {}).items()],
            "meta": _meta(d), "licence": d.get("licence"),
            "note": "Reactions whose product is this molecule (salts and stereo forms included), from patents and papers in the "
                    "Open Reaction Database. They show routes that have been used, not the route any one maker runs."}
