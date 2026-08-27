"""Pure-logic diagnostics bundle for the Q-engine diagnostics view.

No Streamlit, no Redis — only the synced GMP/pharmacopeia knowledge cores
(`gmp_knowledge`, `pharmacopeia_diff`) imported flat from `shared/`. This
module assembles a single NSQ issue + its tenant-scoped context into a
``Diagnosis`` dataclass that ``diagnostics.py`` renders and that the test
suite exercises headlessly.

Two evidence modes (mirroring the Figma 'Q-engine diagnostics' Root cause
analysis screen and the analytics ``_render_manufacturer_investigation``
provenance):

  * **Data-informed signals** — aggregate failure-mode / dosage-form /
    geographic / temporal signals over the *tenant* frame, so 'Dissolution
    is a dominant failure mode (4 alerts)' reflects this manufacturer's real
    counts, not a mockup.
  * **API-informed OOS insights** — resolve the issue's product to a curated
    ``Drug`` via ``match_api`` and carry its ``common_alerts`` /
    ``vigibase_risks`` / GMP corridor / pharmacopeial methods. Uncurated
    products fall back to ``generic_standards`` (no fabricated specifics).

Provenance-first: nothing here invents a claim. ``synthesis_gap`` is always
True — the Figma's synthesis-route steps (patent US7943781B2) are not in the
knowledge core yet and must be surfaced as a gap, never invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from gmp_knowledge import (
    Drug,
    Mitigation,
    PRODUCT_CATALOG,
    generic_standards,
    match_api,
    mitigations_for,
)
from pharmacopeia_diff import MethodDiff, diff_drug, nsq_relevant_count


@dataclass
class Diagnosis:
    """A single-issue diagnostics bundle, ready to render."""

    # --- issue identity (the targeted NSQ alert row) ---
    product: str
    batch: str
    nsq_result: str
    failure_category: str
    form: str
    lab: str
    month: str

    # --- data-informed signals (computed over the tenant frame) ---
    dominant_failures: list[tuple[str, int, float]]  # (category, count, pct) top-3
    form_span: int
    geo_concentration: list[tuple[str, int]]          # (state, count) top-3
    temporal_clusters: list[tuple[str, int]]          # ("YYYY-MM", count) sorted
    is_dominant_failure: bool                         # this issue's category is #1
    tenant_alert_count: int

    # --- api-informed ---
    api_id: str | None                                # match_api result, lowercase id
    drug: Drug | None                                 # curated Drug, or None
    generic_fallback: bool                            # True when no curated match
    generic_text: dict[str, str] | None               # generic_standards() when fallback
    method_diffs: list[MethodDiff] = field(default_factory=list)
    nsq_relevant_method_diffs: int = 0

    # --- mitigation preview ---
    mitigations: list[Mitigation] = field(default_factory=list)

    # --- honest gap ---
    synthesis_gap: bool = True  # no synthesis-route data in the knowledge core yet


def _col(row: pd.Series, name: str, default: str = "—") -> str:
    """Safe scalar pull from an issue row as a clean string."""
    if name not in row.index:
        return default
    val = row.get(name)
    if pd.isna(val) or val is None or str(val).strip() == "":
        return default
    return str(val).strip()


def _dominant_failures(df: pd.DataFrame) -> list[tuple[str, int, float]]:
    """Top-3 failure categories as (category, count, pct-of-tenant-alerts)."""
    if "Failure_Category" not in df.columns or df.empty:
        return []
    counts = df["Failure_Category"].fillna("Uncategorised").value_counts()
    total = int(counts.sum()) or 1
    return [(str(cat), int(n), round(int(n) / total * 100, 1))
            for cat, n in counts.head(3).items()]


def _geo_concentration(df: pd.DataFrame) -> list[tuple[str, int]]:
    if "Mfg_State" not in df.columns or df.empty:
        return []
    states = df["Mfg_State"].dropna()
    states = states[states.astype(str).str.strip() != ""]
    if states.empty:
        return []
    return [(str(s), int(n)) for s, n in states.value_counts().head(3).items()]


def _temporal_clusters(df: pd.DataFrame) -> list[tuple[str, int]]:
    if "Parsed_Date" not in df.columns or df.empty:
        return []
    dates = df["Parsed_Date"].dropna()
    if dates.empty:
        return []
    months = pd.to_datetime(dates, errors="coerce").dropna()
    if months.empty:
        return []
    counts = months.dt.strftime("%Y-%m").value_counts().sort_index()
    return [(str(m), int(n)) for m, n in counts.items()]


def build_diagnosis(row: pd.Series, tenant_df: pd.DataFrame) -> Diagnosis:
    """Assemble a ``Diagnosis`` for one NSQ issue row, scoped against the
    tenant frame for the data-informed signals."""
    product = _col(row, "Product_Name_Canonical") or _col(row, "Name of Product")
    if product == "—":
        product = _col(row, "Name of Product")
    failure_category = _col(row, "Failure_Category")

    # Data-informed signals over the tenant frame.
    dom = _dominant_failures(tenant_df)
    is_dom = bool(dom) and failure_category != "—" and dom[0][0] == failure_category

    # API-informed: resolve to a curated Drug. Match on the raw product name
    # (retains the API token match_api expects), then the canonical name.
    raw_name = _col(row, "Name of Product")
    api_id = match_api(raw_name) or match_api(product)
    drug = PRODUCT_CATALOG.get(api_id) if api_id else None
    generic_fallback = drug is None
    generic_text = generic_standards(raw_name if raw_name != "—" else product) if generic_fallback else None

    method_diffs = diff_drug(drug) if drug is not None else []
    nq = nsq_relevant_count(drug) if drug is not None else 0

    mitigations = mitigations_for(failure_category) if failure_category != "—" else []

    return Diagnosis(
        product=product,
        batch=_col(row, "Batch No"),
        nsq_result=_col(row, "NSQ Result"),
        failure_category=failure_category,
        form=_col(row, "Form type"),
        lab=_col(row, "Reporting by Lab/State"),
        month=_col(row, "Reporting Month & Year"),
        dominant_failures=dom,
        form_span=int(tenant_df["Form type"].dropna()
                      [tenant_df["Form type"].dropna().astype(str).str.strip() != ""].nunique())
        if "Form type" in tenant_df.columns and not tenant_df.empty else 0,
        geo_concentration=_geo_concentration(tenant_df),
        temporal_clusters=_temporal_clusters(tenant_df),
        is_dominant_failure=is_dom,
        tenant_alert_count=int(len(tenant_df)),
        api_id=api_id,
        drug=drug,
        generic_fallback=generic_fallback,
        generic_text=generic_text,
        method_diffs=method_diffs,
        nsq_relevant_method_diffs=nq,
        mitigations=mitigations,
        synthesis_gap=True,
    )