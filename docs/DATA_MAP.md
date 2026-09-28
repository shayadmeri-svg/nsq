# Data map

This page covers where every dataset comes from, where it lives, what changes it, and which screens read it.

The same graph is live in the app at **Platform → Data map** (`/admin/data-map`):
- click a box to trace it upstream and downstream;
- the **Mutations** tab lists every write path;
- the **Stores** tab shows live row and key counts.

The graph is defined once in `backend/app/datamap.py`. Update that file (and this page) when a job, store or screen changes; `datamap.validate()` is run by the tests.

## 1. The whole flow

```mermaid
flowchart LR
  subgraph O[Origins]
    CDSCO[CDSCO NSQ portal]
    FDA[FDA Orange / Purple Book]
    EMA[EMA medicines data]
    CT[ClinicalTrials.gov]
    FDAS[FDA site records<br/>DECRS · import alert · recalls]
    CPL[CDSCO plant lists<br/>SUGAM · WHO-GMP PDF]
    EUG[EudraGMDP<br/>EU GMP certificates · NCRs]
    FDI[FDA Data Dashboard<br/>inspection classifications]
    FIL[FDA DMF list · EDQM CEPs]
    HLT[NFHS · IDSP · UN Comtrade]
    ORD[Open Reaction Database]
    SEED[Curated seeds]
    UP[(Upstash backup)]
    SCH([Scheduler]) --> RUN([Job runner])
  end
  subgraph I[Ingest]
    SYNC[sync_cdsco.py]
    FETCH[fetch_source.py]
  end
  subgraph F[Files · data/]
    CSV[NSQ CSV]
    SRC[sources/*.json + manifest]
    GEN[generated/ universe]
    ENT[generated/ app exports]
    SNAP[nsq_snapshot.json.gz]
    UPL[uploads/]
  end
  subgraph B[Build]
    LOAD[load_csv_redis + ontologies]
    FRAME[build_enriched_frame]
    UNI[build_universe]
    CDMO[load_patents / regulatory / demand]
    PL[load_plant_assets / sync-plants]
  end
  subgraph R[Redis · analytics]
    RN[(nsq:record:* …)]
    RO[(nsq:ontology:*)]
    RF[(nsq:frame:enriched)]
    RC[(cdmo:patent/regulatory/demand)]
    RP[(cdmo:plant:*)]
    RG[(geo:india_states)]
  end
  subgraph P[Postgres · app state]
    PA[(users · sessions · invites)]
    PO[(orgs)]
    PP[(plants)]
    PM[(molecule_entries · watch_molecules)]
    PJ[(job_runs · pipeline_schedules)]
    PAU[(audit_log)]
  end
  subgraph S[API services]
    SF{{NSQ frame · 5 min cache}}
    SC{{Molecule intelligence · 2 min}}
    SS{{Site directory}}
    SPL{{Plant registry}}
    SK{{Built-in knowledge}}
  end
  subgraph V[Screens]
    PG[Playground]
    ORG[Org dashboards]
    ADM[Admin pages]
  end

  CDSCO --> SYNC --> CSV
  FDA & EMA & CT & FDAS --> FETCH --> SRC
  CPL & EUG & FDI & FIL & HLT & ORD -->|laptop, then push| FETCH
  UPL --> FETCH
  SEED --> UNI
  CSV --> LOAD --> RN & RO
  RN & RO --> FRAME --> RF
  SRC & ENT & RN --> UNI --> GEN --> CDMO --> RC
  PM --> ENT
  PP --> PL --> RP
  UP <--> RN
  RN --> SNAP
  RF & RN & RO --> SF
  RC & RP --> SC
  SF & SRC --> SS
  SRC & SS --> SPL --> PG & ORG & ADM
  SF --> PG & ORG & ADM
  SC --> PG & ORG & ADM
  SS --> PG & ORG & ADM
  SK --> PG
  RG --> PG
  PO --> ORG
  RUN -.-> SYNC & FETCH & LOAD & FRAME & UNI & CDMO & PL
  RUN ==> PJ

  ADM ==>|molecule form| PM
  ADM ==>|orgs, users| PO & PA
  ORG ==>|add plant| PP & RP
  ADM ==>|run job, schedule| PJ
  ADM & ORG ==> PAU

  classDef redis fill:#fff1f2,stroke:#e11d48;
  classDef pg fill:#eff6ff,stroke:#2563eb;
  classDef file fill:#fffbeb,stroke:#d97706;
  class RN,RO,RF,RC,RP,RG redis;
  class PA,PO,PP,PM,PJ,PAU pg;
  class CSV,SRC,GEN,ENT,SNAP,UPL file;
```

