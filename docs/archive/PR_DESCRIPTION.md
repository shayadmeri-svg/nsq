## Summary

This PR delivers the current evolution of the NSQ platform: a four-pillar CDMO off-patent drug intelligence engine with contextual GMP methodological guidance, plus a restored local Redis data layer and a consolidated project plan.

## Changes

### Data layer restoration
- Created `.env` pointing the Docker Compose stack at the local Redis instance (`redis://host.docker.internal:6379`).
- Reloaded local Redis with:
  - 2,799 NSQ alert records from `data/data Jan25_May26.csv`
  - 26 patent molecules, 5 plant assets, 26 regulatory passports, 26 demand profiles
- Rebuilt and restarted the Docker Compose stack; all services report healthy.

### Portfolio & scoring engine (`engine/`)
- FastAPI service (`engine/api_main.py`) with:
  - `GET /molecules`, `/molecules/{key}`, `/molecules/{key}/geo`, `/molecules/{key}/regulatory`, `/molecules/{key}/demand`, `/molecules/{key}/complexity`, `/molecules/{key}/roadmap`
  - `GET /plants`, `/plants/{id}`, `/plants/{id}/fit/{molecule_key}`
  - `GET /regulatory`, `/demand`
  - `POST /score`
  - `POST /portfolio/score`, `POST /portfolio/{id}`, `GET /portfolio/{id}`, `GET /portfolio/{id}/export?format=csv|json`
- Pydantic v2 models: `PatentIntelligence`, `PlantAsset`, `RegulatoryPassport`, `DemandProfile`, `ManufacturingComplexity`, `ManufacturingRoadmap`, `CandidateScore`, `PortfolioScenario`, `PortfolioEntry`, `PortfolioSnapshot`.
- Four-pillar scoring: patent, regulatory, demand, plant-fit with configurable weights.
- Manufacturing complexity derivation, customer profile fit, and modality-specific roadmaps.

### GMP pillar contextualization (new)
- Added `GmpPillar` model and extended `ManufacturingComplexity` to carry derived GMP pillars.
- Added `derive_gmp_pillars()` with rules for:
  1. Aseptic Processing & Sterility Assurance
  2. HPAPI Containment & Operator Safety
  3. Cleaning Validation & Cross-Contamination Control
  4. Lifecycle Process & Method Validation
  5. Packaging, CCIT & Supply-Chain Integrity
- Integrated GMP pillar readiness into plant-fit scoring.
- Exposed GMP pillars via new endpoint `GET /molecules/{key}/gmp-pillars` and included them in `/complexity` and `/plants/{id}/fit/{key}`.
- Updated simulator pages:
  - **Plant Readiness:** GMP pillars card with per-pillar rationale and plant readiness badges.
  - **Plant Match:** GMP context summary below the four-pillar score.
  - **Regulatory Passport:** GMP manufacturing context section.

### Intelligence data layer (`redis-loader/`, `shared/`, data seeds)
- Loaders for patents, plant assets, regulatory passports, demand signals, and the NSQ CSV.
- `company_ontology.py` for harmonized manufacturer / lab normalization.
- JSON seed files under `data/`.
- `justfile` recipes: `load-patents`, `load-plant-assets`, `load-regulatory`, `load-demand`, `load-intelligence`, `reload-csv`, etc.

### Simulator UI refresh (`simulator/intelligence/`, `simulator/app.py`)
- Shared design system in `simulator/intelligence/ui_components.py`.
- Pages: demand radar, patent radar, plant match, plant readiness, regulatory passport, portfolio.
- Refreshed scientific color palette (Okabe-Ito) across analytics and simulator.

### Project planning cleanup
- Archived `PLAN.md` and `PLAN_PHASE0.md` through `PLAN_PHASE5.md` into `PLAN_HISTORY.md`.
- `.claude/plan.md` is the single active plan for current work.

## How to verify

```bash
# 1. Start all services
docker compose up -d --build

# 2. Load CDMO intelligence seeds
just load-intelligence

# 3. Check health
curl http://localhost:8000/health
curl http://localhost:8501/_stcore/health
curl http://localhost:8502/_stcore/health

# 4. Score a candidate
curl -X POST http://localhost:8000/score \
  -H 'Content-Type: application/json' \
  -d '{"molecule_key":"paracetamol","plant_asset_id":"baddi-osd-a"}'

# 5. Inspect GMP pillars for a biologic
curl http://localhost:8000/molecules/pembrolizumab/gmp-pillars

# 6. Run a portfolio score
curl -X POST http://localhost:8000/portfolio/score \
  -H 'Content-Type: application/json' \
  -d '{"min_readiness_score": 0.4, "top_n": 5}'

# 7. Export CSV
curl 'http://localhost:8000/portfolio/{id}/export?format=csv'
```

## Related plans / documentation

- `.claude/plan.md` — active plan: GMP pillar contextualization + 8 oncology molecules
- `PLAN_HISTORY.md` — archived phase-by-phase plans
- `PLAN_ANALYTICS_HOME.md` — completed analytics home-page plan
