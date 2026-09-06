import os
import sys

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import json
import re
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))
from nsq_redis import load_geojson as load_redis_geojson  # noqa: E402
from company_ontology import (  # noqa: E402
    load_ontology,
    load_product_ontology,
    normalize_company_name,
)
from data_loader import (  # noqa: E402
    load_and_preprocess_data,
    fuzzy_search_products,
)
from gmp_knowledge import (  # noqa: E402
    PRODUCT_CATALOG,
    match_api,
    match_molecule,
    mitigations_for,
    generic_standards,
    Provenance,
    AUTHORITY_TIER_ORDER,
    provenance_audit,
    GENERIC_STANDARDS_PROVENANCE,
    Pharmacopeia,
    PharmacopeialMethod,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    DIFF_NSQ_RELEVANT,
    DIFF_METHOD_EQUIVALENT,
    DIFF_INCOMPARABLE,
)
import pharmacopeia_diff  # noqa: E402
import us_regulatory_data  # noqa: E402  # stamps real FDA Orange Book data onto the catalog
import ich_registry  # noqa: E402  # stamps cited ICH Q4B harmonisation context onto the catalog

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & SETUP
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="CDSCO NSQ Dissolution Analytics",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling for Titles and Metric Cards
# Scientific, colorblind-safe palette used for charts and UI accents.
_SCIENTIFIC_COLORWAY = [
    "#0072B2", "#E69F00", "#009E73", "#D55E00",
    "#56B4E9", "#CC79A7", "#F0E442", "#999999",
]
_SCIENTIFIC_CONTINUOUS = [
    [0.0, "#f2f2f2"], [0.25, "#56B4E9"],
    [0.5, "#0072B2"], [0.75, "#CC79A7"], [1.0, "#D55E00"],
]

st.markdown("""
    <style>
    .metric-card {
        background-color: #fafafa;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #0072B2;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .metric-title { font-size: 14px; color: #737373; margin-bottom: 5px; }
    .metric-value { font-size: 24px; font-weight: bold; color: #1a1a1a; }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. DATA LOADING & ENRICHMENT
# -----------------------------------------------------------------------------
# Data loading / enrichment helpers live in analytics/shared/data_loader.py

def _render_product_investigation(df: pd.DataFrame) -> None:
    """Render the "search a product, see which manufacturers had issues,
    drill into a manufacturer's history" UI."""
    st.markdown(
        "Search any product name to see **which manufacturers have faced "
        "NSQ issues with it**, then drill into a manufacturer to see their "
        "**full NSQ alert history** — every batch, every defect category, "
        "every reporting lab."
    )

    query = st.text_input(
        "🔎 Search product name (fuzzy match)",
        value=st.session_state.get("inv_query", ""),
        placeholder="e.g. Telmisartan 40mg, Paracetamol, Calcium + Vitamin D3",
        key="inv_query_input",
    )
    threshold = st.slider(
        "Fuzzy-match threshold (token-set ratio 0-100)",
        min_value=40, max_value=95, value=70, step=5,
        key="inv_threshold",
        help="Lower = more permissive matching. 70 catches most spelling "
             "variants without false positives.",
    )

    if not query.strip():
        st.info("Type a product name above to begin.")
        return

    with st.spinner("Fuzzy-matching product names…"):
        hits = fuzzy_search_products(df_raw, query, threshold=threshold)

    if not hits:
        st.warning(
            f"No product names matched `{query!r}` at threshold {threshold}. "
            "Try a shorter spelling or lower the threshold."
        )
        return

    # Use the BEST-scoring hit to anchor the search — show the user the
    # chosen product at the top, then a small table of "other close matches"
    # so they can pivot if the fuzzy picked the wrong product.
    chosen_idx, chosen_score, chosen_name = hits[0]
    st.success(
        f"**Top match:** `{chosen_name}` "
        f"(score {chosen_score}/100, fuzzy threshold {threshold})."
    )
    if len(hits) > 1:
        with st.expander(f"Other close matches ({len(hits)-1} more at threshold ≥ {threshold})", expanded=False):
            alt_df = pd.DataFrame(
                [(name, score) for _, score, name in hits[1:25]],
                columns=["Product Name", "Score"],
            )
            st.dataframe(alt_df, use_container_width=True, hide_index=True)

    # Filter the full dataset to every row whose product matches either
    # the chosen raw spelling OR any of the top-N alternatives (so
    # spelling variants roll up together).
    matched_names = {name for _, _, name in hits[:25]}
    matched_rows = df[df['Name of Product'].isin(matched_names)].copy()

    if matched_rows.empty:
        st.warning("No rows in the dataset for this product.")
        return

    st.markdown(f"### Manufacturers with NSQ issues for `{chosen_name}`")
    st.caption(
        f"Spelling-variant aggregator: {matched_rows['Name of Product'].nunique()} "
        f"raw spellings · {len(matched_rows)} total alerts."
    )

    # Manufacturers — collapse to the canonical ontology key when present,
    # fall back to the first segment of 'Manufactured By' (which is the
    # raw company name). Reuses _mfg_group_label so this table groups
    # identically to the heatmap/Sankey/table flows: grouping is by the
    # deterministic bin (constant per bin), so 'Regent Ajanta Biotech' and
    # 'Regent Ajanta Biotech 86-87' collapse to one row.
    mfg_df = matched_rows.copy()
    mfg_df['__mfg'] = _mfg_group_label(mfg_df)
    # Drop empty/Unknown placeholders so the table is informative.
    mfg_df = mfg_df[mfg_df['__mfg'].fillna('') != '']
    # Parse reporting month to datetime so first_seen/last_seen min/max and
    # column sorting are chronological, not alphabetical on month names.
    mfg_df['__rmy_dt'] = _rmy_datetime(mfg_df)
    mfg_summary = (
        mfg_df.groupby('__mfg')
              .agg(
                  alerts=('Name of Product', 'size'),
                  products=('Name of Product', 'nunique'),
                  first_seen=('__rmy_dt', 'min'),
                  last_seen=('__rmy_dt', 'max'),
                  cities=('Mfg_City', lambda s: sorted(set(x for x in s if x))),
              )
              .reset_index()
              .rename(columns={'__mfg': 'Manufacturer'})
              .sort_values(['alerts', 'Manufacturer'], ascending=[False, True])
    )
    st.dataframe(
        mfg_summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "first_seen": st.column_config.DateColumn("First seen", format=_DATE_FMT),
            "last_seen": st.column_config.DateColumn("Last seen", format=_DATE_FMT),
        },
    )

    # ---- Drill into one manufacturer ----
    st.markdown("### Drill into a manufacturer")
    mfg_choice = st.selectbox(
        "Pick a manufacturer to see every NSQ alert they've had with this product:",
        options=["(show all manufacturers)"] + mfg_summary['Manufacturer'].tolist(),
        key="inv_mfg_choice",
    )

    if mfg_choice == "(show all manufacturers)":
        drill = matched_rows.copy()
        st.caption(f"Showing all {len(drill)} alerts for the product, across every manufacturer.")
    else:
        drill = matched_rows[mfg_df['__mfg'] == mfg_choice].copy()
        st.caption(f"Showing {len(drill)} alerts for `{mfg_choice}` with this product.")

    # Pick the most useful columns for the alert ledger
    alert_cols = [
        'Name of Product',
        'Batch No',
        'Mfg', 'Exp',
        'Manufactured By',
        'Mfg_State',
        'NSQ Result',
        'Failure_Category_Primary',
        'Reporting Source',
        'Reporting by Lab/State',
        'Reporting Month & Year',
    ]
    alert_cols = [c for c in alert_cols if c in drill.columns]
    alert_view = _sort_alerts_chronological(drill[alert_cols])
    st.dataframe(alert_view, use_container_width=True, hide_index=True)

    # Download the drill-down as CSV
    st.download_button(
        label="📥 Export this manufacturer's NSQ history for the product to CSV",
        data=alert_view.to_csv(index=False).encode('utf-8'),
        file_name=f"nsq_history_{chosen_name[:30].replace(' ', '_').replace('/', '_')}.csv",
        mime="text/csv",
        key="inv_drill_csv",
    )

    # ---- NSQ alert history timeline (chronological bar chart) ----
    st.markdown("### NSQ alert history timeline")
    timeline = drill.copy()
    timeline['Reporting Month & Year'] = timeline['Reporting Month & Year'].fillna('Unknown')
    timeline['__date'] = pd.to_datetime(
        timeline['Reporting Month & Year'], format='%b-%Y', errors='coerce'
    )
    timeline = timeline.dropna(subset=['__date'])

    if timeline.empty:
        st.info("No parseable `Reporting Month & Year` for this product/manufacturer.")
        return

    # Aggregate by month AND by primary category for a stacked view. Fold the
    # failure-category tail into "Other" so the stack uses <=8 hues (top-7 +
    # Other) and never cycles past _SCIENTIFIC_COLORWAY.
    timeline['Failure_Category_Primary'] = _fold_categories(
        timeline['Failure_Category_Primary'], top_k=7, other="Other"
    )
    monthly = (
        timeline.groupby([pd.Grouper(key='__date', freq='MS'), 'Failure_Category_Primary'])
               .size()
               .reset_index(name='count')
               .sort_values('__date')
    )

    fig = px.bar(
        monthly, x='__date', y='count', color='Failure_Category_Primary',
        title=f"NSQ alert history — {chosen_name}" + (
            f" ({mfg_choice})" if mfg_choice != "(show all manufacturers)" else ""
        ),
        labels={'__date': 'Reporting Month', 'count': 'Alert Count',
                'Failure_Category_Primary': 'Failure Category'},
        color_discrete_sequence=_SCIENTIFIC_COLORWAY,
    )
    fig.update_layout(barmode='stack', legend_title='Failure Category')
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Manufacturer-first investigation. Counterpart to _render_product_investigation
# (product-first). Lets a sales agent start from the manufacturers facing the most
# NSQ issues and drill into one for full alert history, issue analysis, GMP &
# testing standards recap, probable causes, and a mitigation plan. Uses df_raw
# (full dataset) deliberately — same contract as the product-first mode.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Reusable chart helpers (shared by the Sankey, heatmaps, timelines, and the
# manufacturer summary). Form follows the dataviz method: a single accent color
# on nominal bars (color is reserved for where it *is* the encoding —
# heatmaps/choropleth), and categorical tails fold into "Other" so we never
# cycle past the 8-hue _SCIENTIFIC_COLORWAY ceiling.
# ---------------------------------------------------------------------------