In the diagram, `-->` means data is read, `==>` means a write (mutation) and `-.->` means a job is started.

**Rule of thumb:**
- **Postgres** holds what people do in the app: accounts, organisations, plants, molecule edits, jobs, audit. It is durable (Neon).
- **Redis** holds the analytics data. It can always be rebuilt from the files and jobs.
- **Files** under `data/` are the ingest trail: raw downloads, normalised sources, the cumulative CSV, generated outputs and the snapshot.

## 2. Daily pipelines

```mermaid
flowchart TB
  subgraph FN [fetch-nsq · daily 06:30 IST]
    a1[export_watchlist] --> a2[sync_cdsco: new months] -->|nothing new: stop| x1((done))
    a2 -->|new alerts| a3[load_csv_redis --flush --augment] --> a4[build_product_ontology] --> a5[build_enriched_frame] --> a6[build_universe] --> a7[load patents / regulatory / demand]
  end
  subgraph SS [sync-sources · daily 02:30 IST]
    b1[export_watchlist] --> b2[fetch every server-reachable source<br/>Orange / Purple Book · EMA · FDA sites · Comtrade …<br/>each may fail without stopping; ORD and WC PDFs never] --> b3[build_universe] --> b4[fetch ClinicalTrials for candidates] --> b5[build_universe] --> b6[load patents / regulatory / demand]
  end
```

Other jobs are on the Data jobs and Data pipelines pages:
- `build-universe`
- `src-*`, one per source
- `build-frame`
- `snapshot` and `restore-snapshot`
- `pull-upstash` and `backup-to-upstash`
- `load-seeds` and `sync-plants`

Orange Book and Purple Book are fetched at most weekly. DECRS is fetched at most every 3 days.

## 3. Stores

### Redis

| Key pattern | Type | Holds | Written by | Read by |
|---|---|---|---|---|
| `nsq:records`, `nsq:record:<id>`, `nsq:prediction:<id>`, `nsq:by_month:*`, `nsq:meta` | set / hash | One hash per CDSCO alert, plus manufacturer augmentation | `load_csv_redis` (fetch-nsq, refresh-nsq), `restore_snapshot`, `pull_upstash` | build_enriched_frame, build_universe (alert counts), frame fallback, snapshot, data status |
| `nsq:ontology:companies`, `nsq:ontology:products` (+`:meta`) | hash of JSON | Canonical manufacturer and product names | `load_csv_redis`, `build_product_ontology`; **also the API** when it has to rebuild the frame | build_enriched_frame, the frame fallback |
| `nsq:frame:enriched` (+`:meta`) | gzip+base64 parquet | The analytics table every NSQ chart uses | `build_enriched_frame` | API frame (preferred source) |
| `geo:india_states` (+`:meta`) | gzip+base64 GeoJSON | State boundaries | `load_geojson_redis` (manual) | Playground map |
| `cdmo:patent:<m>`, `cdmo:regulatory:<m>`, `cdmo:demand:<m>` | hash | Molecule intelligence with provenance | `load_patents` / `load_regulatory` / `load_demand` (flush and reload after every universe build), `pull_upstash` | Every opportunity, workbench, insights and world view |
| `cdmo:plant:<id>` | hash | Plant capabilities used for matching | `load_plant_assets`, `sync-plants`; **the API** when a plant is added or edited, and on start-up if a user plant is missing | Infrastructure, matching, workbench |

### Postgres

| Table | Holds | Written by | Read by |
|---|---|---|---|
| `users`, `sessions`, `invites` | Accounts, sessions, invites | Sign-in, account page, Users & team; the super admin is seeded on API start | Every request (session check), Users, Admin overview |
| `orgs` | Organisations, their NSQ manufacturer keys and plant ids | Organisations page; adding a plant attaches its id | All org dashboards, workbench (your plants) |
| `plants` | Durable copy of plants made in the app | Infrastructure (org admin), Site directory "add as plant" | sync-plants, API start-up restore |
| `molecule_entries`, `watch_molecules` | Typed molecule values and watchlist | Molecule universe (**super admin only**) | export_watchlist → build_universe |
| `job_runs`, `pipeline_schedules` | Runs, logs, schedules | Job runner, scheduler, Data pipelines | Data jobs, Data pipelines, Admin overview |
| `audit_log` | Every sign-in and change | Every mutating API call | Audit log, Admin overview |

