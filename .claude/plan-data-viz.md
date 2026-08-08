# Comprehensive Data-Visualization Plan

## Objective
Replace uninformative charts, add missed visualization opportunities, and establish a coherent scientific chart vocabulary for every statistic and computation in the CDMO intelligence engine.

## Guiding principles
1. **Every 0–100 score gets a visual scale.** A number out of 100 is a completion/proportion and should be shown as a gauge, bullet, ring, or radial bar — never just a big number.
2. **Scatter plots must encode a decision.** If two axes are only weakly related (e.g. LOE horizon vs. export markets), replace them with a quadrant chart or decompose into ranked bars.
3. **Multi-dimensional comparisons use small multiples or nested rings.** Four-pillar profiles, customer-fit dimensions, and GMP pillar readiness are naturally shown with nested rings, radar, or bullet arrays.
4. **Categorical breakdowns use ordered bars or dot plots.** Molecule rankings, geography eligibility, and roadmap phase durations are best shown as horizontal bars sorted by magnitude.
5. **All new charts reuse the shared helpers in `simulator/intelligence/ui_components.py`.** No one-off Plotly code inside pages.
6. **No decorative color.** Use the Okabe-Ito palette for risk, section, and semantic meaning only.

---

## 1. Current chart audit

| Page | Current chart / metric | Problem | Proposed replacement |
|------|------------------------|---------|------------------------|
| Patent Radar | `LOE horizon vs. export-eligible market count` scatter | Weak relationship; color = LOE days is redundant with x-axis; no actionable signal. | **Patent attractiveness bubble chart**: x = years to LOE, y = FTO risk (ordinal), size = peak sales, color = therapeutic cluster. Adds a "patent window" reference band (3–5 yr sweet spot). |
| Patent Radar | Score table after shortlist | 4 pillar scores as plain dataframe. | **Horizontal bullet bars** for Patent / Regulatory / Demand / Plant Fit with target = 80. |
| Demand Radar | `Demand heat vs. LOE horizon` scatter | `demand_heat` is a synthetic sum; axes are weakly coupled; no clear decision. | **Decomposed demand bar chart**: one ordered bar per molecule showing the 5 demand components (prevalence, trend, pipeline, cluster premium, momentum) as a stacked bar normalized to 100. |
| Demand Radar | Four-pillar score table | Plain dataframe of 4 scores + total. | **Nested multi-ring radial bar chart** for the 4 pillar scores + **bullet bar** for total. |
| Plant Match | 5 metric tiles + radar chart | Radar chart overlaps labels and is hard to read for 4 dimensions; decision rationale is text-only. | **Nested multi-ring radial bar chart** for 4 pillar scores (replaces radar). **Capability gap matrix** for plant vs. molecule required capabilities. |
| Plant Match | Plant capability / approved forms dataframes | Dense tables with no visual hierarchy. | **Horizontal dot plot** of matched vs. missing required capabilities grouped by molecule class. |
| Plant Readiness | Complexity scores as 4 metric tiles | No relative scale or target. | **Bullet charts** for Process / Analytical / Biologic complexity with scale 0–10 and modality benchmarks. |
| Plant Readiness | Customer fit scores as 4 metric tiles | Same issue: no visual scale. | **Nested multi-ring radial bar chart** for Infrastructure / Talent / Certifications / GMP Readiness. |
| Plant Readiness | Roadmap as expander list | No timeline view. | **Gantt / phase-duration bar chart** by roadmap phase. |
| Plant Readiness | Four-pillar bar chart at bottom | Fine, but inconsistent with Plant Match. | Keep as **horizontal bullet bars** aligned with Plant Match radial chart. |
| Portfolio | `Top 10 candidates by total score` horizontal bar | Good. | Keep, but add **score-delta annotation** and color by tier. |
| Portfolio | `Demand attractiveness vs. plant fit` scatter | Weak signal; color/size = total score is self-referential. | **Quadrant scatter**: x = plant fit, y = demand, quadrants labeled (e.g. "high demand / low fit"), point color = cluster, size = total score. Add quadrant reference lines at median values. |
| Portfolio | Launch calendar Gantt | Good. | Keep; add **milestone markers** for LOE dates if available. |
| Portfolio | Decision cards use `st.metric` | 4 pillar scores shown as plain numbers. | Add **mini radial bar** or **sparkline bullet** inside each card. |
| Regulatory Passport | No charts at all | Missed opportunities for monographs, geography, exclusivity. | **Monograph availability donut** (3 monographs). **Export-eligibility horizontal bar** by country. **Exclusivity timeline** if dates exist. **Regulatory clarity gauge**. |
| Product Catalog | No charts | 8 oncology molecules shown as cards. | Add a **portfolio-at-a-glance horizontal bar** of total CDMO score for the 8 molecules (no plant selected = average across default plants). |

