"""Animated analytics home page.

Renders a scroll-driven, anime.js-powered landing experience inside the
existing Streamlit analytics app via `streamlit.components.v1.html`. The
page surfaces:

  - A political heat map of India (NSQ alert density by manufacturing
    state) with disputed / neighbour regions greyed out.
  - A correlation explorer (Issue vs Form vs Testing Lab) for the selected
    product.
  - A product risk card with probable causes and blurred potential
    solutions that reveal on click.
  - A sticky "Contact us" pill.
  - A gateway to the existing full dashboard.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))
from data_loader import load_and_preprocess_data  # noqa: E402
from company_ontology import product_key  # noqa: E402

DEFAULT_PRODUCT_KEY = "paracetamol"
DEFAULT_DISPLAY_NAME = "Paracetamol"
STATIC_DIR = Path(__file__).parent / "static"
HOME_HTML = STATIC_DIR / "home.html"


def _display_name_for_key(df: pd.DataFrame, key: str) -> str:
    """Return the most common human-readable product name for a product key."""
    mask = df["Product_Ontology_Key"] == key
    if mask.any():
        col = (
            df.loc[mask, "Product_Name_Canonical"]
            .where(df.loc[mask, "Product_Name_Canonical"].fillna("") != "", df.loc[mask, "Product_Name_Norm"])
        )
        return col.value_counts().index[0]
    # Fallback: scan normalized names for the substring
    norm_mask = df["Product_Name_Norm"].str.lower().str.contains(key.replace("_", " "), na=False)
    if norm_mask.any():
        return df.loc[norm_mask, "Product_Name_Norm"].value_counts().index[0]
    return key.replace("_", " ").title()


def _product_group_key(df: pd.DataFrame) -> pd.Series:
    """Return a stable grouping key per row.

    Prefer the Redis-backed product ontology key, but fall back to a locally
    computed product key when Redis is unavailable (common in local/offline
    runs). This keeps the landing page functional regardless of Redis state.
    """
    keys = df["Product_Ontology_Key"].fillna("")
    fallback = df["Product_Name_Norm"].apply(product_key)
    return keys.where(keys != "", fallback)


def _display_name_for_row(df: pd.DataFrame) -> pd.Series:
    """Best-effort human-readable product name per row."""
    return (
        df["Product_Name_Canonical"]
        .where(df["Product_Name_Canonical"].fillna("") != "", df["Product_Name_Norm"])
    )


def _build_product_catalog(df: pd.DataFrame) -> tuple[dict[str, str], list[str]]:
    """Return ({product_key: display_name}, ordered_display_names).

    The default product (paracetamol) is always first if present; remaining
    products are sorted alphabetically.
    """
    group_keys = _product_group_key(df)
    display = _display_name_for_row(df)

    catalog: dict[str, str] = {}
    for key, name in zip(group_keys, display):
        if not key:
            continue
        if key not in catalog:
            catalog[key] = name
        else:
            # Keep the shorter, cleaner name when possible.
            if len(str(name)) < len(str(catalog[key])):
                catalog[key] = name

    # Ensure the default key exists, even if not in the data.
    if DEFAULT_PRODUCT_KEY not in catalog:
        catalog[DEFAULT_PRODUCT_KEY] = DEFAULT_DISPLAY_NAME

    # Filter to products with at least a few alerts so the selector is usable.
    MIN_ALERTS = 5
    group_keys = _product_group_key(df)
    key_counts = group_keys.value_counts().to_dict()
    filtered_catalog = {
        k: v for k, v in catalog.items()
        if k == DEFAULT_PRODUCT_KEY or key_counts.get(k, 0) >= MIN_ALERTS
    }

    names = sorted(filtered_catalog.values())
    if filtered_catalog.get(DEFAULT_PRODUCT_KEY):
        default_name = filtered_catalog[DEFAULT_PRODUCT_KEY]
        names = [default_name] + [n for n in names if n != default_name]

    # Build inverse lookup display_name -> key
    display_to_key = {v: k for k, v in filtered_catalog.items()}
    return display_to_key, names


def _state_counts(df: pd.DataFrame, product_name: str | None = None, display_to_key: dict[str, str] | None = None) -> dict[str, int]:
    """Aggregate alert counts by Indian manufacturing state."""
    subset = df.copy()
    if product_name and product_name != "All products":
        key = (display_to_key or {}).get(product_name, product_key(product_name))
        subset = subset[_product_group_key(subset) == key]
    counts = subset[subset["Mfg_State"].fillna("") != ""]["Mfg_State"].value_counts().to_dict()
    return {k: int(v) for k, v in counts.items()}


def _region_metadata(df: pd.DataFrame) -> list[dict]:
    """Build per-region metadata (count, top product, top issue) for tooltips."""
    regions = []
    for state, group in df[df["Mfg_State"].fillna("") != ""].groupby("Mfg_State"):
        display_col = (
            group["Product_Name_Canonical"]
            .where(group["Product_Name_Canonical"].fillna("") != "", group["Product_Name_Norm"])
        )
        top_product = display_col.value_counts().index[0] if not display_col.empty else ""
        top_issue = group["Failure_Category_Primary"].value_counts().index[0] if not group.empty else ""
        regions.append({
            "name": state,
            "type": "india_state",
            "count": int(len(group)),
            "top_product": str(top_product),
            "top_issue": str(top_issue),
        })
    return regions


def _product_records(df: pd.DataFrame, product_name: str, display_to_key: dict[str, str]) -> list[dict]:
    """Return lightweight record list for the correlation explorer."""
    key = display_to_key.get(product_name, product_key(product_name))
    subset = df[_product_group_key(df) == key]
    records = []
    for _, row in subset.iterrows():
        records.append({
            "state": str(row.get("Mfg_State") or ""),
            "form": str(row.get("Form") or "Other"),
            "issue": str(row.get("Failure_Category_Primary") or "Uncategorized"),
            "lab": str(row.get("Reporting by Lab/State") or "Unknown"),
            "month": str(row.get("Reporting Month & Year") or "Unknown"),
            "drug_type": str(row.get("Drug type") or "Other / Unclassified"),
        })
    return records


def _cross_tab(records: list[dict], key_a: str, key_b: str) -> dict[str, dict[str, int]]:
    """Build a nested count matrix for two record keys."""
    matrix: dict[str, dict[str, int]] = {}
    for r in records:
        a = str(r.get(key_a) or "Unknown")
        b = str(r.get(key_b) or "Unknown")
        matrix.setdefault(a, {}).setdefault(b, 0)
        matrix[a][b] += 1
    return matrix


def _correlations(df: pd.DataFrame, product_name: str, display_to_key: dict[str, str]) -> dict[str, dict]:
    """Return precomputed cross-tabs for issue/form/lab."""
    records = _product_records(df, product_name, display_to_key)
    return {
        "issue_form": _cross_tab(records, "issue", "form"),
        "issue_lab": _cross_tab(records, "issue", "lab"),
        "form_lab": _cross_tab(records, "form", "lab"),
    }


def _risk_card(df: pd.DataFrame, product_name: str, display_to_key: dict[str, str]) -> dict[str, list[str]]:
    """Build a rule-based risk card from the product's NSQ history."""
    key = display_to_key.get(product_name, product_key(product_name))
    subset = df[_product_group_key(df) == key]

    if subset.empty:
        return {
            "probable_causes": [f"No NSQ alerts on record for {product_name}."],
            "potential_solutions": ["Continue routine pharmacopeial monitoring and stability trending."],
        }

    top_issues = subset["Failure_Category_Primary"].value_counts().head(3)
    top_forms = subset["Form"].value_counts().head(2)
    top_states = subset["Mfg_State"].value_counts().head(3)

    causes: list[str] = []
    for issue, count in top_issues.items():
        causes.append(f"{issue} is the dominant failure mode ({count} alerts).")
    if len(top_forms) > 1:
        causes.append(f"Issues span {len(top_forms)} dosage forms: {', '.join(top_forms.index)}.")
    if any(s != "Unknown" for s in top_states.index):
        causes.append(f"Geographic concentration: {', '.join(top_states.index[:3])}.")

    # Map top issues to generic, evidence-backed mitigation actions.
    solution_bank: dict[str, list[str]] = {
        "Dissolution": [
            "Tighten dissolution method transfer and validate sink conditions per USP <711> / IP 2026.",
            "Use design-of-experiments to lock granule PSD and tablet hardness ranges.",
        ],
        "Assay / Content": [
            "Implement in-process blend uniformity sampling (n=10) and NIR trend monitoring.",
            "Re-validate HPLC sample preparation to rule out extraction variability.",
        ],
        "Related Substances": [
            "Stress-test API-excipient compatibility and tighten storage RH limits.",
            "Validate impurity profiling method against a qualified reference standard.",
        ],
        "Description / Appearance": [
            "Review film-coat formulation and pan loading; target consistent exhaust temperature.",
            "Add visual inspection stations with standardized lighting and defect catalog.",
        ],
        "Sterility / Microbial": [
            "Re-qualify media-fill simulations and environmental monitoring programs.",
            "Audit aseptic technique and gowning qualification records.",
        ],
        "Uniformity of Weight": [
            "Calibrate feed frames and compression force sensors on a tighter schedule.",
            "Set weight-control limits at ±3% with automatic reject diverters.",
        ],
        "pH": [
            "Validate pH meter calibration cadence and electrode maintenance SOP.",
            "Tighten buffer preparation tolerances and solution ageing limits.",
        ],
    }

    solutions: list[str] = []
    seen = set()
    for issue in top_issues.index:
        for sol in solution_bank.get(issue, []):
            if sol not in seen:
                solutions.append(sol)
                seen.add(sol)
    if not solutions:
        solutions.append("Conduct a targeted QRM review against ICH Q9 and update the control strategy.")

    return {"probable_causes": causes, "potential_solutions": solutions}