_ACCENT = _SCIENTIFIC_COLORWAY[0]       # #0072B2 — single accent for nominal bars
_CONTEXT = _SCIENTIFIC_COLORWAY[7]      # #999999 — de-emphasis / context series
_MOLECULE_OTHER = "Other / unmapped molecule"


def _mfg_label(df: pd.DataFrame) -> pd.Series:
    """Per-row manufacturer DISPLAY label (trusted upstream canonical, else
    the raw first segment). NOT used for grouping — callers group on
    _mfg_group_label (constant per bin) so same-company rows with different
    display spellings collapse. The trust rule is the deterministic defense
    against stale/contaminated upstream canonicals: the bin is re-derived
    from the raw company name (Mfg_Bin_Key = a pure function of the name via
    normalize_company_name), NOT trusted from Mfg_Company_Canonical. The
    upstream canonical is used as the DISPLAY label ONLY when it normalizes
    to the same bin as the raw name — so a canonical that was contaminated
    upstream (e.g. a Regent Ajanta row stamped with a Jackson canonical, the
    bin contamination we traced) is rejected and the raw name's first
    segment is used instead. This keeps unrelated manufacturers in separate
    bins even if stale canonicals persist in Redis.

    Index-aligned to df (no rows dropped) so Sankey/heatmap/timeline callers
    can group and slice freely."""
    canon = df['Mfg_Company_Canonical'].fillna('').astype(str)
    raw = (
        df['Manufactured By'].fillna('').astype(str)
        .str.split(',').str[0].str.strip()
    )
    # Re-derived bin from the raw name. Prefer the Mfg_Bin_Key column
    # (populated in data_loader); fall back to normalizing the raw first
    # segment for frames that lack it (legacy/offline).
    if 'Mfg_Bin_Key' in df.columns:
        bin_from_raw = df['Mfg_Bin_Key'].fillna('').astype(str)
    else:
        bin_from_raw = raw.apply(normalize_company_name)
    # Trust the upstream canonical only when it agrees with the raw bin.
    canon_bin = canon.apply(normalize_company_name)
    trusted = (canon != '') & (canon_bin == bin_from_raw) & (bin_from_raw != '')
    return canon.where(trusted, raw)


def _mfg_bin(df: pd.DataFrame) -> pd.Series:
    """Per-row deterministic manufacturer BIN key — the grouping key, not a
    display label. The bin is normalize_company_name of the raw first
    segment (a pure function of the name), re-derived here so grouping
    NEVER splits same-company rows over a stale/contaminated upstream
    canonical. Index-aligned to df. This is what makes 'Regent Ajanta
    Biotech' and 'Regent Ajanta Biotech 86-87' (both -> 'regent ajanta')
    collapse to one row in every manufacturer view."""
    if 'Mfg_Bin_Key' in df.columns:
        return df['Mfg_Bin_Key'].fillna('').astype(str)
    raw = (
        df['Manufactured By'].fillna('').astype(str)
        .str.split(',').str[0].str.strip()
    )
    return raw.apply(normalize_company_name)


def _mfg_group_label(df: pd.DataFrame) -> pd.Series:
    """Per-row manufacturer label that is CONSTANT within each bin: the
    best display label for the bin, applied to every row in it. Callers
    group/crosstab/Sankey on this so two rows with the same bin but
    different per-row display labels (e.g. 'Regent Ajanta Biotech' and
    'Regent Ajanta Biotech 86-87', or 'Martin & Brown Bio-Sciences' &
    'Martin And Brown Bio-Sciences' variants) collapse to one group
    instead of splitting.

    Label selection per bin prefers a TRUSTED upstream canonical (so a raw
    'M/s. ...' spelling never wins over a clean canonical 'Regent Ajanta
    Biotech' in the same bin); among those, .mode() picks the most frequent
    spelling and breaks ties alphabetically (the shorter/cleaner spelling
    sorts first, e.g. 'Regent Ajanta Biotech' before 'Regent Ajanta Biotech
    86-87'). Falls back to raw labels only when no row in the bin has a
    trusted canonical. Index-aligned to df; empty bins map to '' so the
    existing `!= ''` drop keeps working."""
    bin_ = _mfg_bin(df)
    canon = df['Mfg_Company_Canonical'].fillna('').astype(str)
    label = _mfg_label(df)
    # True where this row's label came from a trusted upstream canonical
    # (not the raw fallback) — prefer those for the bin's display label.
    is_canon = (canon != '') & (label == canon)
    paired = pd.DataFrame({'__b': bin_, '__l': label, '__c': is_canon}, index=df.index)
    mask = paired['__b'].fillna('') != ''

    def _pick(g: pd.DataFrame) -> str:
        canon_rows = g[g['__c']]
        src = canon_rows if len(canon_rows) else g
        m = src['__l'].mode()
        return str(m.iloc[0]) if not m.empty else str(src['__l'].iloc[0])

    mode_map = paired[mask].groupby('__b')[['__l', '__c']].apply(_pick).to_dict()
    return bin_.map(mode_map).fillna('')


def _molecule_hybrid(df: pd.DataFrame, other_label: str = _MOLECULE_OTHER) -> pd.Series:
    """Hybrid molecule label per row, index-aligned to df. Curated API via
    match_molecule (PRODUCT_CATALOG then EXTRA_CURATED_APIS) where it matches
    — clean, aggregated top nodes (paracetamol, telmisartan …) — and the
    product-ontology canonical key (active-ingredient token grouping, ~99.5%
    coverage) for the rest, so the tail carries real named molecules instead
    of a blanket 'unclassified' bucket. Blank keys fall to other_label.

    Curated-first matters for aggregation: a combo like 'Aceclofenac
    Paracetamol' matches the curated token 'paracetamol' and rolls into the
    paracetamol node, while 'Albendazole' (not yet curated) keeps its own
    ontology-key node and shows up as a curation candidate."""
    curated = df['Name of Product'].map(match_molecule).fillna('')
    key = df['Product_Ontology_Key'].fillna('').astype(str)
    label = curated.where(curated != '', key)
    return label.where(label != '', other_label)


def _fallback_molecules(df: pd.DataFrame) -> pd.Series:
    """Distinct product-ontology keys used as the molecule fallback — i.e.
    products whose name matched no curated/extra API — ranked by alert count.
    These are the candidates to promote into EXTRA_CURATED_APIS in
    shared/gmp_knowledge.py to progressively grow the curated molecule list."""
    curated = df['Name of Product'].map(match_molecule).fillna('')
    key = df['Product_Ontology_Key'].fillna('').astype(str)
    fb = key[(curated == '') & (key != '')]
    return fb.value_counts()


def _fold_categories(series: pd.Series, top_k: int = 7, other: str = "Other") -> pd.Series:
    """Keep the top_k categories by count; replace the tail (and NaN) with
    `other`. Index-aligned. Keeps stacked-bar/timeline colour counts within the
    8-hue _SCIENTIFIC_COLORWAY ceiling (top-7 + Other)."""
    s = series.fillna(other).astype(str)
    counts = s[s != other].value_counts()
    keep = set(counts.head(top_k).index.tolist())
    return s.where(s.isin(keep) | (s == other), other)


def _rmy_datetime(df: pd.DataFrame) -> pd.Series:
    """A datetime view of 'Reporting Month & Year' (format %b-%Y, e.g.
    'Apr-2025') for chronological min/max aggregation and chronological column
    sorting. String min/max on '%b-%Y' values is alphabetical on the month
    name, so 'Apr-2026' ranks before 'Sep-2025' — wrong. Reuses the loader's
    'Parsed_Date' when present; otherwise parses on the fly. Unparseable values
    become NaT so min/max skip them (never alphabetically ranked)."""
    if "Parsed_Date" in df.columns:
        return df["Parsed_Date"]
    return pd.to_datetime(df["Reporting Month & Year"], format="%b-%Y", errors="coerce")


# Display format for the first_seen / last_seen DateColumns — matches the
# source '%b-%Y' string ('Apr-2025') exactly while sorting chronologically.
_DATE_FMT = "MMM-YYYY"


def _sort_alerts_chronological(view: pd.DataFrame) -> pd.DataFrame:
    """Sort an alert ledger by reporting month chronologically (then product
    name), returning the view without the temp datetime key. String sort on
    '%b-%Y' is alphabetical on the month name ('Apr-2026' before 'Sep-2025');
    parsing to datetime first makes the default row order chronological."""
    view = view.copy()
    view["__sort_dt"] = _rmy_datetime(view)
    by = ["__sort_dt"]
    if "Name of Product" in view.columns:
        by.append("Name of Product")
    view = view.sort_values(by, na_position="last")
    return view.drop(columns="__sort_dt")


def _render_sankey(df: pd.DataFrame, levels, title: str) -> None:
    """Generic N-level Sankey. `levels` is a list of (series, label, cap,
    other_label) tuples; each `series` is index-aligned to df. Each level is
    capped to its top `cap` values by count (tail -> other_label). Nodes use
    the accent hue; links are light-gray. Per-level node ids keep coincident
    labels (e.g. "Other" on every level) as distinct nodes."""
    if df.empty:
        st.warning("No rows available for this flow under the current filters.")
        return
    capped = []
    for series, _label, cap, other_label in levels:
        s = series.fillna(other_label).astype(str)
        top = s[s != other_label].value_counts().head(cap).index.tolist()
        capped.append(s.where(s.isin(top) | (s == other_label), other_label))
    # Per-level node order: count desc, other_label forced last.
    node_labels = []
    for (series, _label, _cap, other_label), s in zip(levels, capped):
        vc = s[s != other_label].value_counts().sort_values(ascending=False)
        ordered = vc.index.tolist()
        if (s == other_label).any():
            ordered = ordered + [other_label]
        node_labels.append(ordered)
    all_nodes: list[str] = []
    node_idx: dict[tuple[int, str], int] = {}
    for li, ordered in enumerate(node_labels):
        for name in ordered:
            node_idx[(li, name)] = len(all_nodes)
            all_nodes.append(name)
    sources, targets, values = [], [], []
    for i in range(len(capped) - 1):
        pair = pd.crosstab(capped[i], capped[i + 1])
        for src in pair.index:
            for tgt in pair.columns:
                v = int(pair.loc[src, tgt])
                if v:
                    sources.append(node_idx[(i, src)])
                    targets.append(node_idx[(i + 1, tgt)])
                    values.append(v)
    if not sources:
        st.warning("No flow links could be built from the current filters.")
        return
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15, thickness=20, line=dict(color="black", width=0.5),
            label=all_nodes, color=_ACCENT,
        ),
        link=dict(
            source=sources, target=targets, value=values,
            color="rgba(180, 180, 180, 0.35)",
        ),
    )])
    fig.update_layout(title_text=title, font_size=11)
    st.plotly_chart(fig, use_container_width=True)


