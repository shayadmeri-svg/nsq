# Phase 0 + Phase 1 Implementation Plan
## Off-Patent Drug Intelligence Engine — First Brick

> **Decisions captured from user:**
> 1. First 10 molecules: **Keytruda, Darzalex, Opdivo, Tagrisso, Imfinzi, Verzenio, Kisqali, Ibrance, Ozempic, Dupixent**
> 2. Plant data: create a **template schema** and populate representative assets for a **mid-tier CDMO experienced with small molecules**
> 3. Loaders: **one-time seed loaders first**, with clear **API placeholders** for future refresh
> 4. Output surface: **API must account for various inputs**, so we will design both a Streamlit UI and a thin FastAPI scoring endpoint

---

## 1. Goal of this brick

Ship a usable Patent Radar inside the existing simulator that:
- Loads patent intelligence for the 10 chosen molecules into Redis (`cdmo:patent:*`).
- Loads a representative plant asset registry into Redis (`cdmo:plant:*`).
- Renders a 3–5 year LOE horizon with FTO risk flags.
- Lets the user add/remove molecules to a candidate shortlist.
- Provides a FastAPI endpoint that scores a molecule against the four pillars (patent + regulatory placeholders + demand placeholders + plant-fit via existing simulator engine).

The existing NSQ workbench and analytics dashboard remain untouched.

---

## 2. Files to create / modify

### New files

| Path | Purpose |
|------|---------|
| `simulator/intelligence/__init__.py` | Package marker |
| `simulator/intelligence/models.py` | Pydantic/dataclass models: `MoleculeIntelligence`, `PlantAsset`, `PatentThicket`, `CandidateScore`, etc. |
| `simulator/intelligence/store.py` | Redis read/write for `cdmo:*` keys; mirrors patterns in `shared/nsq_redis.py` |
| `simulator/intelligence/scorer.py` | Four-pillar scoring; first real version uses patent + plant-fit, with placeholders for regulatory/demand |
| `simulator/intelligence/api.py` | FastAPI router for scoring endpoints |
| `simulator/intelligence/pages/patent_radar.py` | Streamlit page for Patent Radar |
| `simulator/intelligence/pages/plant_match.py` | Streamlit page for Plant Match |
| `data/patent_seed.json` | Hand-curated seed for the 10 molecules |
| `data/plant_assets_seed.json` | Representative mid-tier CDMO plant asset registry |
| `redis-loader/load_patents.py` | One-time loader for `cdmo:patent:*` |
| `redis-loader/load_plant_assets.py` | One-time loader for `cdmo:plant:*` |
| `PLAN_PHASE0.md` | This plan |

### Modified files

| Path | Change |
|------|--------|
| `simulator/app.py` | Add sidebar navigation / tabs to the new engine pages; keep existing workbench as default tab |
| `simulator/requirements.txt` | Add `fastapi`, `uvicorn` (optional API dependencies) |
| `justfile` | Add recipes: `load-patents`, `load-plant-assets`, `run-api` |
| `docker-compose.yml` | Optionally expose port 8000 for the API service |

---

## 3. Data model details

### `cdmo:patent:<molecule_key>`

Redis HASH fields:
- `molecule_key` — stable key (e.g., `pembrolizumab`, `daratumumab`)
- `brand_name` — originator brand
- `api_name` — active ingredient
- `therapeutic_area` — e.g. Oncology, Immunology, Diabetes, Dermatology
- `estimated_loe_us`, `estimated_loe_eu`, `estimated_loe_in` — ISO date strings or `YYYY-MM`
- `originator` — company
- `market_size_usd_bn` — approximate peak sales (string, for display)
- `formulation_patents` — JSON list of {description, expiry, jurisdiction, risk_level}
- `process_patents` — JSON list of {description, expiry, jurisdiction, risk_level}
- `secondary_patents` — JSON list of {description, expiry, jurisdiction, risk_level}
- `fto_risk` — `low` | `medium` | `high`
- `notes` — free text
- `source_url` — where the data came from
- `updated_at` — ISO timestamp

### `cdmo:plant:<asset_id>`

Redis HASH fields:
- `asset_id` — unique id
- `site_name` — e.g. "Baddi OSD Plant A"
- `city`, `state` — location
- `capabilities` — JSON list: `granulation`, `compression`, `film_coating`, `enteric_coating`, `blister_packing`, `bottle_packing`, `sterile_liquid`, `lyophilization`, `bioreactor`, etc.
- `approved_forms` — JSON list: `solid_oral`, `enteric_tablet`, `syrup`, `suspension`, `injection`, `ophthalmic`, etc.
- `containment_class` — e.g. `standard`, `potent`, `cytotoxic`, `biologic_GMP`
- `batch_capacity_kg` — string or number
- `certifications` — JSON list: `WHO_GMP`, `EU_GMP`, `USFDA`, `MHRA`, etc.
- `small_molecule_experience` — boolean / note
- `biologics_experience` — boolean / note
- `talent_profile` — JSON list: `formulation`, `analytical`, `regulatory`, `bioprocess`
- `equipment_highlights` — JSON list of key equipment trains
- `notes`

