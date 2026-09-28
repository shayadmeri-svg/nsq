"""Failure forensics: reverse-engineering why a product fails NSQ, from the pattern of its alerts.

Every CDSCO NSQ alert carries the failed test (in words), the batch's manufacturing and expiry dates, the maker and the
testing laboratory. Grouped by product (same active ingredients + dosage form), those fields say a lot more together than
alone:

  * which test fails, and how that compares with every other product;
  * WHEN in the shelf life it fails — early (the batch was released that way: a formulation / process flaw) or late (it
    degraded: a stability / packaging flaw). The report date lags the sampling date, so the timing is an upper bound;
  * how many independent makers fail it — dozens of makers failing the same test means the usual way of making the
    product is marginal ("class-wide"); a few plants causing most failures means a plant problem ("maker-specific");
  * which laboratory finds it, against that laboratory's share of all alerts (a lab that finds it far more often is
    probably testing differently);
  * the molecule's chemistry (PubChem / structure seed): lipophilic APIs dissolve poorly, amines brown with lactose.

Rules turn those signals into root-cause hypotheses, each with the evidence behind it and the checks a maker would run.
They are hypotheses from public records, labelled as such — never a finding about a named company.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from typing import Any, Optional

import pandas as pd

from . import data, insights

MIN_ALERTS = 8  # a pattern needs a few alerts before it says anything

# failed test -> words in the NSQ result text (one result often names several tests)
TESTS: list[tuple[str, str]] = [
    ("Dissolution", r"dissol|drug release|in.?vitro release"),
    ("Assay / content", r"assay|content of|\bcontent\b|potency|does not conform to (the )?claim|label claim|\bclaim\b"),
    ("Related substances", r"related substance|impurit|degradation product"),
    ("Disintegration", r"disintegrat"),
    ("Uniformity", r"uniformity|weight variation|average weight|\bweight\b"),
    ("Description", r"descri|appearance|colou?r|physical|discolou?r|mottl|spot"),
    ("Identification", r"identif"),
    ("Sterility", r"sterilit"),
    ("Endotoxin", r"endotoxin|pyrogen"),
    ("Particulate matter", r"particulate|particles|visible matter|foreign matter|clarity"),
    ("Microbial", r"microb|\btamc\b|\btymc\b|pathogen|e\.? ?coli|salmonella"),
    ("pH", r"\bph\b"),
    ("Water / LOD", r"water|loss on drying|\blod\b|moisture"),
    ("Labelling", r"misbrand|label|spurious|adulterat"),
]
_TESTS_RX = [(t, re.compile(rx, re.I)) for t, rx in TESTS]

TIMING_BINS = [(0.0, 0.2, "0–20%"), (0.2, 0.4, "20–40%"), (0.4, 0.6, "40–60%"), (0.6, 0.8, "60–80%"), (0.8, 1.0, "80–100%"),
               (1.0, 9.9, "after expiry")]

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None}


def failed_tests(reason: str) -> list[str]:
    got = [t for t, rx in _TESTS_RX if rx.search(reason or "")]
    if "Assay / content" in got and re.search(r"\bcontent uniformity\b", reason or "", re.I) and not re.search(r"assay", reason or "", re.I):
        got.remove("Assay / content")  # "content uniformity" is a uniformity test
    return got or ["Unspecified"]


def _month(s: Any) -> pd.Timestamp:
    s = str(s or "").strip()
    for f in ("%b-%Y", "%m/%d/%Y", "%b-%y", "%B-%Y", "%b %Y", "%m/%Y", "%d/%m/%Y"):
        try:
            return pd.to_datetime(s, format=f)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def _frame() -> pd.DataFrame:
    """Alerts with product group, failed tests and the fraction of shelf life at the report."""
    df = data.frame()
    key = (id(df), len(df))
    with _lock:
        if _cache["key"] == key:
            return _cache["df"]
        d = df.copy()
        d["_product"] = d["Product_Name_Canonical"].fillna(d["Name of Product"]).astype(str)
        ing_keys = {n: tuple(sorted(insights.product_ingredients(n))) for n in d["_product"].unique()}
        d["_ings"] = d["_product"].map(ing_keys)
        d["_form"] = d["Form type"].fillna("Other").astype(str)
        d = d[d["_ings"].map(len) > 0]
        d["_group"] = d["_ings"].map(lambda t: "+".join(t)) + "|" + d["_form"]
        d["_tests"] = d["NSQ Result"].astype(str).map(failed_tests)
        mfg, exp = d["Manufacturing Date"].map(_month), d["Expiry Date"].map(_month)
        life = (exp - mfg).dt.days
        d["_frac"] = ((d["Parsed_Date"] - mfg).dt.days / life).where((life > 60) & (d["Parsed_Date"] >= mfg))
        d["_age_m"] = ((d["Parsed_Date"] - mfg).dt.days / 30.44).where(d["Parsed_Date"] >= mfg)
        _cache.pop("groups", None)
        _cache.pop("vocab", None)
        _cache.update(key=key, df=d, base=_baseline(d))
        return d


def _baseline(d: pd.DataFrame) -> dict[str, Any]:
    """National reference: per-test timing, and each lab's / state's share of all alerts."""
    ex = d.explode("_tests")
    per_test = {}
    for t, g in ex.groupby("_tests"):
        f = g["_frac"].dropna()
        if len(f) >= 20:
            per_test[t] = {"early": float((f < 0.25).mean()), "late": float((f > 0.6).mean()), "n": int(len(f))}
    n = max(len(d), 1)
    return {"tests": per_test,
            "labs": (d["Reporting by Lab/State"].fillna("").value_counts() / n).to_dict(),
            "states": (d["Mfg_State_Ontology"].fillna("").value_counts() / n).to_dict()}


def _label(group: str) -> str:
    ings, form = group.split("|", 1)
    return " + ".join(i.title() for i in ings.split("+")) + f" · {form}"


def _chemistry(ings: list[str]) -> list[dict[str, Any]]:
    """PubChem / seed properties of the product's ingredients that bear on how it fails."""
    try:
        from . import lab
        structs = lab.structures()
        idx = insights.tracked_index()
    except Exception:
        return []
    import ingredients as ing  # core/
    out = []
    for i in ings:
        key = ing.match_tracked(i, idx) or i.replace(" ", "_")
        s = structs.get(key) or next((v for v in structs.values() if (v.get("name") or "").lower() == i.lower()), None)
        if not s or not s.get("smiles"):
            continue
        rec = {"ingredient": i, "key": s.get("key") or key, "xlogp": s.get("xlogp"), "mp_c": s.get("mp_c"), "amine": None,
               "url": s.get("url")}
        try:
            from rdkit import Chem
            from rdkit.Chem import Crippen
            m = Chem.MolFromSmiles(s["smiles"])
            if m is not None:
                if rec["xlogp"] is None:
                    rec["xlogp"] = round(Crippen.MolLogP(m), 1)
                # primary / secondary amine not in an amide: reacts with reducing sugars (lactose) — Maillard browning
                rec["amine"] = m.HasSubstructMatch(Chem.MolFromSmarts("[NX3;H2,H1;!$(NC=[O,S,N]);!$(N-a);!$(N[S](=O)=O)]"))
        except Exception:
            pass
        out.append(rec)
    return out


