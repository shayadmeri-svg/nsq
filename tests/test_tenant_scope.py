"""Tenant registry + tenant-scoping tests for the manufacturer app.

Verifies:
  1. The tenant registry resolves Regent Ajanta Biotech (and NSQ_TENANT
     can override / select it).
  2. Scoping the enriched NSQ frame on ``Mfg_Ontology_Key`` returns the
     correct 8 Regent rows — with a regression guard that documents WHY
     we scope on the ontology key and not a raw/bin key (the raw
     ``Manufactured By`` strings vary across all 8 rows, the ontology
     key unifies them).
  3. The tenant's ontology key is present in the live ontology with the
     expected canonical name.

Integration tests (2, 3) skip when Redis is unreachable.

Runnable both as ``python tests/test_tenant_scope.py`` and via pytest.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MFR = REPO / "manufacturer"
SHARED = REPO / "shared"

EXPECTED_KEY = "regent ajanta"  # re-pinned after the 2026-08-27 deterministic rebuild ("biotech" drops as legal-form noise)
EXPECTED_CANONICAL = "Regent Ajanta Biotech"
EXPECTED_ROWS = 8


def _stub_streamlit() -> None:
    """Neutralize ``@st.cache_data`` so the shared loader runs headless."""
    if "streamlit" not in sys.modules:
        st = types.ModuleType("streamlit")
        st.cache_data = lambda *a, **k: (lambda f: f)
        st.spinner = lambda *a, **k: None
        sys.modules["streamlit"] = st


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__
    # (tenants.py uses @dataclass(frozen=True); without this the
    # decorator raises NoneType.__dict__).
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _redis_reachable() -> bool:
    url = os.environ.get("REDIS_URL")
    if not url:
        return False
    try:
        import redis
        r = redis.from_url(url, decode_responses=True)
        return bool(r.ping())
    except Exception:
        return False


def test_tenant_registry_resolves_regent():
    tenants = _load("manufacturer/tenants.py", "mfr_tenants")
    t = tenants.get_active_tenant()
    assert t.ontology_key == EXPECTED_KEY
    assert t.canonical == EXPECTED_CANONICAL


def test_tenant_registry_env_override(monkeypatch):
    tenants = _load("manufacturer/tenants.py", "mfr_tenants_env")
    monkeypatch.setenv("NSQ_TENANT", "regent-ajanta-biotech")
    assert tenants.get_active_tenant().key == "regent-ajanta-biotech"
    # Unknown env value falls back to the first registered tenant.
    monkeypatch.setenv("NSQ_TENANT", "does-not-exist")
    assert tenants.get_active_tenant().ontology_key == EXPECTED_KEY


@pytest.mark.skipif(not _redis_reachable(), reason="REDIS_URL unreachable")
def test_tenant_filter_returns_eight_rows():
    _stub_streamlit()
    sys.path.insert(0, str(SHARED))
    try:
        data_loader = _load("shared/data_loader.py", "mfr_data_loader")
        df = data_loader.load_and_preprocess_data()
    finally:
        sys.path.remove(str(SHARED))

    assert not df.empty, "enriched frame was empty"
    scoped = df[df["Mfg_Ontology_Key"] == EXPECTED_KEY]
    assert len(scoped) == EXPECTED_ROWS

    # Regression guard: the ontology key unifies rows whose raw
    # manufacturer strings vary. This is WHY tenant identity is the
    # ontology key, not a raw string (whose 7 variants would split the
    # tenant). Mfg_Bin_Key is intentionally not a frame column.
    assert scoped["Mfg_Ontology_Key"].nunique() == 1
    assert scoped["Manufactured By"].nunique() > 1

    # No cross-tenant contamination: the Phenytoin-by-Jackson-Labs row
    # that a CDSCO-index join used to pull in must be absent.
    phenytoin = scoped["Name of Product"].str.contains(
        "Phenytoin", case=False, na=False)
    assert int(phenytoin.sum()) == 0


@pytest.mark.skipif(not _redis_reachable(), reason="REDIS_URL unreachable")
def test_tenant_key_in_ontology():
    sys.path.insert(0, str(SHARED))
    try:
        co = _load("shared/company_ontology.py", "mfr_company_ontology")
        ont = co.load_ontology()
    finally:
        sys.path.remove(str(SHARED))
    rec = ont.get(EXPECTED_KEY)
    assert rec is not None, f"ontology key {EXPECTED_KEY!r} missing"
    assert rec.get("canonical_name") == EXPECTED_CANONICAL


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