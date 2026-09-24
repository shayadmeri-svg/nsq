#!/usr/bin/env python3
"""Simplify a states GeoJSON so the choropleth stops being the slow part.

Why: analytics/india_states_slim.geojson is 7.2 MB / ~525k coordinate pairs
despite the "slim" in its name (Gujarat alone carries 113k points). Plotly
embeds the whole GeoJSON in the figure JSON, and Streamlit pushes that figure
over the websocket on *every* rerun — every filter change, every widget
click. That is the single biggest cost in the analytics app, and it is also
what makes browsers give up mid-render (the WebSocketClosedError flood).

At the zoom a national choropleth is viewed at, a ~1 km vertex spacing is
already finer than one screen pixel, so the detail buys nothing.

What it does, per feature:
  * Douglas-Peucker simplify at --tolerance degrees (topology-preserving
    per polygon; shared borders can develop hairline gaps at high tolerance,
    which is invisible at national zoom but is why the default is modest).
  * Drops islands/slivers smaller than --min-area deg^2 (keeps the largest
    ring of every feature regardless, so no state can vanish).
  * Rounds coordinates to --precision decimals (5 dp ~ 1 m; 4 dp ~ 11 m).

Usage:
    python3 simplify_geojson.py \
        --input ../analytics/india_states_slim.geojson \
        --output ../analytics/india_states_slim.geojson \
        --tolerance 0.01

Re-run it on any replacement boundary file; then push it to Redis with
`just push-geojson` (the apps read geo:india_states from Redis first).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from shapely.geometry import MultiPolygon, mapping, shape


def _count(coords) -> int:
    # shapely's mapping() emits tuples, the source file lists — handle both.
    if isinstance(coords, (list, tuple)):
        if coords and isinstance(coords[0], (int, float)):
            return 1
        return sum(_count(c) for c in coords)
    return 0


def _round(obj, nd: int):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, (list, tuple)):
        return [_round(o, nd) for o in obj]
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    return obj


def _drop_small_parts(geom, min_area: float, rel_frac: float = 0.01):
    """Drop sub-polygons below the threshold, always keeping the largest one.

    The threshold is ``min(min_area, rel_frac * total_area)`` — relative, not
    just absolute. A flat absolute floor deleted 92% of Lakshadweep, whose
    every island is smaller than the floor; scaling by the feature's own area
    keeps archipelago UTs intact while still pruning slivers off big states.

    The parts are disjoint islands, so they are re-wrapped as a MultiPolygon
    rather than dissolved: unary_union on simplified coastlines can raise
    TopologyException on a self-touching ring (seen at 92.69, 11.81 in the
    Andamans), and there is nothing to dissolve anyway.
    """
    if geom.geom_type != "MultiPolygon":
        return geom
    threshold = min(min_area, rel_frac * geom.area)
    parts = sorted(geom.geoms, key=lambda g: g.area, reverse=True)
    kept = [parts[0]] + [p for p in parts[1:] if p.area >= threshold]
    return kept[0] if len(kept) == 1 else MultiPolygon(kept)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--tolerance", type=float, default=0.01,
                    help="Douglas-Peucker tolerance in degrees (0.01 ~ 1.1 km). Default 0.01.")
    ap.add_argument("--min-area", type=float, default=0.0005,
                    help="Absolute ceiling for the small-part threshold (deg^2). "
                         "Default 0.0005 (~6 km^2). The effective threshold is "
                         "min(this, 1%% of the feature's area).")
    ap.add_argument("--precision", type=int, default=5,
                    help="Decimal places to round coordinates to. Default 5 (~1 m).")
    ap.add_argument("--name-key", default="NAME_1",
                    help="Feature property holding the state name (for the report).")
    args = ap.parse_args()

    src = Path(args.input)
    data = json.loads(src.read_text())
    before_pts = sum(_count(f["geometry"]["coordinates"]) for f in data["features"])
    before_bytes = src.stat().st_size

    for feat in data["features"]:
        geom = shape(feat["geometry"])
        if not geom.is_valid:  # a few source rings self-intersect
            geom = geom.buffer(0)
        # Scale the tolerance down for small features. A flat 0.01 deg
        # (~1.1 km) is nothing against Gujarat but is wider than a
        # Lakshadweep island, and shrank that UT by ~48%. Cap the tolerance
        # at 5% of the feature's own linear extent.
        tol = min(args.tolerance, 0.05 * math.sqrt(geom.area)) if geom.area else args.tolerance
        simplified = geom.simplify(tol, preserve_topology=True)
        simplified = _drop_small_parts(simplified, args.min_area)
        if simplified.is_empty:  # never let a state disappear
            simplified = geom
        feat["geometry"] = _round(mapping(simplified), args.precision)

    out = Path(args.output)
    out.write_text(json.dumps(data, separators=(",", ":")))
    after_pts = sum(_count(f["geometry"]["coordinates"]) for f in data["features"])
    after_bytes = out.stat().st_size

    print(f"features:   {len(data['features'])}")
    print(f"points:     {before_pts:,} -> {after_pts:,} "
          f"({100 * after_pts / before_pts:.1f}% kept)")
    print(f"size:       {before_bytes / 1e6:.2f} MB -> {after_bytes / 1e6:.2f} MB "
          f"({100 * after_bytes / before_bytes:.1f}%)")
    print(f"tolerance:  {args.tolerance} deg, min-area {args.min_area} deg^2, "
          f"{args.precision} dp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
