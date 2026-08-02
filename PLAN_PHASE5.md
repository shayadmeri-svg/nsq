# Phase 5 — Portfolio Decision Engine

## Goal
Turn the four-pillar intelligence signals into an actionable portfolio plan:
a ranked list of molecule × plant candidates, configurable scenario weights,
launch-calendar output, and exportable decision snapshots.

## Scope

### 1. Backend (engine service)
- **Model** `PortfolioScenario` — configurable weights (patent, regulatory, demand, plant),
  plant asset filter, cluster filter, LOE horizon cut-off, FTO risk allow-list,
  stretch/exclude/include-stretch toggle, mock-data flag.
- **Model** `PortfolioEntry` — one molecule × plant candidate with per-pillar scores,
  manufacturing complexity summary, recommended tier, launch-quarter estimate, and
  key warnings.
- **Model** `PortfolioSnapshot` — ranked entries, scenario summary, evaluated count,
  included count, and source note.
- **Function** `build_portfolio()` in `engine/shared/intelligence_scorer.py` —
  Cartesian molecule × plant evaluation, filters, scoring, ranking.
- **Persistence** `save_portfolio()` / `load_portfolio()` in
  `engine/shared/intelligence_store.py` — stores scenario + snapshot under
  `cdmo:portfolio:{portfolio_id}` in Redis.
- **API endpoints** in `engine/api_main.py`:
  - `POST /portfolio/score` → return a `PortfolioSnapshot`
  - `POST /portfolio/{portfolio_id}` → save a scenario + snapshot
  - `GET  /portfolio/{portfolio_id}` → retrieve saved portfolio
  - `GET  /portfolio/{portfolio_id}/export?format=csv|json` → export

### 2. Simulator UI
- New `simulator/intelligence/pages/portfolio.py` — scenario panel, weight
  sliders, contextual filters, ranked decision cards, launch-calendar Gantt,
  CSV/JSON export.
- Shared design system `simulator/intelligence/ui_components.py` — monochrome
  SVG bioicons, feature-card navigation, stepper, mock-data badge, metric tiles,
  anime.js entrance/pulse helpers, Plotly chart wrappers with source/stat
  annotations.
- Reskin all engine pages to remove the Streamlit sidebar and use the shared
  monochrome components:
  - `demand_radar.py`
  - `patent_radar.py`
  - `plant_match.py`
  - `plant_readiness.py`
  - `regulatory_passport.py`
  - `portfolio.py`
- Update `simulator/app.py`:
  - `initial_sidebar_state="collapsed"`
  - feature-card nav instead of `st.tabs`
  - stepper showing workflow: Shortlist → Demand → Patent → Match Plant →
    Readiness → Regulatory → Portfolio
  - in-page horizontal catalog for the legacy NSQ Workbench

### 3. Data contracts
- Pydantic v2 with Python 3.9 compatibility (`Optional[X]`, `dict[str, float]`,
  `list[str]`).
- Redis keyspace split remains: `nsq:*` for CDSCO alerts, `cdmo:*` for
  intelligence data.

## Success metrics
- `POST /portfolio/score` returns a ranked snapshot in < 2 s for the seed catalog.
- `GET /portfolio/{id}/export?format=csv` downloads a CSV with the expected columns.
- Simulator renders all six engine pages without sidebar and with monochrome
  bioicons.
- anime.js entrance animations fire on feature cards and page results.
- Plotly charts display source + sample-size / statistical annotation.

## Run / verify
```bash
docker compose build
docker compose up -d
python3 - <<'PY'
import requests
r = requests.post("http://localhost:8000/portfolio/score", json={"use_mock_data": True})
print(r.status_code, r.json()["summary"])
PY
```
