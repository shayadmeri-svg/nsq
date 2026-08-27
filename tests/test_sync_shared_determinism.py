"""Determinism test for `just sync-shared`.

The source-of-truth files in ``shared/`` are copied verbatim into each
service's local ``shared/`` dir (the Dockerfiles COPY from there). This
test makes drift a CI failure: if someone edits a synced copy in place
instead of the root source, the sha256 comparison trips.

Mirrors the sync-shared recipe in the justfile:
  - nsq_redis.py, company_ontology.py  -> analytics, simulator, engine,
    manufacturer
  - data_loader.py                     -> analytics, simulator,
    manufacturer (NOT engine — no streamlit)
  - gmp_knowledge.py, pharmacopeia_methods.py, pharmacopeia_diff.py,
    ich_registry.py, us_regulatory_data.py  -> analytics, manufacturer
    (pure-stdlib GMP/pharmacopeia knowledge cores; engine/simulator do not
    import them)

Runnable both as ``python tests/test_sync_shared_determinism.py`` and
via pytest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (filename, [destination dirs relative to repo root])
SYNC_MAP = {
    "nsq_redis.py": ["analytics/shared", "simulator/shared",
                     "engine/shared", "manufacturer/shared"],
    "company_ontology.py": ["analytics/shared", "simulator/shared",
                            "engine/shared", "manufacturer/shared"],
    "data_loader.py": ["analytics/shared", "simulator/shared",
                       "manufacturer/shared"],
    "gmp_knowledge.py": ["analytics/shared", "manufacturer/shared"],
    "pharmacopeia_methods.py": ["analytics/shared", "manufacturer/shared"],
    "pharmacopeia_diff.py": ["analytics/shared", "manufacturer/shared"],
    "ich_registry.py": ["analytics/shared", "manufacturer/shared"],
    "us_regulatory_data.py": ["analytics/shared", "manufacturer/shared"],
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _test_pair(src: Path, dst: Path):
    assert dst.is_file(), f"synced copy missing: {dst}"
    assert _sha(src) == _sha(dst), (
        f"DRIFT: {dst.name} differs between root shared/ and {dst.parent}/.\n"
        f"  Run `just sync-shared` from the repo root and re-commit."
    )


def test_synced_copies_match_root():
    for fname, dirs in SYNC_MAP.items():
        src = REPO / "shared" / fname
        assert src.is_file(), f"source-of-truth missing: {src}"
        for d in dirs:
            _test_pair(src, REPO / d / fname)


if __name__ == "__main__":
    fns = [v for v in globals().values()
           if callable(v) and v.__name__.startswith("test_")]
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