def _signals(g: pd.DataFrame, base: dict[str, Any]) -> dict[str, Any]:
    n = len(g)
    tests = Counter(t for ts in g["_tests"] for t in ts)
    dom, dom_n = tests.most_common(1)[0]
    makers = g["Mfg_Ontology_Key"].fillna("").replace("", pd.NA).dropna()
    mk = makers.value_counts()
    top3 = float(mk.head(3).sum() / max(len(makers), 1))
    f_dom = g[g["_tests"].map(lambda ts: dom in ts)]["_frac"].dropna()
    early = float((f_dom < 0.25).mean()) if len(f_dom) >= 5 else None
    late = float((f_dom > 0.6).mean()) if len(f_dom) >= 5 else None
    ref = base["tests"].get(dom, {})
    labs = []
    for lab_name, c in g["Reporting by Lab/State"].fillna("").value_counts().items():
        share = base["labs"].get(lab_name) or 0
        if lab_name and c >= 5 and share:
            lift = (c / n) / share
            if lift >= 2:
                labs.append({"lab": lab_name, "alerts": int(c), "share_pct": round(100 * c / n), "national_pct": round(100 * share, 1), "lift": round(lift, 1)})
    return {
        "n": n, "makers": int(len(mk)), "repeat_makers": int((mk > 1).sum()), "top3_share": round(top3, 2),
        "tests": [{"test": t, "alerts": int(c), "share_pct": round(100 * c / n)} for t, c in tests.most_common(8)],
        "dominant": dom, "dominant_share": round(dom_n / n, 2),
        "early": None if early is None else round(early, 2), "late": None if late is None else round(late, 2),
        "early_ref": round(ref["early"], 2) if ref else None, "late_ref": round(ref["late"], 2) if ref else None,
        "timed": int(len(f_dom)), "age_median_m": None if g["_age_m"].dropna().empty else round(float(g["_age_m"].median()), 1),
        "class_wide": len(mk) >= 8 and top3 < 0.45, "maker_specific": len(mk) >= 3 and top3 >= 0.6,
        "labs": sorted(labs, key=lambda x: -x["lift"])[:2],
        # proton-pump inhibitors and 'gastro-resistant' / 'enteric' products fail through their coat
        "enteric": bool(g["_product"].str.contains(r"gastro|enteric|\bDR\b|delayed", case=False, regex=True).mean() > 0.3
                        or any(i.endswith("prazole") for i in g["_ings"].iloc[0])),
        "last": g["Parsed_Date"].max().strftime("%Y-%m") if g["Parsed_Date"].notna().any() else None,
        "recent_24m": int((g["Parsed_Date"] >= g["Parsed_Date"].max() - pd.DateOffset(months=24)).sum()) if g["Parsed_Date"].notna().any() else 0,
    }