def _topn_heatmap(row_series: pd.Series, col_series: pd.Series,
                  row_cap: int, col_cap: int, title: str,
                  xlab: str, ylab: str,
                  row_other_label: str = "Other",
                  col_other_label: str = "Other",
                  include_other: bool = False) -> None:
    """Crosstab heatmap of top-row_cap rows x top-col_cap cols, rendered with
    the sequential ramp. Both series must be index-aligned to the same frame.
    Sorts rows/cols by marginal total so the densest pairing sits top-right.

    When include_other is False (default) the tail beyond each cap and any
    other-label bucket are dropped entirely and the excluded alert count is
    reported in a caption — no giant 'Other' cell. When True, the tail folds
    into the other-label rows/cols (for callers that want the bucket)."""
    r = row_series.fillna(row_other_label).astype(str)
    c = col_series.fillna(col_other_label).astype(str)
    row_top = r[r != row_other_label].value_counts().head(row_cap).index.tolist()
    col_top = c[c != col_other_label].value_counts().head(col_cap).index.tolist()
    if include_other:
        r = r.where(r.isin(row_top) | (r == row_other_label), row_other_label)
        c = c.where(c.isin(col_top) | (c == col_other_label), col_other_label)
        ct = pd.crosstab(r, c)
        keep_rows = [x for x in row_top if x in ct.index] + (
            [row_other_label] if row_other_label in ct.index else [])
        keep_cols = [x for x in col_top if x in ct.columns] + (
            [col_other_label] if col_other_label in ct.columns else [])
        ct = ct.reindex(index=keep_rows, columns=keep_cols).fillna(0)
        excluded = 0
    else:
        # Drop the tail + other-label bucket entirely; report what's excluded.
        keep = r.isin(row_top) & c.isin(col_top)
        ct = pd.crosstab(r[keep], c[keep])
        ct = ct.reindex(
            index=[x for x in row_top if x in ct.index],
            columns=[x for x in col_top if x in ct.columns],
        ).fillna(0)
        excluded = int(len(r) - keep.sum())
    ct = ct.loc[ct.sum(axis=1).sort_values(ascending=True).index]
    ct = ct[ct.sum(axis=0).sort_values(ascending=True).index]
    if ct.empty or ct.values.sum() == 0:
        st.info("No data to populate this heatmap under the current filters.")
        return
    fig = px.imshow(
        ct,
        labels=dict(x=xlab, y=ylab, color="Alert Count"),
        x=ct.columns, y=ct.index,
        color_continuous_scale=_SCIENTIFIC_CONTINUOUS,
        title=title,
    )
    fig.update_xaxes(side="bottom", tickangle=30)
    fig.update_layout(margin=dict(l=8, r=8, t=40, b=8))
    st.plotly_chart(fig, use_container_width=True)
    if excluded:
        st.caption(
            f"Top {len(ct.index)} × {len(ct.columns)}; {excluded} alerts "
            f"outside this matrix excluded (rare rows/cols or {col_other_label})."
        )


def _manufacturer_heatmap(df: pd.DataFrame, col_series: pd.Series,
                          n_mfg: int, n_col: int, title: str,
                          xlab: str, ylab: str,
                          col_other_label: str = "Other") -> None:
    """Manufacturer × column heatmap with relevance-based manufacturer
    selection and no 'Other' bucket. Columns are the top n_col categories by
    count (col_other_label excluded). Manufacturers are then ranked by how
    many of those top columns they actually appear in (coverage breadth),
    tie-broken by total alerts within the top columns — so the matrix is
    dense and informative instead of a few one-hot rows. The folded tail
    (rare manufacturers, non-top columns, col_other_label) is dropped and its
    alert count reported."""
    mfg = _mfg_group_label(df).fillna('').astype(str)
    col = col_series.fillna(col_other_label).astype(str)
    col_top = col[col != col_other_label].value_counts().head(n_col).index.tolist()
    if not col_top:
        st.info("No data to populate this heatmap under the current filters.")
        return
    keep = (mfg != '') & col.isin(col_top)
    ct = pd.crosstab(mfg[keep], col[keep])
    # Relevance: total alerts within the top columns first (the major
    # manufacturers facing issues), tie-broken by coverage breadth (how many
    # of the top columns they hit). Total-first guarantees every selected row
    # carries real volume; the top-column restriction guarantees no empty rows
    # — a dense, informative matrix rather than a few one-hot rows.
    coverage = (ct > 0).sum(axis=1)
    totals = ct.sum(axis=1)
    mfg_order = (
        pd.DataFrame({'cov': coverage, 'tot': totals})
        .sort_values(['tot', 'cov'], ascending=[False, False])
        .head(n_mfg).index.tolist()
    )
    ct = ct.reindex(index=mfg_order, columns=col_top).fillna(0)
    # Columns by total desc; rows by total asc so the biggest sits on top.
    ct = ct[ct.sum(axis=0).sort_values(ascending=False).index]
    ct = ct.loc[ct.sum(axis=1).sort_values(ascending=True).index]
    excluded = int(len(mfg) - int(ct.values.sum()))
    if ct.empty or ct.values.sum() == 0:
        st.info("No data to populate this heatmap under the current filters.")
        return
    fig = px.imshow(
        ct,
        labels=dict(x=xlab, y=ylab, color="Alert Count"),
        x=ct.columns, y=ct.index,
        color_continuous_scale=_SCIENTIFIC_CONTINUOUS,
        title=title,
    )
    fig.update_xaxes(side="bottom", tickangle=30)
    fig.update_layout(margin=dict(l=8, r=8, t=40, b=8))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Top {len(ct.index)} manufacturers by alert volume within the top "
        f"{len(ct.columns)} {xlab.lower()}s (coverage breadth as tiebreaker). "
        f"{excluded} alerts outside this matrix excluded (rare manufacturers, "
        f"non-top {xlab.lower()}s, or {col_other_label})."
    )


