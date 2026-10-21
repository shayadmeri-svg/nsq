"""A plant's own batch records: the files its equipment and QC lab export, read into one row per batch, charted
against limits, and used to calibrate the process twin (chem.process_twin) to that plant.

Formats (one per apparatus) — each a CSV / Excel layout with known column names; a file's own headers are matched to
them by name and common synonyms, and anything unmatched can be mapped by hand:

    batch_summary   batch manufacturing record summary, one row per batch (any process parameter or QC result)
    rmg             rapid mixer granulator: binder and dry-mix quantities, impeller power, wet-mixing time
    fbd             fluid-bed dryer log: inlet / outlet / product temperature, inlet humidity or dew point, air flow, LOD
    blender         blender / lubrication: lubricated blend time, speed
    press           tablet press log: compression force, punch diameter, tablet weights
    ipqc            in-process checks: individual weights, hardness, thickness, friability, disintegration
    dissolution     dissolution tester export: % dissolved per vessel and time point
    qc_release      QC release results (certificate of analysis of the batch)
    api_coa         API certificate of analysis per product batch: assay, particle size, water

How a per-batch value is derived from raw rows (each derived value carries this note in the output):

    compression pressure  = mean main compression force / punch face area (flat-faced, round)
    weight RSD            = SD / mean of the individual tablet weights (≥ 5 weights)
    tensile strength      = 2F / (π·D·t), Fell & Newton (1970), flat-faced round tablets
    dew point             = Magnus formula from relative humidity and temperature (Alduchov & Eskridge 1996 constants)
    granulation liquid    = binder solution / dry mix × 100
    drying time           = span of the dryer log; final LOD = the last LOD reading of the batch
    dissolution at Q time = mean of the vessels, linearly interpolated at the Q time point

Charts: individuals control chart per field — centre = mean, limits = mean ± 3·MR̄/1.128 (I-MR, Montgomery) —
with Nelson's rules 1 (a point beyond 3σ), 2 (nine in a row on one side) and 3 (six in a row rising or falling).
Cpk uses the within-batch-to-batch σ (MR̄/1.128); with fewer than 25 batches it is indicative only.
"""

from __future__ import annotations

import io
import math
import re
from typing import Any, Optional

import numpy as np
import pandas as pd

from . import process_twin as twin

# --- fields -------------------------------------------------------------------------------------------------------
# kind: meta | param (a twin parameter, same id) | cqa (a quality result; `cqa` = the twin test it is) | raw (feeds a
# derived value or is charted on its own)

F: dict[str, dict[str, Any]] = {}


def _f(id: str, label: str, unit: str, kind: str, syn: tuple[str, ...] = (), cqa: Optional[str] = None,
       spec: Optional[dict[str, Any]] = None, note: str = "") -> None:
    F[id] = {"id": id, "label": label, "unit": unit, "kind": kind, "synonyms": list(syn), "cqa": cqa, "spec": spec, "note": note}


_f("batch_no", "Batch number", "", "meta", ("batch", "batch no", "batch number", "batch id", "lot", "lot no", "lot number", "b no", "bno", "batch code"))
_f("product", "Product", "", "meta", ("product name", "item", "item name", "product description", "brand"))
_f("mfg_date", "Manufacturing date", "", "meta", ("mfg date", "date of manufacture", "manufacturing date", "mfd", "date"))
_f("elapsed_min", "Elapsed time", "min", "meta", ("time min", "elapsed", "elapsed time", "minutes", "run time", "process time"))
_f("timestamp", "Timestamp", "", "meta", ("time stamp", "datetime", "date time", "time"))
_f("time_min", "Sampling time", "min", "meta", ("sampling time", "time point", "timepoint", "pull time"))
_f("vessel", "Vessel / unit", "", "meta", ("vessel no", "jar", "unit", "position", "bowl"))
_f("sample_no", "Sample number", "", "meta", ("sample", "sample no", "tablet no", "tablet", "s no", "sr no"))
_f("api_lot", "API lot", "", "meta", ("api batch", "api lot no", "raw material lot", "ar no"))

# twin parameters
_f("api_potency_pct", "API assay (CoA)", "%", "param", ("api assay", "api potency", "assay of api", "api purity", "coa assay"))
_f("api_d50_um", "API particle size d50", "µm", "param", ("d50", "d 50", "psd d50", "d 0 5", "d0 5", "particle size d50", "median particle size"))
_f("weighing_error_pct", "Dispensing error", "%", "param", ("dispensing error", "weighing error", "dispensing deviation"))
_f("granulation_liquid_pct", "Granulation liquid", "% w/w", "param", ("binder pct", "binder %", "granulation liquid", "liquid w w", "binder solution pct"))
_f("inlet_c", "Inlet air temperature", "°C", "param", ("inlet temp", "inlet temperature", "inlet air temp", "inlet air temperature", "supply temp"))
_f("dew_point_c", "Inlet dew point", "°C", "param", ("dew point", "inlet dew point", "dewpoint"))
_f("air_m3_h", "Air flow", "m³/h", "param", ("airflow", "air flow", "air volume", "air flow m3 h", "air flow cmh", "cmh"))
_f("drying_min", "Drying time", "min", "param", ("drying time", "drying duration", "dry time"))
_f("blend_min", "Lubricated blend time", "min", "param", ("blend time", "lubrication time", "lubricated blend time", "mixing time", "lube time"))
_f("pressure_mpa", "Compression pressure", "MPa", "param", ("compression pressure", "compaction pressure"))
_f("weight_rsd_pct", "Tablet weight RSD", "%", "param", ("weight rsd", "weight variation rsd", "rsd weight", "weight cv"))