def _archetype(s: dict[str, Any]) -> tuple[str, str]:
    """(id, short headline) — the one pattern that best describes the product's failures."""
    dom, early, late = s["dominant"], s["early"], s["late"]
    er = s["early_ref"] or 0.2
    if dom in ("Sterility", "Endotoxin", "Particulate matter"):
        return "aseptic", "Sterile-process failures"
    if dom == "Labelling":
        return "labelling", "Labelling / misbranding, not a lab failure"
    if early is not None and early >= max(0.35, 1.6 * er):
        return "born", "Fails from the first months — released that way"
    if late is not None and late >= 0.45 and (early or 0) < 0.2:
        return "ages", "Passes at release, fails with age"
    if s["maker_specific"]:
        return "plant", "A few plants cause most failures"
    return "marginal", "Fails throughout its shelf life — a marginal formula"


def _hypotheses(s: dict[str, Any], chem: list[dict[str, Any]], form: str) -> list[dict[str, Any]]:
    H: list[dict[str, Any]] = []
    dom, share = s["dominant"], round(100 * s["dominant_share"])
    early, late = s["early"], s["late"]
    pct = lambda x: f"{round(100 * x)}%" if x is not None else "—"  # noqa: E731
    lipo = [c for c in chem if c.get("xlogp") is not None and float(c["xlogp"]) >= 3]
    amines = [c for c in chem if c.get("amine")]
    enteric = s.get("enteric", False)

    def add(title, confidence, evidence, checks):
        H.append({"title": title, "confidence": confidence, "evidence": [e for e in evidence if e], "checks": checks})

    timing = f"{pct(early)} of its {dom.lower()} failures surface in the first quarter of shelf life (all products: {pct(s['early_ref'])}); {pct(late)} after 60% of shelf life (all products: {pct(s['late_ref'])})"
    if dom in ("Dissolution", "Disintegration"):
        if early is not None and early >= max(0.35, 1.6 * (s["early_ref"] or 0.2)):
            add("Release / formulation flaw — the batches never had the dissolution profile", "strong",
                [f"{share}% of alerts fail {dom.lower()}", timing,
                 *(f"{c['ingredient'].title()} is lipophilic (XLogP3 {c['xlogp']}): poorly water-soluble, so dissolution depends on particle size and wetting" for c in lipo)],
                ["API particle size (d90) in the specification — micronise if it drifts", "Wetting agent / surfactant (e.g. SLS) and disintegrant level",
                 "Lubricant over-blending (magnesium stearate) and compression force / hardness window",
                 "Release dissolution in the pharmacopoeial medium, every batch — and a profile (f2) against the innovator"])
        elif late is not None and late >= 0.45:
            add("Stability flaw — dissolution slows as the batch ages", "strong",
                [f"{share}% of alerts fail {dom.lower()}", timing],
                [*(["Gastro-resistant product: the enteric coat is the usual culprit — check acid-stage resistance and buffer-stage "
                    "release on aged samples, coat thickness and plasticiser"] if enteric else []),
                 "Hardness and dissolution on real-time stability at 30 °C / 75 % RH (India is climatic zone IVb)",
                 "Moisture protection: PVC blister → PVDC or Alu-Alu, desiccant in bottles",
                 "Capsules: gelatin cross-linking (aldehyde traces in excipients) — consider HPMC shells",
                 "Film-coat curing and binder level (post-compression hardening)"])
        else:
            add("Marginal formulation — fails at any age", "moderate",
                [f"{share}% of alerts fail {dom.lower()}", timing,
                 *(f"{c['ingredient'].title()} is lipophilic (XLogP3 {c['xlogp']})" for c in lipo)],
                ["Process capability on dissolution (how close release results sit to the limit)",
                 "API supplier / grade changes against failing batches", "Dissolution profile (f2) against the innovator"])
    elif dom in ("Assay / content", "Related substances"):
        if late is not None and late >= 0.45:
            add("Chemical degradation — potency falls over the shelf life", "strong",
                [f"{share}% of alerts fail {dom.lower()}", timing],
                ["Forced-degradation study: hydrolysis, oxidation, light", "Overage justified by stability data (common for vitamins)",
                 "Light / moisture barrier packaging (amber, Alu-Alu)", "Antioxidant / pH buffer in liquids"])
        elif early is not None and early >= 0.3:
            add("Under- or over-dosed at release — a manufacturing error", "strong",
                [f"{share}% of alerts fail {dom.lower()}", timing],
                ["Blend uniformity and content uniformity per batch", "API dispensing corrected for assay / water content (as-is basis)",
                 "Overage and fill volume (liquids) at release"])
        else:
            add("Potency out of limits through the shelf life", "moderate", [f"{share}% of alerts fail {dom.lower()}", timing],
                ["Release assay against limits (how much margin)", "Stability-indicating method", "Packaging barrier"])
    elif dom == "Description":
        add("Physical change — colour, mottling, spots", "moderate",
            [f"{share}% of alerts fail description / appearance", timing,
             *(f"{c['ingredient'].title()} has a free amine: with lactose or other reducing sugars it browns (Maillard reaction)" for c in amines)],
            ["Excipient compatibility (swap lactose for mannitol / MCC if an amine API)", "Moisture and light protection",
             "Colour / coating dye stability"])
    elif dom in ("Sterility", "Endotoxin", "Particulate matter"):
        add("Sterile-process failure", "strong",
            [f"{share}% of alerts fail {dom.lower()}",
             f"{round(100 * s['top3_share'])}% of these alerts come from 3 makers" if s["maker_specific"] else None],
            ["Media fills and filter-integrity tests", "Depyrogenation of containers, endotoxin in water for injection",
             "Container-closure integrity (large-volume bags / bottles)", "Visual inspection of every unit for particles"])
    elif dom == "Uniformity":
        add("Process variability — weight / content not uniform", "moderate", [f"{share}% of alerts fail uniformity"],
            ["Granule size distribution and flow", "Press speed and die fill", "In-process weight checks frequency"])
    elif dom == "Labelling":
        add("Labelling / misbranding", "strong", [f"{share}% of alerts are misbranding or labelling"],
            ["Label claim versus composition", "Artwork control and change management"])
    if s["class_wide"]:
        add("Class-wide: the usual way of making it is marginal", "strong",
            [f"{s['makers']} different makers had it fail; the three largest account for only {round(100 * s['top3_share'])}%"],
            ["Do not copy the common formula — benchmark against the innovator, not the market",
             "Tighten release limits inside the pharmacopoeial ones (a guard band)"])
    elif s["maker_specific"]:
        add("Plant-specific: a few makers cause most failures", "strong",
            [f"{round(100 * s['top3_share'])}% of alerts come from 3 of {s['makers']} makers ({s['repeat_makers']} makers failed more than once)"],
            ["The formula is workable — the other makers pass. Look at the plants, not the product"])
    for lab in s["labs"]:
        add(f"{lab['lab']} finds it {lab['lift']}× more than expected", "moderate",
            [f"{lab['share_pct']}% of this product's alerts, against {lab['national_pct']}% of all alerts from that laboratory"],
            ["Check your release method against the monograph edition and apparatus that laboratory uses",
             "Stock in that region may be older or stored hotter — check distribution conditions"])
    return H


