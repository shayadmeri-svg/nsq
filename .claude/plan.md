# Core GMP Methodological Pillars + 8-Oncology-Molecule Table

## Overall objective
Make the simulator’s manufacturing-intelligence surfaces actionable for complex oncology molecules by grounding every molecule-to-plant comparison in **five Core GMP Methodological Pillars** (Aseptic Processing, HPAPI Containment, Cleaning & Cross-Contamination Prevention, Lifecycle Validation & Tech Transfer, and Packaging & Supply-Chain Integrity). This workstream also seeds and validates an **8-molecule oncology table** so the engine has a coherent, high-value starting portfolio.

> **Dropped concept.** The previous “molecule info side drawer” plan was evaluated and rejected. No drawer code was implemented and it is not part of this workstream.

## Current status

| Area | Status | Evidence |
|------|--------|----------|
| Five-pillar derivation | ✅ Done | `derive_gmp_pillars()` in `engine/shared/intelligence_scorer.py` and `simulator/intelligence/intelligence_scorer.py` implements `aseptic`, `hpapi`, `cleaning`, `lifecycle`, and `packaging`. |
| Capability catalog (7 sections) | ✅ Done | `engine/shared/capability_catalog.py` and `simulator/intelligence/capability_catalog.py` define the same taxonomy: `architectural_hvac`, `biologics_fill_finish`, `hpapi_osd`, `qc_analytical`, `process_utilities`, `automation_digital`, `warehousing_coldchain`. |
| Plant Profile Builder page | ✅ Done | `simulator/intelligence/pages/plant_profile_builder.py` renders a searchable, section-grouped selector and persists a `PlantAsset` via `create_plant()`. |
| Simulator navigation | ✅ Done | `simulator/app.py` adds tab index 7 / feature-card "Plant Builder" and dispatches to `plant_profile_builder.render()`. |
| API surface | ✅ Done | `engine/api_main.py` exposes `GET /plants/capability-taxonomy`, `POST /plants`, and `GET /molecules/{key}/gmp-pillars`. |
| API client | ✅ Done | `simulator/intelligence/api_client.py` has `get_capability_taxonomy()` and `create_plant()`. |
| Pillar rendering on pages | ✅ Done | `render_gmp_pillars()` is used in `plant_match.py`, `plant_readiness.py`, and `regulatory_passport.py`. |
| Oncology seed enrichment | ✅ Done | `redis-loader/enrich_oncology_seeds.py` enriches `patent_seed.json`, `regulatory_seed.json`, and `demand_seed.json` for the 8 oncology molecules. |
| Standalone oncology table JSON | ✅ Done | `data/oncology_molecule_table.json` created and the loader reads from it. |
| README documentation | ✅ Done | README documents the five GMP pillars, Plant Profile Builder, `/plants/capability-taxonomy`, and the oncology table. |
| Product Catalog rename + oncology cards | ✅ Done | `simulator/app.py` renames "NSQ Catalog" → "Product Catalog", surfaces the 8 oncology molecules, and adds jump links to Regulatory Passport, Plant Readiness, and Plant Match. |
| Preselected molecule navigation | ✅ Done | `plant_match.py` and `plant_readiness.py` honor `pending_molecule_key` from the Product Catalog. |

## Remaining work
1. **End-to-end smoke test.** Run `docker compose build && docker compose up`, open each page, verify:
   - Product Catalog shows both NSQ Workbench formulations and the 8 oncology intelligence molecules.
   - Clicking **Regulatory**, **Readiness**, or **Match** on an oncology card jumps to the right page with the molecule preselected (for Readiness/Match).
   - Plant Builder saves a profile and the new plant appears in Plant Match / Plant Readiness.
   - Plant Match, Plant Readiness, and Regulatory Passport show GMP pillar cards for oncology molecules.
   - The 8 oncology molecules score and produce roadmaps without errors.

## Files (current state)

### Created / already exist
- `simulator/intelligence/pages/plant_profile_builder.py` — ✅ implemented.
- `simulator/intelligence/capability_catalog.py` — ✅ implemented.
- `redis-loader/enrich_oncology_seeds.py` — ✅ reads from `data/oncology_molecule_table.json`.
- `data/oncology_molecule_table.json` — ✅ created.

