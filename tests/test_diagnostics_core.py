"""Headless tests for ``manufacturer/diagnostics_core.build_diagnosis``.

No Streamlit, no Redis — exercises the pure diagnostics assembler against a
synthetic issue row + tenant frame, for a curated API (telmisartan), an
uncurated fallback (luliconazole), and an outlier failure category. The
GMP/pharmacopeia cores are imported from ``manufacturer/shared`` (the synced
copies the app imports at runtime).

Runnable both as ``python tests/test_diagnostics_core.py`` and via pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
MFR = REPO / "manufacturer"
MFR_SHARED = MFR / "shared"


@pytest.fixture(scope="module", autouse=True)
def _import_core():
    """Put the synced cores + the manufacturer app dir on sys.path so
    ``import diagnostics_core`` resolves its flat imports."""
    for p in (str(MFR_SHARED), str(MFR)):
        if p not in sys.path:
            sys.path.insert(0, p)
    yield


def _tenant_df() -> pd.DataFrame:
    """Four rows: Dissolution x2 (dominant), Description x1, Assay x1 — so the
    dominant-failure flag is deterministic, not tie-broken."""
    return pd.DataFrame([
        {"Name of Product": "Telmisartan Tablets IP 20mg",
         "Product_Name_Canonical": "Telmisartan 20mg", "Batch No": "PRT2602-149",
         "NSQ Result": "Not of Standard Quality (Dissolution fails)",
         "Failure_Category": "Dissolution", "Form type": "Tablet",
         "Reporting by Lab/State": "CDTL Mumbai",
         "Reporting Month & Year": "Jun-2026",
         "Parsed_Date": pd.Timestamp("2026-06-01"), "Mfg_State": "Maharashtra"},
        {"Name of Product": "Luliconazole Cream IP 1%",
         "Product_Name_Canonical": "Luliconazole Cream", "Batch No": "X1",
         "NSQ Result": "Not of Standard Quality (Description)",
         "Failure_Category": "Description", "Form type": "Cream",
         "Reporting by Lab/State": "CDTL", "Reporting Month & Year": "Jan-2025",
         "Parsed_Date": pd.Timestamp("2025-01-01"), "Mfg_State": "Gujarat"},
        {"Name of Product": "Telmisartan & Amlodipine Tablets IP",
         "Product_Name_Canonical": "Telmisartan Amlodipine", "Batch No": "X2",
         "NSQ Result": "Not of Standard Quality (Dissolution)",
         "Failure_Category": "Dissolution", "Form type": "Tablet",
         "Reporting by Lab/State": "CDTL", "Reporting Month & Year": "Jun-2026",
         "Parsed_Date": pd.Timestamp("2026-06-01"), "Mfg_State": "Maharashtra"},
        {"Name of Product": "Aceclofenac & Drotaverine Tablets",
         "Product_Name_Canonical": "Aceclofenac Drotaverine", "Batch No": "X3",
         "NSQ Result": "Not of Standard Quality (Assay)",
         "Failure_Category": "Assay", "Form type": "Tablet",
         "Reporting by Lab/State": "CDTL", "Reporting Month & Year": "Jun-2026",
         "Parsed_Date": pd.Timestamp("2026-06-01"), "Mfg_State": "Maharashtra"},
    ])


def test_curated_telmisartan_diagnosis():
    from diagnostics_core import build_diagnosis
    df = _tenant_df()
    d = build_diagnosis(df.iloc[0], df)
    assert d.api_id == "telmisartan"
    assert d.drug is not None and d.drug.name == "Telmisartan"
    assert d.drug.optimal_process == "Direct Compression"
    assert not d.generic_fallback
    # Pharmacopeial diff: 3 sections, at least one NSQ-relevant for telmisartan.
    assert len(d.method_diffs) == 3
    assert d.nsq_relevant_method_diffs >= 1
    # Mitigation playbook for Dissolution is curated.
    assert len(d.mitigations) >= 1
    # Data-informed signals over the tenant frame.
    assert d.dominant_failures[0] == ("Dissolution", 2, 50.0)
    assert d.is_dominant_failure is True
    assert d.form_span == 2
    assert d.tenant_alert_count == 4
    assert d.synthesis_gap is True
    # Common OOS alert for telmisartan surfaces in the curated alerts.
    alerts_blob = " ".join(d.drug.common_alerts)
    assert "meglumine" in alerts_blob.lower()


def test_uncurated_fallback_diagnosis():
    from diagnostics_core import build_diagnosis
    df = _tenant_df()
    d = build_diagnosis(df.iloc[1], df)  # Luliconazole — not curated
    assert d.api_id is None
    assert d.drug is None
    assert d.generic_fallback is True
    assert d.generic_text is not None
    assert "scientific" in d.generic_text and "regulatory" in d.generic_text
    assert d.method_diffs == []
    assert d.nsq_relevant_method_diffs == 0
    # Description is not the dominant failure (Dissolution is).
    assert d.is_dominant_failure is False
    assert d.synthesis_gap is True


def test_outlier_failure_is_flagged():
    from diagnostics_core import build_diagnosis
    df = _tenant_df()
    d = build_diagnosis(df.iloc[3], df)  # Assay — outlier, not dominant
    assert d.failure_category == "Assay"
    assert d.is_dominant_failure is False
    assert d.dominant_failures[0][0] == "Dissolution"


if __name__ == "__main__":
    fns = [v for v in globals().values()
           if callable(v) and v.__name__.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            # lightweight fixture wiring for standalone run
            for p in (str(MFR_SHARED), str(MFR)):
                if p not in sys.path:
                    sys.path.insert(0, p)
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