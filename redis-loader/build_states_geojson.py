#!/usr/bin/env python3
"""Build analytics/india_states_slim.geojson from the LGD states parquet.

Source of truth for state/UT boundaries is the Local Government Directory
(the official GoI registry) via the india-geodata release
(github.com/yashveeeeeeer/india-geodata, release asset admin/states ->
LGD_States.parquet), committed at data/LGD_States.parquet for
reproducible builds. The output is a 36-feature FeatureCollection whose
NAME_1 values are exactly the canonical display names
company_ontology._STATE_CANONICAL emits, so the choropleth join
(featureidkey='properties.NAME_1') needs no alias table.

The raw WKB is ~15.6 MB; each feature is simplified (Douglas-Peucker,
topology-preserving within the feature) through a tolerance ladder until
the serialized JSON fits under --max-mb (default 3 MB — the previous
GADM-era file was 6.9 MB, so this is a strict improvement). Hairline gaps
between neighbouring simplified states are invisible at dashboard zoom;
if they ever matter, rebuild with `npx mapshaper` topology-aware
simplification instead.

Usage (from anywhere; paths resolve relative to this file):
    redis-loader/.venv/bin/python redis-loader/build_states_geojson.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pyarrow.parquet as pq
import shapely.geometry  # noqa: F401  (shapely.wkb below)
import shapely.wkb
from shapely.geometry import mapping
from shapely.ops import transform

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PARQUET = REPO / "data" / "LGD_States.parquet"
DEFAULT_OUTPUT = REPO / "analytics" / "india_states_slim.geojson"

# LGD STNAME (as stored, UPPERCASE) -> canonical display name. Deliberately
# an explicit map, not case-munging: the display names must match
# company_ontology._STATE_CANONICAL values exactly (the choropleth join
# key). Unknown STNAMEs fail the build loudly rather than shipping a
# mismatched feature.
STNAME_MAP = {
    "ANDAMAN & NICOBAR": "Andaman and Nicobar",
    "ANDHRA PRADESH": "Andhra Pradesh",
    "ARUNACHAL PRADESH": "Arunachal Pradesh",
    "ASSAM": "Assam",
    "BIHAR": "Bihar",
    "CHANDIGARH": "Chandigarh",
    "CHHATTISGARH": "Chhattisgarh",
    "DADRA,NAGAR HAVELI,DAMAN & DIU": "Dadra and Nagar Haveli and Daman and Diu",
    "DELHI": "Delhi",
    "GOA": "Goa",
    "GUJARAT": "Gujarat",
    "HARYANA": "Haryana",
    "HIMACHAL PRADESH": "Himachal Pradesh",
    "JAMMU & KASHMIR": "Jammu and Kashmir",
    "JHARKHAND": "Jharkhand",
    "KARNATAKA": "Karnataka",
    "KERALA": "Kerala",
    "LAKSHADWEEP": "Lakshadweep",
    "LADAKH": "Ladakh",
    "MADHYA PRADESH": "Madhya Pradesh",
    "MAHARASHTRA": "Maharashtra",
    "MANIPUR": "Manipur",
    "MEGHALAYA": "Meghalaya",
    "MIZORAM": "Mizoram",
    "NAGALAND": "Nagaland",
    "ODISHA": "Odisha",
    "PUDUCHERRY": "Puducherry",
    "PUNJAB": "Punjab",
    "RAJASTHAN": "Rajasthan",
    "SIKKIM": "Sikkim",
    "TAMIL NADU": "Tamil Nadu",
    "TELANGANA": "Telangana",
    "TRIPURA": "Tripura",
    "UTTAR PRADESH": "Uttar Pradesh",
    "UTTARAKHAND": "Uttarakhand",
    "WEST BENGAL": "West Bengal",
}

# India's rough bbox (lon/lat) — a sanity check that geometries are in
# degrees and none were mangled to null-island or swapped axes.
INDIA_BBOX = (68.0, 6.0, 97.5, 37.5)

# Tolerance ladder in degrees (~0.001deg ~ 110 m at the equator). First
# tolerance whose serialized size fits under --max-mb wins.
TOLERANCES = (0.001, 0.002, 0.004, 0.008)
COORD_PRECISION = 5  # ~1 m at the equator; enough for dashboard zoom


def load_states(parquet_path: Path) -> list[tuple[int, str, object]]:
    """[(State_LGD, STNAME, shapely geometry)] sorted by State_LGD."""
    table = pq.read_table(parquet_path)
    cols = table.column_names
    for required in ("STNAME", "State_LGD", "geometry"):
        if required not in cols:
            raise SystemExit(
                f"{parquet_path}: expected columns STNAME/State_LGD/"
                f"geometry, found {cols}")
    unknown = sorted({
        str(row["STNAME"]) for row in table.to_pylist()
        if str(row["STNAME"]) not in STNAME_MAP
    })
    if unknown:
        raise SystemExit(
            "parquet contains STNAME(s) missing from STNAME_MAP: "
            f"{unknown} — extend the map (values must match "
            "company_ontology._STATE_CANONICAL).")
    out = []
    for row in table.to_pylist():
        geom = shapely.wkb.loads(row["geometry"])
        out.append((int(row["State_LGD"]), str(row["STNAME"]), geom))
    return sorted(out, key=lambda t: t[0])


def _round_coords(geom):
    return transform(
        lambda x, y: (round(x, COORD_PRECISION), round(y, COORD_PRECISION)),
        geom)


def build_features(states, tolerance):
    """FeatureCollection dict for one ladder run (no size check here)."""
    features = []
    for st_lgd, stname, geom in states:
        simple = geom.simplify(tolerance, preserve_topology=True)
        if simple.is_empty:
            simple = geom  # never ship an empty feature
        features.append({
            "type": "Feature",
            "properties": {"NAME_1": STNAME_MAP[stname], "st_lgd": st_lgd},
            "geometry": mapping(_round_coords(simple)),
        })
    return {"type": "FeatureCollection", "features": features}


def _validate(fc: dict) -> None:
    feats = fc["features"]
    names = [f["properties"]["NAME_1"] for f in feats]
    if len(feats) != 36:
        raise SystemExit(f"expected 36 features, built {len(feats)}")
    if len(set(names)) != 36:
        raise SystemExit("duplicate NAME_1 in output")
    if set(names) != set(STNAME_MAP.values()):
        missing = set(STNAME_MAP.values()) - set(names)
        raise SystemExit(f"NAME_1 set != map values; missing {sorted(missing)}")
    lon_lo = lat_lo = 180.0
    lon_hi = lat_hi = -180.0
    for f in feats:
        if f["geometry"] is None or not f["geometry"].get("coordinates"):
            raise SystemExit(f"empty geometry for {f['properties']['NAME_1']}")
        g = shapely.geometry.shape(f["geometry"])
        if g.is_empty:
            raise SystemExit(f"empty geometry for {f['properties']['NAME_1']}")
        b = g.bounds
        lon_lo, lat_lo = min(lon_lo, b[0]), min(lat_lo, b[1])
        lon_hi, lat_hi = max(lon_hi, b[2]), max(lat_hi, b[3])
    if not (INDIA_BBOX[0] <= lon_lo and INDIA_BBOX[1] <= lat_lo
            and lon_hi <= INDIA_BBOX[2] and lat_hi <= INDIA_BBOX[3]):
        raise SystemExit(
            f"geometry bbox {lon_lo:.1f},{lat_lo:.1f},{lon_hi:.1f},{lat_hi:.1f}"
            " falls outside India — degrees/axis confusion?")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--max-mb", type=float, default=3.0)
    args = ap.parse_args(argv)

    states = load_states(args.parquet)
    wkb_mb = sum(len(s[2].wkb) for s in states) / 1e6
    for tolerance in TOLERANCES:
        fc = build_features(states, tolerance)
        _validate(fc)
        payload = json.dumps(fc, separators=(",", ":"), ensure_ascii=False)
        size_mb = len(payload.encode("utf-8")) / 1e6
        print(f"tolerance {tolerance}: {size_mb:.2f} MB "
              f"(raw WKB {wkb_mb:.2f} MB)")
        if size_mb <= args.max_mb:
            tmp = args.output.with_suffix(".geojson.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, args.output)
            print(f"wrote {args.output} ({size_mb:.2f} MB, 36 features, "
                  f"tolerance {tolerance})")
            return 0
    raise SystemExit(
        f"no tolerance in {TOLERANCES} got the JSON under "
        f"{args.max_mb} MB (best {size_mb:.2f} MB) — extend TOLERANCES "
        "or lower --max-mb")


if __name__ == "__main__":
    sys.exit(main())