# raw values that feed a parameter, or are worth charting on their own
_f("binder_kg", "Binder solution added", "kg", "raw", ("binder added", "binder qty", "binder solution", "granulating fluid", "water added"))
_f("dry_mix_kg", "Dry mix", "kg", "raw", ("dry mix", "dry mix weight", "blend weight", "batch size"))
_f("impeller_kw", "Impeller power (end)", "kW", "raw", ("impeller power", "power kw", "impeller load", "end point power"))
_f("wet_mix_min", "Wet mixing time", "min", "raw", ("wet mixing time", "kneading time", "wet mix time"))
_f("outlet_c", "Outlet air temperature", "°C", "raw", ("outlet temp", "outlet temperature", "exhaust temp", "exhaust temperature"))
_f("product_c", "Product temperature", "°C", "raw", ("product temp", "product temperature", "bed temp", "bed temperature"))
_f("inlet_rh_pct", "Inlet relative humidity", "%RH", "raw", ("inlet rh", "rh", "relative humidity", "humidity", "inlet humidity"))
_f("air_cfm", "Air flow", "CFM", "raw", ("cfm", "air flow cfm", "airflow cfm"))
_f("blender_rpm", "Blender speed", "rpm", "raw", ("blender rpm", "blender speed", "speed rpm"))
_f("force_kn", "Main compression force", "kN", "raw", ("main compression force", "compression force", "main force", "mcf", "force"))
_f("precompression_kn", "Pre-compression force", "kN", "raw", ("pre compression", "precompression", "pre compression force"))
_f("punch_diameter_mm", "Punch diameter", "mm", "raw", ("punch diameter", "punch dia", "punch size", "die diameter", "tooling diameter", "diameter", "dia"))
_f("press_rpm", "Turret speed", "rpm", "raw", ("turret speed", "press speed", "turret rpm"))
_f("tablet_weight_mg", "Tablet weight", "mg", "raw", ("tablet weight", "weight", "individual weight", "wt", "weight mg"))
_f("hardness_n", "Hardness", "N", "raw", ("hardness", "breaking force", "crushing strength", "hardness n"))
_f("hardness_kp", "Hardness", "kp", "raw", ("hardness kp", "hardness kg", "kp"))
_f("thickness_mm", "Thickness", "mm", "raw", ("thickness",))
_f("dissolution_min_unit", "Dissolution, lowest vessel at Q time", "%", "raw", ())
_f("pct_dissolved", "Dissolved", "%", "raw", ("dissolved", "% dissolved", "pct dissolved", "release", "% release", "drug release"))
_f("api_water_pct", "API water content", "%", "raw", ("api water", "api moisture", "api kf", "water content api"))
_f("related_subs_pct", "Total impurities", "%", "raw", ("total impurities", "related substances", "total related substances", "impurities"))

# quality results (twin tests where one exists)
_f("assay_pct", "Assay", "% of label claim", "cqa", ("assay", "assay %", "content", "potency"), cqa="assay")
_f("av", "Content uniformity (AV)", "AV", "cqa", ("acceptance value", "content uniformity av", "cu av", "uniformity av"), cqa="uniformity")
_f("dissolution_pct", "Dissolution at Q time", "%", "cqa", ("dissolution", "dissolution %", "dissolution at q", "dissolution result"), cqa="dissolution")
_f("disintegration_min", "Disintegration time", "min", "cqa", ("disintegration", "dt", "disintegration time", "dt min"), cqa="disintegration")
_f("lod_pct", "Loss on drying", "%", "cqa", ("lod", "loss on drying", "moisture", "lod %", "moisture content"), cqa="lod")
_f("tensile_mpa", "Tensile strength", "MPa", "cqa", ("tensile strength", "tensile"), cqa="strength")
_f("friability_pct", "Friability", "%", "cqa", ("friability", "friability %"),
   spec={"hi": 1.0, "text": "≤ 1.0% loss: Ph. Eur. 2.9.7 / USP <1216> (acceptable for most products)"})

# --- formats ------------------------------------------------------------------------------------------------------

