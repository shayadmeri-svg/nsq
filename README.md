# NSQ Platform

A four-part platform built on India's CDSCO **Not-of-Standard-Quality (NSQ)** alert
data, aimed at both directions of the drug-quality problem:

1. **Analytics** — a public-health dashboard over ~5,600 real NSQ alerts
   (Jan 2021 – Jul 2026): trends, geography, failure taxonomy, and a
   product → manufacturer investigation workflow.
2. **Manufacturer app** — a tenant-scoped "Q-engine" deep dive for a single
   manufacturer: their own NSQ issues, root-cause analysis, GMP corridor,
   pharmacopeial methods, and mitigations.
3. **Off-patent decision engine** — a four-pillar CDMO intelligence engine
   (patent / regulatory / demand / plant-fit) for off-patent & LOE molecules,
   plus mechanistic process models for manufacturing-route simulation.
4. **A rigorous knowledge layer** — curated GMP, pharmacopeia (IP / Ph. Eur. /
   USP), ICH, and FDA Orange Book data where **every structured claim carries a
   provenance authority tier**, and parsers refuse to fabricate what they
   cannot extract.

Everything shares one Redis instance as the data bus.

```
                        ┌──────────────────────────────────────────────┐
                        │                  Redis                       │
                        │  nsq:*  (alerts, ontology)                   │
                        │  cdmo:* (patents, plants, regulatory, demand)│
                        │  geo:india_states                            │
                        └──────┬───────────┬───────────┬───────────┬───┘
                               │           │           │           │
   redis-loader/ ────────▶ writes        │           │           │
   (CSV + seeds)                  ┌─────▼────┐ ┌────▼─────┐ ┌───▼───────┐
                                  │analytics │ │simulator │ │  engine   │
                                  │ :8501    │ │ :8502    │ │(FastAPI)  │
                                  └──────────┘ └────┬─────┘ │  :8000    │
                                                    │ HTTP  └─────▲─────┘
                                                    └─────────────┘
                                  ┌──────────┐
                                  │manufacturer│  (Redis-only; no HTTP
                                  │  :8503   │   dependency on engine)
                                  └──────────┘
```

## Services