### Modified / already updated
- `simulator/app.py` — ✅ "NSQ Catalog" renamed to "Product Catalog"; oncology molecule cards with Regulatory / Readiness / Match jump links; `_navigate_to_molecule_page()` helper.
- `simulator/intelligence/pages/plant_match.py` — ✅ preselects molecule from `pending_molecule_key`.
- `simulator/intelligence/pages/plant_readiness.py` — ✅ preselects molecule from `pending_molecule_key`.
- `simulator/intelligence/pages/regulatory_passport.py` — ✅ renders triggered GMP pillars.
- `engine/shared/intelligence_scorer.py` / `simulator/intelligence/intelligence_scorer.py` — ✅ five-pillar derivation complete.
- `engine/shared/intelligence_models.py` / `simulator/intelligence/intelligence_models.py` — ✅ `GmpPillar` + `ManufacturingComplexity.gmp_pillars` aligned.
- `engine/api_main.py` — ✅ capability-taxonomy, plant create, and GMP-pillars endpoints live.
- `simulator/intelligence/api_client.py` — ✅ client methods present.
- `README.md` — ✅ pillars, Plant Builder, capability-taxonomy, and oncology table documented.

## Data model
- `GmpPillar` (`engine/shared/intelligence_models.py:269`): `pillar_id`, `title`, `applies`, `rationale`, `key_controls`, `applicable_forms`, `required_capabilities`, `required_certifications`, `risk_signals`.
- Five canonical pillar IDs: `aseptic`, `hpapi`, `cleaning`, `lifecycle`, `packaging`.
- Capability catalog: 7 infrastructure sections (`architectural_hvac`, `biologics_fill_finish`, `hpapi_osd`, `qc_analytical`, `process_utilities`, `automation_digital`, `warehousing_coldchain`).

## UI/UX tone guidelines (recall every session)
The interface targets scientific, regulatory, and manufacturing professionals. It must feel like a precision instrument, not a consumer app.
- **No emoji in functional UI.** Use only the shared `bioicon` SVG library in `simulator/intelligence/ui_components.py`.
- **Bioicon defaults:** plant/infrastructure → `factory`; biologics → `dna`; small molecule/OSD/HPAPI → `pill`; QC/analytical → `microscope`; process utilities → `beaker`; automation/digital → `chart`; logistics/warehousing → `document`; warnings → `warning`; completion → `check`.
- **Color is functional, not decorative.** Use the Okabe-Ito palette in `simulator/intelligence/palette.py` for risk, section, and grade semantics.
- **Dense selectors must not collapse.** For long scientific option lists, use tabs, radio buttons, or persistent checkbox grids — never `st.expander` with checkboxes.
- **Labels are precise.** Use “capabilities”, “molecules”, “plants”, “profiles”, “assessment”, etc. Pluralize correctly in dynamic strings.

## Success metrics / definition of done
- [x] Plant Profile Builder page renders the 7-section capability catalog and saves a new `PlantAsset` to Redis.
- [x] Plant Match shows a Core GMP Pillars context card for the selected molecule.
- [x] Plant Readiness shows the pillar breakdown plus gap/partial/ready summary against the selected plant.
- [x] Regulatory Passport surfaces the triggered pillars and rationale for the molecule.
- [x] 8 oncology molecules are enriched in the patent/regulatory/demand seeds and produce complexity, pillars, and roadmaps.
- [x] Standalone `data/oncology_molecule_table.json` exists and `redis-loader/enrich_oncology_seeds.py` reads from it.
- [x] `README.md` mentions the Plant Profile Builder page and `/plants/capability-taxonomy`.
- [x] "NSQ Catalog" renamed to "Product Catalog" in feature-card navigation and page header.
- [x] Product Catalog displays the 8 oncology molecules with **Regulatory**, **Readiness**, and **Match** action buttons.
- [x] Clicking **Readiness** or **Match** preselects the chosen molecule in the target page dropdown.
- [x] Plant Profile Builder uses tabs (not pills/dropdowns/expanders) for section navigation and bioicons instead of emoji.
- [ ] `docker compose build && docker compose up` stays healthy and every page renders without errors.
- [x] No file references the previous molecule drawer concept.

# Data-Visualization Workstream

## Objective
Replace weak or uninformative charts with decision-oriented scientific visualizations and ensure every computed statistic has an appropriate visual representation.

## Current status