def _groups() -> list[dict[str, Any]]:
    d = _frame()
    base = _cache["base"]
    hit = _cache.get("groups")
    if hit is not None:
        return hit
    out = []
    for grp, g in d.groupby("_group"):
        if len(g) < MIN_ALERTS:
            continue
        s = _signals(g, base)
        arch, headline = _archetype(s)
        out.append({"key": grp, "label": _label(grp), "form": grp.split("|", 1)[1], "ingredients": list(g["_ings"].iloc[0]),
                    "archetype": arch, "headline": headline,
                    "products": g["_product"].value_counts().head(3).index.tolist(), **{k: s[k] for k in (
                        "n", "makers", "top3_share", "dominant", "dominant_share", "early", "late", "class_wide", "maker_specific",
                        "last", "recent_24m")}, "lab_hotspot": s["labs"][0]["lab"] if s["labs"] else None})
    out.sort(key=lambda r: -r["n"])
    _cache["groups"] = out
    return out


ARCHETYPES = {
    "born": "Fails from the first months — released that way (formulation / process)",
    "ages": "Passes at release, fails with age (stability / packaging)",
    "marginal": "Fails at any age — a marginal formula",
    "plant": "A few plants cause most failures",
    "aseptic": "Sterile-process failures",
    "labelling": "Labelling / misbranding",
}


