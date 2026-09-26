"""Playground: the exploratory views of the old apps, rebuilt on the platform
data, plus cross-cutting analytics.

* cube()       — filterable national NSQ view: map by state, heatmaps, Sankey
* ledger()     — sortable / column-choosable alert ledger (+ CSV)
* insights()   — derived analytics (shelf-life at failure, detection lag,
                 lab effect, repeat offenders, hubs, FDA overlap, export whitespace)
* world()      — regulation by market + per-country molecule status
* workbench()  — one molecule: passport, demand, complexity, pillar scores,
                 Orange Book and pharmacopoeia comparison, national NSQ record
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import math
import re
import threading
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Optional

import pandas as pd

from . import data, insights, sites

_MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
_lock = threading.Lock()
MIN_STATE_ALERTS = 20
_geo_cache: dict[str, Any] = {}


# --- filters -------------------------------------------------------------------

def _norm_source(s: str) -> str:
    s = (s or "").lower()
    if "cdsco" in s:
        return "CDSCO lab"
    if "state" in s:
        return "State lab"
    return "Other"


def base_frame() -> pd.DataFrame:
    df = data.frame()
    if df.empty:
        return df
    if "_src" not in df.columns:
        df = df.copy()
        df["_src"] = df["Reporting Source"].astype(str).map(_norm_source)
        df["_state"] = df["Mfg_State"].fillna("").astype(str).replace("", "Unknown")
        df["_month"] = df["Parsed_Date"].dt.strftime("%Y-%m")
    return df


def apply_filters(df: pd.DataFrame, f: dict[str, Any]) -> pd.DataFrame:
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    focus = f.get("focus") or "all"
    if focus == "dissolution":
        m &= df["Is_Dissolution"].astype(bool)
    elif focus == "non_dissolution":
        m &= ~df["Is_Dissolution"].astype(bool)
    for key, col in (("drug_type", "Drug type"), ("form", "Form type"), ("category", "Failure_Category_Primary"),
                     ("state", "_state"), ("source", "_src")):
        vals = [v for v in (f.get(key) or []) if v]
        if vals:
            m &= df[col].isin(vals)
    auth = f.get("authenticity") or ""
    if auth and "_spurious" in df.columns:
        m &= df["_spurious"] if auth == "spurious" else ~df["_spurious"]
    if f.get("since"):
        m &= df["_month"] >= f["since"]
    if f.get("until"):
        m &= df["_month"] <= f["until"]
    q = (f.get("q") or "").strip().lower()
    if q:
        hay = (df["Name of Product"].astype(str) + " " + df["Manufactured By"].astype(str) + " "
               + df["Product_Name_Canonical"].astype(str) + " " + df["Mfg_Company_Canonical"].astype(str)).str.lower()
        m &= hay.str.contains(re.escape(q), regex=True)
    return df[m]


def facets() -> dict[str, Any]:
    df = base_frame()
    def opts(col, top=60):
        return [{"name": str(k), "count": int(v)} for k, v in df[col].fillna("Unknown").value_counts().head(top).items()]
    months = sorted(df["_month"].dropna().unique().tolist())
    return {"drug_type": opts("Drug type"), "form": opts("Form type"), "category": opts("Failure_Category_Primary"),
            "state": opts("_state"), "source": opts("_src"), "months": months}


# --- cube ------------------------------------------------------------------------

def _matrix(df: pd.DataFrame, rows_col: str, cols_col: str, top_r: int, top_c: int) -> dict[str, Any]:
    if df.empty:
        return {"rows": [], "cols": [], "values": []}
    rows = df[rows_col].fillna("Unknown").value_counts().head(top_r).index.tolist()
    cols = df[cols_col].fillna("Unknown").value_counts().head(top_c).index.tolist()
    sub = df[df[rows_col].isin(rows) & df[cols_col].isin(cols)]
    piv = sub.groupby([rows_col, cols_col]).size().unstack(fill_value=0).reindex(index=rows, columns=cols, fill_value=0)
    return {"rows": [str(r) for r in rows], "cols": [str(c) for c in cols], "values": piv.astype(int).values.tolist()}


def _mfr_label(df: pd.DataFrame) -> pd.Series:
    return df["Mfg_Company_Canonical"].fillna("").astype(str).str.replace(r"^M/s\.?\s*", "", regex=True).str.strip().replace("", "Unknown")


def _sankey(df: pd.DataFrame, cols: list[str], tops: list[int]) -> dict[str, Any]:
    d = df.copy()
    for c, t in zip(cols, tops):
        keep = d[c].fillna("Unknown").value_counts().head(t).index
        d[c] = d[c].fillna("Unknown").where(d[c].isin(keep), "Other")
    nodes: list[dict[str, Any]] = []
    idx: dict[tuple[int, str], int] = {}
    for level, c in enumerate(cols):
        for v in d[c].value_counts().index:
            idx[(level, v)] = len(nodes)
            nodes.append({"name": str(v), "level": level})
    links = []
    for level in range(len(cols) - 1):
        g = d.groupby([cols[level], cols[level + 1]]).size()
        for (a, b), n in g.items():
            if n > 0:
                links.append({"source": idx[(level, a)], "target": idx[(level + 1, b)], "value": int(n)})
    return {"nodes": nodes, "links": links}


def cube(f: dict[str, Any]) -> dict[str, Any]:
    df = apply_filters(base_frame(), f)
    n = len(df)
    if n == 0:
        return {"empty": True, "kpis": {"alerts": 0}}
    d = df.assign(_mfr=_mfr_label(df))
    # Company rankings use only alerts attributable to the named maker: a
    # spurious (counterfeit) batch carries a company's name it did not make.
    spur = d["_spurious"] if "_spurious" in d.columns else pd.Series(False, index=d.index)
    da = d[~spur]
    ing_rows = []
    for mfr, prod in zip(da["_mfr"], da["Name of Product"].astype(str)):
        for i in insights.product_ingredients(prod)[:3]:
            ing_rows.append((mfr, i))
    ing = pd.DataFrame(ing_rows, columns=["_mfr", "_ing"]) if ing_rows else pd.DataFrame(columns=["_mfr", "_ing"])
    states = d.groupby("_state").agg(alerts=("record_id", "size"), dissolution=("Is_Dissolution", "sum")).sort_values("alerts", ascending=False)
    makers = da.groupby("_state")["_mfr"].nunique()
    att_alerts = da.groupby("_state").size()
    states["manufacturers"] = makers.reindex(states.index).fillna(0).astype(int)
    states["attributable"] = att_alerts.reindex(states.index).fillna(0).astype(int)
    nat_rate = len(da) / max(int(da["_mfr"].nunique()), 1)
    return {
        "empty": False,
        "kpis": {
            "alerts": n, "manufacturers": int(da["_mfr"].nunique()), "spurious": int(spur.sum()), "products": int(d["Product_Name_Canonical"].nunique()),
            "states": int((states.index != "Unknown").sum()), "labs": int(d["Reporting by Lab/State"].nunique()),
            "dissolution_share": round(100 * float(d["Is_Dissolution"].astype(bool).mean()), 1),
            "cdsco_share": round(100 * float((d["_src"] == "CDSCO lab").mean()), 1),
        },
        "period": insights._period(d),
        "trend": insights._month_series(d, "Failure_Category_Primary", top=7),
        # Raw counts follow where samples were drawn and how many plants a state
        # has; per-maker intensity (indexed to the national average) is the
        # fairer comparison. Small states are left out of the index.
        "states": [{"name": s, "count": int(r.alerts), "manufacturers": int(r.manufacturers),
                    "per_maker": round(r.attributable / r.manufacturers, 2) if r.manufacturers else None,
                    "intensity": (round((r.attributable / r.manufacturers) / nat_rate, 2)
                                  if r.manufacturers and r.attributable >= MIN_STATE_ALERTS else None),
                    "dissolution_pct": round(100 * r.dissolution / max(r.alerts, 1), 1)} for s, r in states.iterrows()],
        "national_per_maker": round(nat_rate, 2),
        "categories": insights._counts(d, "Failure_Category_Primary", 20),
        "forms": insights._counts(d, "Form type", 12),
        "drug_types": insights._counts(d, "Drug type", 12),
        "labs": insights._counts(d, "Reporting by Lab/State", 15),
        "sources": insights._counts(d, "_src", 4),
        "top_products": insights._counts(d, "Product_Name_Canonical", 12),
        "top_manufacturers": [{"name": k, "count": int(v)} for k, v in da["_mfr"].value_counts().head(15).items()],
        "heat_form_lab": _matrix(d, "Form type", "Reporting by Lab/State", 10, 10),
        "heat_mfr_reason": _matrix(da, "_mfr", "Failure_Category_Primary", int(f.get("top_mfr") or 15), 12),
        "heat_mfr_molecule": _matrix(ing, "_mfr", "_ing", 15, 12),
        "sankey_state": _sankey(d, ["_state", "Drug type", "Failure_Category_Primary"], [8, 6, 6]),
        "sankey_molecule": _sankey(d.assign(_ing=d["Name of Product"].astype(str).map(lambda p: (insights.product_ingredients(p) or ["unknown"])[0])),
                                   ["Drug type", "_ing", "Failure_Category_Primary"], [6, 10, 6]),
    }


# --- ledger ------------------------------------------------------------------------

LEDGER_COLS = {
    "month": ("_month", "Month"), "product": ("Name of Product", "Product"), "batch": ("Batch No", "Batch"),
    "manufacturer": ("Manufactured By", "Manufacturer (as printed)"), "company": ("Mfg_Company_Canonical", "Company"),
    "state": ("_state", "State"), "city": ("Mfg_City", "City"), "category": ("Failure_Category_Primary", "Failure category"),
    "reason": ("NSQ Result", "NSQ result"), "form": ("Form type", "Form"), "drug_type": ("Drug type", "Drug type"),
    "lab": ("Reporting by Lab/State", "Testing lab"), "source": ("_src", "Lab type"), "mfg": ("Manufacturing Date", "Mfg"),
    "exp": ("Expiry Date", "Exp"), "website": ("Mfg_Website", "Website"), "product_key": ("Product_Ontology_Key", "Product key"),
    "company_key": ("Mfg_Ontology_Key", "Company key"), "flag": ("_flag", "Authenticity"), "record": ("record_id", "Record id"),
}
# The old branch's "Scientific context research" / "Regulatory guidelines
# research" columns were filled from a per-ingredient template (or generic
# boilerplate), not researched per alert, so they are not offered here.
DEFAULT_COLS = ["month", "product", "company", "state", "category", "reason", "form", "lab", "flag"]
SPURIOUS_FLAG = "Declared spurious: the maker on the label may not be the real maker"


def _with_flag(df: pd.DataFrame) -> pd.DataFrame:
    spur = df["_spurious"] if "_spurious" in df.columns else pd.Series(False, index=df.index)
    return df.assign(_flag=spur.map({True: SPURIOUS_FLAG, False: ""}))


def ledger(f: dict[str, Any], cols: list[str], sort: str, desc: bool, page: int, size: int) -> dict[str, Any]:
    df = _with_flag(apply_filters(base_frame(), f))
    cols = [c for c in cols if c in LEDGER_COLS] or DEFAULT_COLS
    sort_col = LEDGER_COLS.get(sort, LEDGER_COLS["month"])[0]
    df = df.sort_values(sort_col, ascending=not desc, na_position="last", kind="stable")
    total = len(df)
    pages = max(1, math.ceil(total / size))
    page = max(1, min(page, pages))
    sub = df.iloc[(page - 1) * size: page * size]
    rows = [{c: insights._s(r[LEDGER_COLS[c][0]]) for c in cols} for _, r in sub.iterrows()]
    return {"total": total, "page": page, "pages": pages, "cols": [{"key": c, "label": LEDGER_COLS[c][1]} for c in cols],
            "all_cols": [{"key": k, "label": v[1]} for k, v in LEDGER_COLS.items()], "rows": rows}


def ledger_csv(f: dict[str, Any], cols: list[str], sort: str, desc: bool) -> str:
    df = _with_flag(apply_filters(base_frame(), f))
    cols = [c for c in cols if c in LEDGER_COLS] or DEFAULT_COLS
    df = df.sort_values(LEDGER_COLS.get(sort, LEDGER_COLS["month"])[0], ascending=not desc, na_position="last")
    out = df[[LEDGER_COLS[c][0] for c in cols]].rename(columns={LEDGER_COLS[c][0]: LEDGER_COLS[c][1] for c in cols})
    buf = io.StringIO()
    out.to_csv(buf, index=False)
    return buf.getvalue()


# --- geo ----------------------------------------------------------------------------

def _round_coords(obj: Any, nd: int = 3) -> Any:
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(obj[0], nd), round(obj[1], nd)]
        out = [_round_coords(x, nd) for x in obj]
        # drop consecutive duplicate points created by rounding
        if out and isinstance(out[0], list) and out[0] and isinstance(out[0][0], (int, float)):
            ded = [out[0]] + [p for i, p in enumerate(out[1:], 1) if p != out[i - 1]]
            return ded if len(ded) >= 4 else out
        return out
    return obj


def india_geo() -> Optional[dict[str, Any]]:
    with _lock:
        if "india" in _geo_cache:
            return _geo_cache["india"]
        raw = data.redis_client().get("geo:india_states")
        if not raw:
            return None
        try:
            text = gzip.decompress(base64.b64decode(raw)).decode("utf-8")
        except Exception:
            text = raw
        g = json.loads(text)
        feats = []
        for ft in g.get("features", []):
            name = (ft.get("properties") or {}).get("NAME_1") or (ft.get("properties") or {}).get("name") or ""
            geom = ft.get("geometry") or {}
            feats.append({"type": "Feature", "properties": {"name": name},
                          "geometry": {"type": geom.get("type"), "coordinates": _round_coords(geom.get("coordinates"), 2)}})
        _geo_cache["india"] = {"type": "FeatureCollection", "features": feats}
        return _geo_cache["india"]


# --- insights ---------------------------------------------------------------------------

def _ym(s: Any) -> Optional[int]:
    """'Sep-2021' -> months since year 0."""
    s = str(s or "").strip()
    m = re.match(r"([A-Za-z]{3})[a-z]*[-/ ]?(\d{2,4})", s)
    if not m:
        return None
    mon = _MON.get(m.group(1).upper())
    y = int(m.group(2))
    if y < 100:
        y += 2000
    return y * 12 + mon - 1 if mon else None


_ins_cache: dict[tuple, dict[str, Any]] = {}


def _by_company(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    for s in rows:
        a = agg.setdefault(s["ontology_key"], {"company": s["company"], "alerts": 0, "sites": 0})
        a["alerts"] += s["alerts"]
        a["sites"] += 1
    return sorted(agg.values(), key=lambda x: -x["alerts"])[:25]


def insights_view() -> dict[str, Any]:
    key = (id(data.frame()), id(data.cdmo()), sites._mtimes())
    hit = _ins_cache.get(key)
    if hit is None:
        _ins_cache.clear()
        hit = _ins_cache[key] = _insights_view()
    return hit


def _insights_view() -> dict[str, Any]:
    full = base_frame()
    spur = full[full["_spurious"]] if "_spurious" in full.columns else full.iloc[0:0]
    df = full[~full["_spurious"]] if "_spurious" in full.columns else full
    d = df.assign(_mfr=_mfr_label(df))
    rep = d["Reporting Month & Year"].map(_ym)
    mfg = d["Manufacturing Date"].map(_ym)
    exp = d["Expiry Date"].map(_ym)
    life = (exp - mfg)
    age = (rep - mfg)
    frac = (age / life).where((life > 0) & age.notna())

    # 1. When in its shelf life does a batch fail?
    bins = [-0.01, 0.25, 0.5, 0.75, 1.0, 10]
    labels = ["first quarter", "second quarter", "third quarter", "last quarter", "after expiry"]
    d = d.assign(_life_bucket=pd.cut(frac, bins=bins, labels=labels), _age=age)
    cats = d["Failure_Category_Primary"].value_counts().head(8).index.tolist()
    shelf = []
    for c in cats:
        sub = d[d["Failure_Category_Primary"] == c]
        vc = sub["_life_bucket"].value_counts()
        tot = int(vc.sum())
        if tot:
            shelf.append({"category": c, "n": tot, "median_months": float(sub["_age"].median()) if sub["_age"].notna().any() else None,
                          **{lab: round(100 * int(vc.get(lab, 0)) / tot, 1) for lab in labels}})
    lag_hist = age[(age >= 0) & (age <= 48)].value_counts().sort_index()
    forms_age = (d.dropna(subset=["_age"]).groupby("Form type")["_age"].median().sort_values())

    # 2. Does the testing lab change what is found?
    src = d[d["_src"].isin(["CDSCO lab", "State lab"])]
    ct = pd.crosstab(src["Failure_Category_Primary"], src["_src"], normalize="columns") * 100
    lab_mix = [{"category": c, "cdsco": round(float(ct.loc[c].get("CDSCO lab", 0)), 1), "state": round(float(ct.loc[c].get("State lab", 0)), 1)}
               for c in d["Failure_Category_Primary"].value_counts().head(10).index if c in ct.index]
    labs = d.groupby("Reporting by Lab/State").agg(alerts=("record_id", "size"), dissolution=("Is_Dissolution", "sum"),
                                                   manufacturers=("_mfr", "nunique")).query("alerts >= 40")
    labs["dissolution_pct"] = 100 * labs["dissolution"] / labs["alerts"]
    lab_rows = [{"lab": k, "alerts": int(r.alerts), "dissolution_pct": round(float(r.dissolution_pct), 1), "manufacturers": int(r.manufacturers)}
                for k, r in labs.sort_values("dissolution_pct", ascending=False).iterrows()][:15]

    # 3. Repeat offenders
    g = d.groupby("_mfr").agg(alerts=("record_id", "size"), months=("_month", "nunique"), products=("Product_Name_Canonical", "nunique"),
                              first=("_month", "min"), last=("_month", "max"), state=("_state", lambda s: s.mode().iat[0] if not s.mode().empty else ""))
    rep_pairs = d.groupby(["_mfr", "Product_Name_Canonical", "Failure_Category_Primary"]).size()
    repeats = rep_pairs[rep_pairs > 1].groupby(level=0).sum()
    g["repeat_alerts"] = repeats.reindex(g.index).fillna(0).astype(int)
    g = g[g.index != "Unknown"]
    tiers = [("1 alert", g.alerts == 1), ("2–4", g.alerts.between(2, 4)), ("5–9", g.alerts.between(5, 9)), ("10+", g.alerts >= 10)]
    concentration = [{"tier": t, "manufacturers": int(mask.sum()), "alerts": int(g.alerts[mask].sum()),
                      "alert_share": round(100 * float(g.alerts[mask].sum()) / max(int(g.alerts.sum()), 1), 1)} for t, mask in tiers]
    offenders = [{"manufacturer": k, **{c: (int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for c, v in r.items()}}
                 for k, r in g.sort_values(["months", "alerts"], ascending=False).head(20).iterrows()]

    # 4. Manufacturing hubs (PIN clusters) and FDA overlap
    dir_ = sites.directory()
    pins: dict[str, dict[str, Any]] = {}
    for s in dir_:
        if not s["pincode"]:
            continue
        p = pins.setdefault(s["pincode"], {"pin": s["pincode"], "city": s["city"], "state": s["state"], "sites": 0, "alerts": 0, "fda": 0})
        p["sites"] += 1
        p["alerts"] += s["alerts"]
        p["fda"] += 1 if s["fda"]["registered"] else 0
    hubs = sorted(pins.values(), key=lambda x: -x["alerts"])[:15]
    reg = [s for s in dir_ if s["fda"]["registered"]]
    nonreg = [s for s in dir_ if not s["fda"]["registered"]]

    def prof(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"sites": 0}
        alerts = sum(r["alerts"] for r in rows)
        inj = sum(r["forms"].get("Injection", 0) for r in rows)
        cats = Counter()
        for r in rows:
            cats.update(r["categories"])
        return {"sites": len(rows), "alerts": alerts, "alerts_per_site": round(alerts / len(rows), 1),
                "injection_share": round(100 * inj / max(alerts, 1), 1),
                "top_categories": [{"name": k, "count": v} for k, v in cats.most_common(4)]}

    fda_overlap = {"registered": prof(reg), "not_registered": prof(nonreg),
                   "import_alert_companies": _by_company([s for s in dir_ if s["fda"]["import_alert"]]),
                   "registered_sites": [{"company": s["company"], "state": s["state"], "alerts": s["alerts"], "match": s["fda"]["match"],
                                         "operations": (s["fda"]["establishments"] or [{}])[0].get("operations"), "id": s["id"]}
                                        for s in sorted(reg, key=lambda x: -x["alerts"])][:25]}

    # 5. Export whitespace: molecules Indian firms make (NSQ) that are off-patent in the US with few Indian ANDA holders
    ws = []
    for key, p in data.cdmo()["patents"].items():
        sig = getattr(p, "signals", None) or {}
        ob, nsq = sig.get("orange_book") or {}, sig.get("nsq") or {}
        if not ob or not nsq:
            continue
        us_open = (p.estimated_loe_us is None) or (p.estimated_loe_us <= date.today())
        makers, ind = int(nsq.get("manufacturers") or 0), len(ob.get("indian_anda_holders") or [])
        andas = int(ob.get("anda_active") or 0)
        ws.append({"key": key, "name": p.api_name, "indian_makers": makers, "indian_anda_holders": ind, "anda_active": andas,
                   "us_open": us_open, "eu_generics": (sig.get("ema") or {}).get("generics"),
                   "whitespace": round(makers / (1 + ind) * (1.0 if us_open else 0.3), 1)})
    ws.sort(key=lambda x: -x["whitespace"])

    # 6. Seasonality of manufacture (monsoon humidity) for moisture-sensitive failures
    mfg_month = d["Manufacturing Date"].map(lambda s: _ym(s) % 12 + 1 if _ym(s) is not None else None)
    season = []
    focus_cats = [c for c in ("Description / Appearance", "Dissolution", "Assay / Content", "Disintegration") if c in cats or c in d["Failure_Category_Primary"].values]
    base = mfg_month.value_counts()
    for mth in range(1, 13):
        row = {"month": mth, "alerts": int(base.get(mth, 0))}
        sub = d[mfg_month == mth]
        for c in focus_cats:
            row[c] = round(100 * float((sub["Failure_Category_Primary"] == c).mean()), 1) if len(sub) else 0
        season.append(row)

    return {
        "shelf_life": {"buckets": labels, "rows": shelf,
                       "lag_hist": [{"months": int(k), "alerts": int(v)} for k, v in lag_hist.items()],
                       "median_age_by_form": [{"name": k, "months": float(v)} for k, v in forms_age.items() if k][:10],
                       "after_expiry": int((d["_life_bucket"] == "after expiry").sum()), "with_dates": int(frac.notna().sum())},
        "labs": {"mix": lab_mix, "top": lab_rows},
        "repeat": {"concentration": concentration, "top": offenders,
                   "repeat_share": round(100 * float(g.repeat_alerts.sum()) / max(int(g.alerts.sum()), 1), 1)},
        "hubs": hubs,
        "fda_overlap": fda_overlap,
        "whitespace": ws[:25],
        "seasonality": {"categories": focus_cats, "rows": season},
        "spurious": {
            "alerts": int(len(spur)), "share": round(100 * len(spur) / max(len(full), 1), 2),
            "products": [{"name": str(k), "count": int(v)} for k, v in spur["Product_Name_Canonical"].fillna(spur["Name of Product"]).value_counts().head(10).items()],
            "labs": [{"name": str(k), "count": int(v)} for k, v in spur["Reporting by Lab/State"].value_counts().head(8).items()],
            "drug_types": [{"name": str(k), "count": int(v)} for k, v in spur["Drug type"].fillna("Unknown").value_counts().head(8).items()],
            "by_year": [{"name": str(k), "count": int(v)} for k, v in spur["Parsed_Date"].dt.year.value_counts().sort_index().items()],
        },
    }


# --- world ---------------------------------------------------------------------------------

def world(molecule: str = "") -> dict[str, Any]:
    import regulatory_regions as rr

    m = data.cdmo()
    counts: dict[str, Counter] = defaultdict(Counter)
    for key, p in m["patents"].items():
        for g in p.geo_coverage or []:
            c = g.country_code
            counts[c][g.market_status] += 1
            if g.export_eligible:
                counts[c]["export_eligible"] += 1
    per_mol = None
    if molecule and molecule in m["patents"]:
        p = m["patents"][molecule]
        per_mol = {"key": molecule, "name": p.api_name,
                   "countries": {g.country_code: {"status": g.market_status, "loe": g.loe_date.isoformat() if g.loe_date else None,
                                                  "export_eligible": g.export_eligible, "barrier": g.patent_barrier, "notes": g.notes}
                                 for g in p.geo_coverage or []},
                   "provenance": (getattr(p, "provenance", {}) or {}).get("geo_coverage")}
    # Data-backed market facts
    df = base_frame()
    dir_ = sites.directory()
    us_open = sum(1 for p in m["patents"].values() if (getattr(p, "signals", {}) or {}).get("orange_book") and (p.estimated_loe_us is None or p.estimated_loe_us <= date.today()))
    eu_gen = sum(1 for p in m["patents"].values() if ((getattr(p, "signals", {}) or {}).get("ema") or {}).get("generics"))
    facts = {
        "IN": {"NSQ alerts": len(df), "Manufacturing sites with alerts": len(dir_),
               "FDA-registered NSQ sites": sum(1 for s in dir_ if s["fda"]["registered"]),
               "NSQ companies on FDA Import Alert 66-40 (name match)": len({s["ontology_key"] for s in dir_ if s["fda"]["import_alert"]})},
        "US": {"Tracked molecules off-patent (Orange Book)": us_open,
               "Active ANDAs across tracked molecules": sum(int(((getattr(p, "signals", {}) or {}).get("orange_book") or {}).get("anda_active") or 0) for p in m["patents"].values())},
        "EU": {"Tracked molecules with EU generics (EMA)": eu_gen},
    }
    return {
        **rr.table(),
        "molecule_counts": {c: dict(v) for c, v in counts.items()},
        "molecule_total": len(m["patents"]),
        "facts": facts,
        "molecule": per_mol,
        "molecules": sorted(({"key": k, "name": p.api_name} for k, p in m["patents"].items()), key=lambda x: x["name"].lower()),
    }


# --- molecule workbench ----------------------------------------------------------------------------

def workbench(key: str, weights: Optional[dict[str, float]], plant_ids: list[str], plant_id: str = "") -> Optional[dict[str, Any]]:
    from intelligence_scorer import derive_manufacturing_complexity, score_candidate

    m = data.cdmo()
    p = m["patents"].get(key)
    if p is None:
        return None
    reg, dem = m["regulatory"].get(key), m["demand"].get(key)
    plants = [m["plants"][i] for i in plant_ids if i in m["plants"]]
    plant = next((x for x in plants if x.asset_id == plant_id), plants[0] if plants else None)
    cx = derive_manufacturing_complexity(key, p, reg)
    cand = score_candidate(key, p, plant, weights=weights or None, regulatory=reg, demand=dem)

    # curated knowledge for the 17 catalogue drugs
    ob_curated, pharma = None, None
    try:
        import gmp_knowledge as gk
        import pharmacopeia_diff as pdiff
        import us_regulatory_data as usr

        first = (p.api_name or key).split()[0].lower()
        cat_key = key if key in gk.PRODUCT_CATALOG else (first if first in gk.PRODUCT_CATALOG else None)
        if cat_key:
            rec = usr.orange_book_for(cat_key)
            ob_curated = insights.json_safe(rec.__dict__) if rec else None
            if ob_curated and rec and rec.provenance:
                ob_curated["provenance"] = insights.json_safe(rec.provenance.__dict__)
            diffs = pdiff.diff_drug(gk.PRODUCT_CATALOG[cat_key])
            pharma = []
            for dd in diffs:
                row = {"section": dd.section, "significance": dd.significance, "rationale": dd.rationale,
                       "ich": dd.ich_harmonisation if isinstance(dd.ich_harmonisation, (str, type(None))) else str(dd.ich_harmonisation), "methods": {}}
                for ph, meth in dd.methods.items():
                    row["methods"][getattr(ph, "value", str(ph))] = None if meth is None else {
                        k: getattr(meth, k) for k in ("apparatus", "medium", "medium_ph", "rpm", "timepoints", "q_limit_pct",
                                                       "impurity_name", "impurity_limit_pct", "detection", "column", "mobile_phase", "raw_text")}
                pharma.append(row)
    except Exception:
        pass

    # national NSQ record for this molecule
    idx = insights.tracked_index()
    df = base_frame()
    hits = df[df["Name of Product"].astype(str).map(lambda n: key in (insights.tracked_for(n, idx) or []))]
    nsq = None
    if not hits.empty:
        h = hits.assign(_mfr=_mfr_label(hits))
        nsq = {"alerts": len(h), "manufacturers": int(h["_mfr"].nunique()),
               "categories": insights._counts(h, "Failure_Category_Primary", 6), "forms": insights._counts(h, "Form type", 5),
               "states": insights._counts(h, "_state", 6), "trend": insights._month_series(h),
               "top_manufacturers": [{"name": k, "count": int(v)} for k, v in h["_mfr"].value_counts().head(8).items()]}

    return insights.json_safe({
        "patent": p.model_dump(mode="json"),
        "regulatory": reg.model_dump(mode="json") if reg else None,
        "demand": dem.model_dump(mode="json") if dem else None,
        "complexity": cx.model_dump(mode="json"),
        "score": cand.model_dump(mode="json"),
        "plants": [{"asset_id": x.asset_id, "name": x.site_name} for x in plants],
        "plant_id": plant.asset_id if plant else None,
        "orange_book_curated": ob_curated,
        "pharmacopeia": pharma,
        "nsq": nsq,
    })