| Surface | Status | Chart type used | Evidence |
|---------|--------|-----------------|----------|
| Patent Radar bubble chart | ✅ Done | `scientific_bubble_chart` with LOE-window band | `patent_radar.py` |
| Patent Radar shortlist bullets | ✅ Done | `scientific_bullet_chart` | `patent_radar.py` |
| Demand Radar stacked demand bar | ✅ Done | `scientific_stacked_bar` decomposing 5 demand components | `demand_radar.py` |
| Demand Radar evaluation ring + gauge | ✅ Done | `scientific_nested_ring` + `scientific_gauge` | `demand_radar.py` |
| Plant Match nested ring | ✅ Done | `scientific_nested_ring` for 4 pillar scores | `plant_match.py` |
| Plant Match capability gap matrix | ✅ Done | `scientific_gap_matrix` | `plant_match.py` |
| Plant Readiness complexity bullets | ✅ Done | `scientific_bullet_chart` on 0–10 scale | `plant_readiness.py` |
| Plant Readiness customer-fit ring | ✅ Done | `scientific_nested_ring` | `plant_readiness.py` |
| Plant Readiness roadmap Gantt | ✅ Done | `scientific_phase_gantt` | `plant_readiness.py` |
| Plant Readiness four-pillar bullets + gauge | ✅ Done | `scientific_bullet_chart` + `scientific_gauge` | `plant_readiness.py` |
| Portfolio top-10 colored bars | ✅ Done | Plotly bar colored by tier | `portfolio.py` |
| Portfolio quadrant scatter | ✅ Done | `scientific_quadrant_scatter` with median lines | `portfolio.py` |
| Portfolio tier donut + modality bar | ✅ Done | `scientific_nested_ring` + Plotly bar | `portfolio.py` |
| Portfolio decision-card mini rings | ✅ Done | `scientific_nested_ring` per candidate | `portfolio.py` |
| Regulatory Passport clarity gauge | ✅ Done | `scientific_gauge` | `regulatory_passport.py` |
| Regulatory Passport monograph donut | ✅ Done | `scientific_nested_ring` | `regulatory_passport.py` |
| Regulatory Passport geo bar | ✅ Done | Plotly horizontal bar of eligible markets | `regulatory_passport.py` |
| Product Catalog oncology score bar | ✅ Done | `scientific_bar_chart` of average total CDMO score | `app.py` |
| Shared chart helpers | ✅ Done | 7 new helpers in `ui_components.py` | `ui_components.py` |

## Files
- `simulator/intelligence/ui_components.py` — ✅ added `scientific_bullet_chart`, `scientific_nested_ring`, `scientific_gauge`, `scientific_quadrant_scatter`, `scientific_stacked_bar`, `scientific_gap_matrix`, `scientific_bubble_chart`, `scientific_phase_gantt`.
- `simulator/intelligence/pages/patent_radar.py` — ✅ bubble chart + bullet bars.
- `simulator/intelligence/pages/demand_radar.py` — ✅ stacked demand bar + nested ring/gauge.
- `simulator/intelligence/pages/plant_match.py` — ✅ nested ring + gap matrix + bullet bars; removed radar.
- `simulator/intelligence/pages/plant_readiness.py` — ✅ bullet charts + nested ring + Gantt + gauge; removed metric-tile score dumps.
- `simulator/intelligence/pages/portfolio.py` — ✅ quadrant scatter + tier donut + modality bar + mini rings.
- `simulator/intelligence/pages/regulatory_passport.py` — ✅ gauge + monograph donut + geo bar.
- `simulator/app.py` — ✅ average oncology score bar in Product Catalog.

## Remaining work
All implementation, verification, and documentation items are complete.

1. **Smoke test.** ✅ Verified every intelligence tab renders without exceptions using `streamlit.testing.v1.AppTest` over `/app/app.py` inside the Docker Compose stack; the app container logs show no errors after the fix for the `demand_heat` column.
2. **Polish.** ✅ No emoji remains in the intelligence page functional UI; the Plant Match button and GMP pillar symbols use monochrome geometric markers, and `⚠` / `✓` are reserved for warning/confirmation states.
3. **README update.** ✅ Added the data-visualization vocabulary table to `README.md` documenting all 8 shared chart helpers.

## Success metrics / definition of done
- [x] No page shows a plain metric/dataframe for a 0–100 score where a bullet/gauge/ring is clearer.
- [x] Patent Radar and Demand Radar no longer use weak scatter axes.
- [x] Plant Match uses a nested multi-ring radial bar chart for the 4 pillar scores.
- [x] Plant Readiness uses bullet charts for complexity and a nested ring for customer fit.
- [x] Portfolio uses a quadrant scatter with reference lines and a tier distribution donut.
- [x] Regulatory Passport has 3+ charts.
- [x] All new charts are rendered through shared helpers in `ui_components.py`.
- [x] `py_compile` passes for every modified file.
- [x] Docker compose smoke test renders every page without chart errors.
