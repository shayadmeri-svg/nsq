# Ontology & Derived-Field Review — Findings Report

**Branch:** `offpatentdi` · **Date:** 2026-09-24 · **Status:** analysis only — no code changes made
**Purpose:** groundwork for the L0–L4 product ontology (breaking change) + deduplication of derived-field logic. Prepared for review; numbers verified against the repo on this date.

---

## 1. Proposed ontology (user-supplied definition)

Five levels, per NSQ record:

| Level | Definition | Example |
|---|---|---|
| L0 | Therapeutic type (`|`-separated if multiple, do not merge if same) | `Other`, `Unmapped`, `Unmapped \| Other` |
| L1 | Drug type / drug class (ATC) | `HMG CoA reductase inhibitors`, `Dihydropyridine derivatives` |
| L2 | Drug name (ATC-pinned INN) | `Atorvastatin`, `Telmisartan \| Amlodipine` |
| L3 | General product name = drug name(s) + form | `Telmisartan & Amlodipine Tablets` |
| L4 | Specific product name = raw name | `Telmisartan 40 mg and Amlodipine 5 mg Tablets IP (Telma-AM Tablets)` |

Rules from the definition:
- Multi-drug order follows common order in **literature**, not alphabetic.
- Drug names stick to **official ATC classification**.
- `Unmapped` values encode curation state (curated, partially-resolved artifact).
- Combo L3 joins drug names with `&` (e.g. `Telmisartan & Amlodipine Tablets`).

## 2. Verified dataset scale

| Entity | Count | Source |
|---|---|---|
| Raw cumulative CSV rows | 5,634 | `data/CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv` |
| Redis/snapshot records | 5,619 | `data/nsq_snapshot.json.gz` (sections.records) |
| Company-ontology entries | 1,555 | snapshot `ontology_companies` |
| Product-ontology entries | 1,939 | snapshot `ontology_products` |
| Molecule-key namespace (CDMO seeds) | 26 molecules + 5 plant assets | `data/*_seed.json` |

## 3. Current architecture (read path)

```
raw CSV ──redis-loader/load_csv_redis.py──▶ nsq:record:*, nsq:prediction:*,
                                             nsq:ontology:{companies,products}
snapshot ──data/nsq_snapshot.json.gz──▶ shared/nsq_redis.load_snapshot() fallback
shared/data_loader._load_and_preprocess ──▶ all derived columns (the derived-field layer)
        ├─ analytics/app.py (Streamlit)
        ├─ manufacturer/ dashboard+diagnostics (Streamlit)
        └─ manufacturer_api/ (FastAPI) ──▶ web/ (React)
```

- Ontology lives in **code + Redis hashes only** (no YAML/JSON registry).
- `shared/` is fanned out to per-service copies by `just sync-shared`; two tests enforce it:
  `tests/test_sync_shared_determinism.py` (byte-identical) and `tests/test_ontology_lockstep.py`.

## 4. Current derived fields vs proposed levels

| Level | Today's code | Where | Verdict |
|---|---|---|---|
| L4 raw | `Name of Product` | CSV | exists |
| L3 drug+form | `Product_Name_Canonical` = **first-seen raw alias** | `company_ontology.py:749`, `data_loader.py:485–551` | wrong semantics |
| L2 drug name | `match_molecule`/`PRODUCT_CATALOG` (not persisted); `Product_Ontology_Key` = `product_key()` **alphabetizes tokens, strips form+strength+brand** | `company_ontology.py:565–609` | wrong shape (alphabetical vs literature order; `\|`-separation unsupported) |
| L1 ATC class | **nothing** | — | hard gap |
| L0 therapeutic | `therapeutic_area` (26 molecules, free-text) vs `infer_drug_type` (8 buckets, all rows) | seeds vs `data_loader.py:376–401` | two disagreeing vocabularies |

## 5. Per-molecule information inventory

| Store | Molecules | Depth | Contents |
|---|---|---|---|
| `shared/gmp_knowledge.py` `PRODUCT_CATALOG` | 17 | deep | dose, dosage_form, alerts, vigibase risks, patents, excipients, CPP specs, **IP 2026 + Ph. Eur. methods**; Orange Book stamped from `us_regulatory_data.py` |
| `shared/data_loader.py` `RESEARCH_PROFILES` (L47–80) | 4 | medium | patent link, formulation, GMP params, patent status, monograph summaries |
| CDMO seeds (`patent/demand/regulatory_seed.json` + `oncology_molecule_table.json`) | 26 | shallow-broad | `therapeutic_area` (8 free-text), `dosage_form` (11 free-text), strength, BCS, RLD/TE, LOE, patents, market size, FTO |