def _mfg_summary(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group alerts by canonical manufacturer: Mfg_Company_Canonical, falling
    back to the first segment of 'Manufactured By' (the raw company name).
    Returns (mfg_df labelled with an '__mfg' column, empties dropped; summary
    table sorted by alert count desc). Mirrors the grouping in the product
    investigation flow so both modes collapse manufacturers identically."""
    mfg_df = df.copy()
    mfg_df['__mfg'] = _mfg_group_label(mfg_df)
    mfg_df = mfg_df[mfg_df['__mfg'].fillna('') != '']
    # Parse reporting month to datetime so first_seen/last_seen min/max and
    # column sorting are chronological, not alphabetical on month names.
    mfg_df['__rmy_dt'] = _rmy_datetime(mfg_df)
    summary = (
        mfg_df.groupby('__mfg')
              .agg(
                  alerts=('Name of Product', 'size'),
                  products=('Name of Product', 'nunique'),
                  first_seen=('__rmy_dt', 'min'),
                  last_seen=('__rmy_dt', 'max'),
                  cities=('Mfg_City', lambda s: sorted(set(x for x in s if x))),
              )
              .reset_index()
              .rename(columns={'__mfg': 'Manufacturer'})
              .sort_values(['alerts', 'Manufacturer'], ascending=[False, True])
    )
    return mfg_df, summary


def _render_provenance_badge(prov: Provenance | None, label: str = "Source") -> None:
    """Compact, monochrome provenance caption — the rigour gate made visible.
    Renders the authority tier + source ref (and a 'citation TODO' flag where a
    real citation is still to be sourced). No emoji: the tier name is the label."""
    if prov is None:
        st.caption(f"{label}: no provenance — do not treat as authoritative.")
        return
    tier = prov.authority_tier
    bits = [f"{label}: [{tier}] {prov.source_ref or '(no ref)'}"]
    if prov.reference_url:
        bits.append(f"({prov.reference_url})")
    if prov.retrieved_at:
        bits.append(f"retrieved {prov.retrieved_at}")
    if prov.n:
        bits.append(f"n={prov.n}")
    if "TODO" in (prov.notes or ""):
        bits.append("· citation TODO")
    st.caption(" ".join(bits))


def _render_tier_legend() -> None:
    """One-time authority-tier legend for the manufacturer-investigation
    section. Ordered highest-to-lowest evidentiary strength per ICH Q9(R1)."""
    st.caption(
        "**Authority tiers** — every claim below carries one: "
        "[monograph] compendial spec · [ich_guideline] ICH Q4B/Q8/Q9/Q10 "
        "(cited to database.ich.org) · [regulatory_registry] FDA Orange Book / "
        "EMA / CDSCO determination · [patent] registry-cited · "
        "[empirical_cohort] cohort n+query · [expert_corridor] illustrative · "
        "[uncited] citation TODO. Uncited/TODO claims are shown for "
        "transparency, not as grounded fact."
    )


_VERDICT_LABEL = {
    DIFF_NSQ_RELEVANT: "NSQ-relevant",
    DIFF_METHOD_EQUIVALENT: "equivalent",
    DIFF_INCOMPARABLE: "incomparable",
}


def _fmt_method(method: PharmacopeialMethod | None, section: str) -> str:
    """Compact one-line rendering of a parsed PharmacopeialMethod cell. Returns
    '—' for an absent/NONE method (the USP seam today). A trailing [LOW]/
    [MEDIUM] flag marks sparse parses so the reader never mistakes an
    unparseable compendial line for a clean structured method."""
    if method is None or method.parse_confidence == CONFIDENCE_NONE:
        return "—"
    parts: list[str] = []
    if section == "dissolution":
        if method.apparatus:
            parts.append(method.apparatus)
        if method.rpm is not None:
            parts.append(f"{method.rpm:g} RPM")
        if method.medium:
            parts.append(method.medium)
        if method.medium_ph is not None:
            parts.append(f"pH {method.medium_ph:g}")
        if method.q_limit_pct is not None:
            parts.append(f"Q≥{method.q_limit_pct:g}%")
        for t in method.timepoints:
            parts.append(f"@{t.time_min:g} min")
    elif section == "assay":
        if method.detection:
            parts.append(method.detection)
        if method.column:
            parts.append(method.column)
        if method.mobile_phase:
            parts.append(f"MP {method.mobile_phase}")
    elif section == "impurities":
        if method.impurity_name:
            parts.append(method.impurity_name)
        if method.impurity_limit_pct is not None:
            parts.append(f"≤{method.impurity_limit_pct:g}%")
    conf = "" if method.parse_confidence == CONFIDENCE_HIGH else f" [{method.parse_confidence}]"
    if not parts:
        return f"text unparseable{conf}"
    return " · ".join(parts) + conf


def _render_pharmacopeia_diff(drug) -> None:
    """Structured cross-pharmacopeia method diff for one curated API (Idea 4).
    Parses the IP 2026 / Ph. Eur. TestingGuidelines text into comparable
    PharmacopeialMethod objects and classifies each section's comparison.
    USP is empty today (the simulator regulatory-passport seam — see caption)."""
    diffs = pharmacopeia_diff.diff_drug(drug)
    nq = pharmacopeia_diff.nsq_relevant_count(drug)
    st.markdown(
        f"**Cross-pharmacopeia method diff** — {nq}/3 sections NSQ-relevant "
        f"(IP 2026 vs Ph. Eur.)"
    )
    rows = []
    for d in diffs:
        rows.append({
            "Section": d.section,
            "IP 2026": _fmt_method(d.methods[Pharmacopeia.IP2026], d.section),
            "Ph. Eur.": _fmt_method(d.methods[Pharmacopeia.PH_EUR], d.section),
            "USP": _fmt_method(d.methods[Pharmacopeia.USP], d.section),
            "ICH Q4B": (
                "Annex 7(R2) — general ch.; prod.-specific outside scope"
                if d.ich_harmonisation else "—"
            ),
            "Verdict": _VERDICT_LABEL[d.significance],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    # Surface only the NSQ-relevant rationales — the signal the app exists for.
    nq_rationales = [
        f"**{d.section}**: {d.rationale}"
        for d in diffs if d.significance == DIFF_NSQ_RELEVANT
    ]
    if nq_rationales:
        st.caption("NSQ-relevant differences: " + " | ".join(nq_rationales))
    # ICH Q4B harmonisation scope note (dissolution only): states the honest
    # boundary — the general chapter is harmonised across ICH regions, but the
    # product-specific conditions compared here, and IP, are outside Q4B scope.
    diss = next((d for d in diffs if d.ich_harmonisation), None)
    if diss is not None:
        st.caption(f"**ICH Q4B harmonisation** — {diss.ich_harmonisation}")
        _render_provenance_badge(drug.ich_harmonisation_prov, "ICH Q4B source")
    st.caption(
        "USP method column empty: USP-NF compendial method text is "
        "subscription-gated. The US regulatory axis is carried by the real FDA "
        "Orange Book block below (TE codes, RLD, applicant — cited to openFDA). "
        "The FDA Dissolution Methods database is the identified public citable "
        "source to wire next for US dissolution methods. Verdict compares the "
        "two sourced compendial axes (IP 2026 vs Ph. Eur.); incomparable = a "
        "side too sparse to compare honestly, never silent equivalence."
    )


def _fmt_te_codes(te_codes: list[str]) -> str:
    """Therapeutic Equivalence codes as a compact, honest label. AB1/AB2/AB3
    is flagged because it means not all AB generics are equivalent to each
    other — a real NSQ-relevant substitution risk, not just 'equivalent'."""
    if not te_codes:
        return "(none — OTC / not TE-coded)"
    parts = []
    for c in te_codes:
        if c in ("AB", "AA", "AN", "AO", "AP", "AT"):
            parts.append(c)
        elif c.startswith("AB"):
            parts.append(f"{c} (not all generics equivalent)")
        elif c in ("BC", "BD", "BE", "BN", "BP", "BR", "BS", "BT", "BX"):
            parts.append(f"{c} (NOT therapeutically equivalent)")
        else:
            parts.append(c)
    return " · ".join(parts)


def _render_orange_book(drug) -> None:
    """Real FDA Orange Book regulatory-equivalence block for the US axis (Idea 4).
    TE codes, RLD originator, application number, approval date, dosage forms —
    all from the openFDA Orange Book endpoint with a real, dated citation."""
    ob = drug.orange_book
    if ob is None:
        st.caption(
            "FDA Orange Book: no entry (not FDA-approved in the US, e.g. "
            "vildagliptin) — honestly absent, not faked."
        )
        return
    st.markdown("**FDA Orange Book** — real US regulatory-equivalence data")
    rows = [
        {"Field": "Active ingredient (US)", "Value": ob.active_ingredient},
        {"Field": "TE codes", "Value": _fmt_te_codes(ob.te_codes)},
        {"Field": "RLD applicant", "Value": ob.rld_applicant or "—"},
        {"Field": "RLD application", "Value": ob.rld_app_number or "—"},
        {"Field": "RLD approval date", "Value": (ob.rld_approval_date or "—")},
        {"Field": "Reference standard", "Value": "yes" if ob.reference_standard else "no"},
        {"Field": "Dosage forms", "Value": ", ".join(ob.dosage_forms) or "—"},
        {"Field": "Marketing status", "Value": ", ".join(ob.marketing_statuses) or "—"},
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    _render_provenance_badge(ob.provenance, "FDA Orange Book")


def _render_api_card(drug) -> None:
    """One curated-API standards card: optimal process, patent, GMP corridor,
    IP 2026 / Ph. Eur. testing, typical defect causes. Each block is followed
    by its provenance caption so the authority tier is visible per claim."""
    st.markdown(
        f"**Process:** {drug.optimal_process or '—'}  ·  **Patent:** {drug.patent_ref or '—'}"
    )
    _render_provenance_badge(drug.optimal_process_prov, "Process")
    _render_provenance_badge(drug.patent_prov, "Patent")
    if drug.ideal_parameters:
        gmp_lines = [
            f"- {p.label}: {p.min}–{p.max} {p.unit} (target {p.ideal} {p.unit})"
            for p in drug.ideal_parameters.values()
        ]
        st.markdown("**GMP corridor**\n" + "\n".join(gmp_lines))
        # All ParamSpec corridors share the expert-corridor default until a
        # design-space / vendor spec is sourced; surface it once for the block.
        first_prov = next(iter(drug.ideal_parameters.values())).provenance
        _render_provenance_badge(first_prov, "GMP corridor")
    elif drug.gmp_note:
        st.markdown(f"**GMP** — {drug.gmp_note}")
    else:
        st.markdown("**GMP corridor** — not specified in the curated catalog.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**IP 2026**")
        st.markdown(f"- Assay: {drug.ip2026.assay}")
        st.markdown(f"- Dissolution: {drug.ip2026.dissolution}")
        st.markdown(f"- Impurities: {drug.ip2026.impurities}")
        _render_provenance_badge(drug.ip2026.provenance, "IP 2026")
    with c2:
        st.markdown("**Ph. Eur.**")
        st.markdown(f"- Assay: {drug.ph_eur.assay}")
        st.markdown(f"- Dissolution: {drug.ph_eur.dissolution}")
        st.markdown(f"- Impurities: {drug.ph_eur.impurities}")
        _render_provenance_badge(drug.ph_eur.provenance, "Ph. Eur.")
    _render_pharmacopeia_diff(drug)
    _render_orange_book(drug)
    if drug.common_alerts:
        st.markdown("**Typical defect causes:** " + "; ".join(drug.common_alerts))
        # Honest label: common_alerts is authored narrative with no denominator.
        _render_provenance_badge(drug.common_alerts_prov, "Typical causes")


def _curated_apis(drill: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Return (curated API ids in first-appearance order, uncurated product
    names) for the manufacturer's distinct flagged products. Matches on the
    raw 'Name of Product' (always present, retains the API token match_api
    expects) so no product is silently skipped — consistent with the
    'matched K of M' caption, which uses Name of Product nunique for M."""
    curated: list[str] = []
    seen: set[str] = set()
    uncurated: list[str] = []
    for p in drill['Name of Product'].dropna().unique():
        name = str(p).strip()
        if not name:
            continue
        api = match_api(name)
        if api and api not in seen:
            curated.append(api)
            seen.add(api)
        elif not api:
            uncurated.append(name)
    return curated, uncurated


def _render_standards_recap(drill: pd.DataFrame) -> None:
    """(d) Recap of GMP & testing standards — one card per curated API among the
    manufacturer's flagged products; generic pharmacopeial guidance for the rest.
    No fabricated specifics: uncurated products show generic_standards()."""
    curated, uncurated = _curated_apis(drill)
    n_products = drill['Name of Product'].nunique()
    st.caption(
        f"Matched {len(curated)} of {n_products} distinct flagged products to a "
        f"curated active ingredient; {len(uncurated)} product(s) fall back to "
        f"generic pharmacopeial guidance."
    )
    _render_tier_legend()
    if curated:
        for api_id in curated:
            drug = PRODUCT_CATALOG[api_id]
            with st.expander(f"{drug.name} ({api_id})", expanded=False):
                _render_api_card(drug)
    if uncurated:
        with st.expander(
            f"Uncurated products — generic pharmacopeial guidance ({len(uncurated)})",
            expanded=False,
        ):
            gs = generic_standards(uncurated[0])
            st.markdown(f"**Scientific context** — {gs['scientific']}")
            _render_provenance_badge(GENERIC_STANDARDS_PROVENANCE["scientific"], "Scientific")
            st.markdown(f"**Regulatory guidelines** — {gs['regulatory']}")
            _render_provenance_badge(GENERIC_STANDARDS_PROVENANCE["regulatory"], "Regulatory")
            st.caption(
                "Applies to: " + ", ".join(uncurated[:12])
                + (" …" if len(uncurated) > 12 else "")
            )


def _render_probable_causes(drill: pd.DataFrame, fc_counts: pd.DataFrame) -> None:
    """(e) Potential causes — data-driven failure-mode signals (recovered
    _risk_card logic) + API-informed typical defect mechanisms."""
    causes: list[str] = []
    for _, r in fc_counts.head(3).iterrows():
        causes.append(
            f"{r['Failure Category']} is a dominant failure mode ({int(r['Alerts'])} alerts)."
        )
    if 'Form type' in drill.columns:
        forms = drill['Form type'].dropna()
        forms = forms[forms.astype(str) != '']
        if forms.nunique() > 1:
            causes.append(
                f"Issues span {forms.nunique()} dosage forms: "
                f"{', '.join(sorted(forms.unique()))}."
            )
    if 'Mfg_State' in drill.columns:
        states = drill['Mfg_State'].dropna()
        states = states[states.astype(str) != '']
        if not states.empty:
            causes.append(
                "Geographic concentration: "
                + ", ".join(states.value_counts().head(3).index.tolist()) + "."
            )
    st.markdown("**Data-driven signals**")
    if causes:
        for c in causes:
            st.markdown(f"- {c}")
    else:
        st.caption("No dominant failure-mode signal for this manufacturer.")

    st.markdown("**API-informed typical defect mechanisms**")
    st.caption(
        "Curated typical-defect lists below are authored narrative (uncited, no "
        "denominator) — review against the empirical cohort distribution, not as "
        "grounded fact."
    )
    curated, uncurated = _curated_apis(drill)
    if curated:
        for api_id in curated:
            drug = PRODUCT_CATALOG[api_id]
            if drug.common_alerts:
                st.markdown(f"- **{drug.name}**: " + "; ".join(drug.common_alerts))
            else:
                st.markdown(
                    f"- **{drug.name}**: no curated typical-defect list "
                    f"(review the NSQ result text for this product)."
                )
    if uncurated:
        st.markdown(
            "- For products not in the curated catalog: review the NSQ result "
            "text against the relevant pharmacopeial monograph for the active "
            "substance."
        )
    if not curated and not uncurated:
        st.caption("No products resolved for this manufacturer.")


def _render_mitigation_plan(drill: pd.DataFrame, fc_counts: pd.DataFrame) -> None:
    """(f) Mitigation plan — per top failure category, pull mitigations from
    SOLUTION_BANK (via mitigations_for). Categories without a curated playbook
    fall back to ICH Q9; never fabricates. The bank is a general ICH Q9-rooted
    playbook (cited), not a product-specific verdict."""
    st.caption(
        "General ICH Q9-rooted mitigation playbook (not product-specific, not a "
        "verdict). Mitigations are keyed to the manufacturer's dominant failure "
        "categories; categories without a curated playbook fall back to ICH Q9 "
        "risk-management."
    )
    top = fc_counts.head(5)
    if top.empty:
        st.caption("No failure categories resolved for this manufacturer.")
        return
    for _, r in top.iterrows():
        cat = r['Failure Category']
        n = int(r['Alerts'])
        st.markdown(f"**{cat}** ({n} alerts)")
        mitigations = mitigations_for(cat)
        for m in mitigations:
            st.markdown(f"- {m.text}")
        # All bank entries share the ICH-guideline provenance; surface it once
        # per category rather than per mitigation to avoid noise.
        if mitigations:
            _render_provenance_badge(mitigations[0].provenance, "Playbook")


def _render_manufacturer_investigation(df: pd.DataFrame) -> None:
    """Manufacturer-first investigation: visualize the major manufacturers
    facing NSQ issues, then drill into one for its full alert history, an issue
    analysis, a recap of GMP & testing standards, probable causes, and a
    mitigation plan."""
    st.markdown(
        "Start from the manufacturers facing the most NSQ issues, then drill "
        "into one for its full alert history, issue analysis, a recap of GMP "
        "& testing standards, probable causes, and a mitigation plan."
    )
    st.caption(
        "This view uses the full dataset (all reporting periods); sidebar "
        "filters (Drug type / Form type / search / dissolution focus) scope "
        "tabs 1–4 only."
    )

    mfg_df, summary = _mfg_summary(df)
    if summary.empty:
        st.info("No manufacturer-resolved alerts in the dataset.")
        return

    # ---- (a) Major manufacturers facing issues (visualized) ----
    st.subheader("Major manufacturers facing NSQ issues")
    top_n = summary.head(15)
    fig_bar = px.bar(
        top_n, x='alerts', y='Manufacturer', orientation='h',
        title=f"Top {len(top_n)} manufacturers by NSQ alert count",
        labels={'alerts': 'NSQ Alerts', 'Manufacturer': 'Manufacturer'},
        color_discrete_sequence=[_ACCENT],
    )
    # Single accent — bar length already encodes the alert count.
    fig_bar.update_layout(
        showlegend=False,
        yaxis=dict(categoryorder='total ascending'),
        margin=dict(l=8, r=8, t=40, b=8),
    )
    st.plotly_chart(fig_bar, use_container_width=True)
    st.dataframe(
        summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "first_seen": st.column_config.DateColumn("First seen", format=_DATE_FMT),
            "last_seen": st.column_config.DateColumn("Last seen", format=_DATE_FMT),
        },
    )

    # ---- Pick a manufacturer ----
    st.markdown("---")
    mfg_choice = st.selectbox(
        "Pick a manufacturer to investigate:",
        options=summary['Manufacturer'].tolist(),
        key="inv_mfg_mfg_choice",
    )
    drill = mfg_df[mfg_df['__mfg'] == mfg_choice].copy()
    st.caption(
        f"Showing {len(drill)} alerts for **{mfg_choice}** across "
        f"{drill['Name of Product'].nunique()} products."
    )

    # ---- (b) What errors they've had in the past ----
    st.subheader("Past NSQ alerts (full history)")
    alert_cols = [
        'Name of Product', 'Batch No', 'Mfg', 'Exp', 'Manufactured By',
        'Mfg_State', 'NSQ Result', 'Failure_Category_Primary',
        'Reporting Source', 'Reporting by Lab/State', 'Reporting Month & Year',
    ]
    alert_cols = [c for c in alert_cols if c in drill.columns]
    alert_view = _sort_alerts_chronological(drill[alert_cols])
    st.dataframe(alert_view, use_container_width=True, hide_index=True)
    st.download_button(
        label="Export this manufacturer's NSQ history to CSV",
        data=alert_view.to_csv(index=False).encode('utf-8'),
        file_name=f"nsq_history_{mfg_choice[:30].replace(' ', '_').replace('/', '_')}.csv",
        mime="text/csv",
        key="inv_mfg_drill_csv",
    )

    # ---- (c) Issue analysis ----
    st.subheader("Issue analysis")
    fc_col = 'Failure_Category_Primary'
    fc_counts = (
        drill[fc_col].fillna('Uncategorized').value_counts()
        .reset_index()
    )
    fc_counts.columns = ['Failure Category', 'Alerts']
    fig_fc = px.bar(
        fc_counts, x='Alerts', y='Failure Category', orientation='h',
        title=f"Failure-category breakdown — {mfg_choice}",
        labels={'Alerts': 'NSQ Alerts'},
        color_discrete_sequence=[_ACCENT],
    )
    # Single accent — bar length already encodes the alert count.
    fig_fc.update_layout(
        showlegend=False,
        yaxis=dict(categoryorder='total ascending'),
        margin=dict(l=8, r=8, t=40, b=8),
    )
    st.plotly_chart(fig_fc, use_container_width=True)

    timeline = drill.copy()
    timeline['__date'] = pd.to_datetime(
        timeline['Reporting Month & Year'].fillna('Unknown'),
        format='%b-%Y', errors='coerce',
    )
    timeline = timeline.dropna(subset=['__date'])
    if timeline.empty:
        st.info("No parseable reporting dates for this manufacturer.")
    else:
        # Fold the failure-category tail into "Other" so the stacked bar uses
        # <=8 hues (top-7 + Other) and never cycles past _SCIENTIFIC_COLORWAY.
        timeline[fc_col] = _fold_categories(timeline[fc_col], top_k=7, other="Other")
        monthly = (
            timeline.groupby([pd.Grouper(key='__date', freq='MS'), fc_col])
                   .size().reset_index(name='count').sort_values('__date')
        )
        fig_t = px.bar(
            monthly, x='__date', y='count', color=fc_col,
            title=f"NSQ alert history — {mfg_choice}",
            labels={'__date': 'Reporting Month', 'count': 'Alert Count',
                    fc_col: 'Failure Category'},
            color_discrete_sequence=_SCIENTIFIC_COLORWAY,
        )
        fig_t.update_layout(barmode='stack', legend_title='Failure Category')
        st.plotly_chart(fig_t, use_container_width=True)

    n_labs = (
        drill['Reporting by Lab/State'].dropna().nunique()
        if 'Reporting by Lab/State' in drill.columns else 0
    )
    # Chronological first/last seen (string min/max on '%b-%Y' is alphabetical
    # on the month name; parse to datetime first). Fallback '—' if no dates parse.
    _rmy = _rmy_datetime(drill)
    first_seen = _rmy.min()
    last_seen = _rmy.max()
    fs = first_seen.strftime('%b-%Y') if pd.notna(first_seen) else '—'
    ls = last_seen.strftime('%b-%Y') if pd.notna(last_seen) else '—'
    st.caption(
        f"Totals — alerts: {len(drill)} · products: {drill['Name of Product'].nunique()} · "
        f"reporting labs: {n_labs} · first seen: {fs} · last seen: {ls}"
    )

    # ---- (d) Recap of GMP & testing standards ----
    st.subheader("Recap of GMP & testing standards")
    _render_standards_recap(drill)

    # ---- (e) Potential causes of issue/failure ----
    st.subheader("Potential causes of issue / failure")
    _render_probable_causes(drill, fc_counts)

    # ---- (f) Mitigation plan ----
    st.subheader("Mitigation plan")
    _render_mitigation_plan(drill, fc_counts)


