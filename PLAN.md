# Off-Patent Drug Intelligence Engine — Long-Horizon Iteration Plan

> **Goal:** Evolve the existing `simulator` (In-Silico NSQ Agent / GMP workbench, port 8502) into a four-pillar decision engine that helps a CDMO pick, prepare, and flawlessly manufacture off-patent / LOE (Loss of Exclusivity) molecules.
>
> **Principles:**
> 1. Brick-by-brick delivery: each phase ships a usable increment.
> 2. Reuse before rewrite: plant-expertise / QbD AI reuses the simulator engine.
> 3. Backward compatible: the existing NSQ root-cause workbench keeps working.
> 4. Data-grounded: new intelligence layers are persisted alongside the existing Redis-backed CDSCO corpus.

---

## 1. Vision: four pillars mapped to the current stack

| Pillar | What the engine must do | Where it lives / starts | Existing asset to reuse |
|--------|------------------------|-------------------------|--------------------------|
| **A. Patent Intelligence** | Global LOE calendar, formulation/secondary patent thicket mapping, FTO scoring, early-launch window (3–5 yr horizon). | New module `intelligence/patents` + UI page in simulator. | Company/product ontologies; date parsing from `Reporting Month & Year`. |
| **B. Market Access & Regulatory Rules** | EP 2026 / IP 2026 monograph mapping, test protocols, dissolution/apparatus limits, analytical specs per molecule. | Extend simulator `Drug` model + analytics research profiles. | `TestingGuidelines`, `RESEARCH_PROFILES`, IP/Ph.Eur fields in simulator. |
| **C. Multi-Factor Demand Trends** | Disease burden, trial pipeline, buyer/wholesaler signals, target clusters (oncology, specialty injectables, lifestyle). | New module `intelligence/demand` + demand scorecard. | Form/Indication/Drug type classifiers in analytics. |
| **D. Plant Expertise & Shop-Floor AI** | Match molecule to plant capability (equipment, talent, facility footprint) and run real-time QbD/NSQ prevention. | New simulator page + asset ontology. | Entire simulator grading engine, excipient/parameter model, live CDSCO overlay. |

The final engine surfaces a **portfolio ranking**: for every candidate molecule it returns a single decision score combining patent readiness, regulatory clarity, demand attractiveness, and manufacturing fit, plus a risk-adjusted launch window.

---

## 2. Target architecture (evolutionary)

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit apps (Docker Compose)                              │
│  • analytics  :8501  (unchanged CDSCO dashboard)              │
│  • simulator  :8502  (engine UI)                            │
│       ├─ NSQ Workbench     (existing, preserved)             │
│       ├─ Patent Radar      (new)                              │
│       ├─ Regulatory Rules  (new, extends D1 pharmacopeia)   │
│       ├─ Demand Signals    (new)                              │
│       └─ Plant Match + QbD (extends existing D2/D3/D5)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Redis keyspace (existing)                                    │
│  • nsq:record:*, nsq:records, nsq:meta                        │
│  • nsq:ontology:companies, nsq:ontology:products             │
│  • geo:india_states                                           │
│  NEW keys:                                                    │
│  • cdmo:patent:<molecule>  (LOE, patents, FTO)               │
│  • cdmo:regulatory:<molecule> (monographs, specs)             │
│  • cdmo:demand:<molecule>   (disease, trial, buyer signals)    │
│  • cdmo:plant:<asset>       (equipment, lines, certifications)│
│  • cdmo:portfolio           (ranked candidates)              │
└─────────────────────────────────────────────────────────────┘

New loader scripts under redis-loader/:
  • load_patents.py       (seed patent intelligence)
  • load_demand.py        (seed demand signals)
  • load_plant_assets.py  (seed plant capability master)
