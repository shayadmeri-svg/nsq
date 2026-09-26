"""Read models for the dashboards, composed from the core/ engines.

Everything here is a pure function of the enriched frame, the CDMO maps and
an org's links (ontology keys + plant ids). No writes.
"""

from __future__ import annotations

import dataclasses
import enum
import re
from datetime import date
from typing import Any, Iterable, Optional

import pandas as pd

import capability_catalog
import eu_export
from diagnostics_core import build_diagnosis
from intelligence_scorer import (
    customer_profile_requirements,
    derive_manufacturing_complexity,
    plant_active_certifications,
    plant_available_capabilities,
    score_candidate,
    score_customer_profile_fit,
)

import ingredients as ing

from . import data

TOP_CATEGORIES = 6


# --- helpers ------------------------------------------------------------------

def json_safe(obj):
    """Dataclass/enum/numpy/pandas → plain JSON types."""
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, float):
        return None if pd.isna(obj) else obj
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (pd.Timestamp, date)):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: json_safe(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(json_safe(k)): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return obj.item()
        except Exception:
            return str(obj)
    if hasattr(obj, "model_dump"):
        return json_safe(obj.model_dump(mode="json"))
    return str(obj)


def _s(v, default: str = "") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    s = str(v).strip()
    return s or default


def _month_series(df: pd.DataFrame, by: Optional[str] = None, top: int = TOP_CATEGORIES) -> dict[str, Any]:
    """Monthly counts, optionally split by a column folded to top-N + Other."""
    if df.empty or "Parsed_Date" not in df.columns:
        return {"months": [], "series": []}
    d = df.dropna(subset=["Parsed_Date"]).copy()
    d["month"] = d["Parsed_Date"].dt.strftime("%Y-%m")
    all_months = pd.period_range(d["Parsed_Date"].min(), d["Parsed_Date"].max(), freq="M").strftime("%Y-%m").tolist()
    if not by:
        counts = d.groupby("month").size().reindex(all_months, fill_value=0)
        return {"months": all_months, "series": [{"name": "Alerts", "values": counts.astype(int).tolist()}]}
    keep = d[by].value_counts().head(top).index.tolist()
    d["_k"] = d[by].where(d[by].isin(keep), "Other")
    piv = d.groupby(["month", "_k"]).size().unstack(fill_value=0).reindex(all_months, fill_value=0)
    order = keep + (["Other"] if "Other" in piv.columns and "Other" not in keep else [])
    return {
        "months": all_months,
        "series": [{"name": k, "values": piv[k].astype(int).tolist()} for k in order if k in piv.columns],
    }


def _counts(df: pd.DataFrame, col: str, top: int = 10) -> list[dict[str, Any]]:
    if df.empty or col not in df.columns:
        return []
    vc = df[col].fillna("Unknown").replace("", "Unknown").value_counts()
    rows = [{"name": str(k), "count": int(v)} for k, v in vc.head(top).items()]
    rest = int(vc.iloc[top:].sum()) if len(vc) > top else 0
    if rest:
        rows.append({"name": "Other", "count": rest})
    return rows


def _period(df: pd.DataFrame) -> dict[str, Optional[str]]:
    if df.empty or "Parsed_Date" not in df.columns or df["Parsed_Date"].isna().all():
        return {"first": None, "last": None}
    return {"first": df["Parsed_Date"].min().strftime("%Y-%m"), "last": df["Parsed_Date"].max().strftime("%Y-%m")}


_ING_CACHE: dict[str, list[str]] = {}
_INDEX_HOLDER: dict[str, dict[str, str]] = {}


def product_ingredients(name: str) -> list[str]:
    name = name or ""
    got = _ING_CACHE.get(name)
    if got is None:
        got = ing.extract_ingredients(name)
        if len(_ING_CACHE) < 50_000:
            _ING_CACHE[name] = got
    return got


def tracked_index() -> dict[str, str]:
    return ing.tracked_index(data.cdmo()["patents"])


def tracked_for(name: str, index: Optional[dict[str, str]] = None) -> list[str]:
    """Tracked molecule keys among a product's ingredients."""
    index = index if index is not None else tracked_index()
    out: list[str] = []
    for k in product_ingredients(name):
        m = ing.match_tracked(k, index)
        if m and m not in out:
            out.append(m)
    return out


def ingredient_coverage(df: pd.DataFrame, index: Optional[dict[str, str]] = None, top: int = 25) -> dict[str, Any]:
    """Split a frame's alerts into tracked molecules vs untracked ingredients."""
    index = index if index is not None else tracked_index()
    tracked: dict[str, int] = {}
    untracked: dict[str, dict[str, Any]] = {}
    alerts_tracked = 0
    for _, r in df.iterrows():
        name = _s(r.get("Product_Name_Canonical")) or _s(r.get("Name of Product"))
        keys = product_ingredients(name)
        hit = False
        for k in keys:
            m = ing.match_tracked(k, index)
            if m:
                tracked[m] = tracked.get(m, 0) + 1
                hit = True
            else:
                u = untracked.setdefault(k, {"ingredient": k, "alerts": 0, "products": {}, "forms": {}, "last": None, "categories": {}})
                u["alerts"] += 1
                u["products"][name] = u["products"].get(name, 0) + 1
                f = _s(r.get("Form type"), "—")
                u["forms"][f] = u["forms"].get(f, 0) + 1
                c = _s(r.get("Failure_Category_Primary"), "Uncategorized")
                u["categories"][c] = u["categories"].get(c, 0) + 1
                d = r.get("Parsed_Date")
                if pd.notna(d):
                    m_ = d.strftime("%Y-%m")
                    u["last"] = max(u["last"] or m_, m_)
        alerts_tracked += 1 if hit else 0
    rows = _fold_spellings(sorted(untracked.values(), key=lambda u: -u["alerts"]))
    for u in rows:
        u["products"] = [p for p, _ in sorted(u["products"].items(), key=lambda x: -x[1])[:3]]
        u["forms"] = [f for f, _ in sorted(u["forms"].items(), key=lambda x: -x[1])[:3]]
        u["categories"] = [c for c, _ in sorted(u["categories"].items(), key=lambda x: -x[1])[:3]]
    return {
        "alerts": int(len(df)),
        "alerts_tracked": alerts_tracked,
        "tracked_counts": tracked,
        "untracked": rows[:top],
        "untracked_total": len(rows),
    }


def _fold_spellings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge misspelt variants in CDSCO data (guiaphenesin -> guaiphenesin,
    nofloxacin -> norfloxacin) into the most frequent spelling."""
    from rapidfuzz import fuzz

    kept: list[dict[str, Any]] = []
    for u in rows:  # already sorted by alerts desc, so the first spelling wins
        name = u["ingredient"]
        target = None
        if len(name) > 5 and "vitamin" not in name:
            target = next((k for k in kept
                           if k["ingredient"][:2] == name[:2]
                           and abs(len(k["ingredient"]) - len(name)) <= 3
                           and "vitamin" not in k["ingredient"]
                           and fuzz.ratio(k["ingredient"], name) >= 88), None)
        if target is None:
            u.setdefault("variants", [])
            kept.append(u)
            continue
        target["alerts"] += u["alerts"]
        target["variants"].append(u["ingredient"])
        for fld in ("products", "forms", "categories"):
            for k, v in u[fld].items():
                target[fld][k] = target[fld].get(k, 0) + v
        if u["last"] and (not target["last"] or u["last"] > target["last"]):
            target["last"] = u["last"]
    return sorted(kept, key=lambda u: -u["alerts"])


def issue_row(row: pd.Series) -> dict[str, Any]:
    return {
        "id": _s(row.get("record_id")),
        "product": _s(row.get("Product_Name_Canonical")) or _s(row.get("Name of Product"), "—"),
        "batch": _s(row.get("Batch No"), "—"),
        "reason": _s(row.get("NSQ Result"), "—"),
        "category": _s(row.get("Failure_Category_Primary"), "Uncategorized"),
        "form": _s(row.get("Form type"), "—"),
        "drug_type": _s(row.get("Drug type"), "—"),
        "month": row["Parsed_Date"].strftime("%Y-%m") if pd.notna(row.get("Parsed_Date")) else _s(row.get("Reporting Month & Year")),
        "lab": _s(row.get("Reporting by Lab/State"), "—"),
        "source": _s(row.get("Reporting Source"), "—"),
        "manufacturer": _s(row.get("Mfg_Company_Canonical")) or _s(row.get("Mfg_Company"), "—"),
        "mfg_state": _s(row.get("Mfg_State_Ontology")) or _s(row.get("Mfg_State"), "—"),
        "mfg_date": _s(row.get("Manufacturing Date"), "—"),
        "expiry": _s(row.get("Expiry Date"), "—"),
        "ingredients": product_ingredients(_s(row.get("Product_Name_Canonical")) or _s(row.get("Name of Product"))),
        "tracked": tracked_for(_s(row.get("Product_Name_Canonical")) or _s(row.get("Name of Product")), _INDEX_HOLDER.get("idx")),
    }


def filter_issues(df: pd.DataFrame, q: str = "", category: str = "", form: str = "") -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if category:
        out = out[out["Failure_Category_Primary"] == category]
    if form:
        out = out[out["Form type"] == form]
    if q:
        ql = q.lower()
        mask = pd.Series(False, index=out.index)
        for col in ("Product_Name_Canonical", "Name of Product", "Batch No", "NSQ Result", "Mfg_Company_Canonical", "Reporting by Lab/State"):
            if col in out.columns:
                mask |= out[col].astype(str).str.lower().str.contains(re.escape(ql), na=False)
        out = out[mask]
    return out


def paginate(df: pd.DataFrame, page: int, size: int) -> dict[str, Any]:
    _INDEX_HOLDER["idx"] = tracked_index()
    size = max(1, min(size, 200))
    total = int(len(df))
    if not df.empty and "Parsed_Date" in df.columns:
        df = df.sort_values("Parsed_Date", ascending=False, kind="stable")
    start = max(0, (page - 1) * size)
    rows = [issue_row(r) for _, r in df.iloc[start:start + size].iterrows()]
    return {"total": total, "page": page, "size": size, "pages": (total + size - 1) // size, "items": rows}


# --- platform analytics (all alerts) --------------------------------------------

def platform_summary() -> dict[str, Any]:
    df = data.frame()
    per = _period(df)
    last_month = per["last"]
    latest = df[df["Parsed_Date"].dt.strftime("%Y-%m") == last_month] if last_month else df.iloc[0:0]
    mfg = df.groupby("Mfg_Ontology_Key").agg(
        alerts=("record_id", "size"),
        name=("Mfg_Company_Canonical", "first"),
        state=("Mfg_State_Ontology", "first"),
        last=("Parsed_Date", "max"),
    ).sort_values("alerts", ascending=False)
    top_mfg = [
        {"key": k, "name": _s(r["name"], k.title()), "state": _s(r["state"]), "alerts": int(r["alerts"]),
         "last": r["last"].strftime("%Y-%m") if pd.notna(r["last"]) else None}
        for k, r in mfg.head(15).iterrows() if k
    ]
    return {
        "kpis": {
            "alerts": int(len(df)),
            "manufacturers": int(df["Mfg_Ontology_Key"].nunique()),
            "products": int(df["Product_Ontology_Key"].nunique()) if "Product_Ontology_Key" in df else None,
            "latest_month": last_month,
            "latest_month_alerts": int(len(latest)),
            "dissolution_share": round(float(df["Is_Dissolution"].mean()) * 100, 1) if "Is_Dissolution" in df else None,
        },
        "period": per,
        "trend": _month_series(df, "Failure_Category_Primary"),
        "categories": _counts(df, "Failure_Category_Primary", 10),
        "forms": _counts(df, "Form type", 8),
        "drug_types": _counts(df, "Drug type", 8),
        "mfg_states": _counts(df[df["Mfg_State"].astype(str).str.strip() != ""], "Mfg_State", 12),
        "top_manufacturers": top_mfg,
        "latest_alerts": [issue_row(r) for _, r in latest.head(12).iterrows()],
        "coverage": _platform_coverage(df),
    }


_COVERAGE_CACHE: dict[str, Any] = {}


def _platform_coverage(df: pd.DataFrame) -> dict[str, Any]:
    key = f"{len(df)}:{data.frame_source()}"
    if _COVERAGE_CACHE.get("key") != key:
        cov = ingredient_coverage(df, top=20)
        _COVERAGE_CACHE.update(key=key, value={
            "alerts": cov["alerts"], "alerts_tracked": cov["alerts_tracked"],
            "tracked_counts": cov["tracked_counts"], "untracked": cov["untracked"],
            "untracked_total": cov["untracked_total"],
        })
    return _COVERAGE_CACHE["value"]


def manufacturer_search(q: str, limit: int = 20) -> list[dict[str, Any]]:
    df = data.frame()
    g = df.groupby("Mfg_Ontology_Key").agg(
        alerts=("record_id", "size"), name=("Mfg_Company_Canonical", "first"),
        city=("Mfg_City", "first"), state=("Mfg_State_Ontology", "first"),
        raw=("Mfg_Company", lambda s: sorted(set(map(str, s)))[:6]),
    )
    ql = (q or "").strip().lower()
    if ql:
        mask = g.index.str.contains(re.escape(ql)) | g["name"].astype(str).str.lower().str.contains(re.escape(ql))
        g = g[mask]
    g = g.sort_values("alerts", ascending=False).head(limit)
    return [
        {"key": k, "name": _s(r["name"], k.title()), "city": _s(r["city"]), "state": _s(r["state"]),
         "alerts": int(r["alerts"]), "raw_names": r["raw"]}
        for k, r in g.iterrows() if k
    ]


# --- org: quality -------------------------------------------------------------

def org_quality(ontology_keys: list[str]) -> dict[str, Any]:
    df = data.org_frame(ontology_keys)
    national = data.frame()
    n_all = max(len(national), 1)
    if df.empty:
        return {"empty": True, "kpis": {"alerts": 0}, "period": _period(df)}

    rank_series = national["Mfg_Ontology_Key"].value_counts()
    ranks = [int(rank_series.index.get_loc(k)) + 1 for k in ontology_keys if k in rank_series.index]
    cat_org = df["Failure_Category_Primary"].value_counts(normalize=True)
    cat_nat = national["Failure_Category_Primary"].value_counts(normalize=True)
    compare = [
        {"name": c, "org_pct": round(float(cat_org.get(c, 0)) * 100, 1), "national_pct": round(float(cat_nat.get(c, 0)) * 100, 1)}
        for c in cat_org.head(TOP_CATEGORIES).index
    ]
    last = df["Parsed_Date"].max()
    recent = df[df["Parsed_Date"] >= last - pd.DateOffset(months=11)] if pd.notna(last) else df.iloc[0:0]
    products = df.groupby("Product_Name_Canonical").agg(
        alerts=("record_id", "size"),
        reasons=("Failure_Category_Primary", lambda s: s.value_counts().index.tolist()[:3]),
        last=("Parsed_Date", "max"),
    ).sort_values("alerts", ascending=False).head(10)

    return {
        "empty": False,
        "kpis": {
            "alerts": int(len(df)),
            "products": int(df["Product_Name_Canonical"].nunique()),
            "batches": int(df["Batch No"].nunique()),
            "last_12m": int(len(recent)),
            "national_share_pct": round(100 * len(df) / n_all, 2),
            "national_rank": min(ranks) if ranks else None,
            "manufacturers_ranked": int(len(rank_series)),
            "top_category": str(df["Failure_Category_Primary"].value_counts().index[0]),
        },
        "period": _period(df),
        "trend": _month_series(df, "Failure_Category_Primary", top=5),
        "categories": _counts(df, "Failure_Category_Primary", 8),
        "forms": _counts(df, "Form type", 8),
        "labs": _counts(df, "Reporting by Lab/State", 8),
        "compare": compare,
        "products": [
            {"name": str(k), "alerts": int(r["alerts"]), "reasons": r["reasons"],
             "last": r["last"].strftime("%Y-%m") if pd.notna(r["last"]) else None}
            for k, r in products.iterrows()
        ],
    }


def org_issue_detail(ontology_keys: list[str], issue_id: str) -> Optional[dict[str, Any]]:
    df = data.org_frame(ontology_keys)
    if df.empty:
        return None
    hit = df[df["record_id"].astype(str) == issue_id]
    if hit.empty:
        return None
    row = hit.iloc[0]
    diag = build_diagnosis(row, df)
    same_product = df[df["Product_Name_Canonical"] == row.get("Product_Name_Canonical")]
    return {
        "issue": issue_row(row),
        "diagnosis": json_safe(diag),
        "history": [issue_row(r) for _, r in same_product.sort_values("Parsed_Date", ascending=False).head(20).iterrows()],
    }


# --- org: infrastructure --------------------------------------------------------

def plant_profile(plant) -> dict[str, Any]:
    caps = plant_available_capabilities(plant)
    basis = plant.capability_basis or {}
    sections = []
    in_catalog: set[str] = set()
    for sec in capability_catalog.SECTIONS:
        tokens = [c.token for c in sec.capabilities]
        in_catalog.update(tokens)
        have = [c for c in sec.capabilities if c.token in caps]
        sections.append({
            "id": sec.section_id, "title": sec.title, "icon": sec.icon,
            "have": [{"token": c.token, "label": c.label, "basis": basis.get(c.token, "derived")} for c in have],
            "total": len(tokens),
            "coverage_pct": round(100 * len(have) / len(tokens)) if tokens else 0,
        })
    other = sorted(t for t in plant.capabilities if t not in in_catalog)
    d = plant.model_dump(mode="json")
    d["sections"] = sections
    d["other_capabilities"] = [{"token": t, "label": _label(t), "basis": basis.get(t, "derived")} for t in other]
    d["certifications_active_norm"] = sorted(plant_active_certifications(plant))
    d["evidence"] = {
        "stated": sum(1 for v in basis.values() if v == "stated"),
        "inferred": sum(1 for v in basis.values() if v == "inferred"),
        "user": sum(1 for v in basis.values() if v == "user"),
    }
    return d


def org_plants(plant_ids: list[str]) -> list:
    plants = data.cdmo()["plants"]
    return [plants[p] for p in plant_ids if p in plants]


def org_infrastructure(plant_ids: list[str]) -> dict[str, Any]:
    plants = org_plants(plant_ids)
    return {
        "plants": [plant_profile(p) for p in plants],
        "missing": [p for p in plant_ids if p not in {x.asset_id for x in plants}],
        "taxonomy": [
            {"id": s.section_id, "title": s.title, "icon": s.icon,
             "capabilities": [{"token": c.token, "label": c.label} for c in s.capabilities]}
            for s in capability_catalog.SECTIONS
        ],
    }


# --- org: opportunities (patents × infra) -------------------------------------------

def _years(d: Optional[date], today: date) -> Optional[float]:
    return round((d - today).days / 365.25, 1) if d else None


def _label(token: str) -> str:
    c = capability_catalog.CAPABILITY_BY_TOKEN.get(token)
    return c.label if c else token.replace("_", " ").capitalize()


_OPP_CACHE: dict[tuple, dict[str, Any]] = {}


def org_opportunities(plant_ids: list[str], ontology_keys: Optional[list[str]] = None, today: Optional[date] = None) -> dict[str, Any]:
    """Cached per (plants, identities, data generation): scoring every molecule
    against every plant is the most expensive dashboard call."""
    key = (tuple(plant_ids), tuple(ontology_keys or []), id(data.cdmo()), id(data.frame()), today or date.today())
    hit = _OPP_CACHE.get(key)
    if hit is None:
        if len(_OPP_CACHE) > 64:
            _OPP_CACHE.clear()
        hit = _OPP_CACHE[key] = _org_opportunities(plant_ids, ontology_keys, today)
    return hit


def _org_opportunities(plant_ids: list[str], ontology_keys: Optional[list[str]] = None, today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    m = data.cdmo()
    coverage = ingredient_coverage(data.org_frame(ontology_keys or []))
    plants = org_plants(plant_ids)
    rows: list[dict[str, Any]] = []
    unlock: dict[str, dict[str, Any]] = {}

    for key, patent in m["patents"].items():
        reg = m["regulatory"].get(key)
        dem = m["demand"].get(key)
        complexity = derive_manufacturing_complexity(key, patent, reg)
        req = customer_profile_requirements(complexity)
        best = None
        for plant in plants or [None]:
            cand = score_candidate(key, patent, plant, regulatory=reg, demand=dem)
            fit = score_customer_profile_fit(complexity, plant)
            item = (fit[4], cand.total_score, plant, cand, fit)
            if best is None or item[:2] > best[:2]:
                best = item
        fit_score, total, plant, cand, fit = best
        missing_caps: list[str] = []
        missing_certs: list[str] = []
        if plant is not None:
            missing_caps = sorted(set(req["capabilities"]) - plant_available_capabilities(plant))
            missing_certs = sorted(set(req["certifications"]) - plant_active_certifications(plant))
        # Capabilities required by applicable GMP pillars (e.g. HPAPI containment).
        pillar_missing: list[str] = []
        if plant is not None:
            avail = plant_available_capabilities(plant)
            for p in complexity.gmp_pillars:
                if p.applies:
                    pillar_missing += [c for c in p.required_capabilities if c.lower() not in avail]
        pillar_missing = sorted(set(pillar_missing) - set(missing_caps))

        loe = {
            "in": patent.estimated_loe_in.isoformat() if patent.estimated_loe_in else None,
            "eu": patent.estimated_loe_eu.isoformat() if patent.estimated_loe_eu else None,
            "us": patent.estimated_loe_us.isoformat() if patent.estimated_loe_us else None,
        }
        earliest = patent.earliest_loe()
        row = {
            "molecule_key": key,
            "api_name": patent.api_name,
            "brand_name": patent.brand_name,
            "originator": patent.originator,
            "therapeutic_area": patent.therapeutic_area,
            "cluster": dem.cluster if dem else "",
            "market_size_usd_bn": patent.market_size_usd_bn,
            "fto_risk": patent.fto_risk,
            "loe": loe,
            "years_to_loe": _years(earliest, today),
            "available_now": earliest is None or earliest <= today,
            "modality": complexity.modality,
            "drug_form": complexity.drug_form,
            "sterile": complexity.sterility_required,
            "best_plant": {"asset_id": plant.asset_id, "name": plant.site_name} if plant else None,
            "fit_tier": fit[5],
            "fit_score": fit[4],
            "total_score": cand.total_score,
            "scores": {
                "patent": cand.patent_readiness_score, "regulatory": cand.regulatory_clarity_score,
                "demand": cand.demand_attractiveness_score, "plant": cand.plant_fit_score,
                "infrastructure": fit[0], "talent": fit[1], "certification": fit[2], "gmp": fit[3],
            },
            "missing_capabilities": [{"token": t, "label": _label(t)} for t in missing_caps],
            "missing_certifications": missing_certs,
            "pillar_gaps": [{"token": t, "label": _label(t)} for t in pillar_missing],
            "warnings": cand.warnings,
            "tracked": True,
            "alerts_in_org": coverage["tracked_counts"].get(key, 0),
            "origin": getattr(patent, "origin", "curated"),
            "sources": (getattr(patent, "signals", None) or {}).get("sources", []),
            "prov": {k: v for k, v in (getattr(patent, "provenance", None) or {}).items()
                     if k in ("loe_us", "loe_eu", "loe_in", "fto_risk", "market_size_usd_bn", "patents")},
        }
        rows.append(row)

        if fit[5] not in ("strategic", "core"):
            for t in missing_caps:
                u = unlock.setdefault(f"cap:{t}", {"kind": "capability", "token": t, "label": _label(t), "molecules": [], "market_usd_bn": 0.0})
                u["molecules"].append(patent.api_name)
                u["market_usd_bn"] += patent.market_size_usd_bn or 0
            for c in missing_certs:
                u = unlock.setdefault(f"cert:{c}", {"kind": "certification", "token": c, "label": c.replace("_", " ").upper(), "molecules": [], "market_usd_bn": 0.0})
                u["molecules"].append(patent.api_name)
                u["market_usd_bn"] += patent.market_size_usd_bn or 0

    rows.sort(key=lambda r: (-r["fit_score"], -r["total_score"]))
    unlocks = sorted(unlock.values(), key=lambda u: (-len(u["molecules"]), -u["market_usd_bn"]))
    for u in unlocks:
        u["market_usd_bn"] = round(u["market_usd_bn"], 1)
        u["count"] = len(u["molecules"])
    tiers: dict[str, int] = {}
    for r in rows:
        tiers[r["fit_tier"]] = tiers.get(r["fit_tier"], 0) + 1
    ready_soon = [r for r in rows if r["fit_tier"] in ("strategic", "core") and (r["years_to_loe"] is None or r["years_to_loe"] <= 5)]
    return {
        "has_plants": bool(plants),
        "molecules": rows,
        "tiers": tiers,
        "unlocks": unlocks[:12],
        "ready_within_5y": len(ready_soon),
        "coverage": {k: coverage[k] for k in ("alerts", "alerts_tracked", "untracked_total")},
        "untracked": coverage["untracked"],
    }


# --- org: EU export -------------------------------------------------------------

def _alerts_for_api(df: pd.DataFrame, api_name: str) -> int:
    if df.empty or not api_name:
        return 0
    word = re.escape(api_name.split()[0].lower())
    col = df["Product_Name_Canonical"].astype(str).str.lower()
    return int(col.str.contains(rf"\b{word}", regex=True, na=False).sum())


def org_eu_export(ontology_keys: list[str], plant_ids: list[str], molecule_keys: Optional[Iterable[str]] = None) -> dict[str, Any]:
    m = data.cdmo()
    plants = org_plants(plant_ids)
    df = data.org_frame(ontology_keys)
    keys = list(molecule_keys) if molecule_keys else list(m["patents"].keys())
    out = []
    for key in keys:
        patent = m["patents"].get(key)
        if patent is None:
            continue
        reg = m["regulatory"].get(key)
        complexity = derive_manufacturing_complexity(key, patent, reg)
        nsq = _alerts_for_api(df, patent.api_name)
        best = None
        for plant in plants or [None]:
            a = eu_export.assess(patent, reg, complexity, plant, nsq)
            if best is None or a.readiness_pct > best.readiness_pct:
                best = a
        d = best.to_dict()
        prov = getattr(patent, "provenance", None) or {}
        d["prov"] = {k: prov[k] for k in ("loe_eu", "geo_coverage") if k in prov}
        d["origin"] = getattr(patent, "origin", "curated")
        out.append(d)
    out.sort(key=lambda a: (-a["readiness_pct"], a["api_name"]))

    # Org-level blockers: items that are a gap for most molecules.
    blocker_counts: dict[str, dict[str, Any]] = {}
    for a in out:
        for it in a["items"]:
            if it["status"] == "gap":
                b = blocker_counts.setdefault(it["id"], {"id": it["id"], "title": it["title"], "how_to_close": it["how_to_close"], "reference": it["reference"], "molecules": 0})
                b["molecules"] += 1
    verdicts: dict[str, int] = {}
    for a in out:
        verdicts[a["verdict"]] = verdicts.get(a["verdict"], 0) + 1
    eu_certified = [p.site_name for p in plants if "eu_gmp" in plant_active_certifications(p)]
    return {
        "assessments": out,
        "blockers": sorted(blocker_counts.values(), key=lambda b: -b["molecules"]),
        "verdicts": verdicts,
        "eu_gmp_sites": eu_certified,
        "plants": len(plants),
        "org_nsq_alerts": int(len(df)),
    }


def org_overview(org) -> dict[str, Any]:
    q = org_quality(org.ontology_keys or [])
    opp = org_opportunities(org.plant_ids or [], org.ontology_keys or [])
    eu = org_eu_export(org.ontology_keys or [], org.plant_ids or [])
    plants = org_plants(org.plant_ids or [])
    return {
        "quality": {"kpis": q.get("kpis"), "period": q.get("period"), "trend": q.get("trend"), "categories": q.get("categories", [])[:5]},
        "infrastructure": {
            "plants": len(plants),
            "certifications": sorted({c for p in plants for c in plant_active_certifications(p)}),
            "capabilities": len({c for p in plants for c in plant_available_capabilities(p)}),
        },
        "opportunities": {
            "tiers": opp["tiers"], "ready_within_5y": opp["ready_within_5y"],
            "top": opp["molecules"][:5], "unlocks": opp["unlocks"][:3],
        },
        "eu": {"verdicts": eu["verdicts"], "top": eu["assessments"][:5], "blockers": eu["blockers"][:3], "eu_gmp_sites": eu["eu_gmp_sites"]},
    }