FORMATS: list[dict[str, Any]] = [
    {"id": "batch_summary", "label": "Batch record summary", "apparatus": "BMR / batch summary sheet", "shape": "per batch",
     "what": "One row per batch with any process settings and QC results you already tabulate.",
     "required": ["batch_no"],
     "fields": ["batch_no", "product", "mfg_date", "api_potency_pct", "api_d50_um", "granulation_liquid_pct", "inlet_c", "dew_point_c",
                "air_m3_h", "drying_min", "blend_min", "pressure_mpa", "weight_rsd_pct", "assay_pct", "av", "dissolution_pct",
                "disintegration_min", "lod_pct", "friability_pct"]},
    {"id": "rmg", "label": "Rapid mixer granulator", "apparatus": "RMG / high-shear granulator printout", "shape": "per batch",
     "what": "Binder and dry-mix quantities, wet-mixing time and the impeller power at the end point.",
     "required": ["batch_no"], "fields": ["batch_no", "mfg_date", "dry_mix_kg", "binder_kg", "granulation_liquid_pct", "wet_mix_min", "impeller_kw"]},
    {"id": "fbd", "label": "Fluid-bed dryer log", "apparatus": "FBD / FBP trend export (SCADA or printout)", "shape": "time series",
     "what": "One row per reading: inlet / outlet / product temperature, inlet humidity or dew point, air flow, and LOD checks.",
     "required": ["batch_no"], "fields": ["batch_no", "mfg_date", "elapsed_min", "inlet_c", "outlet_c", "product_c", "inlet_rh_pct", "dew_point_c",
                                          "air_m3_h", "lod_pct"]},
    {"id": "blender", "label": "Blender / lubrication", "apparatus": "Octagonal / bin / V-blender record", "shape": "per batch",
     "what": "Lubricated blend time and speed per batch.", "required": ["batch_no"], "fields": ["batch_no", "mfg_date", "blend_min", "blender_rpm"]},
    {"id": "press", "label": "Tablet press log", "apparatus": "Compression machine report (Cadmach, Karnavati, ACG, Fette, Korsch…)", "shape": "time series",
     "what": "One row per reading or sample: main compression force, punch diameter, tablet weight.",
     "required": ["batch_no"], "fields": ["batch_no", "mfg_date", "timestamp", "force_kn", "precompression_kn", "punch_diameter_mm", "tablet_weight_mg", "press_rpm"]},
    {"id": "ipqc", "label": "In-process checks", "apparatus": "IPQC: balance, hardness tester, vernier, friabilator, DT apparatus", "shape": "per tablet",
     "what": "One row per tablet sampled: weight, hardness, thickness, diameter; friability and disintegration per batch.",
     "required": ["batch_no"], "fields": ["batch_no", "mfg_date", "sample_no", "tablet_weight_mg", "hardness_n", "thickness_mm", "punch_diameter_mm",
                                          "friability_pct", "disintegration_min"]},
    {"id": "dissolution", "label": "Dissolution tester export", "apparatus": "Dissolution apparatus (Electrolab, LabIndia, Agilent, Distek…)", "shape": "per vessel × time",
     "what": "One row per vessel and time point: % dissolved.", "required": ["batch_no", "pct_dissolved"],
     "fields": ["batch_no", "mfg_date", "vessel", "time_min", "pct_dissolved"]},
    {"id": "qc_release", "label": "QC release results", "apparatus": "Certificate of analysis / LIMS export", "shape": "per batch",
     "what": "Finished-product results per batch.", "required": ["batch_no"],
     "fields": ["batch_no", "product", "mfg_date", "assay_pct", "av", "dissolution_pct", "disintegration_min", "lod_pct", "related_subs_pct", "friability_pct"]},
    {"id": "api_coa", "label": "API certificate of analysis", "apparatus": "API supplier CoA / incoming QC", "shape": "per batch",
     "what": "For each product batch, the API lot used and its assay, particle size and water.", "required": ["batch_no"],
     "fields": ["batch_no", "api_lot", "api_potency_pct", "api_d50_um", "api_water_pct"]},
]
FORMAT_BY_ID = {f["id"]: f for f in FORMATS}

PARAM_IDS = [p.id for p in twin.PARAMS]
CQA_FIELDS = {k: v["cqa"] for k, v in F.items() if v["kind"] == "cqa" and v["cqa"]}


# --- reading ------------------------------------------------------------------------------------------------------

def norm(h: Any) -> str:
    h = str(h or "").lower().replace("µ", "u")
    h = re.sub(r"\(.*?\)|\[.*?\]", " ", h)
    return re.sub(r"[^a-z0-9%]+", " ", h).strip()


