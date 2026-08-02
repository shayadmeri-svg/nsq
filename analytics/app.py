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
)
from data_loader import (  # noqa: E402
    load_and_preprocess_data,
    fuzzy_search_products,
)
from landing import render_landing_page  # noqa: E402

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
    # raw company name).
    mfg_df = matched_rows.copy()
    mfg_df['__mfg'] = mfg_df['Mfg_Company_Canonical'].fillna('').where(
        mfg_df['Mfg_Company_Canonical'].fillna('') != '',
        mfg_df['Manufactured By'].fillna('').astype(str).str.split(',').str[0].str.strip()
    )
    # Drop empty/Unknown placeholders so the table is informative.
    mfg_df = mfg_df[mfg_df['__mfg'].fillna('') != '']
    mfg_summary = (
        mfg_df.groupby('__mfg')
              .agg(
                  alerts=('Name of Product', 'size'),
                  products=('Name of Product', 'nunique'),
                  first_seen=('Reporting Month & Year', 'min'),
                  last_seen=('Reporting Month & Year', 'max'),
                  cities=('Mfg_City', lambda s: sorted(set(x for x in s if x))),
              )
              .reset_index()
              .rename(columns={'__mfg': 'Manufacturer'})
              .sort_values(['alerts', 'Manufacturer'], ascending=[False, True])
    )
    st.dataframe(mfg_summary, use_container_width=True, hide_index=True)

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
    alert_view = drill[alert_cols].sort_values(
        ['Reporting Month & Year', 'Name of Product'], na_position='last'
    )
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

    # Aggregate by month AND by primary category for a stacked view.
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
    )
    fig.update_layout(barmode='stack', legend_title='Failure Category')
    st.plotly_chart(fig, use_container_width=True)


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

# Map dataset state names to GeoJSON NAME_1 values
GEOJSON_NAME_MAP = {
    'Odisha': 'Orissa',
    'Uttarakhand': 'Uttaranchal',
    'Andaman and Nicobar': 'Andaman and Nicobar',
    'Andhra Pradesh': 'Andhra Pradesh',
    'Arunachal Pradesh': None,  # not in dataset
    'Chhattisgarh': None,
    'Delhi': None,
    'Jharkhand': None,
    'Lakshadweep': None,
    'Manipur': None,
    'Meghalaya': None,
    'Mizoram': None,
    'Nagaland': None,
    'Tripura': None,
}

def to_geojson_name(state):
    if state in GEOJSON_NAME_MAP:
        return GEOJSON_NAME_MAP[state]
    return state if state else None

# -----------------------------------------------------------------------------
# 3. HOME / DASHBOARD VIEW SWITCHER
# -----------------------------------------------------------------------------
if "nsq_view" not in st.session_state:
    st.session_state["nsq_view"] = "home"

if st.session_state["nsq_view"] == "home":
    with st.sidebar:
        st.title("🗺️ NSQ Analytics")
        st.caption("Animated home page")
        if st.button("🔬 Open Dashboard", use_container_width=True):
            st.session_state["nsq_view"] = "dashboard"
            st.rerun()
    render_landing_page()
    st.stop()

# When in dashboard mode, offer a way back to the animated home page.
if st.sidebar.button("🏠 Back to home"):
    st.session_state["nsq_view"] = "home"
    st.rerun()

try:
    df_raw = load_and_preprocess_data()
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