---

## 2. New chart components to add in `ui_components.py`

### `scientific_bullet_chart(df, label_col, value_col, target, max_value, title, source)`
- Horizontal bar from 0 to `max_value`, thin background track, colored bar to `value_col`, vertical marker at `target`.
- Color by value: `< target/2` danger, `< target` warning, `>= target` success.
- Use for: all 0–100 pillar scores, complexity scores.

### `scientific_nested_ring(values: dict[str, float], max_value: float = 100, title: str = "")`
- Concentric rings, one per category. Arc length = value / max_value × 360°.
- Inner ring = first category, outer ring = last category.
- Color per category from a stable palette.
- Use for: 4-pillar score profile, 4-dimension customer fit, 3 monograph coverage.

### `scientific_gauge(value: float, title: str, max_value: float = 100)`
- Half-ring gauge with needle, threshold bands.
- Use for: single headline scores (Total CDMO Score, Regulatory Clarity).

### `scientific_quadrant_scatter(df, x, y, color_col, size_col, x_med, y_med, x_label, y_label, title, source)`
- Scatter with light horizontal/vertical reference lines at medians.
- Quadrant labels in corners.
- Use for: Portfolio demand vs. plant fit, Patent attractiveness bubble chart.

### `scientific_stacked_bar(df, label_col, segments: dict[str, str], title, source)`
- 100%-stacked or absolute-stacked horizontal bars.
- Use for: Demand decomposition, GMP pillar readiness by section.

### `scientific_gap_matrix(required: list[str], available: set[str], sections: dict[str, list[str]])`
- Dot matrix: rows = capabilities, columns = "Required" / "Available". Filled dot = present, empty dot = missing.
- Group rows by capability section.
- Use for: Plant Match capability gaps, Plant Readiness missing capabilities.

### `scientific_phase_gantt(phases: list[dict])`
- Horizontal bar chart with phase durations, cumulative start offsets, optional milestone annotations.
- Use for: Plant Readiness and Portfolio launch calendars.

---

## 3. Per-page implementation plan

### Patent Radar (`patent_radar.py`)
1. Replace the LOE vs. export scatter with a **bubble chart** (new helper or direct Plotly):
   - x: `loe_years`
   - y: FTO risk encoded as ordinal (low=1, medium=2, high=3)
   - size: `market_size_usd_bn` (fallback to 1)
   - color: `therapeutic_area` / cluster
   - Add reference band x=2 to 5 years (sweet-spot rectangle).
2. After shortlist scoring, render **horizontal bullet bars** for the 4 scores.
3. Keep the patent table and add-to-shortlist cards.

### Demand Radar (`demand_radar.py`)
1. Replace `Demand heat vs. LOE horizon` scatter with a **stacked horizontal bar chart** of demand score components:
   - One bar per molecule.
   - Segments: prevalence score, trend score, pipeline score, cluster premium, momentum score.
   - All segments sum to the demand attractiveness score (or show normalized 0–100).
2. After four-pillar evaluation, use the **nested multi-ring radial bar chart** for the 4 pillar scores + a **gauge** for total.
3. Keep the evaluation table but make it secondary to the chart.

