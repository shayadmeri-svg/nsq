"""Tests for the headless (non-Streamlit) data-loader path.

The manufacturer_api FastAPI service imports ``shared/data_loader.py``
without Streamlit installed. The refactor split the enrichment body into a
pure :func:`_load_and_preprocess` and made :func:`load_and_preprocess_data`
a dispatcher: it memoises via ``@st.cache_data`` when Streamlit is importable,
and calls the pure core directly otherwise.

These tests pin:
  1. The pure core exists and returns an enriched frame with the full column
     set the dashboard / diagnostics views depend on.
  2. The dispatcher converges to the same frame regardless of the
     ``_HAS_ST`` branch (the no-Streamlit branch used by manufacturer_api).

Integration tests skip when Redis is unreachable (CSV fallback is exercised
implicitly when Redis is down, but the canonical store is Redis).

Runnable both as ``python tests/test_data_loader_uncached.py`` and via pytest.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SHARED = REPO / "shared"

# Columns the dashboard + diagnostics views read. Must all be present on the
# enriched frame regardless of which dispatcher branch produced it.
REQUIRED_COLUMNS = [
    "Name of Product",
    "NSQ Result",
    "Batch No",
    "Reporting by Lab/State",
    "Reporting Month & Year",
    "Manufactured By",
    "Failure_Category",
    "Form type",
    "Parsed_Date",
    "Mfg_Ontology_Key",
    "Mfg_State",
    "Product_Name_Canonical",
]


def _stub_streamlit() -> None:
    """Neutralize ``@st.cache_data`` (no-op decorator) so the loader runs
    without a Streamlit runtime — mirrors test_tenant_scope.py."""
    if "streamlit" not in sys.modules:
        st = types.ModuleType("streamlit")
        st.cache_data = lambda *a, **k: (lambda f: f)
        st.spinner = lambda *a, **k: None
        sys.modules["streamlit"] = st


def _load_data_loader():
    spec = importlib.util.spec_from_file_location("dl_uncached", SHARED / "data_loader.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dl_uncached"] = mod
    spec.loader.exec_module(mod)
    return mod


def _redis_reachable() -> bool:
    url = os.environ.get("REDIS_URL")
    if not url:
        return False
    try:
        import redis

        return bool(redis.from_url(url, decode_responses=True).ping())
    except Exception:
        return False


@pytest.mark.skipif(not _redis_reachable(), reason="REDIS_URL unreachable")
def test_pure_core_returns_enriched_frame():
    _stub_streamlit()
    sys.path.insert(0, str(SHARED))
    try:
        dl = _load_data_loader()
        df = dl._load_and_preprocess()
    finally:
        sys.path.remove(str(SHARED))

    assert not df.empty, "enriched frame was empty"
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    assert not missing, f"missing enriched columns: {missing}"


@pytest.mark.skipif(not _redis_reachable(), reason="REDIS_URL unreachable")
def test_dispatcher_converges_across_branches():
    """Both ``_HAS_ST`` branches must yield the same enriched frame shape."""
    _stub_streamlit()
    sys.path.insert(0, str(SHARED))
    try:
        dl = _load_data_loader()
        pure = dl._load_and_preprocess()

        # Streamlit-present branch (the stub's no-op cache_data decorator).
        dl._HAS_ST = True
        cached = dl.load_and_preprocess_data()
        assert len(cached) == len(pure)

        # Streamlit-absent branch (the manufacturer_api runtime path).
        dl._HAS_ST = False
        direct = dl.load_and_preprocess_data()
        assert len(direct) == len(pure)

        missing = [c for c in REQUIRED_COLUMNS if c not in direct.columns]
        assert not missing, f"no-streamlit branch missing columns: {missing}"
    finally:
        sys.path.remove(str(SHARED))


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