---

## 4. UI flow

### Simulator reorganized into tabs

Current simulator is a single-page NSQ workbench. We add a tabbed layout:
- **Workbench** — existing root-cause / grading simulator (default).
- **Patent Radar** — LOE timeline, thicket heatmap, candidate shortlist builder.
- **Plant Match** — pick a molecule + plant line, see fit score and NSQ risk overlay.
- **Portfolio** — ranked candidate list (placeholder in this brick; real scoring in Phase 1).

### Patent Radar page
1. Header: "Off-Patent Intelligence — Patent Radar".
2. LOE timeline: Plotly Gantt-like bar chart (molecule × market × LOE window).
3. Thicket table: molecule rows with FTO risk badge, patent counts, earliest LOE market.
4. "Add to shortlist" button per molecule.
5. Sidebar shortlist panel showing selected molecules and a "Score candidates" button.

### Plant Match page
1. Select molecule (from shortlist or catalog).
2. Select plant line.
3. Display:
   - Plant fit score (capability overlap).
   - Predicted NSQ flags from existing simulator engine (if we have a matching product profile).
   - Recommended Critical Quality Attributes / Critical Process Parameters.

---

## 5. FastAPI surface

A new optional Uvicorn server running inside the simulator container on port `8000`.

Endpoints (v0):
- `GET /health` — liveness.
- `POST /score` — accepts `{molecule_key, plant_asset_id, weights?}` and returns a `CandidateScore` JSON with four pillar scores, total score, and explanation.
- `GET /molecules` — list loaded molecules.
- `GET /molecules/{molecule_key}` — full intelligence for one molecule.
- `GET /plants` — list plant assets.
- `GET /plants/{asset_id}` — one plant asset.

The API will be **modular**: regulatory and demand dimensions return placeholder scores with explanatory fields, while patent and plant-fit are real.

---

## 6. Implementation sequence

### Step A — scaffold (no UI yet)
1. Create `simulator/intelligence/` package with `models.py`, `store.py`, `scorer.py`.
2. Create seed JSON files for patents and plant assets.
3. Create loaders `redis-loader/load_patents.py` and `redis-loader/load_plant_assets.py`.
4. Add `just load-patents` and `just load-plant-assets` recipes.
5. Run loaders to populate Redis.

### Step B — engine pages
6. Add tab navigation to `simulator/app.py`.
7. Implement `simulator/intelligence/pages/patent_radar.py`.
8. Implement `simulator/intelligence/pages/plant_match.py`.

### Step C — API
9. Add FastAPI router `simulator/intelligence/api.py`.
10. Add a small `simulator/api_main.py` entry point.
11. Add `just run-api` recipe and update `docker-compose.yml` to expose port 8000.

### Step D — verification
12. Manual smoke test: simulator UI still renders; Patent Radar shows 10 molecules; Plant Match returns a score; API health endpoint responds.

---

## 7. Plant asset schema assumptions (mid-tier, small-molecule CDMO)

We will create **4–6 representative assets**:
- Baddi, Himachal Pradesh — OSD solids plant (granulation → compression → coating → blister).
- Ahmedabad, Gujarat — OSD + liquid orals plant.
- Hyderabad, Telangana — sterile injectables / oncology cytotoxic suite.
- Pune, Maharashtra — pilot / R&D scale-up lab.
- A sterile biologics placeholder flagged as "not yet qualified" (to explain why mAbs are high-risk for this CDMO).

This gives the engine a realistic "fit" signal: most mAb candidates will score low on plant-fit, while small-molecule oncology orals may fit well.

---

## 8. Patent seed assumptions

The 10 molecules are all high-value biologics / small molecules. For the seed we will capture:
- API/generic name.
- Originator company.
- Primary therapeutic area.
- Approximate LOE windows based on publicly known data (US/EU/India).
- Known formulation / device / secondary patent risks.
- FTO risk level.

Data will be hand-curated in `data/patent_seed.json`. We will flag the source as "publicly reported LOE estimates; to be refreshed via FDA Orange Book / EMA / India IPO APIs in later phase."

---

## 9. Backwards compatibility

- The existing `PRODUCT_CATALOG`, grading engine, and session state stay unchanged.
- New tabs are additive.
- New Redis keys (`cdmo:*`) are independent of `nsq:*` keys; `just clean` will be documented to only wipe `nsq:*` by default, with a separate recipe to wipe `cdmo:*` if needed.

---

## 10. Open items before coding

1. Should the **FastAPI server run as a separate container** or as an optional second process inside the existing simulator container? (I recommend the latter for this brick to keep the Compose file simple, with a clear path to split later.)
2. Should the patent seed include **India-specific LOE estimates** for these molecules, or global US/EU/India triad? (I recommend the triad.)
3. Do you want the **Plant Match page** to reuse the existing 16-drug simulator catalog for NSQ risk overlay, or should we expand the catalog to cover some of these 10 molecules? (I recommend keeping the existing catalog for now and showing a "no direct NSQ profile" fallback.)

Please confirm or adjust these choices, and I will begin implementation.