def read_table(content: bytes, filename: str = "") -> pd.DataFrame:
    """CSV / TSV (any delimiter) or Excel (first sheet), headers in the first row, every cell as text."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(io.BytesIO(content), dtype=str)
    else:
        text = content.decode("utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, skip_blank_lines=True)
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df.loc[:, [c for c in df.columns if c and not c.lower().startswith("unnamed")]]


def _candidates(fid: str) -> list[str]:
    f = F[fid]
    return [c for c in dict.fromkeys([norm(fid.replace("_", " ")), norm(fid), norm(f["label"]), *map(norm, f["synonyms"])]) if c]


# A unit written in the header decides between fields measured in different units
_UNIT_FIELD = [(r"\bcfm\b", "air_cfm"), (r"\b(kp|kgf|kg)\b", "hardness_kp")]


def _unit_field(header: str) -> Optional[str]:
    h = str(header).lower()
    for rx, fid in _UNIT_FIELD:
        if re.search(rx, h) and (fid != "hardness_kp" or "hard" in h or "break" in h or "crush" in h):
            return fid
    return None


def match_headers(headers: list[str], fields: Optional[list[str]] = None) -> dict[str, str]:
    """{field id: header}: exact (normalised) name or synonym first, then a synonym whose words all appear in the
    header; each header used once, longer (more specific) names winning. A unit in the header (CFM, kp) sends it
    to the field in that unit."""
    fields = list(fields or F)
    forced = {h: u for h in headers if (u := _unit_field(h))}
    for u in forced.values():
        if u not in fields:
            fields.append(u)
    hn = {h: norm(h) for h in headers}
    scored = []
    for fid in fields:
        for c in _candidates(fid):
            ct = set(c.split())
            for h, n in hn.items():
                if h in forced and forced[h] != fid:
                    continue
                if h in forced:
                    scored.append((3, 99, fid, h))
                elif n == c or n == norm(fid):
                    scored.append((2, len(c), fid, h))
                elif ct and ct <= set(n.split()):
                    scored.append((1, len(c), fid, h))
    out: dict[str, str] = {}
    used: set[str] = set()
    for _, _, fid, h in sorted(scored, key=lambda t: (-t[0], -t[1])):
        if fid not in out and h not in used:
            out[fid] = h
            used.add(h)
    return out


def detect_format(headers: list[str]) -> tuple[str, dict[str, str]]:
    """The format whose fields cover the most headers (ties: the more specific format)."""
    best = ("batch_summary", {}, -1.0)
    for fm in FORMATS:
        m = match_headers(headers, fm["fields"])
        if "batch_no" not in m:
            continue
        score = len(m) - 0.01 * len(fm["fields"])
        if score > best[2]:
            best = (fm["id"], m, score)
    if best[2] < 0:
        return "batch_summary", match_headers(headers, FORMAT_BY_ID["batch_summary"]["fields"])
    return best[0], best[1]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False).str.strip(), errors="coerce")


# --- per-batch aggregation ----------------------------------------------------------------------------------------

def dew_point_c(t_c: float, rh_pct: float) -> float:
    """Magnus formula, Alduchov & Eskridge (1996): b = 17.625, c = 243.04 °C."""
    g = math.log(max(rh_pct, 0.1) / 100.0) + 17.625 * t_c / (243.04 + t_c)
    return 243.04 * g / (17.625 - g)


def tensile_mpa(force_n: float, diameter_mm: float, thickness_mm: float) -> float:
    """Fell & Newton (1970), flat-faced round tablets: σ = 2F / (π·D·t)."""
    return 2 * force_n / (math.pi * diameter_mm * thickness_mm)


def to_date(v: Any) -> Optional[pd.Timestamp]:
    """ISO dates as written; anything else read day-first (Indian records: 05/08/2026 is 5 August)."""
    s = str(v or "").strip()
    if not s:
        return None
    d = pd.to_datetime(s, errors="coerce", format="ISO8601") if re.match(r"^\d{4}-\d{1,2}-\d{1,2}", s) else pd.to_datetime(s, errors="coerce", dayfirst=True)
    return None if pd.isna(d) else d


def _batch_key(v: Any) -> str:
    return re.sub(r"\s+", "", str(v or "")).upper()


def aggregate(df: pd.DataFrame, fmt_id: str, mapping: dict[str, str], q_time_min: float = 45.0) -> dict[str, dict[str, Any]]:
    """{batch: {"values": {field: number}, "meta": {...}, "derived": {field: how}}} for one uploaded table."""
    d = pd.DataFrame({fid: df[h] for fid, h in mapping.items() if h in df.columns})
    if "batch_no" not in d:
        raise ValueError("no batch number column: map one to 'Batch number'")
    d["batch_no"] = d["batch_no"].map(_batch_key)
    d = d[d["batch_no"] != ""]
    numeric = [c for c in d.columns if F.get(c, {}).get("kind") in ("param", "cqa", "raw") or c in ("elapsed_min", "time_min")]
    for c in numeric:
        d[c] = _num(d[c])
    out: dict[str, dict[str, Any]] = {}
    for b, g in d.groupby("batch_no", sort=False):
        vals: dict[str, float] = {}
        how: dict[str, str] = {}
        meta = {k: str(g[k].dropna().iloc[0]) for k in ("product", "mfg_date", "api_lot") if k in g and g[k].notna().any()}
        n_rows = len(g)
        series = fmt_id in ("fbd", "press") or n_rows > 1
        for c in numeric:
            col = g[c].dropna()
            if col.empty or c in ("elapsed_min", "time_min", "pct_dissolved", "tablet_weight_mg", "hardness_n", "hardness_kp", "thickness_mm"):
                continue
            if c in ("lod_pct",) and series:
                order = g.sort_values("elapsed_min") if "elapsed_min" in g else g
                vals[c] = float(order[c].dropna().iloc[-1])
                how[c] = "last reading of the batch"
            elif c in ("friability_pct", "disintegration_min") and len(col) > 1:
                vals[c] = float(col.max())
                how[c] = "highest of the batch's readings"
            else:
                vals[c] = float(col.mean())
                if len(col) > 1:
                    how[c] = f"mean of {len(col)} readings"
        # fluid-bed dryer: drying time from the log, dew point from RH
        if "elapsed_min" in g and g["elapsed_min"].notna().any() and "drying_min" not in vals:
            vals["drying_min"] = float(g["elapsed_min"].max())  # an elapsed-time reading counts from the start of drying
            how["drying_min"] = "last elapsed-time reading of the dryer log"
        elif "timestamp" in g and fmt_id == "fbd" and "drying_min" not in vals:
            ts = pd.Series([to_date(t) for t in g["timestamp"]]).dropna()
            if len(ts) >= 2:
                vals["drying_min"] = float((ts.max() - ts.min()).total_seconds() / 60)
                how["drying_min"] = "span of the dryer log timestamps"
        if "dew_point_c" not in vals and "inlet_rh_pct" in vals and "inlet_c" in vals:
            vals["dew_point_c"] = dew_point_c(vals["inlet_c"], vals["inlet_rh_pct"])
            how["dew_point_c"] = "Magnus formula from inlet temperature and RH (Alduchov & Eskridge 1996)"
        if "air_m3_h" not in vals and "air_cfm" in vals:
            vals["air_m3_h"] = vals["air_cfm"] * 1.699
            how["air_m3_h"] = "CFM × 1.699"
        if "granulation_liquid_pct" not in vals and vals.get("binder_kg") and vals.get("dry_mix_kg"):
            vals["granulation_liquid_pct"] = 100 * vals["binder_kg"] / vals["dry_mix_kg"]
            how["granulation_liquid_pct"] = "binder solution / dry mix × 100"
        # press / IPQC: pressure, weight RSD, tensile strength
        dia = vals.get("punch_diameter_mm")
        if "pressure_mpa" not in vals and vals.get("force_kn") and dia:
            vals["pressure_mpa"] = vals["force_kn"] * 1000 / (math.pi * dia ** 2 / 4)
            how["pressure_mpa"] = f"mean main compression force / face area of a {dia:g} mm round punch (flat-faced)"
        if "tablet_weight_mg" in g:
            w = g["tablet_weight_mg"].dropna()
            if len(w) >= 5 and w.mean() > 0:
                vals["weight_rsd_pct"] = float(100 * w.std(ddof=1) / w.mean())
                vals["tablet_weight_mg"] = float(w.mean())
                how["weight_rsd_pct"] = f"SD / mean of {len(w)} tablet weights"
            elif len(w):
                vals["tablet_weight_mg"] = float(w.mean())
        hard = g["hardness_n"].dropna() if "hardness_n" in g else (g["hardness_kp"].dropna() * 9.807 if "hardness_kp" in g else pd.Series(dtype=float))
        if len(hard):
            vals["hardness_n"] = float(hard.mean())
            if "hardness_kp" in g and "hardness_n" not in g:
                how["hardness_n"] = "kp × 9.807"
        if "thickness_mm" in g and g["thickness_mm"].notna().any():
            vals["thickness_mm"] = float(g["thickness_mm"].dropna().mean())
        if "tensile_mpa" not in vals and vals.get("hardness_n") and vals.get("thickness_mm") and dia:
            vals["tensile_mpa"] = tensile_mpa(vals["hardness_n"], dia, vals["thickness_mm"])
            how["tensile_mpa"] = "2F / (π·D·t) from mean hardness and thickness (Fell & Newton 1970, flat-faced)"
        # dissolution tester: mean of the vessels at the Q time
        if "pct_dissolved" in g and g["pct_dissolved"].notna().any():
            if "time_min" in g and g["time_min"].notna().any():
                prof = g.dropna(subset=["time_min", "pct_dissolved"]).groupby("time_min")["pct_dissolved"]
                mean, low = prof.mean().sort_index(), prof.min().sort_index()
                if mean.index.min() <= q_time_min <= mean.index.max():
                    vals["dissolution_pct"] = float(np.interp(q_time_min, mean.index, mean.values))
                    vals["dissolution_min_unit"] = float(np.interp(q_time_min, low.index, low.values))
                    how["dissolution_pct"] = f"mean of {int(g['vessel'].nunique()) if 'vessel' in g else 'all'} vessels at {q_time_min:g} min"
                meta["profile"] = [{"t": float(t), "mean": round(float(m), 2), "min": round(float(low[t]), 2)} for t, m in mean.items()]
            else:
                vals["dissolution_pct"] = float(g["pct_dissolved"].dropna().mean())
                how["dissolution_pct"] = "mean of the vessels"
        out[b] = {"values": {k: round(v, 4) for k, v in vals.items() if v is not None and math.isfinite(v)}, "meta": meta, "derived": how}
    return out


def merge(datasets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Batches from several uploads joined on batch number; for a field present in more than one, the first
    dataset in the list (the newest) wins and the source is recorded."""
    out: dict[str, dict[str, Any]] = {}
    for ds in datasets:
        for b, rec in (ds.get("batches") or {}).items():
            cur = out.setdefault(b, {"batch_no": b, "values": {}, "meta": {}, "derived": {}, "sources": {}})
            for k, v in rec["values"].items():
                if k not in cur["values"]:
                    cur["values"][k] = v
                    cur["sources"][k] = ds.get("name") or ds.get("format")
                    if k in rec.get("derived", {}):
                        cur["derived"][k] = rec["derived"][k]
            for k, v in rec.get("meta", {}).items():
                cur["meta"].setdefault(k, v)
    return out