| Service | Port | Stack | What it is |
|---|---|---|---|
| `analytics` | 8501 | Streamlit | CDSCO NSQ Alerts Dashboard — public-health view of the full dataset |
| `simulator` | 8502 | Streamlit | CDMO Off-Patent Intelligence workbench — 17-drug catalog + 7 intelligence pages backed by the engine |
| `engine` | 8000 | FastAPI | Four-pillar decision engine + portfolio scorer (the simulator's API backend) |
| `manufacturer` | 8503 | Streamlit | Tenant-scoped manufacturer dashboard + Q-engine diagnostics |
| process-model API | 8010 | FastAPI | Mechanistic manufacturing-route simulator (host-only; not in compose) |

## Quickstart

```bash
cp .env.example .env        # set REDIS_URL (rediss:// for Upstash — TLS required)
just setup                  # create redis-loader/.venv + install deps
just ping                   # verify connectivity

# Load the dataset (deterministic CSV pipeline — see below)
just refresh-csv            # flush + reload NSQ CSV + product ontology + verify

# Load the intelligence seeds
just load-intelligence      # patents, plant assets, regulatory, demand

# Run everything
docker compose up --build
#   http://localhost:8501  analytics
#   http://localhost:8502  simulator
#   http://localhost:8503  manufacturer
#   http://localhost:8000  engine API
```

Host-side (no Docker) equivalents: `just run-analytics`, `just run-manufacturer`,
`just run-api` (engine :8000), `just run-simulator` (process-model API :8010).
Host loader/engine runs need `redis://localhost:6379`; the `.env`
`host.docker.internal` URL only resolves inside containers.

Tests: `just test` (see [Tests](#tests)).

## Data pipeline

### The deterministic CSV pipeline (primary)

`redis-loader/load_csv_redis.py` loads the cumulative NSQ CSV
(`data/CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv`). Its core
invariants:

- **Deterministic identity** — `record_id()` hashes
  `(batch_no, product_name, reporting_month, reporting lab, NSQ-result text)`.
  Batch+product alone collapses legitimately distinct alerts (the same batch
  re-failing in consecutive months; one notification failing different tests),
  which the older scheme demonstrably did — it lost 46 alerts on one dataset.
- **Order-independent ontology** — `prepare_rows()` sorts rows before the
  ontology build, so Redis state is a pure function of CSV content. Appending
  new monthly rows cannot perturb manufacturer bins. A non-`--flush` reload is
  therefore **invalid**: the ontology is insertion-order-dependent under fuzzy
  matching and must be rebuilt from scratch each time.
- **Company ontology** — `shared/company_ontology.py` canonicalizes
  manufacturer strings (legal-form and address-tail stripping, brand-root
  binning, fuzzy merge gated at `FUZZY_THRESHOLD=0.85`) into
  `nsq:ontology:companies` + per-record `nsq:prediction:*` enrichment. Six
  copies of the normalizer exist across services and are kept in lockstep by
  `tests/test_ontology_lockstep.py`.

**Monthly refresh runbook** (new CDSCO rows arrive):

```bash
# append new rows to data/CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv
just refresh-csv            # reload-csv --flush + build-product-ontology + verify
```

`--rebuild-ontology` exists only for cleaning legacy-contaminated state (re-key
every company record with the current normalizer); do **not** run it after a
fresh deterministic build — it undoes the intentional threshold-gated fuzzy
merges. Preview with `--rebuild-ontology --dry-run`.

### Legacy JSON path (superseded)

`just load` / `just reload` / `just fetch-cdscoonline` drive
`load_nsq_redis.py` against the CDSCO `publicNsqDrugTable` JSON (a plain
unauthenticated GET via `fetch_cdsco.py`). Kept for ad-hoc live pulls; the CSV
pipeline is the real dataset path.

### Other Redis data

```bash
just push-geojson           # India-states GeoJSON → geo:india_states (gzip+base64)
just load-intelligence      # all four cdmo:* seed families at once
just load-patents | load-plant-assets | load-regulatory | load-demand
just build-product-ontology # batch pre-fill of nsq:ontology:products (fast cold start)
```

## Redis keyspace

| Family | Keys | Written by | Read by |
|---|---|---|---|
| NSQ alerts | `nsq:record:<id>`, `nsq:records`, `nsq:by_month:*`, `nsq:meta` | `load_csv_redis.py` | all services via `shared/nsq_redis.py` |
| Ontology predictions | `nsq:prediction:<id>`, `nsq:ontology:companies`, `nsq:ontology:products`, `nsq:ontology:meta` | CSV loader (with `--augment`) | data loader → `Mfg_Ontology_Key`, canonical names |
| Intelligence seeds | `cdmo:patent:*`, `cdmo:plant:*`, `cdmo:regulatory:*`, `cdmo:demand:*` | seed loaders | engine |
| Geography | `geo:india_states` (+ `:meta`) | `load_geojson_redis.py` | analytics choropleth |

## The services

### analytics (:8501) — CDSCO NSQ Alerts Dashboard

Five tabs over the enriched frame (`shared/data_loader.py` derives form type,
drug category, failure category, state, canonical names, ontology keys):

1. **Trend & Distribution** — temporal stacked-area trend by failure category,
   top defective product matrices, form-factor risk, failure-category mix.
2. **Geographic & Heatmap** — India choropleth, cross-tabulation risk
   correlation, manufacturer risk matrices.
3. **Relational Sankey** — vulnerability-chain topology
   (product → manufacturer → failure → lab).
4. **Searchable Audit Ledger** — sortable, exportable full table.
5. **Product → Manufacturer Investigation** — the analytical depth: from a
   product's fuzzy search to per-manufacturer drill-downs with a GMP &
   testing-standards recap, probable causes, and a mitigation plan.

Tab 5 surfaces the shared knowledge layer (below): provenance-badged claims
with an authority-tier legend, the cross-pharmacopeia method diff
(IP 2026 vs Ph. Eur. vs USP) with ICH Q4B harmonisation columns, and an FDA
Orange Book panel with honest-absence handling.

### manufacturer (:8503) — tenant app & Q-engine diagnostics

Config-driven single-tenant app (`NSQ_TENANT`, registry in
`manufacturer/tenants.py`). The sign-in gate establishes session context
(manufacturer + persona: QA / Regulatory / Executive) — it is **context
establishment, not a security boundary**; SSO/OIDC is future work.

- **Dashboard** — KPI row, issue-by-type donut, issue-over-time line,
  form × issue heatmap, and the full issue-card list with an
  "Include issues to analyse" selector and per-card **Deep dive** buttons.
- **Q-engine diagnostics** — six sections (persona reorders them and chooses
  which default open): Root-cause analysis, GMP corridor, Pharmacopeial
  methods, Regulatory provenance, Synthesis route, Suggested mitigations.
  `manufacturer/diagnostics_core.py` is pure and headless
  (`build_diagnosis()`), with two evidence modes: **data-informed** (dominant
  failure modes, form span, geographic concentration, temporal clusters over
  the tenant frame) and **API-informed** (curated `Drug` from `gmp_knowledge`:
  common alerts, VigiBase risks, GMP corridor, methods). Anything outside the
  curated knowledge — e.g. synthesis routes — is surfaced as an explicit gap,
  never invented.

The tenant scopes on `Mfg_Ontology_Key` (the ontology key), not the raw
manufacturer string — 7 raw string variants must resolve to one tenant.

### simulator (:8502) — CDMO intelligence workbench

- **Step 0 — Catalog/workbench**: the 17-drug fixture catalog (excipients,
  process windows, pharmacopeia view, process deck) with live NSQ alert counts
  overlaid from Redis (`● LIVE CDSCO DATA` / `○ STATIC CATALOG` header).
  NSQ-failure explanation runs a local deterministic heuristic, or live Gemini
  when `GEMINI_API_KEY` is set.
- **Steps 1–7 — intelligence pages** (`simulator/intelligence/pages/`), each
  rendered from the engine API (`CDMO_ENGINE_URL`, default `:8000`):
  **Patent Radar**, **Regulatory Passport**, **Demand Radar**, **Plant Match**,
  **Plant Readiness**, **Plant Profile Builder**, **Portfolio**.

All intelligence pages share one scientific chart vocabulary
(`intelligence/ui_components.py`, Okabe-Ito colorblind-safe palette): bullet
charts, nested rings, gauges, quadrant scatters, stacked bars, LOE×FTO×market
bubble charts, capability gap matrices, and phase Gantts — every chart carries
a `source` caption.

### engine (:8000) — FastAPI decision engine

Four-pillar scoring over the `cdmo:*` seeds. Patent intelligence is fully
implemented; **Regulatory and Demand pillars are structured placeholders that
currently return neutral scores** — the models and API surface exist, the
signal does not yet.

```bash
GET  /health
GET  /molecules                      GET  /molecules/{key}
GET  /molecules/{key}/geo|regulatory|demand|complexity|gmp-pillars
GET  /molecules/{key}/roadmap?plant_asset_id=
GET  /refresh-orange-book/{key}
GET  /plants                         GET  /plants/{asset_id}
GET  /plants/capability-taxonomy     POST /plants        # digital plant from capability tokens
GET  /plants/{asset_id}/fit/{molecule_key}
POST /score                          # four-pillar candidate score
POST /portfolio/score                POST /portfolio/{id}   GET /portfolio/{id}
GET  /portfolio/{id}/export?format=json|csv
```

Derived intelligence in `engine/shared/intelligence_scorer.py`:
`derive_gmp_pillars` (5 rule-based GMP pillars — aseptic/sterility assurance,
HPAPI containment, cleaning validation, lifecycle validation,
packaging/CCIT), manufacturing-complexity derivation, customer-profile fit,
modality-specific roadmaps, plant-fit scoring.

### Process-model API (:8010)

`simulator/api_main.py` is a thin adapter over **framework-agnostic,
pure-Python mechanistic models** in `simulator/process_models/` — the model is
the seam; a better model replaces the rules without touching API or UI.

```bash
GET  /v1/simulate/telmisartan/routes              # stage/CPP/CQA metadata (UI builds sliders from this)
GET  /v1/simulate/telmisartan/{route_id}/metadata
POST /v1/simulate/telmisartan/{route_id}          # flat {"cpp": value} body; 422 out-of-range
```

Two Telmisartan routes ship: a NaOH fluid-bed wet-granulation route and a
direct-compression route anchored to the curated GMP corridor. Each returns
per-stage CQAs with severity/failure-mode and an overall verdict. Adding a
route is a one-line registration in `process_models/__init__.py`.
`static/simulator.html` (served at `/simulator`) is a standalone route-selector
page backed by this API.

## The knowledge layer (`shared/`)

`shared/` is the source of truth; each service gets its own synced copy
(`just sync-shared`, verified by sha256 in
`tests/test_sync_shared_determinism.py`):

| Module | Purpose |
|---|---|
| `company_ontology.py` | Redis-backed company + product ontology; canonical identity, aliases, threshold-gated fuzzy dedupe |
| `data_loader.py` | Streamlit-cached enriched NSQ frame (failure categories, forms, states, ontology keys) |
| `nsq_redis.py` | Redis → DataFrame loader; falls back to `$NSQ_CSV` when Redis is empty/unreachable |
| `gmp_knowledge.py` | Curated GMP core: 17-drug catalog (excipient profiles, critical processing corridors, testing guidelines, VigiBase risks) + mitigation `SOLUTION_BANK` + the provenance gate |
| `pharmacopeia_methods.py` | Regex parser for pharmacopeial methods (apparatus, RPM, medium, Q limits, HPLC conditions) with a strict no-fabrication contract and `parse_confidence` |
| `pharmacopeia_diff.py` | Cross-pharmacopeia diff; classifies sections `NSQ_RELEVANT` / `METHOD_EQUIVALENT` / `INCOMPARABLE` and refuses to claim unproven equivalence |
| `ich_registry.py` | Baked, cited ICH guideline registry (real PDF URLs + retrieval dates) + Q4B harmonisation context |
| `us_regulatory_data.py` | Baked, cited FDA Orange Book data from openFDA (TE codes, RLD, applicant) — 16/17 molecules, `vildagliptin` honestly absent |

**Provenance rigour** is enforced, not aspirational: every structured claim
carries an `authority_tier` (monograph / ich_guideline / regulatory_registry /
patent / empirical_cohort / expert_corridor / uncited), `provenance_audit()`
must report zero un-provenanced claims, and parsers return `None` (never a
guessed number) when they cannot extract a value.

## Tests

`just test` runs `tests/` against a live local Redis (`redis://localhost:6379`;
integration tests skip when unreachable):

| Suite | Guards |
|---|---|
| `test_ontology_lockstep` | the 6 normalizer copies stay identical; bins are pure functions of the name |
| `test_loader_record_keys` | record identity, dedupe, deterministic sort, lab harmonization |
| `test_sync_shared_determinism` | `shared/` copies match by sha256 across services |
| `test_gmp_provenance` | zero un-provenanced claims across the catalog; no fabricated monograph numbers |
| `test_pharmacopeia_diff` | no-fabrication gate; real paracetamol parse; honest INCOMPARABLE |
| `test_ich_registry` / `test_us_regulatory_data` | real cited sources; no placeholder seeds regress |
| `test_diagnostics_core` | headless diagnosis: curated API, uncurated fallback, outlier category |
| `test_tenant_scope` | tenant registry, `NSQ_TENANT` override, row scoping, no cross-tenant contamination |
| `test_telmisartan_process_model` / `..._direct_compression` | CQA formulas, failure-mode precedence, route registry contract |

Plus render-model tests for the intelligence chart vocabulary in
`simulator/intelligence/tests/`.

## Deployment

- **Local**: `docker compose up --build` (all four services on `nsq-net`,
  sharing the root `.env`).
- **AWS**: `terraform/` deploys the same compose stack to a single EC2 box
  (t3.micro, default VPC) — Redis/Gemini URLs pass through SSM SecureStrings +
  KMS; `deploy.sh` (invoked by the `nsq-platform` systemd unit on boot)
  refreshes env and runs `docker compose up -d --build`.
- Terraform's security group currently opens 22/8501/8502 only — the engine
  (8000) and manufacturer (8503) ports are not yet opened for remote access.

## Known gaps & honest limitations

- **Regulatory & Demand pillars are neutral placeholders** in the engine
  scorer (models and endpoints exist; real signals pending).
- The 17-drug simulator catalog is **curated fixture data**, not CDSCO-sourced
  (only the NSQ alert-count overlay is live).
- The manufacturer sign-in gate is **not authentication**.
- The process-model API (8010) and `/simulator` static page are host-only —
  not in docker-compose.
- `PLAN_ANALYTICS_HOME.md` describes an anime.js animated landing page that is
  **not implemented**; `PLAN_HISTORY.md` archives the original phased roadmap.
- `.env.example` is referenced but not yet checked in — copy the shape from
  `docker-compose.yml` (`REDIS_URL`, optional `GEMINI_API_KEY`, optional
  `NSQ_TENANT`).

## Planning docs

`PLAN_HISTORY.md` (archived roadmap) · `PLAN_ANALYTICS_HOME.md` (proposed
analytics landing page) · `PR_DESCRIPTION.md` (prior PR summary).