def overview() -> dict[str, Any]:
    gs = _groups()
    if not gs:
        return {"available": False}
    counts = Counter(g["archetype"] for g in gs)
    # Quality gaps: products many different makers keep failing recently — a buyer (state tender, hospital chain) wants a
    # maker who gets it right, and the fix is known.
    gaps = sorted([g for g in gs if g["class_wide"] and g["recent_24m"] >= 5],
                  key=lambda g: -(g["recent_24m"] * (1 + g["makers"] / 20)))[:12]
    d = _frame()
    full = data.frame()
    source = {"alerts_total": int(len(full)), "alerts_with_ingredients": int(len(d)),
              "first": d["Parsed_Date"].min().strftime("%Y-%m") if d["Parsed_Date"].notna().any() else None,
              "last": d["Parsed_Date"].max().strftime("%Y-%m") if d["Parsed_Date"].notna().any() else None,
              "timed": int(d["_frac"].notna().sum()), "labs": int(d["Reporting by Lab/State"].nunique()),
              "makers": int(d["Mfg_Ontology_Key"].nunique()), "min_alerts": MIN_ALERTS}
    return {
        "available": True, "source": source, "groups": len(gs), "alerts": int(sum(g["n"] for g in gs)),
        "archetypes": [{"id": k, "label": ARCHETYPES[k], "products": counts.get(k, 0)} for k in ARCHETYPES],
        "class_wide": sum(1 for g in gs if g["class_wide"]), "maker_specific": sum(1 for g in gs if g["maker_specific"]),
        "quality_gaps": gaps,
        "born": [g for g in gs if g["archetype"] == "born"][:8], "ages": [g for g in gs if g["archetype"] == "ages"][:8],
        "plant": [g for g in gs if g["archetype"] == "plant"][:8],
        "lab_hotspots": [g for g in gs if g["lab_hotspot"]][:8],
    }