### Files (`data/`)

| Path | Written by | Read by |
|---|---|---|
| `CDSCO … NSQ ….csv` | `sync_cdsco` (append) | `load_csv_redis`, `build_product_ontology` |
| `raw/<source>/*` | every fetcher (plus HTTP cache) | the fetcher's next run |
| `sources/<source>.json`, `sources/manifest.json` | `fetch_source`, `sync_cdsco` (manifest) | build_universe, site directory, pipelines page, molecule lookup |
| `sources/cdsco_plants.json` (+ `.csv`) | `fetch_source cdsco_plants` (`just fetch-plants`, job src-cdsco-plants / plant-registry) | plant registry (Plants tab, site directory match, Infrastructure "Match with CDSCO registry", "Add as plant") |
| `sources/eudragmdp.json` | `fetch_source eudragmdp` (`just fetch-eudragmdp`, job src-eudragmdp / plant-registry) | plant registry (EU GMP status, stated capabilities, non-compliance findings) |
| `sources/ord.json` | `fetch_source ord` (`just fetch-ord [FILE]` on a laptop — ~1.3 GB Parquet from the Hugging Face mirror, scanned with RDKit; job src-ord; `just push-signals` copies it) | Molecule workbench · How it's made: reactions that make each tracked molecule, conditions, solvents, catalysts, hazardous reagents and the API-plant equipment they call for |
| `sources/nfhs.json`, `sources/idsp.json`, `sources/comtrade.json` | `fetch_source nfhs` / `idsp` / `comtrade` (`just fetch-nfhs FILE`, `just fetch-idsp [FILE]`, `just fetch-comtrade`, then `just push-signals HOST KEY`; jobs src-nfhs / src-idsp / src-comtrade) | Playground · Health & trade: disease burden by district and survey round, weekly outbreaks with the medicines they drive, India's pharma exports / imports by partner and API import share from China |
| `sources/cdsco_wc.json`, `docs/cdsco_wc/<id>.pdf` | `fetch_source cdsco_wc` on a laptop (`just fetch-cdsco-wc [LIMIT]`, index only with `NSQ_WC_PDFS=0`; then `just push-wc HOST KEY`, which rsyncs only new PDFs; job src-cdsco-wc) | Playground · Written confirmations: every CDSCO Written Confirmation for API exports to the EU, searchable (company, WC number, products, letter text), each letter viewable as a PDF |
| `sources/fda_dmf.json`, `sources/edqm_cep.json` | `fetch_source fda_dmf` / `edqm_cep` (`just fetch-fda-dmf [FILE]`, `just fetch-cep [FILE]`, jobs src-fda-dmf / src-edqm-cep) | "Who can make it" → API filings: active Type II DMF and valid CEP holders per ingredient, linked to registry plants by company name |
| `sources/fda_inspections.json` | `fetch_source fda_inspections` (`just fetch-fda-inspections [FILE]`, job src-fda-inspections / plant-registry) — API key (FDA_DD_USER / FDA_DD_KEY) or Data Dashboard Excel export | plant registry (US FDA status: latest NAI / VAI / OAI per FEI, import-alert flag), "Who can make it" ranking, USFDA certification on "add as plant" |
| `raw/cdsco_plants/*` | SUGAM pages + WHO-GMP PDF from the last crawl | the next `cdsco_plants` run when CDSCO is unreachable |
| `uploads/*` | Data jobs → Upload | `--from-file` fetches, refresh-nsq |
| `*_seed.json` | hand-edited | build_universe, load-seeds, molecule lookup |
| `generated/watchlist.json`, `molecules.json` | `export_watchlist` (from Postgres) | build_universe |
| `generated/patents.json`, `regulatory.json`, `demand.json`, `molecule_universe.json`, `candidates.json` | build_universe | load_* scripts, Molecule universe page, ClinicalTrials fetch |
| `nsq_snapshot.json.gz` | `snapshot` job | frame fallback, restore-snapshot |

## 4. Every mutation, by trigger