# --- analysis -----------------------------------------------------------------------------------------------------

def specs_for(specs: Optional[dict[str, Any]] = None) -> dict[str, dict[str, Any]]:
    """Limits per quality field, from the twin's specification defaults (and their stated basis) or the user's."""
    S = {**twin.SPECS, **(specs or {})}
    b = twin.SPEC_BASIS
    out = {
        "assay_pct": {"lo": S["assay_lo"], "hi": S["assay_hi"], **b["assay"]},
        "av": {"hi": S["av_max"], **b["uniformity"]},
        "dissolution_pct": {"lo": S["q_pct"], **b["dissolution"]},
        "disintegration_min": {"hi": S["dt_max_min"], **b["disintegration"]},
        "lod_pct": {"hi": S["lod_max"], **b["lod"]},
        "tensile_mpa": {"lo": S["tensile_min"], **b["strength"]},
        "friability_pct": {"hi": 1.0, "kind": "source", "text": F["friability_pct"]["spec"]["text"]},
    }
    for k, (lo, hi) in ((specs or {}).get("fields") or {}).items():
        out[k] = {"lo": lo, "hi": hi, "kind": "yours", "text": "your specification"}
    return out


def _order(batches: dict[str, dict[str, Any]]) -> list[str]:
    def key(b: str):
        d = to_date(batches[b]["meta"].get("mfg_date"))
        return (pd.Timestamp.max if d is None else d, b)
    return sorted(batches, key=key)