# -----------------------------------------------------------------------------
# 4. SIDEBAR CONTROLS & FILTERING
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
    
    c_left, c_right = st.columns(2)
    
    with c_left:
        st.subheader("Temporal Timeline Trend")
        # Line Chart over time
        trend_df = df_filtered.dropna(subset=['Parsed_Date']).copy()
        if not trend_df.empty:
            trend_grouped = trend_df.groupby([trend_df['Parsed_Date'].dt.to_period('M'), 'Is_Dissolution']).size().reset_index(name='Alert Count')
            trend_grouped['Parsed_Date'] = trend_grouped['Parsed_Date'].dt.to_timestamp()
            trend_grouped['Alert Type'] = trend_grouped['Is_Dissolution'].map({True: 'Dissolution Defect', False: 'Other Defect'})
            
            fig_line = px.line(
                trend_grouped, x='Parsed_Date', y='Alert Count', color='Alert Type',
                labels={'Parsed_Date': 'Reporting Timeline', 'Alert Count': 'Volume of Incidents'},
                title="Monthly Progression of Recorded Drug Defects",
                markers=True
            )
            fig_line.update_layout(legend_title="Defect Category", hovermode="x unified")
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.info("Insufficient chronological date variables detected to parse timeline trends.")

    with c_right:
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
            color='Total Incidents', color_continuous_scale=_SCIENTIFIC_CONTINUOUS
        )
        fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, coloraxis_showscale=False)
        st.plotly_chart(fig_bar, use_container_width=True)

    # Secondary Breakdown split
    st.markdown("---")
    st.subheader("Form Factor Risk Assessments")
    
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        # Form Type Breakdown
        form_counts = df_filtered['Form type'].value_counts().head(12).reset_index()
        form_counts.columns = ['Form Factor', 'Alert Volume']
        fig_form = px.bar(
            form_counts, x='Form Factor', y='Alert Volume',
            labels={'Form Factor': 'Formulation Form Type', 'Alert Volume': 'Alert Count'},
            title="Alert Volume Categorized by Dosage Form Factors",
            color='Alert Volume', color_continuous_scale=_SCIENTIFIC_CONTINUOUS
        )
        st.plotly_chart(fig_form, use_container_width=True)

    with col_f2:
        # Failure Category Distribution — replaces the previous "Recall
        # Class" pie (which was always 100% "Unclassified" because the
        # CSV doesn't carry recall-class data). Now uses the harmonized
        # Failure_Category_Primary derived from each row's NSQ Result.
        cat_counts = df_filtered['Failure_Category_Primary'].value_counts().reset_index()
        cat_counts.columns = ['Failure Category', 'Alert Volume']
        fig_pie = px.pie(
            cat_counts, values='Alert Volume', names='Failure Category',
            title="Failure Category Breakdown (Harmonized from NSQ Result)",
            color_discrete_sequence=_SCIENTIFIC_COLORWAY
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 2: GEOGRAPHIC & HEATMAPS
# -----------------------------------------------------------------------------
with tab2:
    st.header("Geographical Vulnerabilities & Inter-Variable Heatmaps")

    # 1. Choropleth Map of India
    st.subheader("Incident Origins — Indian Political Map")
    state_df = df_filtered['Mfg_State'].value_counts().reset_index()
    state_df.columns = ['Indian State / Origin Region', 'Recorded Anomalies']
    # Map dataset state names to GeoJSON NAME_1 values
    state_df['Geo_Name'] = state_df['Indian State / Origin Region'].apply(to_geojson_name)
    state_df = state_df.dropna(subset=['Geo_Name'])

    try:
        india_geo = load_india_geojson()
        if india_geo is None:
            raise FileNotFoundError("no geojson available from Redis or local file")
        fig_geo = px.choropleth(
            state_df,
            geojson=india_geo,
            locations='Geo_Name',
            featureidkey='properties.NAME_1',
            color='Recorded Anomalies',
            color_continuous_scale='Reds',
            range_color=(0, state_df['Recorded Anomalies'].max() if len(state_df) else 1),
            labels={'Recorded Anomalies': 'Total Incident Frequency', 'Geo_Name': 'State'},
            title="Manufacturing-Origin Anomalies Mapped to Indian States",
            hover_name='Indian State / Origin Region',
        )
        fig_geo.update_geos(
            fitbounds="locations",
            visible=False,
            showcountries=False,
            showcoastlines=False,
            showland=False,
            showocean=False,
        )
        fig_geo.update_layout(margin={"r": 0, "t": 50, "l": 0, "b": 0}, height=600)
        st.plotly_chart(fig_geo, use_container_width=True)
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
            state_df.sort_values('Recorded Anomalies', ascending=False),
            x='Indian State / Origin Region', y='Recorded Anomalies',
            color='Recorded Anomalies', color_continuous_scale='Reds',
            labels={'Recorded Anomalies': 'Total Incident Frequency'},
            title="Incident Origins — Sorted Counts"
        )
        st.plotly_chart(fig_geo_bar, use_container_width=True)
    
    st.markdown("---")
    
    # 2. Variable Cross-Tabulation Pseudo Correlation Heatmap
    st.subheader("Cross-Tabulation Risk Correlation Matrix Heatmap")
    st.markdown("Identifies dense systemic risk cross-overs between specific **Form Factors** and **Testing Labs / Sourcing Jurisdictions**.")
    
    # Pivot calculation
    top_forms = df_filtered['Form type'].value_counts().head(10).index.tolist()
    top_labs = df_filtered['Reporting by Lab/State'].value_counts().head(10).index.tolist()
    
    df_pivot_subset = df_filtered[
        df_filtered['Form type'].isin(top_forms) & 
        df_filtered['Reporting by Lab/State'].isin(top_labs)
    ]
    
    if not df_pivot_subset.empty:
        cross_tab = pd.crosstab(df_pivot_subset['Form type'], df_pivot_subset['Reporting by Lab/State'])
        
        fig_heatmap = px.imshow(
            cross_tab,
            labels=dict(x="Testing Lab Branch", y="Formulation Style", color="Incident Density"),
            x=cross_tab.columns,
            y=cross_tab.index,
            color_continuous_scale='YlOrRd',
            title="Risk Co-Occurrence (Top 10 Form Factors vs Top 10 CDSCO Testing Entities)"
        )
        fig_heatmap.update_xaxes(side="bottom", tickangle=45)
        st.plotly_chart(fig_heatmap, use_container_width=True)
    else:
        st.info("Please expand filter parameters to populate the Correlation Matrix Heatmap.")

