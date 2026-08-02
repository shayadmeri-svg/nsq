# Phase 2 Implementation Plan
## Regulatory Passport + Geography-Aware LOE Timeline

> **Goal:** Make the regulatory pillar real and add geography-level patent coverage so the CDMO can see **which countries a molecule can be exported to**, **when LOE happens in each market**, and **the Orange Book-style regulatory context** (TE codes, RLD, exclusivity, pharmacopeia monographs).
>
> **Scope:** all 26 molecules already seeded (10 branded + 16 generic/off-patent).

---

## 1. What we are building

### A. Geography-aware patent coverage

Extend the patent pillar from three regional LOE dates (US/EU/IN) to a per-country `geo_coverage` table:

| Country | ISO code | Market status | LOE date | Export eligible? | Patent barrier | Notes |
|---------|----------|---------------|----------|------------------|----------------|-------|
| United States | US | `patented` / `loe_pending` / `off_patent` / `export_eligible` | 2028-09-01 | Yes / No | formulation + device | Keytruda composition + device patents |
| European Union | EU | ... | ... | ... | ... | ... |
| India | IN | ... | ... | ... | ... | ... |
| Japan | JP | ... | ... | ... | ... | ... |
| Canada | CA | ... | ... | ... | ... | ... |
| Brazil | BR | ... | ... | ... | ... | ... |
| UK | GB | ... | ... | ... | ... | ... |
| Australia | AU | ... | ... | ... | ... | ... |

A country is **export eligible** when the molecule is either already off-patent there or within the LOE-preparation window and no blocking secondary/device patents are flagged.

### B. Regulatory Passport (Pillar B)

A new `cdmo:regulatory:<molecule_key>` hash with:

- **Pharmacopeia monographs**
  - `ip_2026_monograph` — Indian Pharmacopoeia 2026 method
  - `ph_eur_monograph` — European Pharmacopoeia monograph
  - `usp_monograph` — USP monograph / general chapter
- **Orange Book / reference information**
  - `rld` — Reference Listed Drug brand name
  - `rld_applicant` — RLD applicant (originator)
  - `te_code` — Therapeutic Equivalence code, e.g. `AB1`, `AB2`, `BX`
  - `te_rating` — `A` or `B`
  - `dosage_form` — tablet, injection, vial, etc.
  - `strength` — e.g. 40 mg
- **FDA / regulatory exclusivity**
  - `exclusivity` — JSON list of `{type, expiry_date, description}`
  - Types: `NCE` (New Chemical Entity), `ODE` (Orphan Drug Exclusivity), `PED` (Pediatric Exclusivity), `GAN` (Generics Applications), `Biosimilar`.
- **Quality / development context**
  - `bcs_class` — BCS I / II / III / IV
  - `analytical_specs` — list of assay / dissolution / impurity methods
  - `stability_conditions` — ICH zones, storage
  - `bioequivalence_notes` — any known BE complexities
  - `source_url`
  - `readiness` — `placeholder` | `partial` | `ready`

### C. Scoring upgrade

Replace the placeholder `regulatory_clarity_score = 50` with a real score based on:

| Factor | Max points | Logic |
|--------|-----------|-------|
| Monograph coverage | 30 | +10 per available IP/Ph.Eur./USP monograph |
| TE rating | 25 | `A` rating = 25; `B` rating = 10; none = 15 |
| Exclusivity blockers | -20 | Active exclusivity still in force reduces score |
| Export-eligible geographies | 15 | +points per eligible country, capped |
| BCS / development maturity | 10 | Known BCS class and stability conditions |
| Base knowledge | 20 | Having a regulatory record at all |

For the 16 generic molecules, this should produce high regulatory clarity (off-patent, known monographs, AB TE codes). For the 10 branded molecules, scores will vary based on remaining exclusivity and Orange Book data.

---

## 2. Files to create / modify

### New files

| Path | Purpose |
|------|---------|
| `data/regulatory_seed.json` | Hand-curated regulatory passports for 26 molecules |
| `redis-loader/load_regulatory.py` | Loader for `cdmo:regulatory:*` |
| `simulator/intelligence/pages/regulatory_passport.py` | Streamlit Regulatory Passport page |

### Modified files

| Path | Change |
|------|--------|
| `engine/shared/intelligence_models.py` | Add `GeoCoverage` model; extend `PatentIntelligence` with `geo_coverage`; flesh out `RegulatoryPassport`; update serialization |
| `engine/shared/intelligence_store.py` | Add `cdmo:regulatory:*` read/write helpers |
| `engine/shared/intelligence_scorer.py` | Implement real `score_regulatory`; update `score_candidate` to load regulatory data |
| `engine/api_main.py` | Add `/regulatory`, `/molecules/{key}/regulatory`, `/molecules/{key}/geo`, `/refresh-orange-book/{key}` placeholder |
| `simulator/intelligence/api_client.py` | Add client methods for regulatory endpoints |
| `simulator/intelligence/pages/patent_radar.py` | Show export-eligible geography count and per-molecule geo table |
| `simulator/app.py` | Add "Regulatory Passport" tab |
| `redis-loader/load_patents.py` | Parse and persist `geo_coverage` from patent seed |
| `data/patent_seed.json` | Add `geo_coverage` arrays to each molecule |
| `justfile` | Add `load-regulatory` recipe and update `load-intelligence` |
| `simulator/intelligence/intelligence_*.py` | Sync copies from `engine/shared/` |

---

## 3. Data model additions

### `GeoCoverage`

```python
class GeoCoverage(BaseModel):
    country_code: str          # ISO 3166-1 alpha-2, e.g. "US"
    country_name: str
    market_status: str         # patented | loe_pending | off_patent | export_eligible
    loe_date: Optional[date]
    export_eligible: bool
    patent_barrier: str        # none | composition | formulation | process | device | secondary
    notes: str = ""
```