| Trigger | What changes |
|---|---|
| **Scheduler** (every 30 s) | `pipeline_schedules` (fire times). It starts jobs, and each job writes `job_runs` plus the stores below. |
| **fetch-nsq** | CSV, `raw/cdsco`, manifest. When there are new alerts it also writes all `nsq:*` keys (flush and reload), the frame, `generated/*` and `cdmo:patent/regulatory/demand` (flush and reload). |
| **sync-sources / src-\*** | `raw/*`, `sources/*.json`, manifest, `generated/*`, `cdmo:patent/regulatory/demand` |
| **plant-registry / src-cdsco-plants / src-eudragmdp / src-fda-inspections / src-fda-import-alerts** (or `just fetch-plant-registry` + `just fetch-fda-sites` + `just push-plant-registry`) | `raw/*`, `sources/cdsco_plants.json`, `eudragmdp.json`, `fda_inspections.json`, `fda_establishments.json`, `fda_import_alerts.json`, `fda_dmf.json`, `edqm_cep.json`, manifest. Nothing in Redis: the API re-reads the files when they change. Plant profiles linked to a registry plant (demo profiles via `plant_assets_seed.json` → `reference.registry_plant`, organisation plants via "Match with CDSCO registry") take US FDA / EU GMP / WHO-GMP from these records at read time; what the company only states becomes "claimed". |
| **src-cdsco-wc** (laptop: `just fetch-cdsco-wc` + `just push-wc`) | `sources/cdsco_wc.json`, `docs/cdsco_wc/*.pdf` (rsync, only new letters) |
| **Match with CDSCO registry** (Infrastructure) | `plants`, `cdmo:plant:*` (capabilities, basis, certificates, `reference.registry`), `audit_log` |
| **build-universe** (also run after saving a molecule) | `generated/*`, `cdmo:patent/regulatory/demand` |
| **load-seeds / sync-plants** | `cdmo:plant:*` (upsert) and the molecule stores |
| **snapshot / restore-snapshot** | the snapshot file, or `nsq:*` and `geo:*` |
| **pull-upstash / backup-to-upstash** | local `nsq:*`, `geo:*`, `cdmo:*`, or Upstash |
| **Sign in / account** | `sessions`, `users`, `audit_log` |
| **Users & team** | `users`, `invites`, `sessions`, `audit_log` |
| **Organisations** | `orgs`, `audit_log` |
| **Infrastructure / Site directory** | `plants`, `cdmo:plant:*`, `orgs.plant_ids`, `audit_log` |
| **Molecule universe** (super admin) | `molecule_entries`, `watch_molecules`, `audit_log`; then starts build-universe |
| **Data jobs / pipelines** | `job_runs`, `pipeline_schedules`, `uploads/`, `audit_log` |
| **API start** | seeds or repairs the super admin; marks interrupted runs failed; restores missing user plants to Redis |
| **API frame rebuild** (only when the precomputed frame is missing or stale) | `nsq:ontology:products` |

## 5. Which screen reads what

| Screen | Services | Underlying stores |
|---|---|---|
| Playground · Explorer & Ledger | NSQ frame | `nsq:frame:enriched`, `geo:india_states` |
| Playground · Insights | NSQ frame, molecule intelligence, site directory | frame, `cdmo:*`, `sources/fda_*.json` |
| Playground · Regulation map | molecule intelligence, built-in knowledge (`core/regulatory_regions.py`) | `cdmo:*` |
| Playground · Molecule workbench | molecule intelligence, NSQ frame, built-in knowledge, plant registry ("This plant for this molecule", "Who can make it", plant fit for every plant), ORD | `cdmo:*`, frame, `orgs` (your plants — demo profiles are not listed), `sources/cdsco_plants.json`, `eudragmdp.json`, `fda_*.json`, `fda_dmf.json`, `edqm_cep.json`, `ord.json` |
| Playground · Written confirmations | CDSCO International Cell | `sources/cdsco_wc.json`, `docs/cdsco_wc/*.pdf` |
| Playground · Process lab | built-in knowledge (`core/process_models.py`) | none |
| Playground · Plants | plant registry (CDSCO WHO-GMP + SUGAM + EudraGMDP), site directory | `sources/cdsco_plants.json`, `sources/eudragmdp.json`, frame |
| Org · Overview / Opportunities / EU export | NSQ frame, molecule intelligence | frame, `cdmo:*`, `orgs` |
| Org · Quality | NSQ frame (your manufacturer keys and national) | frame, `orgs` |
| Org · Infrastructure | molecule intelligence (plants), site directory, plant registry | `cdmo:plant:*`, `plants`, `sources/fda_*.json`, `sources/cdsco_plants.json`, `sources/eudragmdp.json` |
| Admin overview | NSQ frame, data status | frame, `nsq:meta`, snapshot, `job_runs`, `audit_log`, `users` |
| All-India NSQ | NSQ frame | frame |
| Organisations | NSQ frame (manufacturer search), plants | `orgs`, frame, `cdmo:plant:*` |
| Data pipelines | universe & source status | manifest + each source file's own header (files pushed from a laptop have no manifest entry on the server), `generated/molecule_universe.json`, `pipeline_schedules`, `job_runs` |
| Data jobs | every source with the data held (records, retrieved, PDFs), laptop vs server, recent runs | same as Data pipelines, `job_runs` |
| Molecule universe | universe, molecule intelligence, lookup | `generated/*`, `cdmo:*`, seeds, `sources/*`, `molecule_entries`, `watch_molecules` |
| Site directory | site directory, plant registry | frame, `sources/fda_*.json`, `sources/cdsco_plants.json`, `sources/eudragmdp.json`, `orgs` |
| Audit log | none | `audit_log` |