@st.cache_data
def load_india_geojson():
    """Load the India states GeoJSON from Redis (pushed by
    `just push-geojson` in redis-loader/), falling back to a local
    india_states_slim.geojson file if present (e.g. local dev before
    it's been pushed, or if REDIS_URL isn't set)."""
    try:
        geo = load_redis_geojson()
        if geo is not None:
            return geo
    except RuntimeError:
        pass  # REDIS_URL not set — fall through to local file

    local_path = "india_states_slim.geojson"
    if os.path.exists(local_path):
        with open(local_path) as f:
            return json.load(f)

    return None

# -----------------------------------------------------------------------------
# Dataset state name -> GeoJSON NAME_1 resolution
# -----------------------------------------------------------------------------
# This used to be a hand-written dict that mapped ten real states to None with
# the comment "not in dataset" — Arunachal Pradesh, Chhattisgarh, Delhi,
# Jharkhand, Lakshadweep, Manipur, Meghalaya, Mizoram, Nagaland and Tripura.
# All ten ARE in the GeoJSON, so any manufacturer in those states was silently
# deleted from the choropleth the moment the dataset grew to include them.
#
# It also compared raw strings, while company_ontology.extract_state() returns
# a .title()-cased value: "Jammu And Kashmir" (capital A) never equalled the
# GeoJSON's "Jammu and Kashmir", and neither did "Andaman And Nicobar",
# "Dadra And Nagar Haveli" or "Daman And Diu".
#
# So: match case- and punctuation-insensitively against the GeoJSON's own
# NAME_1 values, and keep an alias table only for genuine renames. Building
# the index from the file means swapping in a newer GeoJSON (one with
# Telangana and Ladakh, say) needs no code change here.