### Plant Match (`plant_match.py`)
1. Replace the radar chart with a **nested multi-ring radial bar chart** for Patent / Regulatory / Demand / Plant Fit.
2. Replace the plain-text "Decision rationale" with **bullet bars** for each pillar, with the rationale as caption.
3. Add a **capability gap matrix** below the plant capability overview:
   - Rows: required capabilities for the inferred molecule class.
   - Columns: Required, Available in plant.
4. Keep the 5 metric tiles at the top (or convert Total to a gauge).
5. Keep GMP pillar HTML card.

### Plant Readiness (`plant_readiness.py`)
1. Replace complexity metric tiles with **bullet charts** (Process / Analytical / Biologic on 0–10 scale).
2. Replace customer fit metric tiles with a **nested multi-ring radial bar chart** (Infrastructure / Talent / Certifications / GMP Readiness).
3. Replace roadmap expanders with a **phase-duration Gantt** (keep expander detail optional).
4. Keep GMP pillar HTML card.
5. Four-pillar score: use **horizontal bullet bars** to match Plant Match.

### Portfolio (`portfolio.py`)
1. Keep top-10 bar chart; color bars by `commercial_fit_tier`.
2. Replace `Demand vs. Plant Fit` scatter with a **quadrant scatter** with median reference lines and cluster color.
3. Add a **tier distribution donut** and a **modality distribution bar** in the summary section.
4. Add a **waterfall or stacked bar** showing contribution of each pillar to the total score for the top candidate.
5. Decision cards: add a **mini radial bar** (small ring chart) for the 4 pillar scores inside each card, or 4 small bullet bars.
6. Keep launch-calendar Gantt; add LOE milestone annotations if available.

### Regulatory Passport (`regulatory_passport.py`)
1. Add a **gauge** for Regulatory Clarity score.
2. Add a **donut** for monograph availability (IP / Ph.Eur. / USP).
3. Add a **horizontal bar chart** of export-eligible countries colored by market status.
4. If exclusivity has dates, add a **vertical timeline** (scatter or lollipop).
5. Keep existing passport HTML and geography table.

### Product Catalog (`app.py`)
1. Add a small **horizontal bar chart** at the top of the oncology section showing the 8 molecules ranked by average total CDMO score (computed with a default plant or no plant).
2. Keep the cards with Regulatory / Readiness / Match links.

---

## 4. Data-binding reference

| Chart | Required fields | Source |
|-------|----------------|--------|
| Patent bubble chart | `loe_years`, `fto_risk`, `market_size_usd_bn`, `therapeutic_area` | `list_molecules()` |
| Demand stacked bar | `disease_prevalence_global_millions`, `growth_trend`, `trial_count_phase_3_plus`, `cluster`, `buyer_activity_score`, `market_momentum_score` | `list_demand()` + scorer breakdown |
| Nested ring (4 pillars) | `patent_readiness_score`, `regulatory_clarity_score`, `demand_attractiveness_score`, `plant_fit_score` | `score()` result |
| Bullet bars | Any single 0–100 score or 0–10 complexity score | Score result / complexity |
| Capability gap matrix | `molecule_class`, `capabilities`, `equipment_trains` | Plant full record + molecule complexity |
| Customer-fit ring | `infrastructure_fit_score`, `talent_fit_score`, `certification_fit_score`, `gmp_readiness_score` | `get_plant_fit_summary()` |
| Roadmap Gantt | `phases[].title`, `phases[].estimated_duration_months` | `get_molecule_roadmap()` |
| Portfolio quadrant | `plant_fit_score`, `demand_attractiveness_score`, `total_score`, `cluster` | Portfolio snapshot entries |
| Portfolio tier donut | `commercial_fit_tier` counts | Portfolio summary |
| Regulatory donut | `ip_2026_monograph`, `ph_eur_monograph`, `usp_monograph` | `get_molecule_regulatory()` |
| Regulatory geo bar | `country_code`, `market_status` | `get_molecule_geo()` |

