# NSQ Platform — Historical Plan Archive

This file preserves the intent, scope, and completion notes from the original phased planning documents. Active planning now lives in `.claude/plan.md`.

---

## Long-Horizon Vision (`PLAN.md` v1.0)

**Goal:** Evolve the simulator (port 8502) into a four-pillar CDMO decision engine for off-patent / LOE molecules.

**Four pillars**
| Pillar | Responsibility | Starting point |
|--------|---------------|----------------|
| A. Patent Intelligence | Global LOE calendar, FTO scoring | New `intelligence/patents` module |
| B. Market Access & Regulatory Rules | EP/IP 2026 monographs, test protocols | Extend simulator `Drug` model |
| C. Multi-Factor Demand Trends | Disease burden, pipeline, buyer signals | New `intelligence/demand` module |
| D. Plant Expertise & Shop-Floor AI | Plant match, QbD/NSQ prevention | Reuse simulator grading engine |

**Target architecture**
- Streamlit apps: analytics (8501), simulator (8502 with workbench + engine pages).
- Redis keyspace: `nsq:*` for CDSCO alerts; `cdmo:*` for intelligence.
- FastAPI engine service on port 8000.

**Phased roadmap (original)**
- Phase 0 — Foundation: scaffold `intelligence/` package, shared models/store.
- Phase 1 — Patent Intelligence: LOE calendar + FTO heatmap.
- Phase 2 — Regulatory Passport: pharmacopeia monographs, Orange Book data, geo coverage.
- Phase 3 — Demand Radar: disease burden, trial pipeline, cluster scoring.
- Phase 4 — Plant Readiness: manufacturing complexity, customer profile fit, roadmaps.
- Phase 5 — Portfolio Decision Engine: ranked portfolio builder with export.
- Phase 6+ — Hardening, feedback loop, headless API.

---

## Phase 0 + Phase 1 (`PLAN_PHASE0.md`)

**Deliverable:** Patent Radar with 10 molecules and representative plant assets.

**First molecule shortlist:** Keytruda, Darzalex, Opdivo, Tagrisso, Imfinzi, Verzenio, Kisqali, Ibrance, Ozempic, Dupixent.

**Files created:**
- `simulator/intelligence/__init__.py`
- `simulator/intelligence/models.py` → later renamed `intelligence_models.py`
- `simulator/intelligence/store.py` → later renamed `intelligence_store.py`
- `simulator/intelligence/scorer.py` → later renamed `intelligence_scorer.py`
- `simulator/intelligence/pages/patent_radar.py`
- `simulator/intelligence/pages/plant_match.py`
- `data/patent_seed.json`
- `data/plant_assets_seed.json`
- `redis-loader/load_patents.py`
- `redis-loader/load_plant_assets.py`

**Completion:** Scaffold + Patent Radar + Plant Match + FastAPI endpoints shipped.

---

## Phase 2 (`PLAN_PHASE2.md`)

**Deliverable:** Regulatory Passport + geography-aware LOE timeline.

**New files:**
- `data/regulatory_seed.json`
- `redis-loader/load_regulatory.py`
- `simulator/intelligence/pages/regulatory_passport.py`

**Model additions:** `GeoCoverage`, expanded `RegulatoryPassport`.

**API additions:** `/regulatory`, `/molecules/{key}/regulatory`, `/molecules/{key}/geo`, `/refresh-orange-book/{key}`.

**Scoring:** Real `score_regulatory` based on monographs, TE rating, exclusivity, export-eligible geographies, BCS/stability.

**Completion status:** All bricks implemented and smoke-tested on 2026-07-30. 26 molecules seeded; endpoints live.

---

## Phase 3 (`PLAN_PHASE3.md`)

**Deliverable:** Demand Radar + real four-pillar evaluation flow.

**New files:**
- `data/demand_seed.json`
- `redis-loader/load_demand.py`
- `simulator/intelligence/pages/demand_radar.py`

**Scoring:** Real `score_demand` using prevalence, growth trend, late-stage pipeline, cluster premium, buyer/momentum.

**API additions:** `/demand`, `/molecules/{key}/demand`.

**Completion status:** 26 demand profiles, real four-pillar scorecard, Docker stack healthy.

---

## Phase 4 (`PLAN_PHASE4.md`)

**Deliverable:** Plant Readiness & Manufacturing Roadmap.

**New models:** `ManufacturingComplexity`, `ManufacturingRoadmap`, `RoadmapPhase`.

**New page:** `simulator/intelligence/pages/plant_readiness.py`.

**API additions:** `/molecules/{key}/complexity`, `/molecules/{key}/roadmap`, `/plants/{id}/fit/{key}`.

**Scoring:** `derive_manufacturing_complexity`, `score_customer_profile_fit`, `build_manufacturing_roadmap`.

**Completion status:** All steps done; biosimilar and small-molecule roadmaps generated; Docker compose stack healthy.

---

## Phase 5 (`PLAN_PHASE5.md`)

**Deliverable:** Portfolio Decision Engine.

**Models:** `PortfolioScenario`, `PortfolioEntry`, `PortfolioSnapshot`.

**New page:** `simulator/intelligence/pages/portfolio.py`.

**API additions:** `POST /portfolio/score`, `POST /portfolio/{id}`, `GET /portfolio/{id}`, `GET /portfolio/{id}/export`.

**UI refresh:** Shared design system in `simulator/intelligence/ui_components.py`, monochrome bioicons, feature-card nav, stepper, Plotly helpers.

**Completion status:** Portfolio scoring, export, and refreshed UI shipped.

---

## Current Workstream

See `.claude/plan.md` for the active plan: **contextualize Plant Readiness, Plant Match, and Regulatory Passport with five Core GMP Methodological Pillars**, and prepare for 8 oncology molecule table.

> **Note on dropped concepts.** A prior session produced a "Molecule Info Side Drawer" plan. It was evaluated and rejected; no code was implemented and it is no longer part of the active roadmap. This archive documents only shipped or active workstreams.

*Archived on 2026-08-04.*