### `RegulatoryPassport` (expanded)

```python
class RegulatoryPassport(BaseModel):
    molecule_key: str
    ip_2026_monograph: str = ""
    ph_eur_monograph: str = ""
    usp_monograph: str = ""
    analytical_specs: list[str] = []
    stability_conditions: str = ""
    bcs_class: str = ""
    rld: str = ""
    rld_applicant: str = ""
    te_code: str = ""
    te_rating: str = ""        # A | B | ""
    dosage_form: str = ""
    strength: str = ""
    exclusivity: list[dict] = []
    bioequivalence_notes: str = ""
    readiness: str = "placeholder"
    source_url: str = ""
    notes: str = ""
```

---

## 4. Seed data assumptions

We will hand-curate two seed files:

1. **`data/patent_seed.json`** — add `geo_coverage` to each molecule.
   - For branded molecules: 8 core markets (US, EU, IN, JP, CA, BR, GB, AU) with appropriate status and barrier.
   - For generic molecules: status `off_patent` / `export_eligible` in all 8 markets, no LOE date needed.

2. **`data/regulatory_seed.json`** — regulatory passport per molecule.
   - For the 16 generic molecules: full monograph info (IP 2026 + Ph. Eur. where known), `te_rating: A`, no exclusivity, `readiness: ready`.
   - For the 10 branded molecules: RLD = originator brand, TE code placeholder (e.g. `BX` or expected future `AB3`), exclusivity entries with expiry, `readiness: partial`.

Both files will carry a `_comment` stating that data is hand-curated from public sources and that live FDA Orange Book / EMA / IP 2026 refresh will be added in a later phase.

---

## 5. UI / UX additions

### New tab: Regulatory Passport

1. Molecule selector.
2. **Geography table** with color-coded market status and export-eligible filter.
3. **Export-eligible countries** badge list.
4. **Pharmacopeia cards** (IP 2026, Ph. Eur., USP).
5. **Orange Book section**: RLD, TE code + rating, dosage form/strength, exclusivity table.
6. **Development context**: BCS class, stability, analytical specs, BE notes.
7. **Regulatory clarity score** with explanation.

### Patent Radar update

- Each molecule card will show a new line: **“Export eligible in N markets.”**
- Expandable per-molecule geography table.

---

## 6. API additions

- `GET /regulatory` — list all regulatory passports (summary).
- `GET /molecules/{key}/regulatory` — full regulatory passport.
- `GET /molecules/{key}/geo` — geo coverage for a molecule.
- `POST /score` — remains the same but now uses real regulatory scoring.
- `POST /refresh-orange-book/{key}` — **placeholder** that returns a message explaining future live-FDA-Orange-Book integration.

---

## 7. Implementation sequence

1. Update `intelligence_models.py` with new models and serialization.
2. Update `intelligence_store.py` with regulatory helpers.
3. Implement real `score_regulatory` in `intelligence_scorer.py`.
4. Update `load_patents.py` to parse `geo_coverage` and add geo data to `data/patent_seed.json`.
5. Create `data/regulatory_seed.json`.
6. Create `redis-loader/load_regulatory.py` and add `just load-regulatory`.
7. Update `api_main.py` with new endpoints.
8. Sync files to `simulator/intelligence/`.
9. Create `simulator/intelligence/pages/regulatory_passport.py`.
10. Update `patent_radar.py` and `simulator/app.py`.
11. Run loaders, test API, build Docker images.

---

## 8. Success metrics

- `/molecules/{key}/geo` returns ≥8 country rows per branded molecule.
- `/molecules/{key}/regulatory` returns monograph, RLD, TE code, and exclusivity data.
- Regulatory clarity score is no longer a fixed placeholder; generic molecules score ≥80, branded molecules score according to exclusivity/monograph state.
- Streamlit Regulatory Passport tab renders without errors.
- Existing NSQ Workbench and Patent Radar continue to work.

---

## 9. Completion status

All Phase 2 bricks implemented and smoke-tested on 2026-07-30:

- Seed data created for 26 molecules: `data/patent_seed.json` (with 10-country `geo_coverage`) and `data/regulatory_seed.json`.
- Loaders built: `redis-loader/load_patents.py`, `load_plant_assets.py`, `load_regulatory.py`.
- Redis populated with `cdmo:patent:*`, `cdmo:plant:*`, and `cdmo:regulatory:*` keys.
- FastAPI endpoints live: `/molecules`, `/molecules/{key}`, `/molecules/{key}/geo`, `/molecules/{key}/regulatory`, `/regulatory`, `/plants`, `/score`, `/refresh-orange-book/{key}`.
- Scoring upgraded: real `score_regulatory` based on monographs, TE rating, exclusivity, export-eligible geographies, and BCS/stability maturity.
- Streamlit tab added: **Regulatory Passport**; Patent Radar shows export-eligible market counts.
- Docker images built and `docker compose up` verified (engine, simulator healthy).

Sample smoke-test results:
- `GET /health` → `{"status": "ok", "redis_ready": true}`
- `GET /molecules` → 26 molecules
- `GET /regulatory` → 26 passports
- `GET /molecules/pembrolizumab/geo` → 10 countries, 0 export-eligible (device barrier)
- `GET /molecules/paracetamol/geo` → 10 countries, 10 export-eligible
- `POST /score` for paracetamol/baddi-osd-a → total 69.0, regulatory 85.0
- `POST /score` for pembrolizumab/baddi-osd-a → total 36.0, regulatory 10.0 (active exclusivity + biologic plant mismatch)

*Plan version 1.0 — 2026-07-30*