```

The company/product ontologies already in Redis are reused for molecule and manufacturer canonicalization, so intelligence data joins cleanly onto the CDSCO alert corpus.

---

## 3. Phased roadmap

### Phase 0 — Foundation (week 1)
**Deliverable:** clean project scaffold, shared library split, and a minimal intelligence registry.

- Create `intelligence/` package inside the simulator service (or shared?) with submodules:
  - `intelligence/models.py` — pydantic/dataclass models for Patent, Regulatory, Demand, PlantAsset, CandidateScore.
  - `intelligence/store.py` — Redis read/write helpers for `cdmo:*` keys.
  - `intelligence/scorer.py` — first portfolio scoring function.
- Add a new simulator sidebar section / top-level tabs for the engine.
- Add `just` recipes: `load-patents`, `load-demand`, `load-plant-assets`, `sync-shared` extended.
- Keep the existing `PRODUCT_CATALOG` and NSQ workbench untouched; new code sits behind feature flags where possible.

**Definition of done:** simulator still passes manual smoke test; a new "Intelligence" tab renders with empty-state placeholder; loader scaffolding is present.

### Phase 1 — Patent Intelligence (weeks 2–4)
**Deliverable:** molecule-level LOE calendar + FTO heatmap.

- Build a seed dataset of ~50–100 high-value molecules (priority: oncology, specialty injectables, lifestyle) with:
  - active ingredient key (matches existing `product_key()`),
  - originator market/key patents,
  - estimated LOE date by market (US, EU, India),
  - known formulation / process / secondary patents,
  - FTO risk flag (green/yellow/red).
- Loader writes `cdmo:patent:<key>` hashes.
- UI page: patent radar with:
  - LOE timeline (3–5 year horizon),
  - defensive thicket visualization,
  - click-to-add molecule to candidate shortlist.
- Add a first scoring dimension: `patent_readiness_score` (0–100).

**Data assumptions:** seed from public sources (FDA Orange Book, EMA EPAR, PatentScope/WIPO, India IPO). Later phases can add scheduled refresh via APIs.

### Phase 2 — Market Access & Regulatory Rules (weeks 5–7)
**Deliverable:** IP 2026 / Ph. Eur. monograph + test protocol matcher.

- Extend the simulator `Drug` dataclass with structured regulatory fields:
  - `monographs: dict[str, TestingGuidelines]` keyed by pharmacopeia (IP 2026, Ph. Eur., USP),
  - `analytical_specs`, `stability_conditions`, `BCS_class`.
- Build a regulatory rules registry in Redis: `cdmo:regulatory:<key>`.
- UI page: regulatory passport for a selected molecule.
- Add `regulatory_clarity_score` dimension.
- Reuse existing simulator pharmacopeia panels (D1) and enrich them beyond the current 16-drug catalog.

### Phase 3 — Multi-Factor Demand Trends (weeks 8–10)
**Deliverable:** demand signal scorecard and cluster targeting.

- Build `cdmo:demand:<key>` with dimensions:
  - disease prevalence / trend (India + global),
  - clinical trial pipeline phase/count,
  - buyer/institution activity proxy (where available),
  - therapeutic cluster label: oncology / specialty injectable / lifestyle / other.
- UI page: demand radar + cluster filter.
- Add `demand_attractiveness_score`.
- Link to analytics app classification (`Indication`, `Form`, `Drug type`) for validation.

### Phase 4 — Plant Expertise & Shop-Floor AI Integration (weeks 11–13)
**Deliverable:** molecule-to-plant matching + real-time QbD/NSQ prevention dashboard.

- Build `cdmo:plant:<asset_id>` registry describing:
  - equipment train (granulation, compression, coating, sterile fill, lyophilization, etc.),
  - cleanroom / containment classes,
  - approved dosage forms,
  - talent/certification footprint,
  - facility location.
- Reuse simulator grading engine to compute a `manufacturing_risk_score` for a candidate molecule on a given plant line.
- Match molecule requirements (process type, dosage form, containment, analytical specs) to plant capabilities → `plant_fit_score`.
- New UI: "Plant Match" — select molecule + plant line, see fit score, predicted NSQ flags, recommended CQA/CPP guardrails.
- Merge live CDSCO overlay with candidate scoring so high-NSQ molecules raise the risk premium.

### Phase 5 — Portfolio Decision Engine (weeks 14–16)
**Deliverable:** ranked candidate portfolio with explainable decision cards.

- Combine the four pillar scores into a weighted `cdmo_score`:
  - Patent readiness (25%)
  - Regulatory clarity (20%)
  - Demand attractiveness (25%)
  - Plant fit / manufacturing risk (30%)
  (weights are configurable in the UI.)
- UI page: portfolio builder — add/remove candidates, adjust weights, sort, export.
- Persist candidate shortlists in Redis: `cdmo:portfolio:<portfolio_id>`.
- Add CSV/JSON export and a "launch calendar" Gantt-like view.

### Phase 6 — Hardening, feedback loop, and optional API (weeks 17+)
**Deliverable:** production-grade monitoring, user feedback capture, and a thin REST API.

- Add unit tests for scoring and matching logic.
- Capture user overrides (e.g., user changes a patent date or LOE status) back to Redis.
- Add a lightweight FastAPI service inside the simulator container for headless scoring.
- Document data refresh cadence and source provenance.

---

## 4. First brick to build (Phase 0 + Phase 1 start)

We will begin with the smallest end-to-end slice:

1. Scaffold `intelligence/` inside `simulator/`.
2. Pick 10 high-value molecules (e.g., oncology injectables, lifestyle blockbusters with known near-LOE windows) and hand-curate a patent seed file (`data/patent_seed.json`).
3. Implement `redis-loader/load_patents.py` that writes `cdmo:patent:<key>` hashes.
4. Add a Patent Radar page to the simulator that renders a 3-year LOE horizon.
5. Add a candidate shortlist in session state that can later feed the portfolio engine.

This delivers visible value immediately while leaving the existing simulator untouched.

---

## 5. Open questions / decisions for the user

1. **Molecule scope:** Should the first seed focus on India-market LOE, global LOE, or a specific therapeutic cluster (oncology, specialty injectables, lifestyle)?
2. **Plant data:** Do you have an existing plant/equipment master file, or should we create a template schema and populate it with representative CDMO assets?
3. **Data refresh:** Are we building one-time seed loaders first, or do you need scheduled/API-driven refresh from sources like FDA Orange Book / clinicaltrials.gov / WIPO?
4. **Monetization boundary:** Is the simulator-only UI sufficient for the first iteration, or do you also need a headless API/scoring endpoint for other tools?

---

## 6. Success metrics

- All existing simulator and analytics functionality remains intact.
- Patent Radar renders ≥10 molecules with LOE windows and FTO risk flags.
- A candidate molecule can be scored across all four pillars within 16 weeks.
- Engine produces an explainable `cdmo_score` with per-pillar breakdown.
- Plant-match page links molecule, plant line, and predicted NSQ risk.

---

*Plan version 1.0 — initialized 2026-07-30*
