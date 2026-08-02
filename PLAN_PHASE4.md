# Phase 4 Implementation Plan
## Plant Expertise & Shop-Floor AI — Manufacturing Readiness & Roadmaps

> **Goal:** Move beyond a single plant-fit score to an actionable **manufacturing readiness evaluation** that tells the CDMO whether it can make a complex off-patent molecule or biosimilar, and if so, what roadmap is required.

> **Context from user:**
> Logic flow: **patent mining data → biochemistry drug analytics (modality, form, etc.) → customer profile fit (commercial fit, current infra, experience, talent)** →
> - For off-patent small molecules: roadmap creation (buy or build active; supply-chain resilience; potential govt support); scale-up plan.
> - For biosimilars: protocol design, development & testing; scale-up plan.

---

## 1. What we are building

### A. Biochemistry drug analytics layer

Derive a `ManufacturingComplexity` profile for each molecule from existing patent, regulatory, and demand data:

| Dimension | Examples |
|-----------|----------|
| `modality` | small_molecule, monoclonal_antibody, peptide, recombinant_protein, fusion_protein |
| `drug_form` | tablet, capsule, enteric_tablet, injection, prefilled_pen, prefilled_syringe, vial, lyophilized_vial |
| `route_of_administration` | oral, subcutaneous, iv, intramuscular, ophthalmic |
| `sterility_required` | true for injectables/biologics |
| `potency_classification` | standard, potent, cytotoxic, high_potency, biologic |
| `critical_quality_attributes` | e.g. dissolution, acid_resistance, content_uniformity, aggregates, glycosylation |
| `process_complexity_score` | 1–10 derived from form + CQAs |
| `analytical_complexity_score` | 1–10 derived from monographs + bioequivalence/biosimilarity requirements |

This layer lives in `engine/shared/intelligence_models.py` as `ManufacturingComplexity` and is generated on demand rather than hand-curated, so it stays in sync with patent/regulatory/demand updates.

### B. Customer profile fit

Extend the plant asset model to capture CDMO readiness depth:

| Field | Meaning |
|-------|---------|
| `equipment_trains` | List of {name, capability, capacity, readiness_level, gmp_status} |
| `talent_depth` | {formulation, analytical, regulatory_affairs, bioprocess, quality} each 0–100 |
| `certifications_active` | WHO-GMP, EU-GMP, USFDA, MHRA, etc. |
| `containment_class` | standard, potent, cytotoxic, biologic_GMP |
| `small_molecule_experience` | years / notable molecules |
| `biologics_experience` | years / biosimilar programs |
| `commercial_fit_tier` | `strategic`, `core`, `adjacent`, `stretch` inferred from capabilities |

A new `score_customer_profile_fit(molecule_complexity, plant_asset)` returns a 0–100 fit score plus a structured explanation:
- **Commercial fit tier** — how close the molecule is to the plant's core business.
- **Infrastructure gaps** — missing equipment/capability.
- **Talent gaps** — missing skill sets.
- **Certification gaps** — missing market-access certifications.

### C. Branching roadmaps

Based on modality, generate a `ManufacturingRoadmap` object:

#### Off-patent small molecules

| Phase | Activity | Inputs |
|-------|----------|--------|
| 1. API strategy | Make-vs-buy decision; supply-chain resilience; government support eligibility (PLI, DENA, state schemes) | API complexity, current API supplier relationships, geopolitical risk |
| 2. Formulation development | Excipient selection, process parameter design space, QbD around CQAs | BCS class, stability, monographs, NSQ history |
| 3. Analytical method transfer | HPLC/UV/dissolution/impurity method setup | IP/Ph.Eur./USP monographs |
| 4. Scale-up plan | Pilot → tech transfer → commercial batches; equipment train mapping | Plant capacity, batch_size_kg |
| 5. Regulatory filing support | ANDA/Dossier prep, BE study management | TE rating, RLD, exclusivity |
| 6. Shop-floor AI / NSQ prevention | Predictive failure diagnostics using existing simulator engine | NSQ alert history, ideal process parameters |

#### Biosimilars

| Phase | Activity | Inputs |
|-------|----------|--------|
| 1. Reference product characterization | Analytical/functional similarity package | RLD, dosage form, originator data |
| 2. Cell-line / process development | Clone selection, upstream/downstream design | mAb/peptide modality |
| 3. Protocol design | Physicochemical, biological, immunogenicity assays | Biosimilar guidelines (FDA/EMA/WHO) |
| 4. Development & testing | Head-to-head comparability, stability, forced degradation | Analytical complexity |
| 5. Clinical / PK-PD immunogenicity | Totality-of-evidence package | Regulatory exclusivity dates |
| 6. Scale-up plan | Bioreactor train, aseptic fill/finish, lyophilization | Plant biologics capability |

### D. UI page: Plant Readiness & Roadmap