# Dataset spelling -> the spelling used in the GeoJSON. Both sides are
# normalised by _norm_state() before lookup, so case/punctuation are free.
_STATE_ALIASES = {
    # Post-2011 renames the current GeoJSON predates.
    "odisha": "orissa",
    "uttarakhand": "uttaranchal",
    "puducherry": "puducherry",
    "pondicherry": "puducherry",
    # Delhi's many official spellings.
    "nct of delhi": "delhi",
    "national capital territory of delhi": "delhi",
    "the government of nct of delhi": "delhi",
    "new delhi": "delhi",
    # Common short forms / longer official forms.
    "j and k": "jammu and kashmir",
    "andaman and nicobar islands": "andaman and nicobar",
}


def _norm_state(name) -> str:
    """Lowercase, expand '&', drop punctuation, collapse whitespace."""
    if not name:
        return ""
    s = str(name).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def build_state_resolver(geo: dict | None):
    """Return (resolve, known_names) for a GeoJSON of Indian states.

    ``resolve(state)`` gives the exact NAME_1 string to plot against, or
    None when that state genuinely has no feature in the file (Telangana
    and Ladakh, in the current pre-2011 export). Callers should surface the
    Nones rather than dropping them silently — a state missing from the map
    is a data-coverage fact the user needs to see.
    """
    index: dict[str, str] = {}
    for feat in (geo or {}).get("features", []):
        name = (feat.get("properties") or {}).get("NAME_1")
        if name:
            index[_norm_state(name)] = name

    def resolve(state):
        key = _norm_state(state)
        if not key:
            return None
        key = _STATE_ALIASES.get(key, key)
        return index.get(key)

    return resolve, sorted(index.values())

try:
    df_raw = load_and_preprocess_data()
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

# -----------------------------------------------------------------------------
# 3. SIDEBAR CONTROLS & FILTERING
# -----------------------------------------------------------------------------
st.sidebar.title("🎯 Control & Filters")
st.sidebar.markdown("Filter downstream metrics to isolate dissolution anomalies.")

# Quick toggle filter to focus purely on Dissolution vs General alerts
view_type = st.sidebar.radio(
    "Focus Area:",
    ["All Alerts", "Dissolution Failures Only", "Excluding Dissolution"]
)

if view_type == "Dissolution Failures Only":
    df_filtered = df_raw[df_raw['Is_Dissolution'] == True]
elif view_type == "Excluding Dissolution":
    df_filtered = df_raw[df_raw['Is_Dissolution'] == False]
else:
    df_filtered = df_raw.copy()

# Advanced Sidebar Search Filter
search_query = st.sidebar.text_input("🔍 Search Product / Manufacturer Name", "")
if search_query:
    df_filtered = df_filtered[
        df_filtered['Product_Name_Norm'].str.contains(search_query, case=False, na=False) |
        df_filtered['Manufactured By'].str.contains(search_query, case=False, na=False) |
        df_filtered['Product_Name_Canonical'].str.contains(search_query, case=False, na=False)
    ]

# Multi-select dropdown Filters
selected_drug_types = st.sidebar.multiselect(
    "Filter by Drug Type:", 
    options=sorted(df_filtered['Drug type'].dropna().unique()),
    default=[]
)
if selected_drug_types:
    df_filtered = df_filtered[df_filtered['Drug type'].isin(selected_drug_types)]

selected_form_types = st.sidebar.multiselect(
    "Filter by Form Type:", 
    options=sorted(df_filtered['Form type'].dropna().unique()),
    default=[]
)
if selected_form_types:
    df_filtered = df_filtered[df_filtered['Form type'].isin(selected_form_types)]

# Company ontology inspector — shows what the resolver built so the
# user can audit how "Cipla Ltd" and "Cipla Limited" are being merged.
with st.sidebar.expander("🏷  Company Ontology", expanded=False):
    try:
        ontology = load_ontology()
        n = len(ontology)
        st.markdown(
            f"**{n} canonical entit{'y' if n == 1 else 'ies'}" +
            (f"** &mdash; fuzzy threshold "
             f"`{os.environ.get('NSQ_FUZZY_THRESHOLD', '0.85')}`" if n else "**")
        )
        if n:
            preview = (
                pd.DataFrame(
                    [
                        {
                            "Canonical": v.get("canonical_name", ""),
                            "City": v.get("city", ""),
                            "State": v.get("state", ""),
                            "Website": v.get("website", ""),
                            "Aliases": len(v.get("aliases", []) or []),
                            "Sources": v.get("sources", 0),
                        }
                        for v in ontology.values()
                    ]
                )
                .sort_values("Sources", ascending=False)
                .head(25)
            )
            st.dataframe(preview, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Export full ontology (JSON)",
                data=json.dumps(ontology, ensure_ascii=False, indent=2),
                file_name="nsq_company_ontology.json",
                mime="application/json",
            )
    except RuntimeError as exc:
        st.caption(f"Ontology unavailable: {exc}")
    except Exception as exc:  # pragma: no cover
        st.caption(f"Ontology load failed: {exc}")

# Product ontology inspector — parallels the Company Ontology one.
# Shows how near-duplicate product names (e.g. `Telmisartan Tablets
# IP 40 mg` and `Telmisartan Tablets IP 40mg`) are being merged.
with st.sidebar.expander("💊  Product Ontology", expanded=False):
    try:
        product_ontology = load_product_ontology()
        n = len(product_ontology)
        st.markdown(
            f"**{n} canonical entit{'y' if n == 1 else 'ies'}" +
            (f"** &mdash; fuzzy threshold "
             f"`{os.environ.get('NSQ_FUZZY_THRESHOLD', '0.85')}`" if n else "**")
        )
        if n:
            preview = (
                pd.DataFrame(
                    [
                        {
                            "Canonical name": v.get("canonical_name", ""),
                            "Canonical key":  v.get("canonical_key", ""),
                            "Aliases":        len(v.get("aliases", []) or []),
                            "Sources":        v.get("sources", 0),
                        }
                        for v in product_ontology.values()
                    ]
                )
                .sort_values("Sources", ascending=False)
                .head(25)
            )
            st.dataframe(preview, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Export full ontology (JSON)",
                data=json.dumps(product_ontology, ensure_ascii=False, indent=2),
                file_name="nsq_product_ontology.json",
                mime="application/json",
            )
    except RuntimeError as exc:
        st.caption(f"Product ontology unavailable: {exc}")
    except Exception as exc:  # pragma: no cover
        st.caption(f"Product ontology load failed: {exc}")

# -----------------------------------------------------------------------------
# 4. MAIN DASHBOARD CONTENT
# -----------------------------------------------------------------------------
st.title("💊 CDSCO NSQ Alerts Dashboard")
st.subheader("Data-driven trends targeting Quality Deficiencies and Dissolution Anomaly Patterns")
st.markdown("---")

# Row 1: KPI Statistics Overview Cards
total_alerts = len(df_raw)
diss_alerts_count = df_raw['Is_Dissolution'].sum()
diss_pct = (diss_alerts_count / total_alerts) * 100 if total_alerts > 0 else 0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Total Consolidated Alerts</div><div class='metric-value'>{total_alerts}</div></div>", unsafe_allow_html=True)
with col2:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Dissolution-Specific Incidents</div><div class='metric-value'>{diss_alerts_count}</div></div>", unsafe_allow_html=True)
with col3:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Dissolution Defect Ratio</div><div class='metric-value'>{diss_pct:.1f}%</div></div>", unsafe_allow_html=True)
with col4:
    st.markdown(f"<div class='metric-card'><div class='metric-title'>Currently Filtered Rows</div><div class='metric-value'>{len(df_filtered)}</div></div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 5. VISUALIZATION TABS
# -----------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Trend & Distribution Analyses",
    "🗺️ Geographic & Heatmap Matrix",
    "🔀 Relational Sankey Flows",
    "📋 Searchable Audit Ledger",
    "🔎 Product → Manufacturer Investigation",
])

