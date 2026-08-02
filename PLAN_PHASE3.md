# Phase 3 Implementation Plan
## Multi-Factor Demand Trends + Four-Pillar Evaluation Flow

> **Goal:** Make the demand pillar real and surface a user flow that starts with a sortable drug list showing Pillar A (patent), B (regulatory), and C (demand) signals, then lets the user evaluate their plant line (Pillar D) against any selected drug.

---

## 1. What we built

### A. Demand signal registry

New `cdmo:demand:<molecule_key>` Redis hashes capture:

| Field | Meaning |
|-------|---------|
| `disease_area` | Primary indication |
| `disease_prevalence_global_millions` | Approx. global patient population |
| `disease_prevalence_india_millions` | Approx. India patient population |
| `growth_trend` | `growing` / `stable` / `declining` |
| `trial_count_total` | Active/completed clinical trials |
| `trial_count_phase_3_plus` | Late-stage trials |
| `cluster` | `oncology`, `specialty injectable`, `immunology`, `lifestyle / chronic`, `commodity` |
| `buyer_activity_score` | 0–100 proxy for tender/institution activity |
| `market_momentum_score` | 0–100 proxy for LOE/competitive momentum |
| `competitor_anda_count` | Approx. generic/biosimilar filing competition |
| `notes`, `source_url` | Context and provenance |

### B. Real demand scoring

`score_demand(profile, molecule_key)` replaced the fixed 50/100 placeholder:

| Factor | Max points | Logic |
|--------|-----------|-------|
| Base profile | 10 | Having demand data |
| Disease burden | 25 | Log-scaled global + India prevalence |
| Growth trend | 15 | Growing +15, stable +5, declining -10 |
| Late-stage pipeline | 20 | +2 per phase-3+ trial |
| Cluster premium | 15 | Oncology/specialty/immunology highest; commodity lowest |
| Buyer/momentum | 15 | Derived from `buyer_activity_score` + `market_momentum_score` |

### C. New API endpoints

- `GET /demand` — list all demand profiles (summary)
- `GET /molecules/{key}/demand` — full demand profile
- `POST /score` — now uses real patent, regulatory, demand, and plant-fit scores

### D. New UI: Demand Radar tab

- Sortable drug table with A/B/C summary: FTO risk, LOE, export-eligible markets, cluster, growth trend, phase-3+ trials, TE rating, regulatory readiness.
- Sidebar filters: cluster, FTO risk, growth trend, minimum export markets.
- Molecule selector + plant-line selector.
- **Run four-pillar evaluation** button returns the full scorecard with explanations and warnings.
- Expandable detail cards for the selected molecule.

### E. Data & loaders

- `data/demand_seed.json` — 26 hand-curated demand profiles.
- `redis-loader/load_demand.py` — one-time loader for `cdmo:demand:*`.
- `justfile` — added `load-demand`; `load-intelligence` now seeds all four pillars.

---

## 2. Files created / modified

### New files

| Path | Purpose |
|------|---------|
| `data/demand_seed.json` | Demand signal seed data |
| `redis-loader/load_demand.py` | Loader for `cdmo:demand:*` |
| `simulator/intelligence/pages/demand_radar.py` | Streamlit Demand Radar page |

### Modified files

| Path | Change |
|------|--------|
| `engine/shared/intelligence_models.py` | Added `DemandProfile` model with full serialization |
| `engine/shared/intelligence_store.py` | Added `cdmo:demand:*` read/write helpers |
| `engine/shared/intelligence_scorer.py` | Implemented real `score_demand`; `score_candidate` auto-loads demand |
| `engine/api_main.py` | Added `/demand` and `/molecules/{key}/demand` endpoints |
| `simulator/intelligence/api_client.py` | Added demand client methods |
| `simulator/intelligence/intelligence_*.py` | Synced copies from `engine/shared/` |
| `simulator/app.py` | Added "📈 Demand Radar" tab as the first engine tab after NSQ Workbench |
| `justfile` | Added `load-demand` recipe and included it in `load-intelligence` |

---

## 3. Success metrics

- [x] `/demand` returns 26 demand profiles.
- [x] `/molecules/{key}/demand` returns full demand profile.
- [x] Demand score is no longer a fixed placeholder; generic molecules score ~50–65, branded oncology/specialty molecules score ~75–98.
- [x] `POST /score` returns a real four-pillar scorecard.
- [x] Streamlit Demand Radar tab imports cleanly and is wired into the main app.
- [x] Docker images build and `docker compose up` reports all services healthy.

---

## 4. Sample smoke-test results

```bash
GET /health        → {"status": "ok", "redis_ready": true}
GET /molecules     → 26 molecules
GET /demand        → 26 profiles
GET /regulatory    → 26 passports

POST /score {"molecule_key":"paracetamol","plant_asset_id":"baddi-osd-a"}
→ patent 62, regulatory 100, demand 56, plant 81, total 73

POST /score {"molecule_key":"pembrolizumab","plant_asset_id":"baddi-osd-a"}
→ patent 80, regulatory 10, demand 83, plant 5, total 44

POST /score {"molecule_key":"semaglutide","plant_asset_id":"baddi-osd-a"}
→ patent 65, regulatory 10, demand 97, plant 5, total 44
```

---

## 5. Next step

Phase 4: **Plant Expertise & Shop-Floor AI Integration**. Make the plant-fit pillar richer by:
- Adding equipment-train-level capability checks from the plant asset registry.
- Surfacing NSQ/QbD risk signals from the existing simulator engine per molecule × plant.
- Adding a "Can we make this well?" score that penalizes molecules with high NSQ alert history or missing critical process parameters at the selected plant.

*Plan version 1.0 — 2026-07-30*