## 6. Things worth knowing

- **Spurious batches.** A batch declared spurious is listed under the company printed on its label, which may not be the real maker. The API flags these rows (`_spurious`) and keeps them out of every company ranking, the site directory and org ranks. They appear in Insights and in the Ledger's Authenticity column.
- **Unused Redis keys.** `cdmo:complexity:*` and `cdmo:portfolio:*` have store functions but no writers today.
- **Legacy `/analytics` service.** It reads the same Redis keys through `analytics/shared/*`, which is a copy of `core/*`. It only starts with the `legacy` compose profile.

## Plant registry (CDSCO)

`redis-loader/sources/cdsco_plants.py` builds `data/sources/cdsco_plants.json` from two official CDSCO lists:
the WHO-GMP certified-units PDF (read by page layout: serial column, name/address, "category of drugs permitted")
and the SUGAM approved-manufacturing-site table (licence number, form, own/loan, loan licensee, dates). The free
text becomes a fixed vocabulary — dosage forms, sterile / API, segregated blocks (beta-lactam, cephalosporin,
hormone, cytotoxic…) scoped to the forms they cover, therapeutic classes — and every capability keeps the CDSCO
sentence it came from. The output also keeps the parsed inputs, so a run that cannot reach CDSCO rebuilds from them
instead of losing data. CDSCO refuses many cloud networks: run it on a machine in India or a laptop, or upload the PDF
to the "CDSCO plant registry" job.

`backend/app/plants.py` links NSQ directory sites to registry plants (company + PIN = `site`; same PIN, near-identical
name = `site_fuzzy`; company + town, or the company's only plant in the state = `company`) and serves `/api/plants*`:
per-capability denominators (plants that can make X, share with NSQ alerts), the plant list and plant detail.
"Add as plant" from the site directory adds the registry's forms as `stated` capabilities and the WHO-GMP certificate.

`core/capability_rules.py` turns a registry listing into capability-catalog tokens: `required` (Schedule M / WHO-GMP
require it for the products listed — e.g. Grade A cleanrooms and WFI for injectables, dedicated segregated areas for
beta-lactam or cytotoxic blocks, export barcoding for WHO-GMP units) or `inferred` (usual, not mandatory — e.g. film
coating for tablets), each with the rule text. It feeds the plant drawer's coverage view, "Add as plant", and
Infrastructure → "Match with CDSCO registry", which adds these tokens to an existing plant without downgrading anything
stated or entered.

`redis-loader/sources/eudragmdp.py` crawls EudraGMDP for every Indian GMP certificate and statement of non-compliance
(a Struts session: form POST search, `action=Page&param=N`, `action=Drilldown&param=<id>` only for rows on the current
page). Part 2 scope lines (Union coded format) become stated capabilities through `capability_rules.from_eu_scope`;
statements of non-compliance keep the inspectors' "nature of non-compliance". `plants.py` attaches each EU site to a
registry plant (company + PIN, or company + town) or adds it as an EU-only plant; the site's status is
non-compliant when its latest document is a statement of non-compliance.

### Running the plant registry

```bash
just setup                    # once: loader venv (includes pdfplumber)
just fetch-plant-registry     # CDSCO SUGAM + WHO-GMP PDF, then EudraGMDP — on a laptop
just push-plant-registry ec2-user@<server> ~/.ssh/<key>.pem   # copy to the server, restart the API
```

Admin → Data jobs has the same as **Rebuild plant registry** (both sources), **CDSCO plant registry** and
**EU GMP certificates** (each accepts an uploaded file when the server cannot reach the site).
