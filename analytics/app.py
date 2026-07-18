import os
import sys

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import json
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "shared"))
from nsq_redis import load_dataframe as load_redis_dataframe  # noqa: E402
from nsq_redis import load_geojson as load_redis_geojson  # noqa: E402

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
st.markdown("""
    <style>
    .metric-card {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #ff4b4b;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .metric-title { font-size: 14px; color: #6c757d; margin-bottom: 5px; }
    .metric-value { font-size: 24px; font-weight: bold; color: #1c2d42; }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. DATA LOADING & ENRICHMENT
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_and_preprocess_data():
    # Load dataset from Redis (populated by redis-loader/load_nsq_redis.py)
    df = load_redis_dataframe()

    # 1. Derive Failure reason from NSQ Result if missing
    if 'Failure reason' not in df.columns:
        df['Failure reason'] = df['NSQ Result'].fillna('')

    # 2. Derive Form type from product name if missing
    if 'Form type' not in df.columns:
        product_text = df['Name of Product'].fillna('').astype(str)
        def infer_form(text):
            t = text.lower()
            if 'tablet' in t: return 'Tablet'
            if 'capsule' in t: return 'Capsule'
            if 'syrup' in t or 'suspension' in t: return 'Syrup/Suspension'
            if 'injection' in t or 'injectable' in t: return 'Injection'
            if 'ointment' in t or 'cream' in t or 'gel' in t: return 'Ointment/Cream'
            if 'drops' in t: return 'Drops'
            if 'powder' in t or 'granules' in t: return 'Powder/Granules'
            return 'Other'
        df['Form type'] = product_text.apply(infer_form)

    # 3. Derive Drug type (therapeutic category) heuristically if missing
    if 'Drug type' not in df.columns:
        def infer_drug_type(text):
            t = str(text).lower()
            antibiotics = ['amoxycillin', 'amoxicillin', 'ciprofloxacin', 'ofloxacin', 'azithromycin', 'cefixime', 'cephalexin', 'metronidazole', 'doxycycline']
            analgesics = ['paracetamol', 'diclofenac', 'ibuprofen', 'aspirin', 'tramadol', 'aceclofenac']
            vitamins = ['vitamin', 'multivitamin', 'iron', 'folic', 'calcium', 'zinc']
            cardiac = ['amlodipine', 'telmisartan', 'losartan', 'atenolol', 'metoprolol', 'ramipril', 'atorvastatin']
            antidiabetic = ['metformin', 'glimepiride', 'glipizide', 'insulin', 'vildagliptin']
            antacid = ['omeprazole', 'pantoprazole', 'rabeprazole', 'ranitidine', 'esomeprazole']
            respiratory = ['salbutamol', 'ambroxol', 'guaiphenesin', 'terbutaline', 'dextromethorphan', 'phenylephrine', 'chlorpheniramine', 'montelukast', 'levocetirizine']
            if any(k in t for k in antibiotics): return 'Antibiotic'
            if any(k in t for k in analgesics): return 'Analgesic/Antipyretic'
            if any(k in t for k in vitamins): return 'Vitamin/Nutritional'
            if any(k in t for k in cardiac): return 'Cardiovascular'
            if any(k in t for k in antidiabetic): return 'Antidiabetic'
            if any(k in t for k in antacid): return 'Antacid/Antiulcer'
            if any(k in t for k in respiratory): return 'Respiratory'
            return 'Other / Unclassified'
        df['Drug type'] = df['Name of Product'].apply(infer_drug_type)

    # 4. Recall Class is absent in this CSV — provide a placeholder
    if 'Recall Class' not in df.columns:
        df['Recall Class'] = 'Unclassified'

    # 1. Identify Dissolution Failures
    # Checks failure reasons or general text rows for "dissolution"
    text_search_space = df[['Failure reason', 'NSQ Result', 'Name of Product']].fillna('').astype(str)
    if text_search_space.empty:
        # pandas' .apply(axis=1) on a zero-row frame can't infer a Series
        # return shape and sometimes yields a DataFrame instead, which
        # breaks the column assignment below. Short-circuit explicitly.
        df['Is_Dissolution'] = pd.Series(dtype=bool)
    else:
        df['Is_Dissolution'] = text_search_space.apply(
            lambda row: row.str.contains('dissolution|Dissolution', case=False).any(), axis=1
        )

    # 2. Parse Date Features
    df['Parsed_Date'] = pd.to_datetime(df['Reporting Month & Year'], format='%b-%Y', errors='coerce')
    # Fallback sorting metric
    df['Year_Month_Str'] = df['Reporting Month & Year'].fillna('Unknown')

    # 3. Extract Indian State from 'Manufactured By'
    def extract_state(text):
        if pd.isna(text):
            return 'Unknown'
        text = str(text)
        # Main manufacturing hubs found in CDSCO lists
        states = [
            'Gujarat', 'Himachal Pradesh', 'Uttarakhand', 'Sikkim', 'Madhya Pradesh',
            'Maharashtra', 'Punjab', 'Haryana', 'Andhra Pradesh', 'Telangana',
            'Tamil Nadu', 'Karnataka', 'Kerala', 'Goa', 'Rajasthan', 'Uttar Pradesh',
            'Bihar', 'West Bengal', 'Odisha', 'Assam', 'Jammu and Kashmir', 'Jammu & Kashmir',
            'Chandigarh', 'Puducherry'
        ]
        for s in states:
            if re.search(r'\b' + re.escape(s) + r'\b', text, re.IGNORECASE):
                return s
        # City -> state fallback map for major pharma manufacturing hubs
        city_state_map = {
            # Uttar Pradesh
            'noida': 'Uttar Pradesh', 'greater noida': 'Uttar Pradesh', 'lucknow': 'Uttar Pradesh',
            'kanpur': 'Uttar Pradesh', 'ghaziabad': 'Uttar Pradesh', 'meerut': 'Uttar Pradesh',
            'agra': 'Uttar Pradesh', 'varanasi': 'Uttar Pradesh', 'prayagraj': 'Uttar Pradesh',
            'allahabad': 'Uttar Pradesh', 'saharanpur': 'Uttar Pradesh', 'manglour': 'Uttar Pradesh',
            'gautam budh nagar': 'Uttar Pradesh', 'gautam buddha nagar': 'Uttar Pradesh',
            # Uttarakhand
            'haridwar': 'Uttarakhand', 'roorkee': 'Uttarakhand', 'dehradun': 'Uttarakhand',
            'bhagwanpur': 'Uttarakhand', 'rudrapur': 'Uttarakhand', 'kashipur': 'Uttarakhand',
            'sidcul': 'Uttarakhand',
            # Himachal Pradesh
            'baddi': 'Himachal Pradesh', 'solan': 'Himachal Pradesh', 'nahan': 'Himachal Pradesh',
            'sirmaur': 'Himachal Pradesh', 'kala amb': 'Himachal Pradesh', 'kalujhanda': 'Himachal Pradesh',
            'barotiwala': 'Himachal Pradesh', 'nalagarh': 'Himachal Pradesh', 'parwanoo': 'Himachal Pradesh',
            'kangra': 'Himachal Pradesh', 'una': 'Himachal Pradesh', 'mandi': 'Himachal Pradesh',
            'subathu': 'Himachal Pradesh', 'ghatti': 'Himachal Pradesh', 'raja ka bagh': 'Himachal Pradesh',
            'jharmajri': 'Himachal Pradesh', 'epip': 'Himachal Pradesh',
            # Madhya Pradesh
            'indore': 'Madhya Pradesh', 'bhopal': 'Madhya Pradesh', 'dewas': 'Madhya Pradesh',
            'mandideep': 'Madhya Pradesh', 'pigdamber': 'Madhya Pradesh', 'pithampur': 'Madhya Pradesh',
            'mandleshwar': 'Madhya Pradesh',
            # Maharashtra
            'mumbai': 'Maharashtra', 'pune': 'Maharashtra', 'nashik': 'Maharashtra',
            'aurangabad': 'Maharashtra', 'nagpur': 'Maharashtra', 'tarapur': 'Maharashtra',
            'boisar': 'Maharashtra', 'palghar': 'Maharashtra', 'raigad': 'Maharashtra',
            'thane': 'Maharashtra', 'mahalunge': 'Maharashtra', 'chakan': 'Maharashtra',
            'raigad': 'Maharashtra',
            # Gujarat
            'ahmedabad': 'Gujarat', 'vadodara': 'Gujarat', 'baroda': 'Gujarat',
            'surat': 'Gujarat', 'rajkot': 'Gujarat', 'bhavnagar': 'Gujarat',
            'mehsana': 'Gujarat', 'kadi': 'Gujarat', 'sanand': 'Gujarat',
            'budas': 'Gujarat', 'budasan': 'Gujarat', 'panchmahal': 'Gujarat',
            # Punjab
            'mohali': 'Punjab', 'chandigarh': 'Punjab', 'ludhiana': 'Punjab',
            'amritsar': 'Punjab', 'jalandhar': 'Punjab', 'patiala': 'Punjab',
            'zirakpur': 'Punjab', 'sahnewal': 'Punjab', 'dera bassi': 'Punjab',
            'karnal': 'Haryana',  # karnal is actually in Haryana
            # Haryana
            'gurugram': 'Haryana', 'gurgaon': 'Haryana', 'faridabad': 'Haryana',
            'panipat': 'Haryana', 'karnal': 'Haryana', 'ambala': 'Haryana',
            'manesar': 'Haryana', 'sonipat': 'Haryana', 'bhiwadi': 'Haryana',
            # Karnataka
            'bengaluru': 'Karnataka', 'bangalore': 'Karnataka', 'mysore': 'Karnataka',
            'mysuru': 'Karnataka', 'mangalore': 'Karnataka', 'hubli': 'Karnataka',
            'belgaum': 'Karnataka', 'tumkur': 'Karnataka',
            # Tamil Nadu
            'chennai': 'Tamil Nadu', 'coimbatore': 'Tamil Nadu', 'madurai': 'Tamil Nadu',
            'salem': 'Tamil Nadu', 'trichy': 'Tamil Nadu', 'tiruchirappalli': 'Tamil Nadu',
            'hosur': 'Tamil Nadu', 'chengalpattu': 'Tamil Nadu', 'sriperumbudur': 'Tamil Nadu',
            'vanagaram': 'Tamil Nadu', 'kanniamman nagar': 'Tamil Nadu',
            'puducherry': 'Puducherry', 'pondicherry': 'Puducherry',
            # Telangana
            'hyderabad': 'Telangana', 'secunderabad': 'Telangana', 'warangal': 'Telangana',
            # Andhra Pradesh
            'visakhapatnam': 'Andhra Pradesh', 'vijayawada': 'Andhra Pradesh',
            'guntur': 'Andhra Pradesh', 'nellore': 'Andhra Pradesh',
            # Kerala
            'kochi': 'Kerala', 'cochin': 'Kerala', 'trivandrum': 'Kerala',
            'thiruvananthapuram': 'Kerala', 'kozhikode': 'Kerala', 'calicut': 'Kerala',
            # Rajasthan
            'jaipur': 'Rajasthan', 'jodhpur': 'Rajasthan', 'udaipur': 'Rajasthan',
            'kota': 'Rajasthan', 'bikaner': 'Rajasthan', 'alwar': 'Rajasthan',
            'bhiwadi': 'Rajasthan',
            # West Bengal
            'kolkata': 'West Bengal', 'howrah': 'West Bengal', 'siliguri': 'West Bengal',
            # Odisha
            'bhubaneswar': 'Odisha', 'cuttack': 'Odisha',
            # Bihar
            'patna': 'Bihar', 'gaya': 'Bihar',
            # Assam
            'guwahati': 'Assam', 'dispur': 'Assam',
            # Sikkim
            'gangtok': 'Sikkim',
            # Goa
            'goa': 'Goa', 'panaji': 'Goa', 'margao': 'Goa',
            # Jammu & Kashmir
            'jammu': 'Jammu and Kashmir', 'srinagar': 'Jammu and Kashmir', 'kathua': 'Jammu and Kashmir',
        }
        for city, st in city_state_map.items():
            if re.search(r'\b' + re.escape(city) + r'\b', text, re.IGNORECASE):
                return st
        return 'Other / Outside India'

    df['Mfg_State'] = df['Manufactured By'].apply(extract_state)

    # 4. Harmonize product names for grouping (e.g. "40mg" vs "40 mg", " IP " vs " ip ")
    def normalize_product(name):
        if pd.isna(name):
            return ''
        s = str(name)
        # collapse whitespace
        s = re.sub(r'\s+', ' ', s).strip()
        # insert space between digit and unit letter: 40mg -> 40 mg, 500mg -> 500 mg, 5W -> 5 W
        s = re.sub(r'(\d)([A-Za-z])', r'\1 \2', s)
        # collapse whitespace again after the insert
        s = re.sub(r'\s+', ' ', s).strip()
        # title-case common abbreviation tokens
        tokens = []
        for tok in s.split(' '):
            upper = tok.upper()
            # preserve common pharma abbreviations in uppercase
            if upper in {'IP', 'BP', 'USP', 'NF', 'NFI', 'HCL', 'HBR', 'EC', 'SR', 'IP.', 'BP.', 'W/V', 'W/W', 'V/V', 'MG', 'ML', 'GM', 'MCG', 'IU'}:
                tokens.append(upper.rstrip('.'))
            else:
                tokens.append(tok.capitalize())
        return ' '.join(tokens)

    df['Product_Name_Norm'] = df['Name of Product'].apply(normalize_product)
    return df

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

try:
    df_raw = load_and_preprocess_data()
except Exception as e:
    st.error(f"Error loading CSV file: {e}")
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
        df_filtered['Manufactured By'].str.contains(search_query, case=False, na=False)
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
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Trend & Distribution Analyses", 
    "🗺️ Geographic & Heatmap Matrix", 
    "🔀 Relational Sankey Flows", 
    "📋 Searchable Audit Ledger"
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
        # Horizontal Bar Chart
        top_products = df_filtered['Product_Name_Norm'].value_counts().head(10).reset_index()
        top_products.columns = ['Product Name', 'Total Incidents']
        
        fig_bar = px.bar(
            top_products, x='Total Incidents', y='Product Name', orientation='h',
            labels={'Total Incidents': 'Alert Counts Recorded', 'Product Name': 'Commercial Formulation Name'},
            title="Top 10 Flagged Products within Selected View Filters",
            color='Total Incidents', color_continuous_scale='Reds'
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
            color='Alert Volume', color_continuous_scale='Blues'
        )
        st.plotly_chart(fig_form, use_container_width=True)

    with col_f2:
        # Risk Class Distribution
        recall_counts = df_filtered['Recall Class'].value_counts().reset_index()
        recall_counts.columns = ['Risk Classification', 'Alert Volume']
        fig_pie = px.pie(
            recall_counts, values='Alert Volume', names='Risk Classification',
            title="Risk Risk Mitigation Profile Breakdown (Recall Classification)",
            color_discrete_sequence=px.colors.qualitative.Pastel
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
    
    # Aggregate data loops to format connections dynamically
    sankey_data = df_filtered.dropna(subset=['Mfg_State', 'Drug type', 'Is_Dissolution']).copy()
    sankey_data['Dissolution_Status'] = sankey_data['Is_Dissolution'].map({True: 'Dissolution Failure', False: 'Other Critical Failures'})
    
    # Cap string sizes for aesthetic balance
    sankey_data['Drug_Type_Short'] = sankey_data['Drug type'].apply(lambda x: str(x)[:25] + '...' if len(str(x)) > 25 else str(x))
    
    if len(sankey_data) > 0:
        # Create Nodes Indexing mapping list
        level0 = sankey_data['Mfg_State'].unique().tolist()
        level1 = sankey_data['Drug_Type_Short'].unique().tolist()
        level2 = sankey_data['Dissolution_Status'].unique().tolist()
        
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
        pair2 = sankey_data.groupby(['Drug_Type_Short', 'Dissolution_Status']).size().reset_index(name='count')
        for _, row in pair2.iterrows():
            sources.append(node_map[row['Drug_Type_Short']])
            targets.append(node_map[row['Dissolution_Status']])
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
    visible_cols = st.multiselect(
        "Modify Ledger Data Field Column Views:",
        options=df_raw.columns.tolist() + ['Product_Name_Norm'],
        default=['Name of Product', 'Product_Name_Norm', 'Drug type', 'Form type', 'Failure reason', 'NSQ Result', 'Manufactured By', 'Mfg_State', 'Reporting Month & Year']
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