**Gap:** L1 (ATC class) has zero data anywhere — needs a reference table or curation.
**Coverage analysis (records matching the 26 molecule names) not yet run** — pending decision.

## 6. Duplication clusters found

| # | Cluster | Copies | Guarded? | Notes |
|---|---|---|---|---|
| 1 | Company normalizer stack (`normalize_company_name`, `_similarity`, extractors, resolvers) | 8 (5 synced + loader inline + 2 dead fixtures) | lockstep test | deliberate (Docker COPY); runtime-live copies: 3 |
| 2 | Product resolve-or-create | 3 (`company_ontology.resolve_or_create_product` L683; `build_product_ontology.main` L74–109; `data_loader._resolve_product_batch` L486–546) | no | same 3-route match flow |
| 3 | Dosage-form mappers | 3+1 (`_infer_form_type` L120; `_FORM_TYPE_TO_FORM` L107; `manufacturer/ui/charts.py _FORM_BUCKET` L99–122; `_PRODUCT_FORM_TOKENS` L533 strip-list) | no | real drift risk |
| 4 | Molecule matchers | 2 (`data_loader._first_api_match`/`RESEARCH_PROFILES`; `gmp_knowledge.match_api`/`match_molecule`) | no | substring matching |
| 5 | State canonicalization | 2 (`_STATE_CANONICAL` in company_ontology L290 + loader L419) | lockstep | + display re-pass `canonical_state_name` L470 |
| 6 | `Mfg_Bin_Key` re-derivation | 3 per row (loader, data_loader prediction-join L225, app.py render L324) | partial | deliberate defense-in-depth |
| 7 | `simulator/intelligence/company_ontology.py` orphan copy | 1 | **drifted, unguarded** | missing snapshot fallback + `logging` import; nothing imports it except the lockstep test (latent). Note: pasting shared fallback in would `ImportError` — `simulator/intelligence/nsq_redis.py` has no `load_snapshot` |
| 8 | Dead-at-runtime shared copies | `simulator/shared/`, `engine/shared/` | sync test | kept for tests only |
| 9 | Stale refs | `company_ontology.py:524–526` (normalize_product location), `data_loader.py:498` (deleted `analytics/landing.py`) | — | trivial fixes |

**Not duplicates but naming variants of the same value:** `canonical` (Redis prediction hash, `load_csv_redis.py:927`) → `canonical_name` (ontology record) → `Mfg_Company_Canonical`/`Product_Name_Canonical` (DataFrame) → `tenant.canonical` (API/React). No alias tables on disk.

## 7. Impact audit — what breaks, per service

### 7.1 analytics/ (`app.py`, 1833 lines)
- **Crash on rename:** `Failure_Category_Primary` (15 hardcoded refs); `Mfg_Company_Canonical`/`Mfg_Bin_Key` in `_mfg_label`/`_mfg_group_label` (every manufacturer view); ledger `_derived_cols` phantom columns → KeyError (app.py:1746).
- **Silent on semantics change:** `Mfg_Bin_Key` trust gate (app.py:321–328 — if canonical normalizes ≠ bin, all canonical labels rejected, raw "M/s." labels return); states outside the 36 geojson `NAME_1` LGD names drop off the choropleth silently (`canonical_state_name` passes unknowns through; dropna at 1495); `Failure_Category` → `Is_Dissolution` regex cascade; `SOLUTION_BANK` key mismatch silently loses curated playbooks (gmp_knowledge.py:1231–1267); **`|`-separated L2 keys break the `EXTRA_CURATED_APIS` substring curation loop** (`token in t` can never match a piped key — needs list/split-key handling, not a rename).
- **Safe:** `Form` (ledger-only), `Mfg_Company/City/Website`, `Mfg_Ontology_Key` (display), `Product_Name_Norm` (has fallback), fuzzy search (raw-name-anchored).

