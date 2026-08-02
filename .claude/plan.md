# Plan: Switch UI/Charts to a Scientific Color Palette

## Goal
Replace the current monochrome slate palette with a colorblind-safe, publication-ready **Okabe-Ito** scientific palette across the NSQ simulator and analytics apps.

## Chosen palette
- Primary / links / active states: `#0072B2` (blue)
- Success / completed / grade A/B: `#009E73` (bluish green)
- Warning / medium risk / adjacent: `#E69F00` (orange)
- Danger / high risk / errors / grade D/F: `#D55E00` (vermilion)
- Info / low emphasis / sky: `#56B4E9` (sky blue)
- Muted / disabled / borders: `#999999` (grey)
- Strategic / highlight: `#CC79A7` (reddish purple)
- Categorical chart colorway: Okabe-Ito sequence
- Backgrounds: warm scientific off-whites (`#fafafa`, `#ffffff`)
- Text: near-black `#1a1a1a` instead of slate-blue

## Approach
1. **Centralize colors** — create `simulator/intelligence/palette.py` exporting:
   - `THEME` dict for CSS / inline styles
   - `CHART_COLORWAY` list for Plotly
   - `RISK_COLORS`, `CLUSTER_COLORS`, `GRADE_COLORS`, `TIER_COLORS` helpers
   - `CONTINUOUS_SCALE` for heatmaps / bars

2. **Update shared UI components** (`simulator/intelligence/ui_components.py`):
   - Rewrite `MONOCHROME_CSS` to use the new theme (backgrounds, text, borders, active/hover states, stepper, metric tiles, mock badge).
   - Update Plotly helpers (`_slate_layout`, `scientific_bar_chart`, `scientific_scatter`, `scientific_box_or_strip`) to use the chart colorway, new text colors, and the continuous scale.
   - Update `tier_badge`, `inline_warning`, `inline_info` defaults.

3. **Update simulator root styling** (`simulator/app.py`):
   - Replace hard-coded slate colors in `CUSTOM_CSS` (header, cards, grade badges, buttons, sliders) with palette references.

4. **Update simulator page files**:
   - `demand_radar.py`: therapeutic cluster colors → Okabe-Ito mapping.
   - `portfolio.py`: cluster colors and Gantt chart marker colors.
   - `patent_radar.py`: risk tier colors.
   - `plant_match.py`: radar chart line/fill colors.
   - `regulatory_passport.py`: alert blocks, borders, backgrounds.

5. **Update analytics app** (`analytics/app.py`):
   - Replace metric-card red accent and hard-coded metric colors with scientific palette.
   - Swap `color_continuous_scale='Reds'/'Blues'` and `color_discrete_sequence=px.colors.qualitative.Pastel` for the scientific colorway / scale.

6. **Verify**:
   - Run a quick grep for old slate hex codes (`#0f172a`, `#64748b`, `#94a3b8`, `#e2e8f0`) to confirm no orphaned styles remain.
   - Start the Streamlit apps (or at least import-check) to catch syntax errors.

## Files touched
- `simulator/intelligence/palette.py` (new)
- `simulator/intelligence/ui_components.py`
- `simulator/app.py`
- `simulator/intelligence/pages/demand_radar.py`
- `simulator/intelligence/pages/portfolio.py`
- `simulator/intelligence/pages/patent_radar.py`
- `simulator/intelligence/pages/plant_match.py`
- `simulator/intelligence/pages/regulatory_passport.py`
- `analytics/app.py`

## Expected result
Both apps share a consistent, accessible scientific color language: colorblind-friendly categorical colors, reduced blue-ish slate tints, warm neutrals, and publication-ready chart defaults.
