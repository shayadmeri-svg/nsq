## Summary

This PR delivers Phase 5 of the NSQ simulator evolution: a four-pillar CDMO off-patent drug intelligence engine with a portfolio decision API and a refreshed, professional Streamlit UI.

## Changes

### Portfolio & scoring engine (`engine/`)
- Added FastAPI service (`engine/api_main.py`) with:
  - `POST /portfolio/score` — Cartesian molecule × plant evaluation, filtering, ranking
  - `GET /portfolio/{id}` and `/portfolio/{id}/export?format=csv|json`
  - `GET /health` and status endpoints
- Pydantic v2 models: `PortfolioScenario`, `PortfolioEntry`, `PortfolioSnapshot`, `CandidateScore`
- Four-pillar scoring: patent, regulatory, demand, plant-fit with configurable weights
- Optimized `build_portfolio()` to pass pre-loaded `demand` and `plant` maps, avoiding per-candidate Redis round-trips
- Fixed CSV export fieldnames (`infrastructure_fit_score`, `talent_fit_score`, `certification_fit_score`, `loe_years`)

### Intelligence data layer (`redis-loader/`, `shared/`, data seeds)
- Added loaders for patents, plant assets, regulatory passports, and demand signals
- Added `company_ontology.py` for harmonized manufacturer / lab normalization
- Added JSON seed files under `data/`
- Updated `justfile` with `load-patents`, `load-plant-assets`, `load-regulatory`, `load-demand`, `load-intelligence`
- Updated `docker-compose.yml` with `engine` service on port 8000

### Simulator UI refresh (`simulator/intelligence/`, `simulator/app.py`)
- Removed default sidebar across intelligence pages
- Added shared design system in `simulator/intelligence/ui_components.py`:
  - Monochrome bio/medical SVG icons
  - Clickable feature cards with brief explainers and invisible overlay buttons
  - Compact horizontal stepper with mobile collapse
  - Mock-data indicator badge
  - anime.js entrance and pulse animations
  - Plotly chart helpers with source / n / statistical annotations
- Added intelligence pages: catalog, demand radar, patent radar, plant match, plant readiness, regulatory passport, portfolio
- Updated main `app.py` header, status pills, and navigation

## How to verify

```bash
# 1. Start all services
docker compose up -d --build

# 2. Load CDMO intelligence seeds
just load-intelligence

# 3. Check health
curl http://localhost:8000/health
curl http://localhost:8502/_stcore/health

# 4. Run a portfolio score
curl -X POST http://localhost:8000/portfolio/score \
  -H 'Content-Type: application/json' \
  -d '{"min_readiness_score": 0.4, "top_n": 5}'

# 5. Export CSV
curl 'http://localhost:8000/portfolio/{id}/export?format=csv'
```

## Related plans / documentation

- `PLAN_PHASE5.md` — full Phase 5 scope, models, API, UI plan, and success metrics