### 7.2 manufacturer/ + manufacturer_api/ + web/ (React)
- **Tenant identity = hardcoded literal `ontology_key="regent ajanta"`** (`tenants.py:45`; filter impls `tenant_scope.py:34`, `api_main.py:95`). Any Mfg_* re-key silently empties the tenant app + 404s diagnostics — the documented 2026-08-27 failure class. Tests pin it (`test_tenant_scope.py:26–28`, `test_manufacturer_api.py:53`).
- `_FORM_BUCKET` (`ui/charts.py:104–115`) hardcodes 4 form labels, default "Other" — new form labels silently land in "Other". Dead legacy `"Suspension"` keys at charts.py:126,166.
- Products KPI = `Product_Name_Canonical.nunique()` (`tenant_scope.py:69–70`); L3 semantics changes it; `EXPECTED_PRODUCTS = 6` pinned in tests.
- **RCA join keys on raw-name substrings only** (`diagnostics_core.py:138`: `match_api(raw_name) or match_api(product)` → 17-molecule `PRODUCT_CATALOG` → pharmacopeia diff + Orange Book + ICH). Once L2 exists, match L2 first — fixes e.g. raw "Amoxycillin" vs catalog "amoxicillin".
- Web persists `Tenant.canonical` in localStorage (`session.ts:20–33`) — stale display after re-key until re-sign-in.
- Graceful-degradation map (renames): product fields fall back to `Name of Product`; form/failure guards return None/[] → "No data" sections. No crashes, but intent silently lost.
- API contracts needing coordinated updates: `/config` tenants, `/{tenant}/dashboard` (kpis, charts, issues), `/{tenant}/diagnostics/{issue_id}` (Diagnosis dataclass, 21 fields ↔ `web/src/lib/types.ts:172–194`).

### 7.3 simulator/ + engine/
- **Zero live consumers of NSQ product-ontology fields.** `simulator/shared/`, `engine/shared/` copies are test fixtures only. `simulator/api_main.py` = process models only; engine runs on the separate `cdmo:*` keyspace.
- Intelligence identity = `molecule_key` (26 hand-curated slugs). **No code join** to product ontology; coincidence unsafe (`product_key("Metformin HCl 500mg Tablet")` → `"hcl metformin"` vs seed `metformin_hcl`).
- Real coupling: `_molecule_class` hardcoded substring list (`intelligence_scorer.py:283–299`); twice-duplicated oncology key sets (`app.py:1363–1372`, `1463–1472`); salt→base renames silently degrade scoring to `small_molecule_oral` defaults. `cdmo:complexity:<key>` derived caches orphan on molecule_key rename.
- If L0/consolidated forms become authoritative: re-key seeds' `therapeutic_area` (8 values), demand `cluster` (5 tokens), regulatory `dosage_form` (11 variants).

## 8. Tests that pin behavior (must be updated in the same change)

| Test | Pins |
|---|---|
| `test_data_loader_uncached.py:40–53` | REQUIRED_COLUMNS (renames/drops fail) |
| `test_ontology_lockstep.py` | normalizer corpus + similarity across 8 copies; bin determinism |
| `test_state_attribution.py:18,238` | `_STATE_TOKENS`/`_CITY_HINTS` FROZEN (changing shifts bins, invalidates persisted Redis bins) |
| `test_tenant_scope.py:26–28,97–104` | tenant identity literal, 8-row count |
| `test_manufacturer_api.py:25–30,53,73` | EXPECTED_CANONICAL, EXPECTED_ALERTS=8, EXPECTED_PRODUCTS=6, ontology_key literal |
| `test_geojson.py` | 36 `NAME_1` == LGD names; legacy names banned |
| `test_sync_shared_determinism.py` | byte-identical shared copies (edits go via `just sync-shared`) |
| `test_diagnostics_core.py:40–61` | literal field values on shared schema |

## 9. Open decisions (gating the design)

1. **L0–L2 production:** who produces values for 5,619 records / 1,939 product entries — user-curated file joined by pipeline (with `Unmapped` + curation queue), pipeline-derived with review, or curated subset (17–26 molecules) first, expanding iteratively. *Directionally chosen: curated subset; pending record-coverage number.*
2. **L1 ATC source:** no data exists — reference table needed or manual curation.
3. **Field policy:** L3 redefines `Product_Name_Canonical` (+ full `nsq:ontology:products` rebuild + snapshot + version bump) vs purely additive vs clean-slate replacement.
4. **Manufacturer canonicalization:** in this round or deferred (highest silent-risk cluster: tenant literal, bin trust-gate, state/geojson drop-out).
5. **Form vocabulary:** single vocabulary at L3 construction consumed by all three mappers, vs keep-3 + CI guard.
6. **L2 grouping mechanics:** `|`-separated multi-drug values need list-typed columns or split-key handling everywhere `value_counts()`/substring matching is used today (Sankey, heatmaps, curation loop, `str.contains` filters).

## 10. Restore point

Working tree clean on `offpatentdi`; commits `f8ecd0b` + `a427c4f` pending push to `origin` at time of writing. **No code changes have been made.**

---
*Prepared from exhaustive read-only audits (5 exploration agents). All file:line references verified on branch `offpatentdi` @ a427c4f.*