def build_nsq_data(df: pd.DataFrame) -> dict:
    """Build the JSON payload consumed by the landing-page HTML/JS."""
    display_to_key, product_names = _build_product_catalog(df)

    default_name = display_to_key.get(DEFAULT_PRODUCT_KEY, DEFAULT_DISPLAY_NAME)
    if DEFAULT_PRODUCT_KEY in display_to_key:
        # Make sure paracetamol is at the front of the name list.
        if default_name not in product_names:
            product_names = [default_name] + product_names
        else:
            product_names = [default_name] + [n for n in product_names if n != default_name]

    months = sorted(df["Reporting Month & Year"].dropna().unique().tolist())
    failure_categories = sorted(df["Failure_Category_Primary"].dropna().unique().tolist())
    form_types = sorted(df["Form"].dropna().unique().tolist())
    drug_types = sorted(df["Drug type"].dropna().unique().tolist())
    lab_names = sorted(df["Reporting by Lab/State"].dropna().unique().tolist())

    state_counts_all = _state_counts(df)

    state_counts_by_product: dict[str, dict[str, int]] = {}
    products_data: dict[str, dict] = {}
    correlations: dict[str, dict] = {}
    risk_cards: dict[str, dict] = {}

    for name in product_names:
        key = display_to_key.get(name, product_key(name))
        state_counts_by_product[name] = _state_counts(df, name, display_to_key)
        products_data[name] = {"records": _product_records(df, name, display_to_key)}
        correlations[name] = _correlations(df, name, display_to_key)
        risk_cards[name] = _risk_card(df, name, display_to_key)

    return {
        "default_product": default_name,
        "products": product_names,
        "filters": {
            "months": months,
            "failure_categories": failure_categories,
            "form_types": form_types,
            "drug_types": drug_types,
            "lab_names": lab_names,
        },
        "state_counts_all": state_counts_all,
        "state_counts_by_product": state_counts_by_product,
        "products_data": products_data,
        "correlations": correlations,
        "risk_cards": risk_cards,
        "regions": _region_metadata(df),
        "disputed_labels": ["Gilgit-Baltistan", "Aksai Chin"],
        "neighbour_labels": ["Pakistan", "Nepal", "Bhutan", "Bangladesh", "Myanmar", "Afghanistan", "China", "Sri Lanka"],
    }