# -----------------------------------------------------------------------------
# TAB 1: TRENDS & BAR CHARTS
# -----------------------------------------------------------------------------
with tab1:
    st.header("Chronological Trends & Product Dissections")

    # The timeline spans 67 months — it needs the full page width. Full-width
    # first row, then the two compact bar pairs below.
    st.subheader("Temporal Timeline Trend")
    # Stacked area chart over time by harmonized failure category —
    # dissolution is one major cause among several (Assay / Content is
    # actually the largest), so the binary Dissolution-vs-Other line
    # hid the composition. Fold the category tail into "Other" so the
    # stack uses <=8 hues (top-7 + Other), matching the drill-down
    # timelines and never cycling past _SCIENTIFIC_COLORWAY.
    trend_df = df_filtered.dropna(subset=['Parsed_Date']).copy()
    if not trend_df.empty:
        trend_df['Failure Category'] = _fold_categories(
            trend_df['Failure_Category_Primary'], top_k=7, other="Other"
        )
        trend_grouped = (
            trend_df.groupby([trend_df['Parsed_Date'].dt.to_period('M'), 'Failure Category'])
                    .size().reset_index(name='Alert Count')
        )
        trend_grouped['Parsed_Date'] = trend_grouped['Parsed_Date'].dt.to_timestamp()
        # Stack largest band first (bottom-up by total volume) so the
        # dominant categories read first and the band order is stable.
        cat_order = (
            trend_grouped.groupby('Failure Category')['Alert Count'].sum()
                         .sort_values(ascending=False).index.tolist()
        )
        fig_line = px.area(
            trend_grouped, x='Parsed_Date', y='Alert Count', color='Failure Category',
            labels={'Parsed_Date': 'Reporting Timeline', 'Alert Count': 'Volume of Incidents'},
            title="Monthly Progression of Recorded Drug Defects",
            category_orders={'Failure Category': cat_order},
            color_discrete_sequence=_SCIENTIFIC_COLORWAY,
        )
        # All traces into one stack group: px.area alone overlays the
        # bands filled-to-zero, which double-counts visually.
        fig_line.update_traces(stackgroup='one', line=dict(width=0.5))
        fig_line.update_layout(
            legend_title="Failure Category", hovermode="x unified",
            height=460, margin=dict(l=8, r=8, t=40, b=8),
        )
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("Insufficient chronological date variables detected to parse timeline trends.")

    # Risk matrices — two compact bar charts share a row.
    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("Top Defective Product Matrices")
        # Horizontal Bar Chart — prefer the canonical column (merged
        # near-duplicate product spellings); fall back to the cosmetic
        # normalized name if the column is missing (offline path).
        col = 'Product_Name_Canonical' if 'Product_Name_Canonical' in df_filtered.columns else 'Product_Name_Norm'
        top_products = df_filtered[col].value_counts().head(10).reset_index()
        top_products.columns = ['Product Name', 'Total Incidents']

        fig_bar = px.bar(
            top_products, x='Total Incidents', y='Product Name', orientation='h',
            labels={'Total Incidents': 'Alert Counts Recorded', 'Product Name': 'Commercial Formulation Name'},
            title="Top 10 Flagged Products within Selected View Filters",
            color_discrete_sequence=[_ACCENT],
        )
        # Single accent color: bar length already encodes magnitude, so a
        # value-ramp would double-encode and burn the colour channel (anti-pattern).
        fig_bar.update_layout(yaxis={'categoryorder': 'total ascending'}, showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)

    with c_right:
        st.subheader("Form Factor Risk Assessments")
        # Form Type Breakdown
        form_counts = df_filtered['Form type'].value_counts().head(12).reset_index()
        form_counts.columns = ['Form Factor', 'Alert Volume']
        # Horizontal + single accent: form-type labels are long, and magnitude
        # is already shown by bar length (no value-ramp on a nominal category).
        fig_form = px.bar(
            form_counts, x='Alert Volume', y='Form Factor', orientation='h',
            labels={'Form Factor': 'Formulation Form Type', 'Alert Volume': 'Alert Count'},
            title="Alert Volume Categorized by Dosage Form Factors",
            color_discrete_sequence=[_ACCENT],
        )
        fig_form.update_layout(yaxis={'categoryorder': 'total ascending'}, showlegend=False)
        st.plotly_chart(fig_form, use_container_width=True)

    # Secondary Breakdown split
    st.markdown("---")
    st.subheader("Failure Category Distribution")
    # Failure Category Distribution — replaces the previous "Recall
    # Class" pie (which was always 100% "Unclassified" because the
    # CSV doesn't carry recall-class data). Now uses the harmonized
    # Failure_Category_Primary derived from each row's NSQ Result.
    # Failure Category Distribution — horizontal bar. The harmonized
    # Failure_Category_Primary yields ~17 classes, which is well past the
    # ~7-class pie/donut ceiling (adjacent slices blur and can't be compared).
    # A sorted horizontal bar is the magnitude-comparison form for many
    # classes; one accent colour, length carries the value. Full width:
    # ~17 labels need the horizontal room the other charts don't.
    cat_counts = df_filtered['Failure_Category_Primary'].value_counts().reset_index()
    cat_counts.columns = ['Failure Category', 'Alert Volume']
    fig_cat = px.bar(
        cat_counts, x='Alert Volume', y='Failure Category', orientation='h',
        labels={'Alert Volume': 'Alert Count', 'Failure Category': 'Failure Category'},
        title="Failure Category Breakdown (Harmonized from NSQ Result)",
        color_discrete_sequence=[_ACCENT],
        height=max(360, 34 * len(cat_counts)),
    )
    fig_cat.update_layout(yaxis={'categoryorder': 'total ascending'}, showlegend=False,
                          margin=dict(l=8, r=8, t=40, b=8))
    st.plotly_chart(fig_cat, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 2: GEOGRAPHIC & HEATMAPS
# -----------------------------------------------------------------------------
with tab2:
    st.header("Geographical Vulnerabilities & Inter-Variable Heatmaps")

    # 1. Choropleth Map of India
    st.subheader("Incident Origins — Indian Political Map")
    state_df = df_filtered['Mfg_State'].value_counts().reset_index()
    state_df.columns = ['Indian State / Origin Region', 'Recorded Anomalies']

    try:
        india_geo = load_india_geojson()
        if india_geo is None:
            raise FileNotFoundError("no geojson available from Redis or local file")

        # Resolve against the GeoJSON's own NAME_1 values (see
        # build_state_resolver): case-insensitive, alias-aware, and it never
        # drops a state that the file actually contains.
        _resolve, _known_states = build_state_resolver(india_geo)
        state_df['Geo_Name'] = state_df['Indian State / Origin Region'].apply(_resolve)

        # States with alerts that this GeoJSON has no polygon for. The current
        # export predates Telangana (2014) and Ladakh (2019), so their alerts
        # would otherwise vanish from the map with no indication. Show them.
        # NB: state_df itself is left complete — the companion bar chart below
        # must still show every state, mapped or not.
        unmapped = state_df[state_df['Geo_Name'].isna()]
        mapped_df = state_df.dropna(subset=['Geo_Name'])

        fig_geo = px.choropleth(
            mapped_df,
            geojson=india_geo,
            locations='Geo_Name',
            featureidkey='properties.NAME_1',
            color='Recorded Anomalies',
            color_continuous_scale=_SCIENTIFIC_CONTINUOUS,
            range_color=(0, mapped_df['Recorded Anomalies'].max() if len(mapped_df) else 1),
            labels={'Recorded Anomalies': 'Total Incident Frequency', 'Geo_Name': 'State'},
            title="Manufacturing-Origin Anomalies Mapped to Indian States",
            hover_name='Indian State / Origin Region',
        )
        fig_geo.update_geos(
            # "geojson", not "locations": frame the whole country, not just
            # the states that happen to have alerts in the current filter.
            # With "locations" a filter matching two states zoomed the map to
            # those two, which is what made it read as "not the India map".
            fitbounds="geojson",
            visible=False,
            showcountries=False,
            showcoastlines=False,
            showland=False,
            showocean=False,
        )
        fig_geo.update_layout(margin={"r": 0, "t": 50, "l": 0, "b": 0}, height=600)
        st.plotly_chart(fig_geo, use_container_width=True)

        if not unmapped.empty:
            rows = ", ".join(
                f"{r['Indian State / Origin Region']} ({int(r['Recorded Anomalies'])})"
                for _, r in unmapped.iterrows()
            )
            st.caption(
                f"⚠️ Not shown on the map — no polygon for these in the current "
                f"boundary file: {rows}. The file is a pre-2011 export "
                f"({len(_known_states)} features), so it predates Telangana "
                f"(2014) and Ladakh (2019). Their alert counts are included in "
                f"the bar chart below."
            )
    except FileNotFoundError:
        st.warning(
            "India GeoJSON not found in Redis (key 'geo:india_states') or locally. "
            "Run `just push-geojson` in redis-loader/ to load it."
        )
    except Exception as e:
        st.error(f"Error rendering choropleth: {e}")

    # Companion bar chart for precise counts
    with st.expander("Show state-level counts as bar chart"):
        fig_geo_bar = px.bar(
            state_df.sort_values('Recorded Anomalies', ascending=True),
            x='Recorded Anomalies', y='Indian State / Origin Region',
            orientation='h',
            labels={'Recorded Anomalies': 'Total Incident Frequency',
                    'Indian State / Origin Region': 'State / Origin Region'},
            title="Incident Origins — Sorted Counts",
            color_discrete_sequence=[_ACCENT],
        )
        # Single accent (magnitude is in the bar length, not a colour ramp).
        fig_geo_bar.update_layout(
            yaxis={'categoryorder': 'total ascending'}, showlegend=False,
        )
        st.plotly_chart(fig_geo_bar, use_container_width=True)
    
    st.markdown("---")
    
    # 2. Variable Cross-Tabulation Pseudo Correlation Heatmap
    st.subheader("Cross-Tabulation Risk Correlation Matrix Heatmap")
    st.markdown("Identifies dense systemic risk cross-overs between specific **Form Factors** and **Testing Labs / Sourcing Jurisdictions**.")

    # Grid magnitude -> sequential colour is the correct encoding (one hue,
    # light->dark). Routed through the shared _topn_heatmap helper so the tail
    # folds into "Other" and the ramp matches the rest of the dashboard.
    if {'Form type', 'Reporting by Lab/State'}.issubset(df_filtered.columns) and not df_filtered.empty:
        _topn_heatmap(
            df_filtered['Form type'], df_filtered['Reporting by Lab/State'],
            row_cap=10, col_cap=10,
            title="Risk Co-Occurrence (Top 10 Form Factors vs Top 10 CDSCO Testing Entities)",
            xlab="Testing Lab Branch", ylab="Formulation Style",
        )
    else:
        st.info("Please expand filter parameters to populate the Correlation Matrix Heatmap.")

    st.markdown("---")

    # 3. Manufacturer-keyed heatmaps — the relational matrices a sales agent
    # needs: which failure reasons cluster on which manufacturers, and which
    # molecules (APIs) each manufacturer's flagged products map to.
    st.subheader("Manufacturer Risk Matrices")
    st.markdown(
        "Each row is a manufacturer; colour is alert count. Manufacturers are "
        "selected by **relevance to the matrix**: ranked by alert volume within "
        "the top failure reasons / molecules, with coverage breadth (how many "
        "of those top categories they hit) as a tiebreaker — so every shown row "
        "carries real volume and the matrix stays dense instead of a few "
        "one-hot rows. The 'Other' buckets are excluded; only the named top "
        "categories are shown. The **Molecule (API)** column uses a hybrid "
        "label: curated active ingredient where known (PRODUCT_CATALOG + the "
        "progressive EXTRA_CURATED_APIS list), otherwise the product-ontology "
        "canonical key (~99.5% coverage). See the Sankey tab's *Molecules to "
        "curate* list for the fallbacks to promote next."
    )
    if not df_filtered.empty:
        n_mfg = st.slider(
            "Manufacturers to show (most relevant first)",
            min_value=5, max_value=25, value=15, step=1, key="hm_mfg_n",
            help="Manufacturers are ranked by alert volume within the top "
                 "categories, then by coverage breadth. Adjust to scope the matrix.",
        )
        _manufacturer_heatmap(
            df_filtered, df_filtered['Failure_Category_Primary'],
            n_mfg=n_mfg, n_col=12,
            title="Manufacturer × Failure Reason",
            xlab="Failure Reason", ylab="Manufacturer",
        )
        _mol = _molecule_hybrid(df_filtered)
        _manufacturer_heatmap(
            df_filtered, _mol,
            n_mfg=n_mfg, n_col=12,
            title="Manufacturer × Molecule (API)",
            xlab="Molecule (API)", ylab="Manufacturer",
            col_other_label=_MOLECULE_OTHER,
        )
    else:
        st.info("No data available for the manufacturer matrices under the current filters.")

# -----------------------------------------------------------------------------
# TAB 3: SANKEY GRAPH COUPLING
# -----------------------------------------------------------------------------
with tab3:
    st.header("Sankey Vulnerability Chain Flow Topology")
    st.markdown(
        "Trace how operational breakdowns flow across three relational cuts. "
        "Pick a flow — the manufacturer- and molecule-keyed cuts are the most "
        "actionable for a sales agent; the state cut is retained for hub mapping. "
        "Each level is capped to its top values (tail folded into **Other**) so "
        "the diagram stays readable."
    )
    st.caption(
        "Molecule (API) is a hybrid label: the curated active ingredient where "
        "one is known (PRODUCT_CATALOG + the progressive EXTRA_CURATED_APIS list "
        "in shared/gmp_knowledge.py), otherwise the product-ontology canonical "
        "key — the active-ingredient token grouping derived from every product "
        "name (~99.5% coverage). Only truly unmapped products fall into "
        "**Other / unmapped molecule**."
    )

    flow = st.radio(
        "Relational flow:",
        [
            "Manufacturer → Molecule (API) → Issue",
            "Indication (Drug type) → Molecule (API) → Reason",
            "State → Drug type → Issue",
        ],
        horizontal=True,
        key="sankey_flow",
    )

    sankey_data = df_filtered.copy()
    if sankey_data.empty:
        st.warning("Insufficient data to draft a Sankey flow under the current filters.")
    else:
        mfg = _mfg_group_label(sankey_data)
        mol = _molecule_hybrid(sankey_data)
        if flow.startswith("Manufacturer"):
            _render_sankey(
                sankey_data,
                [
                    (mfg, "Manufacturer", 12, "Other manufacturers"),
                    (mol, "Molecule (API)", 12, _MOLECULE_OTHER),
                    (sankey_data['Failure_Category_Primary'], "Issue", 10, "Other"),
                ],
                "Traceability Flow: Manufacturer ➔ Molecule (API) ➔ Issue",
            )
        elif flow.startswith("Indication"):
            _render_sankey(
                sankey_data,
                [
                    (sankey_data['Drug type'], "Indication", 12, "Other"),
                    (mol, "Molecule (API)", 12, _MOLECULE_OTHER),
                    (sankey_data['Failure_Category_Primary'], "Reason", 10, "Other"),
                ],
                "Traceability Flow: Indication (Drug type) ➔ Molecule (API) ➔ Reason",
            )
        else:
            _render_sankey(
                sankey_data,
                [
                    (sankey_data['Mfg_State'], "State", 12, "Other"),
                    (sankey_data['Drug type'], "Drug type", 12, "Other"),
                    (sankey_data['Failure_Category_Primary'], "Issue", 10, "Other"),
                ],
                "Traceability Flow: Hub State ➔ Drug type ➔ Issue",
            )

    # Progressive curation list: the molecules seen in the data but not yet
    # in the curated API catalog (or EXTRA_CURATED_APIS). Computed over the
    # full dataset (not the filtered view) so the candidate list is stable
    # and complete. Promote an entry by adding it to EXTRA_CURATED_APIS in
    # shared/gmp_knowledge.py — match_molecule then recognises it on the next
    # run and it leaves this fallback list.
    fb = _fallback_molecules(df_raw)
    with st.expander(
        f"Molecules to curate ({len(fb)} not yet in the curated API list)", expanded=False
    ):
        st.caption(
            "These active-ingredient groupings (product-ontology keys) appear "
            "in the data but match no curated API, so the molecule layer falls "
            "back to the ontology key for them. To promote one, add it to "
            "`EXTRA_CURATED_APIS` in `shared/gmp_knowledge.py` "
            "(`\"<token>\": \"<display label>\"`). Ranked by alert count."
        )
        if fb.empty:
            st.info("Every flagged product already maps to a curated API — no fallbacks.")
        else:
            st.dataframe(
                fb.head(50).rename_axis("Molecule (ontology key)").reset_index(name="Alerts"),
                use_container_width=True, hide_index=True,
            )

# -----------------------------------------------------------------------------
# TAB 4: LEDGER SEARCH AND EXPORT MANAGEMENT
# -----------------------------------------------------------------------------
with tab4:
    st.header("Searchable Data Ledger & Custom Sorting Engine")
    st.markdown("Interact directly with the structured granular audit rows matching active filter selections.")
    
    # Columns selector configuration
    # Build the full options list from the actual df_raw columns plus every
    # derived column the loader/preprocessor may have produced. We intersect
    # the default list against this set so a schema rename (e.g. 'Source' ->
    # 'source') can't crash the page.
    _derived_cols = [
        # derived name columns
        'Product_Name_Norm', 'Product_Name_Canonical', 'Product_Ontology_Key',
        # derived classification columns
        'Form type', 'Form', 'Drug type',
        'Failure_Category', 'Failure_Category_Primary', 'Is_Dissolution',
        # derived temporal columns
        'Parsed_Date',
        # derived location + company ontology columns
        'Mfg_Company', 'Mfg_Company_Canonical', 'Mfg_Ontology_Key',
        'Mfg_City', 'Mfg_State', 'Mfg_Website',
        # derived regulatory research columns
        'Scientific context research', 'Regulatory guidelines research',
    ]
    _all_options = list(dict.fromkeys(list(df_raw.columns) + _derived_cols))
    _desired_default = [
        # raw source columns
        'index',
        'Name of Product',
        'Batch No',
        'Manufactured By',
        'NSQ Result',
        'Reporting Source',
        'Reporting by Lab/State',
        'Reporting Month & Year',
        'source',
        # derived name columns (raw -> normalized -> canonical -> ontology key)
        'Product_Name_Norm',
        'Product_Name_Canonical',
        'Product_Ontology_Key',
        # derived classification columns
        'Form type',
        'Form',
        'Drug type',
        'Failure_Category',
        'Failure_Category_Primary',
        'Is_Dissolution',
        # derived temporal columns
        'Parsed_Date',
        # derived location + company ontology columns
        'Mfg_Company',
        'Mfg_Company_Canonical',
        'Mfg_Ontology_Key',
        'Mfg_City',
        'Mfg_State',
        'Mfg_Website',
        # derived regulatory research columns
        'Scientific context research',
        'Regulatory guidelines research',
    ]
    _safe_default = [c for c in _desired_default if c in _all_options]

    visible_cols = st.multiselect(
        "Modify Ledger Data Field Column Views:",
        options=_all_options,
        default=_safe_default,
    )
    
    # Sorting controls row
    sort_col = st.selectbox("Assign Primary Target Sort Vector:", options=["None"] + visible_cols)
    sort_order = st.radio("Sorting Direction Parameter:", ["Ascending", "Descending"], horizontal=True)
    
    display_ledger = df_filtered[visible_cols].copy()
    
    if sort_col != "None":
        display_ledger = display_ledger.sort_values(by=sort_col, ascending=(sort_order == "Ascending"))
        
    st.dataframe(display_ledger, use_container_width=True, hide_index=True)
    
    # Download Button utilities
    csv_bytes = display_ledger.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Export Screened Data Subset to CSV Format",
        data=csv_bytes,
        file_name="CDSCO_Screened_Dissolution_Subset.csv",
        mime="text/csv"
    )

# -----------------------------------------------------------------------------
# TAB 5: PRODUCT → MANUFACTURER INVESTIGATION
# -----------------------------------------------------------------------------
# Search a product name (fuzzy match) → list manufacturers that have
# faced NSQ issues with it → drill into one manufacturer to see every
# NSQ alert they've had with that product, plus a chronological
# timeline of failures.
#
# Uses df_raw (full dataset) deliberately — the user is investigating
# the product's history, not the currently filtered view.
with tab5:
    st.header("Product → Manufacturer Investigation")
    mode = st.radio(
        "Investigation entry:",
        ["By product", "By manufacturer"],
        horizontal=True,
        key="inv_mode",
        help="By product: search a product, see which manufacturers had issues "
             "with it. By manufacturer: start from major manufacturers, drill "
             "into one's full history, GMP standards, causes and mitigation.",
    )
    if mode == "By product":
        _render_product_investigation(df_raw)
    else:
        _render_manufacturer_investigation(df_raw)