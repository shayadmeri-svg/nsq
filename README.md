# NSQ Platform — merged local stack

2 independent Streamlit services, orchestrated with Docker Compose,
both reading live data from a shared Redis instance.

```
merged/
├── analytics/            # real CDSCO NSQ alert dashboard (was nsq-env_copy_2.zip)
│   ├── app.py
│   ├── shared/nsq_redis.py   # copy of shared loader (Docker build context needs it locally)
│   ├── requirements.txt
│   └── Dockerfile
├── simulator/             # GMP root-cause / grading simulator (was nsq-agent.zip)
│   ├── app.py
│   ├── shared/nsq_redis.py
│   ├── requirements.txt
│   └── Dockerfile
├── shared/
│   └── nsq_redis.py        # source of truth — Redis-to-DataFrame loader, copied into each service
├── redis-loader/           # scripts that populate Redis (invoked via the root justfile)
│   ├── fetch_cdsco.py       # pulls the live CDSCO publicNsqDrugTable JSON
│   ├── load_nsq_redis.py
│   ├── load_geojson_redis.py
│   ├── ping_redis.py / verify_nsq_redis.py / clean_nsq_redis.py
│   └── requirements.txt
├── data/                   (fetched publicNsqDrugTable.json lands here — gitignored)
├── justfile                 # single entry point: setup, fetch-cdscoonline, push-geojson, ...
├── docker-compose.yml
├── .env.example
└── README.md

```

## What each service does

**analytics** (port 8501) — loads data from Redis, derives missing columns
(form type, drug category, dissolution-failure flag, state), and renders
Plotly charts / a state choropleth.

**simulator** (port 8502) — the GMP formulation/root-cause workbench.
Its 16-drug catalog (excipients, process windows, patent refs) is still
hardcoded fixture data — that part was never sourced from CDSCO. What
**is** live: on startup it reads the same Redis data and overlays real
`total_alerts` counts and top failure reasons onto each matching drug,
replacing the static numbers. The header shows
`● LIVE CDSCO DATA (N drugs matched)` when this succeeds, or
`○ STATIC CATALOG DATA` if Redis is unreachable/empty — it never hard-fails.

## How they interact

Neither service calls the other over the network. Both are independent
Redis clients reading the same keyspace:

```
Redis (nsq:record:*, nsq:records, nsq:meta)
   ├── read by analytics  (dashboard + charts)
   └── read by simulator  (live alert-count overlay)
```

`analytics` starts first (compose `depends_on: condition: service_healthy`)
as a basic startup ordering — there's no runtime dependency between the two
containers beyond that; if you stop analytics, the simulator keeps working
off whatever it already cached from Redis (`@st.cache_data(ttl=300)`).

## Prerequisite: get data into Redis

Both services expect `nsq:*` keys to already exist in Redis. Everything —
loader setup, data fetch, and running the two services — is driven from
one `justfile` at the repo root, reading one `.env` at the repo root.

```bash
cp .env.example .env
# edit .env: paste your Redis URL (rediss:// for Upstash — TLS is required)
just setup            # creates redis-loader/.venv and installs its deps
just ping             # confirm connectivity
just fetch-cdscoonline  # pulls the live CDSCO publicNsqDrugTable JSON and loads it into Redis
just verify            # sanity check
```

