"""Tenant-scoped access to the enriched NSQ frame.

This is the only place the manufacturer app touches the shared data
loader. It loads the full enriched frame (cached by ``data_loader`` via
``@st.cache_data``), then filters it down to the active tenant's rows
on ``Mfg_Ontology_Key``. Downstream modules (``dashboard.py``,
``ui/components.py``) receive the already-scoped frame and never need to
know the tenant key.

Display metadata (canonical name, city) is resolved from the live
ontology record in Redis when present, falling back to the static
``Tenant`` fields so the app still renders on a cold/empty ontology.
"""

from __future__ import annotations

import pandas as pd

from company_ontology import load_ontology
from data_loader import load_and_preprocess_data
from tenants import Tenant


def load_tenant_frame(tenant: Tenant) -> pd.DataFrame:
    """Load the enriched NSQ frame and filter to the tenant's rows.

    Returns an empty frame (with a sentinel) if the tenant has no
    records, so callers can render a clear empty state rather than
    crashing on column access.
    """
    df = load_and_preprocess_data()
    if df.empty or "Mfg_Ontology_Key" not in df.columns:
        return df.iloc[0:0]
    scoped = df[df["Mfg_Ontology_Key"] == tenant.ontology_key].copy()
    return scoped


def tenant_display(tenant: Tenant) -> tuple[str, str]:
    """Return (canonical_name, city) for display, preferring the live
    ontology record and falling back to the static tenant fields."""
    try:
        ont = load_ontology()
        rec = ont.get(tenant.ontology_key, {})
        canonical = rec.get("canonical_name") or tenant.canonical
        city = rec.get("city") or tenant.city
    except Exception:
        canonical, city = tenant.canonical, tenant.city
    return canonical, city


def tenant_period(df: pd.DataFrame) -> str:
    """Human-readable alert span, e.g. 'Jan 2025 – Jun 2026'.

    Empty/unordered when the frame has no parseable dates."""
    if "Parsed_Date" not in df.columns or df.empty:
        return "—"
    dates = df["Parsed_Date"].dropna()
    if dates.empty:
        return "—"
    lo, hi = dates.min(), dates.max()
    return f"{lo:%b %Y} – {hi:%b %Y}"


def tenant_product_count(df: pd.DataFrame) -> int:
    """Distinct products for the tenant, preferring the canonicalized
    product name and falling back to the raw product column."""
    if df.empty:
        return 0
    if "Product_Name_Canonical" in df.columns and df["Product_Name_Canonical"].notna().any():
        return int(df["Product_Name_Canonical"].nunique())
    if "Name of Product" in df.columns:
        return int(df["Name of Product"].nunique())
    return 0