New simulator tab:
1. Select a molecule.
2. Select a plant line.
3. Show **biochemistry analytics** (modality, form, sterility, CQAs, complexity scores).
4. Show **customer profile fit** (commercial fit tier, infra/talent/cert gaps).
5. Show **branching roadmap** (small-molecule or biosimilar path) with expandable phases.
6. Show **four-pillar score** and plant-fit score with warnings.
7. Highlight **NSQ/QbD risk** from the existing simulator engine where the molecule exists in the catalog.

---

## 2. Files to create / modify

### New files

| Path | Purpose |
|------|---------|
| `simulator/intelligence/pages/plant_readiness.py` | Streamlit page for Plant Readiness & Roadmap |

### Modified files

| Path | Change |
|------|--------|
| `engine/shared/intelligence_models.py` | Add `ManufacturingComplexity`, `ManufacturingRoadmap`, extend `PlantAsset` with `equipment_trains`, `talent_depth`, `certifications_active` |
| `engine/shared/intelligence_store.py` | Add serialization for new PlantAsset fields; add helpers for complexity/roadmap if persisted |
| `engine/shared/intelligence_scorer.py` | Add `derive_manufacturing_complexity`, `score_customer_profile_fit`, `build_manufacturing_roadmap`; integrate into `score_candidate` |
| `engine/api_main.py` | Add `/molecules/{key}/complexity`, `/molecules/{key}/roadmap`, `/plants/{id}/fit/{key}` endpoints |
| `data/plant_assets_seed.json` | Enrich 5 plants with equipment trains and talent depth |
| `simulator/intelligence/api_client.py` | Add client methods for complexity/roadmap/fit endpoints |
| `simulator/app.py` | Add "🛠️ Plant Readiness" tab |
| `simulator/intelligence/intelligence_*.py` | Sync copies from `engine/shared/` |

---

## 3. Data model additions

### `ManufacturingComplexity`

```python
class ManufacturingComplexity(BaseModel):
    molecule_key: str
    modality: str
    drug_form: str
    route_of_administration: str
    sterility_required: bool = False
    potency_classification: str = "standard"
    critical_quality_attributes: list[str] = []
    process_complexity_score: float = 0.0  # 1–10
    analytical_complexity_score: float = 0.0  # 1–10
    biologic_complexity_score: float = 0.0  # 1–10
    notes: str = ""
```

### `ManufacturingRoadmap` (generated)

```python
class RoadmapPhase(BaseModel):
    phase_id: str
    title: str
    modality: str  # small_molecule | biosimilar
    activities: list[str]
    deliverables: list[str]
    estimated_duration_months: int
    readiness_gates: list[str]
    required_capabilities: list[str]

class ManufacturingRoadmap(BaseModel):
    molecule_key: str
    plant_asset_id: str
    modality: str
    commercial_fit_tier: str  # strategic | core | adjacent | stretch
    customer_profile_fit_score: float  # 0–100
    infrastructure_fit_score: float
    talent_fit_score: float
    certification_fit_score: float
    phases: list[RoadmapPhase]
    gaps: list[str]
    government_support_notes: str = ""
    nsq_risk_notes: str = ""
```

### `PlantAsset` enrichment

Add:
- `equipment_trains: list[dict]`
- `talent_depth: dict[str, float]`
- `certifications_active: list[str]`
- `api_sourcing_experience: bool`
- `biologics_experience: str` (years / description)
- `small_molecule_experience: str` (years / description)

---

## 4. Scoring logic

### Manufacturing complexity derivation

Heuristic rules:
- Small-molecule oral solid: base process 3–5, analytical 3–5.
- Enteric-coated / acid-labile / low-dose / bilayer: process +2–3, analytical +2.
- mAb / biosimilar: process 8–10, analytical 8–10, biologic 8–10.
- Peptide / prefilled pen: process 7–9, analytical 7–9.
- Sterile liquid / injectable: sterility true, potency high if oncology.

### Customer profile fit

For each required capability from the complexity profile, check plant capability + equipment train + talent:
- Infrastructure fit = matched required capabilities / total required.
- Talent fit = average of relevant talent_depth scores.
- Certification fit = certifications needed for target markets / available.
- Commercial fit tier:
  - `strategic`: plant has direct experience in same modality + form.
  - `core`: plant has most capabilities and certifications.
  - `adjacent`: plant has some capabilities but needs investment.
  - `stretch`: major capability/certification/talent gaps.

### Roadmap generation

Small-molecule path (6 phases):
1. API sourcing strategy
2. Formulation development
3. Analytical method transfer
4. Scale-up / tech transfer
5. Regulatory / BE support
6. Shop-floor AI / NSQ prevention

Biosimilar path (6 phases):
1. Reference product characterization
2. Cell-line / process development
3. Protocol design
4. Development & testing
5. Clinical / PK-PD / immunogenicity
6. Scale-up / fill-finish / launch

---

## 5. API additions

- `GET /molecules/{key}/complexity` — derived manufacturing complexity.
- `GET /molecules/{key}/roadmap?plant_asset_id={id}` — generated roadmap.
- `GET /plants/{id}/fit/{key}` — customer profile fit summary.
- `POST /score` — returns four-pillar score plus `roadmap_hint` and `manufacturing_complexity` notes.

---