---

## 5. Status (updated after implementation)
All chart replacements and helper components are implemented.  A few items deviated slightly from the original plan to keep the UI fast and the code maintainable:
- Portfolio “waterfall for top candidate” was skipped; the existing top-10 bar and mini rings in decision cards already surface per-pillar contribution.
- Regulatory Passport exclusivity timeline was skipped because seed exclusivity data rarely has usable dates; the geo bar and gauge/donut cover the missed opportunity.
- Product Catalog bar uses average total score across available plants rather than a default plant, which is more informative.

## 6. Success metrics / definition of done
- [x] No page shows a plain `st.metric` or `st.dataframe` for a 0–100 score where a bullet/gauge/ring would be clearer.
- [x] Patent Radar and Demand Radar no longer use weak scatter axes; they show decision-oriented charts.
- [x] Plant Match uses a nested multi-ring radial bar chart for the 4 pillar scores.
- [x] Plant Readiness uses bullet charts for complexity and a nested ring for customer fit.
- [x] Portfolio uses a quadrant scatter with reference lines and a tier distribution donut.
- [x] Regulatory Passport has at least 3 charts (gauge + donut + geo bar).
- [x] All new charts are rendered through shared helpers in `ui_components.py`.
- [x] `py_compile` passes for every modified file.
- [x] Docker Compose smoke test renders every intelligence page without chart errors (`streamlit.testing.v1.AppTest` over `/app/app.py`, switching `active_tab` across all tabs).
- [x] `README.md` documents the new chart vocabulary.
- [x] GMP pillar symbols and Plant Builder selectors use monochrome geometric/bioicon markers; remaining `⚠` / `✓` glyphs are reserved for warning and confirmation states only.

---

## 7. Chart vocabulary reference (for README)
All new charts live in `simulator/intelligence/ui_components.py` and use the Okabe-Ito colorblind-safe palette from `simulator/intelligence/palette.py`.

| Helper | Purpose | Used in |
|--------|---------|---------|
| `scientific_bullet_chart` | 0–100 (or 0–10) scores shown against a target line with color-coded thresholds. | Plant Match, Plant Readiness, Patent Radar, Demand Radar |
| `scientific_nested_ring` | Concentric 0–100 rings for multi-dimensional profiles; arc length = completion. | Plant Match, Plant Readiness, Demand Radar, Portfolio cards, Regulatory Passport monographs |
| `scientific_gauge` | Half-ring gauge for a single headline score. | Demand Radar, Regulatory Passport, Product Catalog |
| `scientific_quadrant_scatter` | 2-D decision scatter with median reference lines and cluster color. | Portfolio |
| `scientific_stacked_bar` | Decomposes a synthetic score into additive components. | Demand Radar |
| `scientific_bubble_chart` | Encodes LOE horizon × FTO risk × market size × therapeutic area. | Patent Radar |
| `scientific_gap_matrix` | Heat-coded matrix of molecule-required vs. plant-available capabilities. | Plant Match |
| `scientific_phase_gantt` | Horizontal phase timeline with milestones and cumulative offsets. | Plant Readiness, Portfolio |

---

## 8. Suggested implementation order (completed)
1. Add new chart helpers to `ui_components.py` (bullet, nested ring, gauge, quadrant scatter, gap matrix, phase Gantt).
2. Update Plant Match first (highest-impact: replaces radar + adds gap matrix).
3. Update Plant Readiness (complexity bullets + customer-fit ring + roadmap Gantt).
4. Update Demand Radar (stacked demand bar + nested ring for evaluation).
5. Update Patent Radar (bubble chart + bullet bars after shortlist).
6. Update Portfolio (quadrant scatter + tier donut + mini rings in cards).
7. Update Regulatory Passport (gauge + donut + geo bar).
8. Update Product Catalog (overview bar chart).
9. Compile-check and run smoke test.
10. Update `README.md` with the chart vocabulary reference.