def render_landing_page() -> None:
    """Render the animated analytics home page."""
    try:
        df = load_and_preprocess_data()
    except Exception as e:
        st.error(f"Unable to load NSQ data: {e}")
        st.stop()

    nsq_data = build_nsq_data(df)

    # Read the self-contained HTML template.
    html_src = HOME_HTML.read_text(encoding="utf-8")

    # Inject the data payload as a safe JSON script tag so the parent HTML
    # cannot be broken by special characters inside the NSQ strings.
    data_json = json.dumps(nsq_data, ensure_ascii=False)
    payload_block = (
        "\n    <script id=\"nsq-data\" type=\"application/json\">\n"
        f"      {data_json}\n"
        "    </script>\n"
        "    <script>\n"
        "      try {\n"
        "        window.NSQ_DATA = JSON.parse(document.getElementById('nsq-data').textContent);\n"
        "      } catch (e) {\n"
        "        console.error('Failed to parse NSQ_DATA:', e);\n"
        "        window.NSQ_DATA = {};\n"
        "      }\n"
        "    </script>\n"
    )
    # Insert right before </body> so the data is available when scripts run.
    html_src = html_src.replace("</body>", payload_block + "</body>")

    # We use a very tall component so anime.js scroll animations inside the
    # iframe feel natural. The component communicates back via postMessage.
    html(html_src, height=3400, scrolling=True)

    # Listen for postMessage events from the embedded home page.
    # Streamlit's components API doesn't directly expose iframe messages, so we
    # surface a simple state-based toggle via a query-string or session state
    # convention. The "Open Dashboard" button in the iframe can set a URL hash
    # that the parent detects on rerun. Here we provide a dashboard entry
    # button below the fold as a fallback.
    st.markdown("---")
    if st.button("🔬 Open full analytics dashboard", use_container_width=True):
        st.session_state["nsq_view"] = "dashboard"
        st.rerun()