## 6. UI / UX additions

### New tab: Plant Readiness & Roadmap

- Molecule selector (same pool as Demand Radar).
- Plant selector.
- **Biochemistry analytics card**: modality, form, sterility, potency, CQAs, complexity scores.
- **Customer profile fit card**: tier badge, infra/talent/cert fit scores, gap list.
- **Roadmap accordion**: phase title, duration, activities, deliverables, readiness gates.
- **NSQ/QbD risk card**: if the molecule exists in the simulator `PRODUCT_CATALOG`, show top NSQ alerts and ideal process parameters.
- **Four-pillar score** with updated plant-fit explanation.

---

## 7. Implementation sequence

1. Enrich `PlantAsset` model and `data/plant_assets_seed.json` with equipment trains + talent depth.
2. Add `ManufacturingComplexity` model + derivation function.
3. Add `ManufacturingRoadmap` + `RoadmapPhase` models.
4. Implement `score_customer_profile_fit` and `build_manufacturing_roadmap`.
5. Update `intelligence_store.py` serialization for new PlantAsset fields.
6. Add API endpoints.
7. Sync to `simulator/intelligence/`.
8. Build `simulator/intelligence/pages/plant_readiness.py`.
9. Update `simulator/app.py` with new tab.
10. Reload plant assets, test API/UI, build Docker images.

---

## 8. Success metrics

- `/molecules/{key}/complexity` returns modality/form/CQAs for all 26 molecules.
- `/molecules/{key}/roadmap?plant_asset_id={id}` returns a branched roadmap (small molecule vs biosimilar).
- Plant-fit score now explains infrastructure, talent, and certification gaps.
- Small-molecule roadmaps include API buy/build decision and government-support note.
- Biosimilar roadmaps include protocol design and development/testing phases.
- Streamlit Plant Readiness tab renders without errors.
- Docker images build and compose stack stays healthy.

---

---

## 9. Completion status

| Step | Status | Notes |
|------|--------|-------|
| Enrich `PlantAsset` model and seed JSON | ✅ Done | `data/plant_assets_seed.json` reloaded to `cdmo:plant:*` |
| Add `ManufacturingComplexity` model + derivation | ✅ Done | `/molecules/{key}/complexity` returns modality/form/CQAs for all 26 molecules |
| Add `ManufacturingRoadmap` + `RoadmapPhase` models | ✅ Done | 6-phase small-molecule and biosimilar roadmaps generated |
| Implement `score_customer_profile_fit` | ✅ Done | Returns infra/talent/cert scores + commercial fit tier + gaps |
| Implement `build_manufacturing_roadmap` | ✅ Done | Includes government support notes for small molecules |
| Update `intelligence_store.py` serialization | ✅ Done | New PlantAsset fields + complexity helpers |
| Add API endpoints | ✅ Done | `/complexity`, `/roadmap`, `/plants/{id}/fit/{key}` registered and smoke-tested |
| Sync to `simulator/intelligence/` | ✅ Done | `intelligence_scorer.py` synced after import fix |
| Build `plant_readiness.py` | ✅ Done | Streamlit page created with analytics, fit, roadmap, and four-pillar score |
| Update `simulator/app.py` | ✅ Done | New "🛠️ Plant Readiness" tab wired in |
| Reload plant assets / test API | ✅ Done | Engine running locally; complexity/roadmap/fit/score endpoints pass |
| Build Docker images | ✅ Done | Started Docker Desktop; `docker compose build` produced `nsq-engine:local`, `nsq-simulator:local`, `nsq-analytics:local` |
| Run compose stack | ✅ Done | `docker compose up -d`; all three containers healthy |
| Verify UI in container | ✅ Done | Simulator container imports `plant_readiness`; health checks pass |

### Smoke-test results (containerized stack)

All tests run against the Docker Compose stack on ports 8000 (engine), 8501 (analytics), 8502 (simulator):

- `GET /molecules/amlodipine_besylate/complexity` → small_molecule, tablet, CQAs, scores.
- `GET /molecules/daratumumab/complexity` → monoclonal_antibody, vial, sterility, scores.
- `GET /molecules/amlodipine_besylate/roadmap?plant_asset_id=baddi-osd-a` → 31 mo small-molecule roadmap, strategic tier, fit 82.
- `GET /molecules/daratumumab/roadmap?plant_asset_id=mumbai-biologics-placeholder` → 84 mo biosimilar roadmap, adjacent tier, fit 45.
- `GET /plants/baddi-osd-a/fit/amlodipine_besylate` → complexity + customer profile fit.
- `POST /score` for amlodipine × Baddi → total 80.7.
- `curl http://localhost:8502/_stcore/health` → `ok`.
- `docker exec nsq-simulator python -c "from intelligence.pages import plant_readiness"` → imports cleanly.

### Fix applied during testing

- Added missing `load_plant_asset` import to `engine/shared/intelligence_scorer.py` (used by `evaluate_manufacturing_readiness`) and synced to `simulator/intelligence/intelligence_scorer.py`.

*Plan version 1.0 — 2026-07-30*
