"""Structural tests for analytics/india_states_slim.geojson.

The file is built by redis-loader/build_states_geojson.py from the LGD
(Local Government Directory) states parquet — the official GoI registry —
committed at data/LGD_States.parquet. These tests pin what the choropleth
join actually needs: 36 modern features whose NAME_1 values match the
canonical names extract_state emits (so no alias table is required), each
with non-empty geometry and LGD-code provenance.

Runnable both as `python tests/test_geojson.py` and via pytest.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEOJSON_PATH = REPO / "analytics" / "india_states_slim.geojson"


def _stname_map() -> dict:
    """STNAME_MAP from the build script, parsed without executing it (the
    module imports pyarrow/shapely, which only the loader venv has)."""
    src = (REPO / "redis-loader" / "build_states_geojson.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "STNAME_MAP"):
            return ast.literal_eval(node.value)
    raise AssertionError("STNAME_MAP not found in build_states_geojson.py")


STNAME_MAP = _stname_map()

MAX_BYTES = 3 * 1024 * 1024  # previous GADM-era file was 6.9 MB


def _load():
    try:
        return json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AssertionError(
            f"{GEOJSON_PATH} missing — build it with "
            "redis-loader/.venv/bin/python redis-loader/build_states_geojson.py")


def test_36_modern_features():
    fc = _load()
    assert fc["type"] == "FeatureCollection"
    feats = fc["features"]
    assert len(feats) == 36, f"expected 36 states/UTs, found {len(feats)}"
    names = [f["properties"]["NAME_1"] for f in feats]
    assert len(set(names)) == 36, "duplicate NAME_1"
    # The modern roster: Telangana, Ladakh and the merged Dadra & Nagar
    # Haveli / Daman & Diu UT must exist; legacy GADM-era names must not.
    assert set(names) == set(STNAME_MAP.values())
    for legacy in ("Orissa", "Uttaranchal"):
        assert legacy not in names
    for modern in ("Telangana", "Ladakh", "Odisha", "Uttarakhand",
                   "Jammu and Kashmir"):
        assert modern in names


def test_features_have_lgd_provenance_and_geometry():
    fc = _load()
    for f in fc["features"]:
        assert "st_lgd" in f["properties"], \
            f"{f['properties']['NAME_1']} missing st_lgd provenance code"
        geom = f.get("geometry")
        assert geom and geom.get("coordinates"), \
            f"{f['properties']['NAME_1']} has empty geometry"
        assert geom["type"] in (
            "Polygon", "MultiPolygon"), f"{f['properties']['NAME_1']}: {geom['type']}"


def test_file_size_within_budget():
    size = GEOJSON_PATH.stat().st_size
    assert size <= MAX_BYTES, (
        f"geojson is {size / 1e6:.2f} MB (> {MAX_BYTES / 1e6} MB) — "
        "raise the simplify tolerance ladder in build_states_geojson.py")


if __name__ == "__main__":
    fns = [v for v in globals().values() if callable(v) and v.__name__.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)