def nelson(x: list[float], mean: float, sigma: float) -> list[dict[str, Any]]:
    """Nelson (1984) rules 1-3 on an individuals chart: indices of the points that trigger each."""
    sig = []
    for i, v in enumerate(x):
        if sigma > 0 and abs(v - mean) > 3 * sigma:
            sig.append({"rule": 1, "at": i, "text": "beyond 3σ"})
    side = [np.sign(v - mean) for v in x]
    run = 1
    for i in range(1, len(x)):
        run = run + 1 if side[i] == side[i - 1] and side[i] != 0 else 1
        if run == 9:
            sig.append({"rule": 2, "at": i, "text": "nine in a row on one side of the mean"})
    up = down = 1
    for i in range(1, len(x)):
        up = up + 1 if x[i] > x[i - 1] else 1
        down = down + 1 if x[i] < x[i - 1] else 1
        if up == 6 or down == 6:
            sig.append({"rule": 3, "at": i, "text": f"six in a row {'rising' if up == 6 else 'falling'}"})
    return sig


def chart(field: str, batches: dict[str, dict[str, Any]], order: list[str], spec: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    pts = [(b, batches[b]["values"][field]) for b in order if field in batches[b]["values"]]
    if not pts:
        return None
    x = np.array([v for _, v in pts], dtype=float)
    mean = float(x.mean())
    sd = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    mr = float(np.abs(np.diff(x)).mean()) if len(x) > 1 else 0.0
    sw = mr / 1.128 if mr > 0 else sd
    lo, hi = (spec or {}).get("lo"), (spec or {}).get("hi")
    cpk = None
    if spec and sw > 0 and len(x) >= 5:
        sides = [(hi - mean) / (3 * sw)] if hi is not None else []
        sides += [(mean - lo) / (3 * sw)] if lo is not None else []
        cpk = round(min(sides), 2) if sides else None
    oos = [b for b, v in pts if (lo is not None and v < lo) or (hi is not None and v > hi)]
    f = F.get(field, {"label": field, "unit": "", "kind": "raw"})
    return {"field": field, "label": f["label"], "unit": f["unit"], "kind": f["kind"], "cqa": f.get("cqa"), "n": len(x),
            "mean": round(mean, 4), "sd": round(sd, 4), "min": round(float(x.min()), 4), "max": round(float(x.max()), 4),
            "median": round(float(np.median(x)), 4), "ucl": round(mean + 3 * sw, 4), "lcl": round(mean - 3 * sw, 4),
            "sigma_within": round(sw, 4), "spec": spec, "cpk": cpk, "cpk_indicative": len(x) < 25, "oos": oos,
            "signals": [{**s, "batch": pts[s["at"]][0]} for s in nelson(list(x), mean, sw)],
            "points": [{"batch": b, "value": round(float(v), 4)} for b, v in pts]}


def calibration(charts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The twin's baseline = the plant's median per parameter; its normal operating range = mean ± 3·SD of the
    plant's batches (≥ 3 batches with spread)."""
    baseline, nor = {}, {}
    for pid in PARAM_IDS:
        c = charts.get(pid)
        if not c:
            continue
        baseline[pid] = c["median"]
        if c["n"] >= 3 and c["sd"] > 0:
            lo = c["mean"] - 3 * c["sd"]
            if pid in ("weight_rsd_pct", "api_d50_um", "blend_min", "drying_min", "air_m3_h"):
                lo = max(lo, 0.05 * c["mean"])
            nor[pid] = [round(lo, 4), round(c["mean"] + 3 * c["sd"], 4)]
    return {"baseline": baseline, "nor": nor}


def diagnose(b: str, rec: dict[str, Any], charts: dict[str, dict[str, Any]], specs: dict[str, dict[str, Any]],
             predicted: Optional[dict[str, float]] = None) -> Optional[dict[str, Any]]:
    """A batch outside a limit: which tests, and its parameters against the plant's own spread — the ones the twin
    links to the failed test first. Shows where to look; it does not establish the cause."""
    v = rec["values"]
    failed = []
    for fid, s in specs.items():
        if fid in v and ((s.get("lo") is not None and v[fid] < s["lo"]) or (s.get("hi") is not None and v[fid] > s["hi"])):
            failed.append({"field": fid, "label": F[fid]["label"], "value": v[fid], "lo": s.get("lo"), "hi": s.get("hi"),
                           "cqa": F[fid].get("cqa"), "predicted": (predicted or {}).get(F[fid].get("cqa") or "")})
    if not failed:
        return None
    linked = {p for f in failed if f["cqa"] for p in twin.EDGES.get(f["cqa"], [])}
    devs = []
    for fid, val in v.items():
        c = charts.get(fid)
        if not c or F.get(fid, {}).get("kind") not in ("param", "raw") or c["n"] < 3 or c["sd"] <= 0:
            continue
        z = (val - c["mean"]) / c["sd"]
        devs.append({"field": fid, "label": c["label"], "unit": c["unit"], "value": val, "mean": c["mean"], "z": round(z, 2),
                     "linked": fid in linked, "outside_limits": not (c["lcl"] <= val <= c["ucl"])})
    devs.sort(key=lambda d: (not d["linked"], -abs(d["z"])))
    return {"batch": b, "failed": failed, "deviations": devs[:8], "meta": rec.get("meta", {})}


def analyse(batches: dict[str, dict[str, Any]], specs: Optional[dict[str, Any]] = None,
            predict: Optional[Any] = None) -> dict[str, Any]:
    """Charts for every field, the batches outside a limit with their diagnosis, and the twin calibration.
    `predict(values) -> {cqa: value}`: the twin's prediction for one batch's parameters (optional)."""
    sp = specs_for(specs)
    order = _order(batches)
    fields = sorted({k for r in batches.values() for k in r["values"]}, key=lambda k: (["cqa", "param", "raw"].index(F.get(k, {}).get("kind", "raw"))
                                                                                       if F.get(k, {}).get("kind") in ("cqa", "param", "raw") else 3, k))
    charts = {f: c for f in fields if (c := chart(f, batches, order, sp.get(f)))}
    cal = calibration(charts)
    preds: dict[str, dict[str, float]] = {}
    if predict:
        for b in order:
            pv = {k: batches[b]["values"][k] for k in PARAM_IDS if k in batches[b]["values"]}
            if pv:
                preds[b] = predict({**cal["baseline"], **pv})
    diag = [d for b in order if (d := diagnose(b, batches[b], charts, sp, preds.get(b)))]
    check = {}
    for fid, cqa in CQA_FIELDS.items():
        pairs = [(batches[b]["values"][fid], preds[b][cqa]) for b in preds if fid in batches[b]["values"] and cqa in preds[b]]
        if pairs:
            err = [p - o for o, p in pairs]
            check[fid] = {"n": len(pairs), "mean_abs_error": round(float(np.mean(np.abs(err))), 3), "bias": round(float(np.mean(err)), 3)}
    rows = [{"batch_no": b, **batches[b]["meta"], "values": batches[b]["values"], "derived": batches[b]["derived"],
             "sources": batches[b].get("sources", {}), "predicted": preds.get(b),
             "out_of_spec": [f for f in charts if b in charts[f]["oos"]]} for b in order]
    return {"batches": rows, "charts": list(charts.values()), "diagnoses": diag, "calibration": cal, "model_check": check,
            "specs": sp, "counts": {"batches": len(order), "fields": len(charts), "out_of_spec_batches": len(diag),
                                    "signals": sum(len(c["signals"]) for c in charts.values())}}


# --- sample files ----------------------------------------------------------------------------------------------------

def _sample_batches(n: int = 10, seed: int = 3) -> list[dict[str, Any]]:
    """Example batches for the sample files (not real data): settings scattered around the twin's defaults, with
    batch 7 compressed hard (low dissolution, slow disintegration) and batch 9 dried short (high LOD)."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(1, n + 1):
        force = rng.normal(13.0, 0.5) + (5.5 if i == 7 else 0)
        rec = {"batch_no": f"EX{i:03d}", "product": "Paracetamol Tablets IP 500 mg", "mfg_date": f"2026-08-{2 * i:02d}",
               "api_potency_pct": rng.normal(99.6, 0.4), "api_d50_um": rng.normal(22, 2.5), "dry_mix_kg": 100.0,
               "binder_kg": rng.normal(25, 0.8), "inlet_c": rng.normal(60, 1.2), "inlet_rh_pct": rng.normal(8, 1.5),
               "air_m3_h": rng.normal(3000, 60), "drying_min": rng.normal(60, 1.5) - (22 if i == 9 else 0),
               "blend_min": rng.normal(5, 0.3), "force_kn": force, "punch_diameter_mm": 12.0, "weight_mg": 650.0,
               "thickness_mm": rng.normal(4.9, 0.05) - (0.25 if i == 7 else 0)}
        rec["hardness_n"] = 175 + 12 * (force - 13) + rng.normal(0, 5)
        rec["lod_pct"] = 1.6 + rng.normal(0, 0.15) + (1.9 if i == 9 else 0)
        rec["dt_min"] = 6 + 2.2 * (force - 13) + rng.normal(0, 0.6)
        rec["q45"] = min(100.0, 93 - 4.5 * max(0, force - 14) + rng.normal(0, 1.5))
        rec["assay_pct"] = rec["api_potency_pct"] + rng.normal(0, 0.6)
        rec["av"] = abs(rng.normal(4.5, 1.2))
        out.append(rec)
    return out


def sample_csv(fmt_id: str) -> str:
    """A filled-in example of the format, with the format's own column names (ingests as-is)."""
    rng = np.random.default_rng(11)
    B = _sample_batches()
    rows: list[dict[str, Any]] = []
    r2 = lambda v, d=2: round(float(v), d)  # noqa: E731
    for b in B:
        base = {"batch_no": b["batch_no"], "mfg_date": b["mfg_date"]}
        if fmt_id == "batch_summary":
            rows.append({**base, "product": b["product"], "api_potency_pct": r2(b["api_potency_pct"]), "api_d50_um": r2(b["api_d50_um"], 1),
                         "granulation_liquid_pct": r2(b["binder_kg"]), "inlet_c": r2(b["inlet_c"], 1),
                         "dew_point_c": r2(dew_point_c(b["inlet_c"], b["inlet_rh_pct"]), 1), "air_m3_h": r2(b["air_m3_h"], 0),
                         "drying_min": r2(b["drying_min"], 0), "blend_min": r2(b["blend_min"], 1),
                         "pressure_mpa": r2(b["force_kn"] * 1000 / (math.pi * 36), 1), "weight_rsd_pct": r2(abs(rng.normal(1.0, 0.15))),
                         "assay_pct": r2(b["assay_pct"], 1), "av": r2(b["av"], 1), "dissolution_pct": r2(b["q45"], 1),
                         "disintegration_min": r2(b["dt_min"], 1), "lod_pct": r2(b["lod_pct"]), "friability_pct": r2(abs(rng.normal(0.3, 0.08)))})
        elif fmt_id == "rmg":
            rows.append({**base, "dry_mix_kg": 100, "binder_kg": r2(b["binder_kg"]), "wet_mix_min": r2(rng.normal(4, 0.3), 1),
                         "impeller_kw": r2(rng.normal(7.5, 0.4))})
        elif fmt_id == "fbd":
            end = int(round(b["drying_min"]))
            for t in [*range(0, end, 10), end]:  # a reading every 10 min and one at the end of drying
                rows.append({**base, "elapsed_min": t, "inlet_c": r2(b["inlet_c"] + rng.normal(0, 0.6), 1),
                             "outlet_c": r2(30 + 0.25 * t + rng.normal(0, 0.5), 1), "product_c": r2(28 + 0.27 * t + rng.normal(0, 0.5), 1),
                             "inlet_rh_pct": r2(b["inlet_rh_pct"] + rng.normal(0, 0.8), 1), "air_m3_h": r2(b["air_m3_h"] + rng.normal(0, 25), 0),
                             "lod_pct": r2(b["lod_pct"] + max(0, 1 - t / end) * 18, 2) if t % 20 == 0 or t == end else ""})
        elif fmt_id == "blender":
            rows.append({**base, "blend_min": r2(b["blend_min"], 1), "blender_rpm": 12})
        elif fmt_id == "press":
            for k in range(12):
                rows.append({**base, "timestamp": f"{b['mfg_date']} {9 + k // 2:02d}:{(k % 2) * 30:02d}", "force_kn": r2(b["force_kn"] + rng.normal(0, 0.4)),
                             "precompression_kn": r2(rng.normal(2.0, 0.15)), "punch_diameter_mm": 12.0,
                             "tablet_weight_mg": r2(rng.normal(650, 6.5), 1), "press_rpm": 30})
        elif fmt_id == "ipqc":
            for k in range(1, 11):
                rows.append({**base, "sample_no": k, "tablet_weight_mg": r2(rng.normal(650, 6.5), 1), "hardness_n": r2(b["hardness_n"] + rng.normal(0, 5), 0),
                             "thickness_mm": r2(b["thickness_mm"] + rng.normal(0, 0.03)), "punch_diameter_mm": 12.0,
                             "friability_pct": r2(abs(rng.normal(0.3, 0.08))) if k == 1 else "", "disintegration_min": r2(b["dt_min"], 1) if k == 1 else ""})
        elif fmt_id == "dissolution":
            for v in range(1, 7):
                for t in (10, 15, 20, 30, 45):
                    frac = 1 - math.exp(-t / max(3.0, 8 + 1.6 * (b["force_kn"] - 13)))
                    rows.append({**base, "vessel": v, "time_min": t, "pct_dissolved": r2(min(101, b["q45"] / (1 - math.exp(-45 / max(3.0, 8 + 1.6 * (b["force_kn"] - 13)))) * frac + rng.normal(0, 1.2)), 1)})
        elif fmt_id == "qc_release":
            rows.append({**base, "product": b["product"], "assay_pct": r2(b["assay_pct"], 1), "av": r2(b["av"], 1), "dissolution_pct": r2(b["q45"], 1),
                         "disintegration_min": r2(b["dt_min"], 1), "lod_pct": r2(b["lod_pct"]), "related_subs_pct": r2(abs(rng.normal(0.12, 0.03))),
                         "friability_pct": r2(abs(rng.normal(0.3, 0.08)))})
        elif fmt_id == "api_coa":
            rows.append({"batch_no": b["batch_no"], "api_lot": f"API-{2400 + int(b['batch_no'][2:]) // 3}", "api_potency_pct": r2(b["api_potency_pct"]),
                         "api_d50_um": r2(b["api_d50_um"], 1), "api_water_pct": r2(abs(rng.normal(0.2, 0.05)))})
        else:
            raise KeyError(fmt_id)
    cols = FORMAT_BY_ID[fmt_id]["fields"]
    df = pd.DataFrame(rows)
    return df[[c for c in cols if c in df.columns]].to_csv(index=False)


def format_guide() -> list[dict[str, Any]]:
    return [{**fm, "columns": [{"id": c, "label": F[c]["label"], "unit": F[c]["unit"], "kind": F[c]["kind"], "required": c in fm["required"],
                                "twin": c if c in PARAM_IDS else F[c].get("cqa"), "synonyms": F[c]["synonyms"][:4]} for c in fm["fields"]]}
            for fm in FORMATS]