# -----------------------------------------------------------------------------
# TAB 3: SANKEY GRAPH COUPLING
# -----------------------------------------------------------------------------
with tab3:
    st.header("Sankey Vulnerability Chain Flow Topology")
    st.markdown("Traces how operational breakdowns map from **Origin State/Hubs** $\\rightarrow$ **Drug Categories** $\\rightarrow$ **Failure Categorizations**.")
    
    # Aggregate data loops to format connections dynamically.
    # The right-most level now uses the harmonized primary failure
    # category (one node per Failure_Category_Primary, e.g. "Dissolution",
    # "Assay / Content", "Sterility / Microbial", ...) instead of the
    # boolean Dissolution/Other split — gives much more actionable
    # flow insight.
    sankey_data = df_filtered.dropna(subset=['Mfg_State', 'Drug type', 'Failure_Category_Primary']).copy()
    # Cap string sizes for aesthetic balance
    sankey_data['Drug_Type_Short'] = sankey_data['Drug type'].apply(lambda x: str(x)[:25] + '...' if len(str(x)) > 25 else str(x))

    if len(sankey_data) > 0:
        # Create Nodes Indexing mapping list
        level0 = sankey_data['Mfg_State'].unique().tolist()
        level1 = sankey_data['Drug_Type_Short'].unique().tolist()
        level2 = sankey_data['Failure_Category_Primary'].unique().tolist()
        
        all_nodes = level0 + level1 + level2
        node_map = {node: idx for idx, node in enumerate(all_nodes)}
        
        sources = []
        targets = []
        values = []
        
        # Stream 1: State to Drug Type
        pair1 = sankey_data.groupby(['Mfg_State', 'Drug_Type_Short']).size().reset_index(name='count')
        for _, row in pair1.iterrows():
            sources.append(node_map[row['Mfg_State']])
            targets.append(node_map[row['Drug_Type_Short']])
            values.append(row['count'])
            
        # Stream 2: Drug Type to Failure Status
        pair2 = sankey_data.groupby(['Drug_Type_Short', 'Failure_Category_Primary']).size().reset_index(name='count')
        for _, row in pair2.iterrows():
            sources.append(node_map[row['Drug_Type_Short']])
            targets.append(node_map[row['Failure_Category_Primary']])
            values.append(row['count'])
            
        fig_sankey = go.Figure(data=[go.Sankey(
            node=dict(
                pad=15, thickness=20,
                line=dict(color="black", width=0.5),
                label=all_nodes,
                color="cornflowerblue"
            ),
            link=dict(
                source=sources, target=targets, value=values,
                color="rgba(200, 200, 200, 0.4)"
            )
        )])
        
        fig_sankey.update_layout(title_text="Traceability Flow: Hub State ➔ Therapeutic Category ➔ Dissolution Condition Status Map", font_size=11)
        st.plotly_chart(fig_sankey, use_container_width=True)
    else:
        st.warning("Insufficient data combinations available to draft an integrated Sankey Trace Flow Topology.")

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
        'Form type', 'Form', 'Indication', 'Drug type', 'Recall Class',
        'Failure_Category', 'Failure_Category_Primary', 'Is_Dissolution',
        # derived temporal columns
        'Parsed_Date', 'Year_Month_Str',
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
        'Indication',
        'Drug type',
        'Recall Class',
        'Failure_Category',
        'Failure_Category_Primary',
        'Is_Dissolution',
        # derived temporal columns
        'Parsed_Date',
        'Year_Month_Str',
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
    _render_product_investigation(df_raw)