`just fetch-cdscoonline` hits `cdscoonline.gov.in/CDSCO/publicNsqDrugTable`
directly (it's a plain, unauthenticated GET) and flushes/reloads Redis with
the result, so Redis always reflects the latest fetch. If you'd rather
supply your own export (browser network tab, or whatever official export
mechanism CDSCO provides), save it to `data/publicNsqDrugTable.json` and
run `just reload` instead.

The India-states GeoJSON used by the analytics choropleth also lives in
Redis rather than as a checked-in file:

```bash
just push-geojson     # push analytics/india_states_slim.geojson into Redis
```

## Running the two services locally

```bash
docker compose up --build
```

- Analytics dashboard: http://localhost:8501
- Simulator workbench:  http://localhost:8502

To use the simulator's optional live-LLM diagnostics instead of the local
heuristic engine, set `GEMINI_API_KEY` in the root `.env` before starting.

## Updating the dataset

Just re-run `just fetch-cdscoonline` for a fresh pull, or `just reload` if
you're supplying your own export at `data/publicNsqDrugTable.json`. Both
flush and reload Redis. Both services will pick up the new data
automatically within their 5-minute cache TTL, or immediately on container
restart:

```bash
docker compose restart analytics simulator
```

No schema migration needed — the Redis loader only requires
`str_product_name` and, ideally, `str_nsq_result` fields (the CDSCO API's
own field names — see `redis-loader/load_nsq_redis.py` for the full
expected shape).

## CDMO Off-Patent Intelligence Engine

The simulator now includes a four-pillar decision engine (`engine/` service on
port 8000) and six intelligence pages in the simulator UI:

| Pillar | Page | Data keyspace |
|--------|------|---------------|
| A. Patent Intelligence | Patent Radar | `cdmo:patent:*` |
| B. Regulatory Rules | Regulatory Passport | `cdmo:regulatory:*` |
| C. Demand Trends | Demand Radar | `cdmo:demand:*` |
| D. Plant Expertise & Shop-Floor AI | Plant Match, Plant Readiness | `cdmo:plant:*` |
| Plant Profile Builder | Plant Builder | `cdmo:plant:*` |
| Portfolio Decision Engine | Portfolio | `cdmo:portfolio:*` |

### GMP methodological pillars

Plant Readiness, Plant Match, and Regulatory Passport now surface five
contextual GMP pillars derived from each molecule's modality, form, and
potency class:

1. Aseptic Processing & Sterility Assurance
2. HPAPI Containment & Operator Safety
3. Cleaning Validation & Cross-Contamination Control
4. Lifecycle Process & Method Validation
5. Packaging, CCIT, and Supply Chain Integrity

The engine derives these automatically from the existing patent/regulatory
seeds. API endpoints:

```bash
# Derive and list GMP pillars for any molecule
curl http://localhost:8000/molecules/{molecule_key}/gmp-pillars

# Full manufacturing complexity, including gmp_pillars
curl http://localhost:8000/molecules/{molecule_key}/complexity

# Plant fit summary with GMP readiness score
curl http://localhost:8000/plants/{asset_id}/fit/{molecule_key}

# 7-section capability taxonomy used by the Plant Builder
curl http://localhost:8000/plants/capability-taxonomy

# Create a custom digital plant profile from selected capability tokens
curl -X POST http://localhost:8000/plants \
  -H "Content-Type: application/json" \
  -d '{"name": "Hyderabad HPAPI + OSD Hub", "capabilities": ["potent_containment", "wet_granulation", "film_coating", "blister_packing"]}'
```

### Data-visualization vocabulary

The intelligence pages share a single scientific chart vocabulary in
`simulator/intelligence/ui_components.py`, rendered with the Okabe-Ito
colorblind-safe palette. The goal is to turn every 0–100 score, gap, and
timeline into a decision-oriented graphic instead of a plain table or metric.

| Helper | What it shows | Used in |
|--------|---------------|---------|
| `scientific_bullet_chart` | 0–100 (or 0–10) score against a target threshold, with color-coded performance bands. | Plant Match, Plant Readiness, Patent Radar, Demand Radar |
| `scientific_nested_ring` | Concentric completion rings; arc length is proportional to the score. Natural for 4-pillar profiles, customer-fit dimensions, and monograph coverage. | Plant Match, Plant Readiness, Demand Radar, Portfolio decision cards, Regulatory Passport |
| `scientific_gauge` | Half-ring gauge for a single headline score. | Demand Radar total, Regulatory Passport clarity, Product Catalog oncology overview |
| `scientific_quadrant_scatter` | 2-D scatter with median reference lines and cluster color; labels each quadrant. | Portfolio demand vs. plant fit |
| `scientific_stacked_bar` | Additive components of a synthetic score shown as stacked segments. | Demand Radar demand composition |
| `scientific_bubble_chart` | Encodes LOE horizon × FTO risk × market size, colored by therapeutic area. | Patent Radar attractiveness |
| `scientific_gap_matrix` | Heat-coded matrix comparing molecule-required capabilities to plant-available capabilities. | Plant Match |
| `scientific_phase_gantt` | Horizontal phase timeline with cumulative start offsets and milestone annotations. | Plant Readiness roadmap, Portfolio launch calendar |

All charts expose a consistent `source` caption and avoid decorative color or
emoji in functional UI.

### Plant Profile Builder

The simulator includes a **Plant Builder** page where users create digital plant
profiles by selecting capabilities from the canonical 7-section GMP capability
catalog (`/plants/capability-taxonomy`). Once saved, the profile is persisted as
a `PlantAsset` under `cdmo:plant:*` and becomes selectable immediately in
**Plant Match** and **Plant Readiness** for molecule-to-plant comparison.

### Loading intelligence seeds

```bash
# One command loads patents, plants, regulatory passports, and demand signals
just load-intelligence

# Or load each layer individually
just load-patents
just load-plant-assets
just load-regulatory
just load-demand
```

### Oncology molecule table

The repository ships an 8-molecule oncology table in
`data/oncology_molecule_table.json` (pembrolizumab, daratumumab, nivolumab,
osimertinib, durvalumab, abemaciclib, ribociclib, palbociclib). Run
`redis-loader/enrich_oncology_seeds.py` to merge this table into
`data/patent_seed.json`, `data/regulatory_seed.json`, and `data/demand_seed.json`.

The minimum fields needed for GMP pillar derivation are `molecule_key`,
`brand_name`, `api_name`, `therapeutic_area`, and `dosage_form` in the
regulatory seed. The engine infers modality, sterility, potency class, and the
relevant GMP pillars automatically.

For molecule-specific GMP overrides (e.g., exact OEL, containment class,
viral-clearance steps), add a `gmp_overrides` object to the regulatory or
patent seed record; the derivation logic will respect it in a follow-up
iteration.

## Next step

This local stack is the input to the Terraform module (AWS) — same two
images, same Redis dependency, translated to ECS/Fargate + either
continuing with Upstash or moving to ElastiCache. That comes next.
