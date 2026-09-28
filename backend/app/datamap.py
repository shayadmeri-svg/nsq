"""The platform's data map: where every dataset comes from, where it is stored,
who changes it, and which screens read it.

The graph below is maintained by hand next to the code it describes (see
docs/DATA_MAP.md for the same picture as Mermaid). Live numbers (row counts,
key counts, file ages, source status) are added at request time so the map
doubles as a health view.

Edge kinds:
  flow     data is read / derived from -> to
  write    the "from" node changes the "to" store (a mutation)
  trigger  "from" starts "to" (jobs); no data moves
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import data
from .config import settings
from .models import AuditLog, Invite, JobRun, MoleculeEntry, Org, PipelineSchedule, Plant, User, UserSession, WatchMolecule

COLUMNS = [
    {"key": "origin", "label": "Origins", "hint": "Public websites, curated files, and the job runner"},
    {"key": "ingest", "label": "Ingest", "hint": "Scripts that download and normalise"},
    {"key": "files", "label": "Files", "hint": "data/ on the API server"},
    {"key": "build", "label": "Build", "hint": "Scripts that load and derive"},
    {"key": "stores", "label": "Stores", "hint": "Redis (analytics) and Postgres (app state)"},
    {"key": "services", "label": "API services", "hint": "In-process views the API serves from"},
    {"key": "pages", "label": "Screens", "hint": "Where people see it"},
]


def _n(id: str, col: str, kind: str, label: str, sub: str, detail: str, *, group: str = "", keys: Optional[list[str]] = None,
       jobs: Optional[list[str]] = None, route: str = "", endpoints: Optional[list[str]] = None) -> dict[str, Any]:
    return {"id": id, "col": col, "kind": kind, "label": label, "sub": sub, "detail": detail, "group": group,
            "keys": keys or [], "jobs": jobs or [], "route": route, "endpoints": endpoints or []}


NODES: list[dict[str, Any]] = [
    # --- origins ---------------------------------------------------------------------------------
    _n("ext_cdsco", "origin", "external", "CDSCO NSQ portal", "cdscoonline.gov.in",
       "Monthly lists of drug batches declared Not of Standard Quality (and spurious) by central and state labs. The platform's core dataset.",
       keys=["cdscoonline.gov.in/CDSCO/publicNsqDrugTable"]),
    _n("ext_orange", "origin", "external", "FDA Orange Book", "fda.gov data files (zip)",
       "US approved drugs: reference listed drugs, ANDA holders, therapeutic-equivalence codes, patents and exclusivities. Refreshed at most weekly; fda.gov may block automated downloads, in which case upload the zip.",
       keys=["www.fda.gov/media/76860/download"]),
    _n("ext_purple", "origin", "external", "FDA Purple Book", "monthly CSV",
       "US licensed biologics and biosimilars / interchangeables.", keys=["purplebooksearch.fda.gov/downloads"]),
    _n("ext_ema", "origin", "external", "EMA medicines data", "EPAR JSON report",
       "EU centrally authorised medicines: generics, biosimilars, therapeutic areas.",
       keys=["ema.europa.eu/…/medicines-output-medicines_json-report_en.json"]),
    _n("ext_ct", "origin", "external", "ClinicalTrials.gov", "API v2 counts",
       "Trial counts per molecule (total, phase 3+, recent, India). Used as a demand signal. Up to 60 molecules per run.",
       keys=["clinicaltrials.gov/api/v2/studies"]),
    _n("ext_fdasites", "origin", "external", "FDA site records", "DECRS · import alert · openFDA recalls",
       "FDA drug establishment registrations (DECRS), the import-alert page for Indian firms, and openFDA drug recalls for India. Matched to Indian sites by company name (and PIN code where possible).",
       keys=["accessdata.fda.gov/cder/drls_reg.zip", "accessdata.fda.gov/CMS_IA/importalert_189.html", "api.fda.gov/drug/enforcement.json"]),
    _n("ext_cdsco_plants", "origin", "external", "CDSCO plant lists", "WHO-GMP PDF · SUGAM approved sites",
       "CDSCO's WHO-GMP certified manufacturing units (what each is permitted to make, segregated blocks, certificate dates) and the SUGAM approved-manufacturing-site table (licences, own/loan).",
       keys=["cdsco.gov.in/…/Final WHO GMP data for website.pdf", "cdscoonline.gov.in/CDSCO/manuf_site"]),
    _n("ext_eudragmdp", "origin", "external", "EudraGMDP (EU GMP)", "certificates · non-compliance statements",
       "EU / EEA inspection outcomes for Indian sites: GMP certificates with the approved operations in the Union coded format, and statements of non-compliance with what failed.",
       keys=["eudragmdp.ema.europa.eu/inspections/gmpc/searchGMPCompliance.do"]),
    _n("ext_fda_insp", "origin", "external", "FDA inspections", "Data Dashboard · NAI / VAI / OAI",
       "Every FDA drug and biologic inspection of an Indian site (by FEI) with its classification. Needs an API key from FDA, or the Inspections table exported to Excel.",
       keys=["api-datadashboard.fda.gov/v1/inspections_classifications"]),
    _n("ext_filings", "origin", "external", "API filings", "FDA DMF list · EDQM CEPs",
       "Holders of active US Drug Master Files (Type II) and valid European Certificates of Suitability per active ingredient. Company-level: neither names the site.",
       keys=["fda.gov/drugs/drug-master-files-dmfs/list-drug-master-files-dmfs", "extranet.edqm.eu/publications/recherches_CEP.shtml"]),
    _n("ext_ord", "origin", "external", "Open Reaction Database", "reactions · conditions (CC BY-SA)",
       "Reactions from patents and papers (Parquet on Hugging Face). Scanned for reactions that make tracked molecules: temperatures, pressure, solvents, catalysts, hazardous reagents.",
       keys=["huggingface.co/datasets/open-reaction-database/ord-data"]),
    _n("ext_health", "origin", "external", "Health signals", "NFHS fact sheets · IDSP outbreaks",
       "NFHS district / state indicators (high blood sugar, raised blood pressure, obesity, anaemia, child diarrhoea / ARI) across survey rounds, and IDSP weekly outbreak reports (PDF tables).",
       keys=["data.gov.in NFHS-5 districts factsheet", "nfhsiips.in NFHS-6 compendiums", "idsp.mohfw.gov.in weekly outbreaks"]),
    _n("ext_cdsco_wc", "origin", "external", "CDSCO Written Confirmations", "International Cell · API exports to the EU",
       "Every Written Confirmation CDSCO has issued since 2013 (EU Directive 2011/62/EU): WC number, company, products, release date and the letter as a PDF. Refuses cloud servers — fetched on a laptop.",
       keys=["cdsco.gov.in/opencms/opencms/en/International-cell1/"]),
    _n("ext_comtrade", "origin", "external", "UN Comtrade", "India pharma trade by partner",
       "India's exports and imports of pharmaceutical HS codes (3002–3006, 2933–2942) by partner and year. Full API with COMTRADE_KEY, public preview otherwise.",
       keys=["comtradeapi.un.org/data/v1/get/C/A/HS"]),
    _n("ext_pubchem", "origin", "external", "PubChem", "structures · XLogP3 · melting points",
       "Chemical structure (SMILES), InChIKey, XLogP3 and experimental melting points per molecule, for the lab's structure-based models.",
       keys=["pubchem.ncbi.nlm.nih.gov/rest/pug", "…/pug_view (Melting Point)"]),
    _n("ext_faers", "origin", "external", "FDA FAERS (openFDA)", "adverse-event reports, live",
       "Spontaneous adverse-event reports queried live per molecule (cached 24 h) for PRR / ROR safety signals in the Lab.",
       keys=["api.fda.gov/drug/event.json"]),
    _n("ext_curated", "origin", "external", "Curated seeds", "hand-edited JSON in the repo",
       "Molecule seeds (patents, regulatory passports, demand) and demo plant assets written by the team. Every value carries provenance; seeds lose to public sources, which lose to values typed in the app."),
    _n("ext_upstash", "origin", "external", "Upstash Redis", "cloud backup / seed",
       "Optional hosted Redis used as a backup target and to seed a fresh install. Only jobs touch it; the API never reads it."),
    _n("act_scheduler", "origin", "actor", "Scheduler", "inside the API · IST",
       "Checks every 30 s for due schedules (Postgres advisory lock, so one API instance fires). Defaults: fetch-nsq daily 06:30, sync-sources daily 02:30; others off until enabled on Data pipelines."),
    _n("act_runner", "origin", "actor", "Job runner", "subprocesses in redis-loader/",
       "Runs registered jobs as subprocesses, streams logs into job_runs, and clears the API caches afterwards. Started by the scheduler, by Run buttons, or by saving a molecule."),

    # --- ingest -------------------------------------------------------------------------------------
    _n("in_cdsco", "ingest", "script", "sync_cdsco.py", "step 1 of fetch-nsq",
       "Pulls new months from the CDSCO portal (or a backfill range), de-duplicates against the CSV and appends new rows. Exit code 3 = nothing new, and the job stops early.",
       jobs=["fetch-nsq", "refresh-nsq"]),
    _n("in_sources", "ingest", "script", "fetch_source.py", "one per public source",
       "Downloads with conditional GET (ETag / Last-Modified), parses and writes one normalised JSON per source plus a status line in the manifest. Accepts an uploaded file instead of downloading.",
       jobs=["sync-sources", "src-orange-book", "src-purple-book", "src-ema", "src-clinical-trials", "src-fda-establishments", "src-fda-import-alerts", "src-fda-recalls",
             "src-cdsco-plants", "src-eudragmdp", "src-fda-inspections", "src-fda-dmf", "src-edqm-cep", "src-ord", "src-nfhs", "src-idsp", "src-comtrade", "src-cdsco-wc", "plant-registry"]),

    # --- files --------------------------------------------------------------------------------------
    _n("f_csv", "files", "file", "NSQ CSV", "cumulative, all months",
       "Every CDSCO alert since Jan 2021 in one CSV. Source of truth for reloading Redis.",
       keys=["data/CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv"]),
    _n("f_raw", "files", "file", "Raw downloads", "+ HTTP cache",
       "Untouched downloads kept for audit, plus ETags so unchanged files are not downloaded again.",
       keys=["data/raw/<source>/*", "data/raw/cdsco/publicNsqDrugTable-*.json"]),
    _n("f_sources", "files", "file", "Normalised sources", "one JSON per source",
       "Orange Book, Purple Book, EMA, ClinicalTrials, FDA establishments / import alerts / recalls, each as {source, url, retrieved_at, records, data}.",
       keys=["data/sources/<source>.json"]),
    _n("f_manifest", "files", "file", "Source manifest", "status of each source",
       "Last attempt, last success, status (ok / unchanged / unreachable / failed), record count and error per source.",
       keys=["data/sources/manifest.json"]),
    _n("f_uploads", "files", "file", "Uploads", "files added on Data jobs",
       "CSV / zip / JSON / HTML files uploaded by the super admin, used when a site blocks downloads or for a manual NSQ reload.",
       keys=["data/uploads/*"]),
    _n("f_docs", "files", "file", "Written Confirmation PDFs", "data/docs/cdsco_wc/<id>.pdf",
       "Copies of CDSCO's Written Confirmation letters (~700 PDFs, ~2.7 GB), downloaded on a laptop and rsynced to the server; served inline to the Playground.",
       keys=["data/docs/cdsco_wc/*.pdf"]),
    _n("f_seeds", "files", "file", "Seed JSON", "curated molecules & plants",
       "Curated starting values. Edited by hand in the repo.",
       keys=["data/patent_seed.json", "data/regulatory_seed.json", "data/demand_seed.json", "data/plant_assets_seed.json"]),
    _n("f_entries", "files", "file", "App molecule exports", "watchlist + typed values",
       "Postgres molecule entries and watchlist, exported before every universe build so the build script (which has no database access) can apply them.",
       keys=["data/generated/watchlist.json", "data/generated/molecules.json"]),
    _n("f_generated", "files", "file", "Universe outputs", "patents · regulatory · demand",
       "The merged molecule universe with provenance for every value, plus the list of molecules to query on ClinicalTrials.gov.",
       keys=["data/generated/patents.json", "regulatory.json", "demand.json", "molecule_universe.json", "candidates.json"]),
    _n("f_snapshot", "files", "file", "NSQ snapshot", "gzip JSON of nsq:* + geo",
       "Portable copy of the NSQ Redis data. Fallback when Redis is empty and the seed for a fresh install.",
       keys=["data/nsq_snapshot.json.gz"]),
    _n("f_geo", "files", "file", "India states GeoJSON", "built from LGD parquet",
       "State boundaries for the India map, pushed to Redis by hand (just push-geojson).",
       keys=["data/geo/india_states_slim.geojson"]),

    # --- build --------------------------------------------------------------------------------------
    _n("b_export", "build", "script", "export_watchlist", "runs before builds",
       "Copies Postgres molecule entries and the watchlist to JSON files for build_universe.py.",
       jobs=["fetch-nsq", "sync-sources", "build-universe", "src-*", "load-seeds"]),
    _n("b_nsq", "build", "script", "load_csv_redis.py", "flush + reload + augment",
       "Loads the CSV into Redis (one hash per alert), de-duplicates, and augments manufacturers (canonical name, city, state, website) into the company ontology.",
       jobs=["fetch-nsq", "refresh-nsq"]),
    _n("b_products", "build", "script", "build_product_ontology.py", "product names → canonical",
       "Groups spelling variants of product names under one canonical product key.", jobs=["fetch-nsq", "refresh-nsq"]),
    _n("b_frame", "build", "script", "build_enriched_frame.py", "precomputed analytics frame",
       "Joins alerts with manufacturer and product ontologies, derives failure category, form, drug type and state, and stores the result as one compressed parquet in Redis.",
       jobs=["fetch-nsq", "refresh-nsq", "build-frame", "restore-snapshot"]),
    _n("b_universe", "build", "script", "build_universe.py", "seeds + sources + NSQ + typed",
       "Builds the molecule universe in layers: curated seeds, then public sources, then molecules discovered in NSQ alerts (5+ alerts and confirmed by a source), then watchlist and values typed in the app (typed values win; the source value is kept for comparison).",
       jobs=["fetch-nsq", "sync-sources", "build-universe", "src-orange-book", "src-purple-book", "src-ema", "src-clinical-trials", "load-seeds"]),
    _n("b_cdmo", "build", "script", "load_patents / regulatory / demand", "flush + reload",
       "Replaces the cdmo:patent / regulatory / demand hashes with the generated universe.",
       jobs=["fetch-nsq", "sync-sources", "build-universe", "src-*", "load-seeds"]),
    _n("b_plants", "build", "script", "load_plant_assets / sync-plants", "upsert plants",
       "Loads demo plants from the seed and re-publishes every plant saved in Postgres to Redis.", jobs=["load-seeds", "sync-plants"]),
    _n("b_snapshot", "build", "script", "dump / restore snapshot", "Redis ⇄ file",
       "dump_snapshot writes nsq:* and geo:* to the snapshot file; restore_snapshot loads it back (optionally flushing first).",
       jobs=["snapshot", "restore-snapshot"]),
    _n("b_upstash", "build", "script", "pull_upstash.py", "mirror / backup",
       "Mirrors nsq:* and geo:* and upserts cdmo:* between local Redis and Upstash, in either direction.",
       jobs=["pull-upstash", "backup-to-upstash"]),
    _n("b_geo", "build", "script", "load_geojson_redis.py", "manual (just push-geojson)",
       "Compresses the GeoJSON and stores it in Redis."),

    # --- stores: Redis --------------------------------------------------------------------------------
    _n("r_nsq", "stores", "redis", "NSQ records", "nsq:records · nsq:record:* …", "One hash per alert, the id set, month index, manufacturer predictions and load metadata.",
       group="Redis", keys=["nsq:records (set)", "nsq:record:<id> (hash)", "nsq:prediction:<id> (hash)", "nsq:by_month:<YYYY-MM> (set)", "nsq:meta (hash)"]),
    _n("r_onto", "stores", "redis", "Ontologies", "companies · products", "Canonical manufacturer and product names with aliases.",
       group="Redis", keys=["nsq:ontology:companies (hash of JSON)", "nsq:ontology:products (hash of JSON)", "…:meta"]),
    _n("r_frame", "stores", "redis", "Enriched frame", "nsq:frame:enriched", "The analytics table every NSQ chart reads, as gzip+base64 parquet, with a meta hash used to detect staleness.",
       group="Redis", keys=["nsq:frame:enriched (string)", "nsq:frame:enriched:meta (hash)"]),
    _n("r_geo", "stores", "redis", "India geography", "geo:india_states", "State boundaries (GeoJSON, gzip+base64).",
       group="Redis", keys=["geo:india_states (string)", "geo:india_states:meta (hash)"]),
    _n("r_cdmo", "stores", "redis", "Molecule intelligence", "cdmo:patent|regulatory|demand:*",
       "Per molecule: patents and loss of exclusivity, regulatory passport, demand profile, each with provenance.",
       group="Redis", keys=["cdmo:patent:<molecule> (hash)", "cdmo:regulatory:<molecule> (hash)", "cdmo:demand:<molecule> (hash)"]),
    _n("r_plant", "stores", "redis", "Plants (live)", "cdmo:plant:*", "Plant capabilities, certifications and capacity used for matching. User plants are backed up in Postgres and restored on API start if missing.",
       group="Redis", keys=["cdmo:plant:<asset_id> (hash)"]),

    # --- stores: Postgres -----------------------------------------------------------------------------
    _n("pg_auth", "stores", "postgres", "Accounts", "users · sessions · invites", "Who can sign in, their role and organisation, active sessions and pending invites. The super admin is created on API start from SUPERADMIN_EMAIL.",
       group="Postgres", keys=["users", "sessions", "invites"]),
    _n("pg_orgs", "stores", "postgres", "Organisations", "orgs", "Customer organisations, the NSQ manufacturer keys that are theirs, and their plant ids.",
       group="Postgres", keys=["orgs"]),
    _n("pg_plants", "stores", "postgres", "Plants (backup)", "plants", "Durable copy of plants created or edited in the app (full payload).",
       group="Postgres", keys=["plants"]),
    _n("pg_mol", "stores", "postgres", "Molecule edits", "molecule_entries · watch_molecules", "Values the super admin typed for a molecule, and molecules added to or excluded from the universe.",
       group="Postgres", keys=["molecule_entries", "watch_molecules"]),
    _n("pg_jobs", "stores", "postgres", "Jobs & schedules", "job_runs · pipeline_schedules", "Every job run with status and log, and the schedule of each pipeline.",
       group="Postgres", keys=["job_runs", "pipeline_schedules"]),
    _n("pg_audit", "stores", "postgres", "Audit log", "audit_log", "Append-only record of every sign-in and every change made through the API.",
       group="Postgres", keys=["audit_log"]),

    # --- services -------------------------------------------------------------------------------------
    _n("s_frame", "services", "service", "NSQ frame", "cached 5 min", "The enriched alert table in memory. Loaded from the precomputed frame; if that is missing or stale it is rebuilt from the records (which also writes the product ontology). Flags spurious batches.",
       keys=["backend/app/data.py: frame()"]),
    _n("s_cdmo", "services", "service", "Molecule intelligence", "cached 2 min", "All patents, passports, demand profiles and plants from Redis.",
       keys=["backend/app/data.py: cdmo()"]),
    _n("s_sites", "services", "service", "Site directory", "rebuilt when inputs change", "Indian manufacturing sites from the 'Manufactured By' address (company + PIN), matched to FDA registrations, import alerts and recalls. Spurious batches excluded.",
       keys=["backend/app/sites.py: directory()"]),
    _n("s_plants", "services", "service", "Plant registry", "rebuilt when the registry or NSQ frame changes",
       "CDSCO plants with parsed capabilities, linked to NSQ sites on company + PIN (or company + town / state). Gives per-capability denominators: plants that can make X and how many had NSQ alerts.",
       keys=["backend/app/plants.py: registry()", "data/sources/cdsco_plants.json"]),
    _n("s_universe", "services", "service", "Universe & source status", "files, read on request", "The molecule universe list and the per-source status the pipelines page shows.",
       keys=["data/generated/molecule_universe.json", "data/sources/manifest.json"]),
    _n("s_static", "services", "service", "Built-in knowledge", "code, versioned with the app", "Regulation table by country (compiled, indicative), process models, GMP knowledge and pharmacopoeia differences.",
       keys=["core/regulatory_regions.py", "core/process_models.py", "core/gmp_knowledge.py", "core/pharmacopeia_diff.py"]),
    _n("s_lab", "services", "service", "Lab models", "RDKit · thermo · psychrolib",
       "Descriptors, solubility (GSE / ESOL), provisional BCS class, dissolution, compaction and fluid-bed models computed from structure; crystallisation in PharmaPy or the built-in engine.",
       keys=["backend/app/lab.py", "core/chem/*", "data/structures_seed.json"]),
    _n("s_sim", "services", "service", "PharmaPy sim service", "separate container",
       "Purdue's PharmaPy (population-balance crystalliser) behind a small HTTP API. Optional: the lab falls back to the built-in engine.",
       keys=["sim/app.py", "SIM_URL"]),
    _n("s_auth", "services", "service", "Sign-in & permissions", "every request", "Resolves the session cookie to a user and role; enforces who can see and change what.",
       keys=["backend/app/security.py"]),

    # --- pages ----------------------------------------------------------------------------------------
    _n("p_login", "pages", "page", "Sign in & account", "/login · /account", "", group="Everyone", route="/login", endpoints=["/api/auth/*"]),
    _n("p_explore", "pages", "page", "Playground · Explorer & Ledger", "/playground", "", group="Playground", route="/playground/explore",
       endpoints=["/api/playground/facets", "/cube", "/ledger", "/ledger.csv", "/geo/india"]),
    _n("p_insights", "pages", "page", "Playground · Insights", "/playground/insights", "", group="Playground", route="/playground/insights", endpoints=["/api/playground/insights"]),
    _n("p_world", "pages", "page", "Playground · Regulation map", "/playground/world", "", group="Playground", route="/playground/world", endpoints=["/api/playground/world"]),
    _n("p_workbench", "pages", "page", "Playground · Molecule workbench", "/playground/molecule", "", group="Playground", route="/playground/molecule", endpoints=["/api/playground/molecule/{key}"]),
    _n("p_plants", "pages", "page", "Playground · Plants", "/playground/plants", "", group="Playground", route="/playground/plants", endpoints=["/api/plants", "/api/plants/summary", "/api/plants/{id}"]),
    _n("p_health", "pages", "page", "Playground · Health & trade", "/playground/health", "", group="Playground", route="/playground/health",
       endpoints=["/api/playground/signals/nfhs", "/api/playground/signals/outbreaks", "/api/playground/signals/trade"]),
    _n("p_investigate", "pages", "page", "Playground · Investigate", "/playground/investigate", "", group="Playground", route="/playground/investigate",
       endpoints=["/api/playground/investigate/search", "/api/playground/investigate/product", "/api/playground/investigate/manufacturer/{key}",
                  "/api/playground/investigate/manufacturer/{key}/alerts/{id}"]),
    _n("p_forensics", "pages", "page", "Playground · Failure forensics", "/playground/forensics", "", group="Playground", route="/playground/forensics",
       endpoints=["/api/playground/forensics", "/api/playground/forensics/products", "/api/playground/forensics/product"]),
    _n("p_wc", "pages", "page", "Playground · Written confirmations", "/playground/wc", "", group="Playground", route="/playground/wc",
       endpoints=["/api/playground/wc", "/api/playground/wc/{id}.pdf"]),
    _n("p_process", "pages", "page", "Playground · Lab", "/playground/process", "", group="Playground", route="/playground/process", endpoints=["/api/lab/*", "/api/process/*"]),
    _n("p_org_overview", "pages", "page", "Org · Overview", "/o/:slug", "", group="Organisation", endpoints=["/api/orgs/{slug}/overview"]),
    _n("p_org_quality", "pages", "page", "Org · Quality", "/o/:slug/quality", "", group="Organisation", endpoints=["/api/orgs/{slug}/quality", "/quality/issues"]),
    _n("p_org_infra", "pages", "page", "Org · Infrastructure", "/o/:slug/infrastructure", "", group="Organisation",
       endpoints=["/api/orgs/{slug}/infrastructure", "/site-suggestions", "POST /plants", "PUT /plants/{id}", "POST /plants/from-site"]),
    _n("p_org_opps", "pages", "page", "Org · Opportunities", "/o/:slug/opportunities", "", group="Organisation", endpoints=["/api/orgs/{slug}/opportunities"]),
    _n("p_org_eu", "pages", "page", "Org · EU export", "/o/:slug/eu", "", group="Organisation", endpoints=["/api/orgs/{slug}/eu-export"]),
    _n("p_admin_overview", "pages", "page", "Admin overview", "/admin", "", group="Platform admin", route="/admin", endpoints=["/api/admin/overview", "/api/data/status"]),
    _n("p_admin_explorer", "pages", "page", "All-India NSQ", "/admin/explorer", "", group="Platform admin", route="/admin/explorer", endpoints=["/api/nsq/summary", "/api/nsq/alerts"]),
    _n("p_admin_orgs", "pages", "page", "Organisations", "/admin/orgs", "", group="Platform admin", route="/admin/orgs", endpoints=["/api/admin/orgs", "/api/admin/manufacturers", "/api/admin/plants"]),
    _n("p_admin_users", "pages", "page", "Users & team", "/admin/users · /o/:slug/team", "", group="Platform admin", route="/admin/users", endpoints=["/api/admin/users", "/api/admin/invites"]),
    _n("p_admin_pipelines", "pages", "page", "Data pipelines", "/admin/pipelines", "", group="Platform admin", route="/admin/pipelines", endpoints=["/api/pipelines", "PUT /api/pipelines/schedules/{job}"]),
    _n("p_admin_jobs", "pages", "page", "Data jobs", "/admin/jobs", "", group="Platform admin", route="/admin/jobs", endpoints=["/api/jobs", "POST /api/jobs/{key}/run", "/api/jobs/uploads"]),
    _n("p_admin_molecules", "pages", "page", "Molecule universe", "/admin/molecules", "", group="Platform admin", route="/admin/molecules",
       endpoints=["/api/pipelines/molecules", "/api/molecules/*", "/api/pipelines/watchlist"]),
    _n("p_admin_sites", "pages", "page", "Site directory", "/admin/sites", "", group="Platform admin", route="/admin/sites", endpoints=["/api/pipelines/sites*"]),
    _n("p_admin_audit", "pages", "page", "Audit log", "/admin/audit", "", group="Platform admin", route="/admin/audit", endpoints=["/api/admin/audit"]),
    _n("p_admin_datamap", "pages", "page", "Data map", "/admin/data-map", "", group="Platform admin", route="/admin/data-map", endpoints=["/api/platform/datamap"]),
]


def _e(a: str, b: str, kind: str = "flow", label: str = "", when: str = "") -> dict[str, Any]:
    return {"from": a, "to": b, "kind": kind, "label": label, "when": when}


EDGES: list[dict[str, Any]] = [
    # ingest
    _e("ext_cdsco", "in_cdsco", label="publicNsqDrugTable (by month)"),
    _e("in_cdsco", "f_csv", "write", "append new alerts", "fetch-nsq · daily 06:30 IST"),
    _e("in_cdsco", "f_raw", "write", "raw JSON per month", "fetch-nsq"),
    _e("in_cdsco", "f_manifest", "write", "cdsco status", "fetch-nsq"),
    *[_e(s, "in_sources", label=l) for s, l in (("ext_orange", "zip, weekly at most"), ("ext_purple", "monthly CSV"), ("ext_ema", "JSON report"),
                                                 ("ext_ct", "count queries"), ("ext_fdasites", "DECRS · import alert · recalls"),
                                                 ("ext_cdsco_plants", "SUGAM pages + WHO-GMP PDF · laptop"), ("ext_eudragmdp", "certificate pages · laptop"),
                                                 ("ext_fda_insp", "API key or Excel export"), ("ext_filings", "quarterly .xls · daily .txt"),
                                                 ("ext_ord", "Parquet · server, monthly"), ("ext_health", "CSV files · weekly PDFs"), ("ext_comtrade", "API / public preview"), ("ext_cdsco_wc", "page + PDFs · laptop"))],
    _e("in_sources", "f_raw", "write", "downloads + ETags", "sync-sources · daily 02:30 IST, or src-*"),
    _e("in_sources", "f_sources", "write", "normalised JSON", "sync-sources, src-*"),
    _e("in_sources", "f_manifest", "write", "status per source", "sync-sources, src-*"),
    _e("f_uploads", "in_sources", label="--from-file (when a site blocks us)"),
    _e("f_generated", "in_sources", label="candidates.json → which molecules to query on ClinicalTrials"),
    _e("ext_curated", "f_seeds", "write", "edited in the repo", "code change"),
    # build
    _e("pg_mol", "b_export", label="entries + watchlist"),
    _e("b_export", "f_entries", "write", "JSON export", "before every universe build"),
    _e("f_csv", "b_nsq", label="all alerts"),
    _e("f_uploads", "b_nsq", label="csv param (refresh-nsq)"),
    _e("b_nsq", "r_nsq", "write", "flush + reload all nsq:record/*", "fetch-nsq (when new alerts), refresh-nsq"),
    _e("b_nsq", "r_onto", "write", "company ontology (augment)", "fetch-nsq, refresh-nsq"),
    _e("f_csv", "b_products", label="product names"),
    _e("b_products", "r_onto", "write", "product ontology", "fetch-nsq, refresh-nsq"),
    _e("r_nsq", "b_frame", label="records + predictions"),
    _e("r_onto", "b_frame", label="canonical names"),
    _e("b_frame", "r_frame", "write", "replace frame", "fetch-nsq, refresh-nsq, build-frame, restore-snapshot"),
    _e("f_seeds", "b_universe", label="curated layer"),
    _e("f_sources", "b_universe", label="Orange/Purple Book, EMA, trials"),
    _e("f_entries", "b_universe", label="typed values win"),
    _e("r_nsq", "b_universe", label="alert counts per ingredient"),
    _e("b_universe", "f_generated", "write", "universe JSON", "fetch-nsq, sync-sources, build-universe, src-*"),
    _e("f_generated", "b_cdmo", label="patents / regulatory / demand"),
    _e("b_cdmo", "r_cdmo", "write", "flush + reload cdmo:*", "same jobs as the universe build"),
    _e("f_seeds", "b_plants", label="demo plants"),
    _e("pg_plants", "b_plants", label="user plants"),
    _e("b_plants", "r_plant", "write", "upsert", "load-seeds, sync-plants"),
    _e("r_nsq", "b_snapshot", label="dump"),
    _e("b_snapshot", "f_snapshot", "write", "dump nsq:* + geo:*", "snapshot job (weekly if enabled)"),
    _e("f_snapshot", "b_snapshot", label="restore"),
    _e("b_snapshot", "r_nsq", "write", "restore (optional flush)", "restore-snapshot"),
    _e("ext_upstash", "b_upstash", label="pull"),
    _e("b_upstash", "r_nsq", "write", "mirror nsq:* and geo:*", "pull-upstash"),
    _e("b_upstash", "r_cdmo", "write", "upsert cdmo:*", "pull-upstash"),
    _e("b_upstash", "ext_upstash", "write", "backup local → Upstash", "backup-to-upstash"),
    _e("f_geo", "b_geo", label="GeoJSON"),
    _e("b_geo", "r_geo", "write", "compress + store", "manual: just push-geojson"),
    # jobs (triggers)
    _e("act_scheduler", "act_runner", "trigger", "due schedules"),
    *[_e("act_runner", t, "trigger") for t in ("in_cdsco", "in_sources", "b_export", "b_nsq", "b_products", "b_frame", "b_universe", "b_cdmo", "b_plants", "b_snapshot", "b_upstash")],
    _e("act_runner", "pg_jobs", "write", "run status + live log", "every job"),
    _e("act_scheduler", "pg_jobs", "write", "next / last fire time", "every 30 s"),
    # API start-up
    _e("pg_plants", "r_plant", "write", "restore missing user plants", "API start"),
    _e("s_auth", "pg_auth", "write", "seed / repair super admin; sliding session expiry", "API start; every request"),
    # services
    _e("r_frame", "s_frame", label="preferred (if not stale)"),
    _e("r_nsq", "s_frame", label="fallback: rebuild"),
    _e("r_onto", "s_frame", label="canonical names"),
    _e("f_snapshot", "s_frame", label="fallback if Redis empty"),
    _e("s_frame", "r_onto", "write", "product ontology, only on the fallback rebuild", "API, when the frame is missing or stale"),
    _e("r_cdmo", "s_cdmo"),
    _e("r_plant", "s_cdmo"),
    _e("s_frame", "s_sites", label="'Manufactured By' addresses"),
    _e("f_sources", "s_sites", label="FDA establishments, import alerts, recalls"),
    _e("f_generated", "s_universe", label="molecule_universe.json"),
    _e("f_manifest", "s_universe", label="source status"),
    _e("pg_auth", "s_auth", label="session → user"),
    # pages: reads
    _e("s_auth", "p_login"),
    _e("s_frame", "p_explore", label="cube, ledger, facets"), _e("r_geo", "p_explore", label="state boundaries"),
    _e("s_frame", "p_insights"), _e("s_cdmo", "p_insights", label="export whitespace"), _e("s_sites", "p_insights", label="hubs, FDA overlap"),
    _e("s_cdmo", "p_world"), _e("s_static", "p_world", label="regulation table"), _e("s_sites", "p_world"),
    _e("s_cdmo", "p_workbench"), _e("s_frame", "p_workbench"), _e("s_static", "p_workbench"), _e("pg_orgs", "p_workbench", label="your plants"),
    _e("s_static", "p_process", label="legacy Telmisartan demo"),
    _e("s_lab", "p_process", label="molecule, dissolution, crystallisation, compaction, fluid bed"),
    _e("s_sim", "s_lab", label="crystallisation (PharmaPy)"),
    _e("ext_faers", "s_lab", label="safety signals (live, cached 24 h)"),
    _e("f_sources", "s_lab", label="pubchem.json"), _e("f_seeds", "s_lab", label="structures_seed.json"),
    _e("s_frame", "s_lab", label="NSQ alerts per ingredient"),
    _e("ext_pubchem", "in_sources", label="PUG REST, 80 molecules/run"),
    _e("s_frame", "p_org_overview"), _e("s_cdmo", "p_org_overview"), _e("pg_orgs", "p_org_overview"),
    _e("s_frame", "p_org_quality", label="your alerts + national"), _e("pg_orgs", "p_org_quality", label="your manufacturer keys"),
    _e("s_cdmo", "p_org_infra"), _e("s_sites", "p_org_infra", label="site suggestions"), _e("pg_plants", "p_org_infra", label="editable flag"),
    _e("s_cdmo", "p_org_opps"), _e("s_frame", "p_org_opps"),
    _e("s_cdmo", "p_org_eu"), _e("s_frame", "p_org_eu"),
    _e("s_frame", "p_admin_overview"), _e("pg_jobs", "p_admin_overview"), _e("pg_audit", "p_admin_overview", label="sign-in counts"),
    _e("r_nsq", "p_admin_overview", label="data status"), _e("f_snapshot", "p_admin_overview", label="data status"),
    _e("s_frame", "p_admin_explorer"),
    _e("pg_orgs", "p_admin_orgs"), _e("s_frame", "p_admin_orgs", label="manufacturer search"), _e("s_cdmo", "p_admin_orgs", label="plants"),
    _e("s_auth", "p_admin_users"),
    _e("pg_jobs", "p_admin_pipelines"), _e("s_universe", "p_admin_pipelines"), _e("s_sites", "p_admin_pipelines", label="site summary"),
    _e("pg_jobs", "p_admin_jobs"), _e("f_uploads", "p_admin_jobs"),
    _e("s_universe", "p_admin_molecules"), _e("s_cdmo", "p_admin_molecules"), _e("pg_mol", "p_admin_molecules"),
    _e("f_seeds", "p_admin_molecules", label="lookup"), _e("f_sources", "p_admin_molecules", label="lookup"),
    _e("s_sites", "p_admin_sites"), _e("pg_orgs", "p_admin_sites"),
    _e("f_sources", "s_plants", label="cdsco_plants + eudragmdp + fda_inspections + fda_establishments + fda_import_alerts + fda_dmf + edqm_cep"),
    _e("f_seeds", "s_plants", label="demo profiles' registry links (official records replace stated certifications)"),
    _e("s_plants", "s_cdmo", label="linked profiles: confirmed vs claimed certifications, official forms"),
    _e("in_sources", "f_docs", "write", "Written Confirmation PDFs", "laptop: just fetch-cdsco-wc · just push-wc"),
    _e("f_docs", "p_wc", label="PDF viewer"),
    _e("s_frame", "p_forensics", label="alerts grouped by product: failed tests, shelf-life timing, makers, labs"),
    _e("s_lab", "p_forensics", label="XLogP3, amines (chemistry of the failure)"),
    _e("s_frame", "p_investigate", label="any product / manufacturer, nationally"), _e("s_static", "p_investigate", label="GMP standards, causes, mitigation"),
    _e("s_sites", "s_plants", label="NSQ sites to link"), _e("s_plants", "p_plants"), _e("s_plants", "p_workbench", label="this plant for this molecule · who can make it · plant fit for every plant"), _e("s_plants", "p_admin_sites", label="registry match"),
    _e("s_plants", "p_org_infra", label="stated capabilities on 'add as plant'"),
    _e("pg_audit", "p_admin_audit"),
    _e("pg_jobs", "p_admin_datamap", label="live counts"),
    _e("f_sources", "p_health", label="nfhs · idsp · comtrade .json"),
    _e("f_sources", "p_wc", label="cdsco_wc.json + data/docs/cdsco_wc/*.pdf"),
    _e("f_sources", "p_workbench", label="ord.json — how it's made"),
    # pages: mutations (every one is also written to audit_log)
    _e("p_login", "pg_auth", "write", "sign in / out, change password, accept invite", "user action"),
    _e("p_admin_users", "pg_auth", "write", "create user or invite, change role, deactivate, reset password, revoke sessions", "admin or org admin"),
    _e("p_admin_orgs", "pg_orgs", "write", "create / edit organisation, link manufacturers and plants", "platform admin"),
    _e("p_org_infra", "pg_plants", "write", "add / edit plant", "org admin or platform admin"),
    _e("p_org_infra", "r_plant", "write", "same call updates the live copy", "org admin or platform admin"),
    _e("p_org_infra", "pg_orgs", "write", "attach plant id", "org admin or platform admin"),
    _e("p_admin_sites", "pg_plants", "write", "add a site as a plant", "platform admin"),
    _e("p_admin_sites", "r_plant", "write", "same call updates the live copy", "platform admin"),
    _e("p_admin_molecules", "pg_mol", "write", "add / edit / untrack molecule, watchlist", "super admin only"),
    _e("p_admin_molecules", "act_runner", "trigger", "save → build-universe"),
    _e("p_admin_jobs", "act_runner", "trigger", "Run job"),
    _e("p_admin_jobs", "f_uploads", "write", "upload a file", "platform admin"),
    _e("p_admin_pipelines", "act_runner", "trigger", "Run pipeline"),
    _e("p_admin_pipelines", "pg_jobs", "write", "edit schedule", "platform admin"),
    *[_e(p, "pg_audit", "write", "audit entry", "every change above") for p in
      ("p_login", "p_admin_users", "p_admin_orgs", "p_org_infra", "p_admin_sites", "p_admin_molecules", "p_admin_jobs", "p_admin_pipelines")],
]


# --- live numbers ----------------------------------------------------------------------------------------

_cache: dict[str, Any] = {}
_lock = threading.Lock()
TTL_S = 60.0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _file_stat(paths: list[Path]) -> dict[str, Any]:
    files = [p for p in paths if p.exists() and p.is_file()]
    if not files:
        return {"ok": False, "text": "missing"}
    newest = max(p.stat().st_mtime for p in files)
    size = sum(p.stat().st_size for p in files)
    return {"ok": True, "files": len(files), "bytes": size, "updated_at": _iso(newest),
            "text": f"{len(files)} file{'s' if len(files) != 1 else ''} · {size / 1e6:.1f} MB"}


def _glob(d: Path, pattern: str) -> list[Path]:
    return sorted(d.glob(pattern)) if d.exists() else []


def _redis_stats() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        r = data.redis_client()
        meta = r.hgetall("nsq:meta")
        out["r_nsq"] = {"ok": True, "count": r.scard("nsq:records"), "text": f"{r.scard('nsq:records'):,} alerts", "updated_at": meta.get("loaded_at")}
        comp, prod = r.hlen("nsq:ontology:companies"), r.hlen("nsq:ontology:products")
        out["r_onto"] = {"ok": bool(comp or prod), "text": f"{comp:,} companies · {prod:,} products"}
        fm = r.hgetall("nsq:frame:enriched:meta")
        out["r_frame"] = {"ok": bool(fm), "text": f"{int(fm.get('rows', 0)):,} rows · {int(fm.get('stored_bytes', 0)) / 1e6:.1f} MB" if fm else "missing",
                          "updated_at": fm.get("built_at")}
        gm = r.hgetall("geo:india_states:meta")
        out["r_geo"] = {"ok": bool(r.exists("geo:india_states")), "text": "loaded" if r.exists("geo:india_states") else "missing",
                        "updated_at": gm.get("loaded_at")}
        fams = {f: sum(1 for _ in r.scan_iter(match=f"cdmo:{f}:*", count=1000)) for f in ("patent", "regulatory", "demand", "plant")}
        out["r_cdmo"] = {"ok": fams["patent"] > 0, "count": fams["patent"],
                         "text": f"{fams['patent']} patents · {fams['regulatory']} passports · {fams['demand']} demand"}
        out["r_plant"] = {"ok": fams["plant"] > 0, "count": fams["plant"], "text": f"{fams['plant']} plants"}
    except Exception as exc:  # Redis down: the map still renders
        for k in ("r_nsq", "r_onto", "r_frame", "r_geo", "r_cdmo", "r_plant"):
            out[k] = {"ok": False, "text": f"Redis unavailable: {exc.__class__.__name__}"}
    return out


def _pg_stats(db: Session) -> dict[str, dict[str, Any]]:
    def c(model) -> int:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)
    last_job = db.scalar(select(func.max(JobRun.finished_at)))
    last_audit = db.scalar(select(func.max(AuditLog.at)))
    return {
        "pg_auth": {"ok": True, "text": f"{c(User)} users · {c(UserSession)} sessions · {c(Invite)} invites"},
        "pg_orgs": {"ok": True, "count": c(Org), "text": f"{c(Org)} organisations"},
        "pg_plants": {"ok": True, "count": c(Plant), "text": f"{c(Plant)} plants saved in the app"},
        "pg_mol": {"ok": True, "text": f"{c(MoleculeEntry)} molecule entries · {c(WatchMolecule)} watchlist"},
        "pg_jobs": {"ok": True, "text": f"{c(JobRun)} runs · {c(PipelineSchedule)} schedules",
                    "updated_at": last_job.isoformat() if last_job else None},
        "pg_audit": {"ok": True, "count": c(AuditLog), "text": f"{c(AuditLog):,} entries", "updated_at": last_audit.isoformat() if last_audit else None},
    }


def _source_stats() -> dict[str, dict[str, Any]]:
    try:
        import sys
        if str(settings.loader_dir) not in sys.path:
            sys.path.insert(0, str(settings.loader_dir))
        from sources.common import read_manifest
        m = read_manifest()
    except Exception:
        m = {}
    from .jobs import source_status

    def s(keys: list[str]) -> dict[str, Any]:
        # the file itself counts: sources fetched on a laptop and pushed have no manifest entry on the server
        rows = [{**(m.get(k) or {}), **{kk: vv for kk, vv in source_status(k).items() if vv is not None}} if k != "cdsco" else (m.get(k) or {}) for k in keys]
        if not any(r.get("file") or r.get("status") for r in rows):
            return {"ok": False, "text": "never fetched"}
        bad = [k for k, r in zip(keys, rows) if r.get("state") in ("failing", "missing") or (r.get("status") not in ("ok", "unchanged", None) and not r.get("file"))]
        last = max((r.get("last_success") or "" for r in rows), default="")
        recs = sum(int(r.get("records") or 0) for r in rows)
        parts = [f"{recs:,} records"] if recs else []
        parts += [f"{k.replace('_', ' ')}: {rows[keys.index(k)].get('status') or 'missing'}" for k in bad]
        return {"ok": not bad, "text": " · ".join(parts) or "fetched", "updated_at": last or None}
    return {"ext_cdsco": s(["cdsco"]), "ext_orange": s(["orange_book"]), "ext_purple": s(["purple_book"]), "ext_ema": s(["ema"]),
            "ext_ct": s(["clinical_trials"]), "ext_fdasites": s(["fda_establishments", "fda_import_alerts", "fda_recalls"]),
            "ext_cdsco_plants": s(["cdsco_plants"]), "ext_eudragmdp": s(["eudragmdp"]), "ext_fda_insp": s(["fda_inspections"]), "ext_filings": s(["fda_dmf", "edqm_cep"]),
            "ext_health": s(["nfhs", "idsp"]), "ext_ord": s(["ord"]), "ext_comtrade": s(["comtrade"]), "ext_cdsco_wc": s(["cdsco_wc"])}


def _file_stats() -> dict[str, dict[str, Any]]:
    d = settings.data_dir
    repo = settings.loader_dir.parent
    return {
        "f_csv": _file_stat(_glob(d, "CDSCO*NSQ*.csv")),
        "f_raw": _file_stat([p for p in _glob(d / "raw", "**/*") if p.is_file()]),
        "f_sources": _file_stat([p for p in _glob(d / "sources", "*.json") if p.name != "manifest.json"]),
        "f_manifest": _file_stat([d / "sources" / "manifest.json"]),
        "f_uploads": _file_stat(_glob(d / "uploads", "*")),
        "f_seeds": _file_stat([d / f for f in ("patent_seed.json", "regulatory_seed.json", "demand_seed.json", "plant_assets_seed.json")]),
        "f_docs": _file_stat(_glob(d / "docs" / "cdsco_wc", "*.pdf")),
        "f_entries": _file_stat([d / "generated" / f for f in ("watchlist.json", "molecules.json")]),
        "f_generated": _file_stat([d / "generated" / f for f in ("patents.json", "regulatory.json", "demand.json", "molecule_universe.json", "candidates.json")]),
        "f_snapshot": _file_stat([settings.snapshot_path]),
        "f_geo": _file_stat([settings.data_dir / "geo" / "india_states_slim.geojson"]),
    }


def _service_stats() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        df = data.frame()
        spur = int(df["_spurious"].sum()) if "_spurious" in df.columns else 0
        out["s_frame"] = {"ok": not df.empty, "text": f"{len(df):,} alerts · {spur} spurious · from {data.frame_source()}"}
    except Exception as exc:
        out["s_frame"] = {"ok": False, "text": f"unavailable: {exc.__class__.__name__}"}
    try:
        from . import sites
        out["s_sites"] = {"ok": True, "text": f"{len(sites.directory()):,} sites"}
    except Exception as exc:
        out["s_sites"] = {"ok": False, "text": f"unavailable: {exc.__class__.__name__}"}
    try:
        from . import plants
        reg = plants.registry()
        out["s_plants"] = {"ok": bool(reg["plants"]), "text": f"{len(reg['plants']):,} plants · {len(reg['links']):,} NSQ sites linked" if reg["plants"] else "not built"}
    except Exception as exc:
        out["s_plants"] = {"ok": False, "text": f"unavailable: {exc.__class__.__name__}"}
    return out


def live(db: Session) -> dict[str, Any]:
    now = time.monotonic()
    hit = _cache.get("live")
    if hit and now < hit[0]:
        return hit[1]
    with _lock:
        stats: dict[str, Any] = {}
        for fn in (_redis_stats, _source_stats, _file_stats, _service_stats):
            try:
                stats.update(fn())
            except Exception as exc:  # one failing probe must not break the map
                stats[f"_error_{fn.__name__}"] = str(exc)
        stats.update(_pg_stats(db))
        value = {"checked_at": datetime.now(timezone.utc).isoformat(), "stats": stats}
        _cache["live"] = (now + TTL_S, value)
        return value


def mutations() -> list[dict[str, Any]]:
    """Every write edge as a row: which store changes, who changes it, how, and when."""
    by_id = {n["id"]: n for n in NODES}
    rows = []
    for e in EDGES:
        if e["kind"] != "write":
            continue
        a, b = by_id[e["from"]], by_id[e["to"]]
        rows.append({"store": b["id"], "store_label": b["label"], "store_kind": b["kind"], "by": a["id"], "by_label": a["label"],
                     "by_kind": a["kind"], "what": e["label"], "when": e["when"]})
    order = {n["id"]: i for i, n in enumerate(NODES)}
    return sorted(rows, key=lambda r: (order[r["store"]], order[r["by"]]))


def graph(db: Session) -> dict[str, Any]:
    return {"columns": COLUMNS, "nodes": NODES, "edges": EDGES, "mutations": mutations(), **live(db)}


def validate() -> list[str]:
    """Problems in the hand-written graph (used by tests)."""
    ids = [n["id"] for n in NODES]
    errs = [f"duplicate node {i}" for i in set(ids) if ids.count(i) > 1]
    cols = {c["key"] for c in COLUMNS}
    errs += [f"{n['id']}: unknown column {n['col']}" for n in NODES if n["col"] not in cols]
    known = set(ids)
    errs += [f"edge {e['from']}→{e['to']}: unknown node" for e in EDGES if e["from"] not in known or e["to"] not in known]
    errs += [f"edge {e['from']}→{e['to']}: bad kind" for e in EDGES if e["kind"] not in ("flow", "write", "trigger")]
    errs += [f"write edge {e['from']}→{e['to']} has no 'when'" for e in EDGES if e["kind"] == "write" and not e["when"]]
    touched = {e["from"] for e in EDGES} | {e["to"] for e in EDGES}
    errs += [f"{i}: not connected" for i in ids if i not in touched]
    return errs