def listing(q: str = "", archetype: str = "", sort: str = "alerts", page: int = 1, size: int = 25) -> dict[str, Any]:
    gs = _groups()
    ql = (q or "").lower().split()
    sel = [g for g in gs if (not archetype or g["archetype"] == archetype)
           and all(w in (g["label"] + " " + " ".join(g["products"])).lower() for w in ql)]
    if sort == "recent":
        sel.sort(key=lambda g: (-g["recent_24m"], -g["n"]))
    elif sort == "makers":
        sel.sort(key=lambda g: (-g["makers"], -g["n"]))
    pages = max(1, -(-len(sel) // size))
    return {"total": len(sel), "page": min(page, pages), "pages": pages, "items": sel[(min(page, pages) - 1) * size: min(page, pages) * size]}


def detail(key: str) -> Optional[dict[str, Any]]:
    d = _frame()
    g = d[d["_group"] == key]
    if len(g) < MIN_ALERTS:
        return None
    base = _cache["base"]
    s = _signals(g, base)
    arch, headline = _archetype(s)
    form = key.split("|", 1)[1]
    chem = _chemistry(list(g["_ings"].iloc[0]))
    dom = s["dominant"]
    fd = g[g["_tests"].map(lambda ts: dom in ts)]["_frac"].dropna()
    ref = d.explode("_tests")
    ref = ref[ref["_tests"] == dom]["_frac"].dropna()

    def bins(f: pd.Series) -> list[float]:
        return [round(100 * float(((f >= lo) & (f < hi)).mean()), 1) if len(f) else 0.0 for lo, hi, _ in TIMING_BINS]

    makers = []
    for k, mg in g.groupby(g["Mfg_Ontology_Key"].fillna("")):
        if not k:
            continue
        nm = str(mg["Mfg_Company_Canonical"].dropna().iloc[0]) if mg["Mfg_Company_Canonical"].notna().any() else k
        makers.append({"key": k, "name": re.sub(r"^M/s\.?\s*", "", nm, flags=re.I).strip(), "alerts": int(len(mg)),
                       "state": str(mg["Mfg_State_Ontology"].dropna().iloc[0]) if mg["Mfg_State_Ontology"].notna().any() else "",
                       "tests": Counter(t for ts in mg["_tests"] for t in ts).most_common(1)[0][0],
                       "last": mg["Parsed_Date"].max().strftime("%Y-%m") if mg["Parsed_Date"].notna().any() else None})
    makers.sort(key=lambda m: (-m["alerts"], m["name"]))
    idx = insights.tracked_index()
    tracked = sorted({m for p in g["_product"].unique() for m in insights.tracked_for(p, idx)})
    states = []
    for st, c in g["Mfg_State_Ontology"].fillna("").value_counts().head(6).items():
        if st:
            states.append({"state": st, "alerts": int(c), "share_pct": round(100 * c / len(g)), "national_pct": round(100 * (base["states"].get(st) or 0), 1)})
    examples = g.sort_values("Parsed_Date", ascending=False).head(6)
    return {
        "key": key, "label": _label(key), "form": form, "archetype": arch, "archetype_label": ARCHETYPES[arch], "headline": headline,
        "signals": s, "hypotheses": _hypotheses(s, chem, form), "chemistry": chem,
        "timing": {"bins": [b[2] for b in TIMING_BINS], "product": bins(fd), "all_products": bins(ref), "test": dom, "n": int(len(fd))},
        "trend": insights._month_series(g.assign(_t=g["_tests"].map(lambda ts: ts[0])), "_t", top=4),
        "makers": makers[:40], "states": states,
        "products": [{"name": str(k), "alerts": int(v)} for k, v in g["_product"].value_counts().head(8).items()],
        "tracked": tracked,
        "examples": [{"product": r["_product"], "reason": str(r["NSQ Result"]), "month": r["Parsed_Date"].strftime("%Y-%m") if pd.notna(r["Parsed_Date"]) else None,
                      "age_m": None if pd.isna(r["_age_m"]) else round(float(r["_age_m"]), 1), "lab": r["Reporting by Lab/State"],
                      "mfr_key": r["Mfg_Ontology_Key"], "id": str(r["record_id"])} for _, r in examples.iterrows()],
        "caveat": "Hypotheses from the pattern of public NSQ alerts, not findings about any company. The report month lags sampling, "
                  "so the shelf-life timing is an upper bound.",
    }


def clear() -> None:
    with _lock:
        _cache.clear()
        _cache["key"] = None
