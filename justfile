# justfile for the NSQ platform.
#
# SECURITY: never put your Redis URL in this file. It's read from a single
# root-level .env (already in .gitignore).
#
#   cp .env.example .env
#   # edit .env: paste your Redis URL (rediss:// for Upstash — TLS is required)
#
# NOTE: rotate any credential that has ever been pasted into a chat,
# ticket, or log — treat it as burned the moment it left your terminal.

set dotenv-load := true
set dotenv-filename := ".env"

LOADER := "redis-loader"
INPUT := env_var_or_default("NSQ_JSON", "data/publicNsqDrugTable.json")
# The cumulative CDSCO export. Redis (the prod cluster) is the source of
# truth for the running apps; this CSV is the input that *builds* that state.
# It is gitignored (data/*.csv), so a fresh clone will not have it — the
# _require-csv guard below fails with the expected path instead of a pandas
# stack trace. core/nsq_redis.py's _DEFAULT_CSV must match this.
CSV := env_var_or_default("NSQ_CSV", "data/CDSCO Not of Standard Quality (NSQ) Jan 21-Jul 26.csv")
AUGMENT := env_var_or_default("NSQ_AUGMENT", "1")
# Destructive recipes (anything passing --flush) wipe the nsq:* keyspace in
# whatever Redis $REDIS_URL points at — which is the prod Upstash cluster in
# the local .env. They refuse to run unless this is "yes".
CONFIRM_FLUSH := env_var_or_default("CONFIRM_FLUSH", "no")
CDSCO_URL := env_var_or_default("CDSCO_URL", "https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable")
GEOJSON := env_var_or_default("GEOJSON_FILE", "analytics/india_states_slim.geojson")
GEOJSON_KEY := env_var_or_default("GEOJSON_KEY", "geo:india_states")
SNAPSHOT := env_var_or_default("NSQ_SNAPSHOT_OUT", "data/nsq_snapshot.json.gz")

# Show configured target (without leaking the password)
info:
    @echo "Input file: {{INPUT}}"
    @python3 -c "import os,re; u=os.environ.get('REDIS_URL',''); print('Redis host:', re.sub(r'://[^@]*@', '://***:***@', u) or '(unset — set REDIS_URL)')"

# Install loader dependencies into a local venv (redis-loader/.venv)
setup:
    cd {{LOADER}} && python3 -m venv .venv
    cd {{LOADER}} && .venv/bin/pip install --quiet -r requirements.txt

# Verify connectivity to Redis without loading anything
ping:
    cd {{LOADER}} && .venv/bin/python ping_redis.py

# Load {{INPUT}} into Redis (additive — keeps any existing nsq:* keys)
# --- guards ---------------------------------------------------------------
# Private helpers (leading _). Every recipe that reads an input file or wipes
# Redis depends on one of these, so a missing file or an unintended flush
# fails with a sentence instead of a stack trace or silent data loss.

_require-csv:
    @test -f "{{CSV}}" || { \
      echo "CSV not found: {{CSV}} (data/*.csv is gitignored)."; \
      echo "Rebuilding it from the NSQ records in \$REDIS_URL ..."; \
      cd {{LOADER}} && .venv/bin/python sync_cdsco.py --csv "../{{CSV}}" --bootstrap-only || { \
        echo "ERROR: could not rebuild the CSV. Seed Redis first (just seed-local, or"; \
        echo "  Admin → Data jobs → Restore from snapshot), or point at a file with"; \
        echo "    NSQ_CSV='data/your-export.csv' just <recipe>"; \
        exit 1; }; }

_require-json:
    @test -f "{{INPUT}}" || { \
      echo "ERROR: JSON input not found: {{INPUT}}"; \
      echo "  Override with: NSQ_JSON='data/your-export.json' just <recipe>"; \
      exit 1; }

_confirm-flush:
    @test "{{CONFIRM_FLUSH}}" = "yes" || { \
      echo "REFUSING: this recipe wipes the nsq:* keyspace in \$REDIS_URL,"; \
      echo "  which .env points at the prod Redis cluster. The apps read their"; \
      echo "  data from there, not from the CSV."; \
      echo "  Re-run with CONFIRM_FLUSH=yes if that is what you mean:"; \
      echo "    CONFIRM_FLUSH=yes just <recipe>"; \
      exit 1; }

load: _require-json && build-frame
    cd {{LOADER}} && .venv/bin/python load_nsq_redis.py --input "../{{INPUT}}" --redis-url "$REDIS_URL"

# Load {{INPUT}} into Redis, wiping existing nsq:* keys first
reload: _require-json _confirm-flush && build-frame
    cd {{LOADER}} && .venv/bin/python load_nsq_redis.py --input "../{{INPUT}}" --redis-url "$REDIS_URL" --flush

# Load {{CSV}} into Redis (additive, augment=ON by default — populates
# nsq:record:* + nsq:prediction:* + nsq:ontology:companies in one pass).
# Set NSQ_AUGMENT=0 to skip augmentation (raw records only).
load-csv: _require-csv && build-product-ontology build-frame
    cd {{LOADER}} && .venv/bin/python load_csv_redis.py --input "../{{CSV}}" --redis-url "$REDIS_URL" --augment {{AUGMENT}}

# Wipe nsq:* keys and reload {{CSV}} with augmentation. The --flush is
# required for the deterministic rebuild: the manufacturer ontology is
# insertion-order-dependent under fuzzy matching, so it must be built in
# ONE pass over the full cumulative CSV (prepare_rows() sorts first, so
# the result is independent of row order). record_id() is a hash of
# (batch_no, product_name, reporting_month, lab) — a non-flush reload
# would leave stale un-harmonized rows and old-key records in Redis.
reload-csv: _require-csv _confirm-flush && build-product-ontology build-frame
    cd {{LOADER}} && .venv/bin/python load_csv_redis.py --input "../{{CSV}}" --redis-url "$REDIS_URL" --flush --augment {{AUGMENT}}

# Deterministic monthly refresh: when a new CDSCO notification lands,
# append its rows to the cumulative CSV ({{CSV}}), then run this. Wipes
# and rebuilds records, predictions, BOTH ontologies, and re-seeds the
# product ontology — the whole nsq:* state is a pure function of the CSV.
refresh-csv: reload-csv verify

# Pre-compute the enriched NSQ frame into Redis (nsq:frame:enriched).
#
# This is the single biggest lever on how the apps feel. The enrichment
# (ontology joins + per-row fuzzy product resolution over ~5,600 rows) used to
# run inside the Streamlit render, behind a 5-minute cache: 33.5s to first
# paint cold, 13.4s warm, on the deployed box. Precomputed, the apps do one
# Redis GET instead.
#
# Runs inside the analytics image so it does not need pandas/pyarrow/rapidfuzz
# on your machine — which matters on Python 3.14, where several of those have
# no wheels yet. Run it after anything that changes nsq:record:* (refresh-csv
# chains it). Forgetting is safe: the frame carries the record count it was
# built from, and the apps fall back to computing when that no longer matches.
# -e REDIS_URL: compose now points the analytics service at the in-server
# `redis` container, but the frame belongs in the upstream Redis the loaders
# just wrote ($REDIS_URL from .env) — pull-upstash copies it down from
# there. NB: no --redis-url; the script defaults to REDIS_URL — so this works on a box
# where the shell has never exported it (e.g. the EC2 host, where `just`
# itself is not installed and you run the docker command by hand).
build-frame:
    @command -v docker >/dev/null 2>&1 || { \
      echo "WARNING: docker not found — the enriched frame was NOT rebuilt."; \
      echo "  Run it from Admin → Data jobs → Rebuild enriched frame instead."; \
      exit 0; }
    docker compose run --rm --no-deps \
      -e REDIS_URL="$REDIS_URL" \
      --entrypoint python3 api /app/redis-loader/build_enriched_frame.py

# Copy the static dataset from Upstash ($REDIS_URL) into the stack's own
# `redis` container, then restart the services that read it. Run after
# every data refresh (on the box: ./pull-upstash.sh — `just` isn't there).
# The services never read Upstash directly; this is the only Upstash read.
pull-upstash *ARGS:
    ./pull-upstash.sh {{ARGS}}

# Refresh the PRODUCTION (Upstash) Redis with the latest CSV. deploy.sh only
# ships code — it does NOT load data — so this is the prod data-refresh step.
# Requires PROD_REDIS_URL (set it in .env or pass inline); refuses to run
# against the local REDIS_URL so you can't clobber the wrong Redis.
# Finishes by dumping a local snapshot ({{SNAPSHOT}}) — commit it with the
# data refresh so the deployed containers have a fallback when the Upstash
# monthly command quota runs out mid-month.
refresh-prod:
    @test -n "${PROD_REDIS_URL:-}" || { echo "PROD_REDIS_URL not set — refusing to guess the prod Redis."; exit 1; }
    cd {{LOADER}} && .venv/bin/python load_csv_redis.py --input "../{{CSV}}" --redis-url "$PROD_REDIS_URL" --flush --augment {{AUGMENT}}
    cd {{LOADER}} && .venv/bin/python build_product_ontology.py --input "../{{CSV}}" --redis-url "$PROD_REDIS_URL"
    cd {{LOADER}} && REDIS_URL="$PROD_REDIS_URL" .venv/bin/python verify_nsq_redis.py
    cd {{LOADER}} && .venv/bin/python dump_snapshot.py --redis-url "$PROD_REDIS_URL" --output "../{{SNAPSHOT}}" --source-label prod

# Dump the runtime-needed Redis keyspace to a local snapshot (dev Redis).
# The snapshot is the fallback tier served when Redis is unavailable —
# see core/nsq_redis.py. Git-track the file so deploys carry it.
snapshot:
    cd {{LOADER}} && .venv/bin/python dump_snapshot.py --redis-url "$REDIS_URL" --output "../{{SNAPSHOT}}" --source-label dev

# Dump the snapshot from the PRODUCTION Redis (the one the deployed
# containers read). Refuses the dev URL so the snapshot can't be quietly
# overwritten with dev data.
snapshot-prod:
    @test -n "${PROD_REDIS_URL:-}" || { echo "PROD_REDIS_URL not set — refusing to guess the prod Redis."; exit 1; }
    @test "$PROD_REDIS_URL" != "${REDIS_URL:-}" || { echo "PROD_REDIS_URL matches REDIS_URL — that is the dev Redis; refusing."; exit 1; }
    cd {{LOADER}} && .venv/bin/python dump_snapshot.py --redis-url "$PROD_REDIS_URL" --output "../{{SNAPSHOT}}" --source-label prod

# Dry-run: parse the CSV and print what would be written for the first 3
# rows. No Redis connection required.
load-csv-dry: _require-csv
    cd {{LOADER}} && .venv/bin/python load_csv_redis.py --input "../{{CSV}}" --dry-run

# Pre-fill the product ontology (nsq:ontology:products) by ingesting
# every product name in the CSV. Idempotent. The analytics dashboard
# otherwise grows the ontology lazily during its first 5-minute cache
# miss — this is faster for cold starts.
build-product-ontology: _require-csv
    cd {{LOADER}} && .venv/bin/python build_product_ontology.py --input "../{{CSV}}" --redis-url "$REDIS_URL"

# Quick sanity check: count loaded records and show one sample
verify:
    cd {{LOADER}} && .venv/bin/python verify_nsq_redis.py

# (sync-shared / sync-manufacturer-api are gone: core/ is the single copy the
# api image and the loaders import. The legacy analytics app keeps its own
# vendored analytics/shared/ until it is retired.)

# Load the CDMO patent intelligence seed into Redis (cdmo:patent:*)
# (Also available as Admin → Data jobs → Reload CDMO seeds.)
load-patents:
    cd {{LOADER}} && .venv/bin/python load_patents.py --input ../data/patent_seed.json --redis-url "$REDIS_URL" --flush

# Load the CDMO plant asset seed into Redis (cdmo:plant:*)
load-plant-assets:
    cd {{LOADER}} && .venv/bin/python load_plant_assets.py --input ../data/plant_assets_seed.json --redis-url "$REDIS_URL"

# Load the CDMO regulatory passport seed into Redis (cdmo:regulatory:*)
load-regulatory:
    cd {{LOADER}} && .venv/bin/python load_regulatory.py --input ../data/regulatory_seed.json --redis-url "$REDIS_URL" --flush

# Load the CDMO demand signal seed into Redis (cdmo:demand:*)
load-demand:
    cd {{LOADER}} && .venv/bin/python load_demand.py --input ../data/demand_seed.json --redis-url "$REDIS_URL" --flush

# Seed all CDMO intelligence keys in one command
load-intelligence: load-patents load-plant-assets load-regulatory load-demand

# Run the API locally on :8001 (needs Postgres at $DATABASE_URL and Redis at
# $LOCAL_REDIS_URL, default localhost). Seeds the super admin from
# SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD on first boot.
run-api:
    cd backend && REDIS_URL="${LOCAL_REDIS_URL:-redis://localhost:6379/0}" UPSTASH_URL="$REDIS_URL" python3 -m uvicorn app.main:app --port 8001 --reload

# Run the React app (Vite dev server, :5173; proxies /api to :8001).
# First: cd web && npm install
run-web:
    cd web && npm run dev

# Type-check + production-build the React app.
build-web:
    cd web && npm run build

# Seed a local Redis from the bundled snapshot + CDMO seeds (no Upstash needed).
seed-local:
    cd {{LOADER}} && .venv/bin/python restore_snapshot.py --input ../{{SNAPSHOT}} --redis-url "${LOCAL_REDIS_URL:-redis://localhost:6379/0}" --flush
    cd {{LOADER}} && for f in patents:patent_seed regulatory:regulatory_seed demand:demand_seed; do .venv/bin/python load_${f%%:*}.py --input ../data/${f##*:}.json --redis-url "${LOCAL_REDIS_URL:-redis://localhost:6379/0}" --flush; done
    cd {{LOADER}} && .venv/bin/python load_plant_assets.py --input ../data/plant_assets_seed.json --redis-url "${LOCAL_REDIS_URL:-redis://localhost:6379/0}"
    cd {{LOADER}} && REDIS_URL="${LOCAL_REDIS_URL:-redis://localhost:6379/0}" .venv/bin/python build_enriched_frame.py

# Run the test suites: core/loader tests and the API tests (the API tests need
# Postgres at $TEST_DATABASE_URL and a seeded local Redis; they skip otherwise).
test:
    REDIS_URL=redis://localhost:6379 python3 -m pytest tests/ -q
    cd backend && DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg://nsq@localhost:5432/nsq_test}" REDIS_URL=redis://localhost:6379 python3 -m pytest tests -q

# Clean only the CDMO intelligence keys (DESTRUCTIVE, no confirmation)
clean-intelligence:
    @cd {{LOADER}} && .venv/bin/python -c "import redis,os; r=redis.from_url(os.environ['REDIS_URL'], decode_responses=True); [r.delete(k) for k in r.scan_iter('cdmo:*')]; print('cdmo:* keys deleted')"

# Remove all nsq:* keys from Redis — DESTRUCTIVE, asks for confirmation
clean:
    @echo "This will delete all nsq:* keys from the target Redis instance."
    @read -p "Type 'yes' to continue: " confirm && [ "$confirm" = "yes" ]
    cd {{LOADER}} && .venv/bin/python clean_nsq_redis.py

# Rebuild the cumulative CSV from the NSQ records in $REDIS_URL (use when the
# gitignored CSV is missing, e.g. on a fresh clone).
csv-from-redis:
    cd {{LOADER}} && .venv/bin/python sync_cdsco.py --csv "../{{CSV}}" --bootstrap-only

# Fetch the latest month from the live CDSCO NSQ table and append new alerts to
# the cumulative CSV (raw download kept in data/raw/cdsco/). Does not touch Redis.
sync-nsq:
    cd {{LOADER}} && .venv/bin/python sync_cdsco.py --csv "../{{CSV}}"

# Monthly refresh straight from CDSCO: fetch + append, then the full
# deterministic rebuild into $REDIS_URL (needs CONFIRM_FLUSH=yes), then
# ./pull-upstash.sh on the server. Same as Admin → Pipelines → Fetch latest CDSCO month.
# `just fetch-nsq 2026-08` fetches one reporting month instead of the current one.
fetch-nsq MONTH="": _confirm-flush (_sync-nsq-month MONTH) && reload-csv verify

_sync-nsq-month MONTH:
    cd {{LOADER}} && .venv/bin/python sync_cdsco.py --csv "../{{CSV}}" {{ if MONTH != "" { "--month " + MONTH } else { "" } }}

# Fetch every month since FROM that has no rows in the cumulative CSV
# (e.g. `just backfill-nsq 2021-01`). Appends to the CSV only; run
# `just reload-csv` afterwards. `just nsq-gaps` lists the empty months.
backfill-nsq FROM="2021-01":
    cd {{LOADER}} && .venv/bin/python sync_cdsco.py --csv "../{{CSV}}" --backfill-from {{FROM}}

nsq-gaps FROM="2021-01":
    cd {{LOADER}} && .venv/bin/python sync_cdsco.py --csv "../{{CSV}}" --gaps --backfill-from {{FROM}}

# --- public sources → molecule universe + site directory -------------------------
# Each fetcher writes data/sources/<name>.json (raw downloads in data/raw/<name>/).
# A file path as the last argument parses a file you downloaded yourself instead of fetching.
# Same jobs as Admin → Pipelines; the API also runs them on a schedule.

# List the sources
sources:
    cd {{LOADER}} && .venv/bin/python fetch_source.py --list

# Fetch one source: just fetch-source orange_book [~/Downloads/orange_book.zip]
fetch-source NAME FILE="":
    cd {{LOADER}} && DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py {{NAME}} {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }} || [ $? -eq 3 ]  # 3 = unchanged / fetched recently: not a failure

fetch-orange-book FILE="": (fetch-source "orange_book" FILE)
fetch-purple-book FILE="": (fetch-source "purple_book" FILE)
fetch-ema FILE="": (fetch-source "ema" FILE)
fetch-fda-sites: (fetch-source "fda_establishments") (fetch-source "fda_import_alerts") (fetch-source "fda_recalls")

# --- plant registry: CDSCO WHO-GMP + SUGAM lists, EU GMP (EudraGMDP) -------------
# CDSCO and EudraGMDP refuse many cloud networks: run these on your laptop, then
# copy the JSON to the server with `just push-plant-registry`.
#   just fetch-plants ~/Downloads/who_gmp.pdf  # parse a WHO-GMP PDF you saved yourself
#   just push-plant-registry ec2-user@ec2-….compute-1.amazonaws.com ~/.ssh/key.pem

# CDSCO SUGAM sites + WHO-GMP PDF -> data/sources/cdsco_plants.json (+ .csv)
fetch-plants FILE="": _plant-deps
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py cdsco_plants {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }}
# EU GMP certificates + non-compliance statements for India (~1,050 documents, ~15 min first run; later runs fetch only new ones)
fetch-eudragmdp:
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py eudragmdp
# FDA inspection outcomes for Indian sites: API (export FDA_DD_USER / FDA_DD_KEY first) or FILE = Data Dashboard Excel export
fetch-fda-inspections FILE="":
    @cd {{LOADER}} && .venv/bin/python -c "import openpyxl" 2>/dev/null || .venv/bin/pip install --quiet openpyxl
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py fda_inspections {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }}
# API makers per molecule: FDA Type II DMF list (quarterly .xls) and EDQM CEPs (daily .txt); FILE = a file you downloaded
fetch-fda-dmf FILE="":
    @cd {{LOADER}} && .venv/bin/python -c "import xlrd, openpyxl" 2>/dev/null || .venv/bin/pip install --quiet xlrd openpyxl
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py fda_dmf {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }}
fetch-cep FILE="":
    @cd {{LOADER}} && .venv/bin/python -c "import openpyxl" 2>/dev/null || .venv/bin/pip install --quiet openpyxl
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py edqm_cep {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }}
# Health & trade signals (Playground): NFHS downloads open NFHS-5 fact-sheet extracts (FILE adds e.g. an NFHS-6 table);
# IDSP downloads the latest weekly PDFs (or FILE = folder of PDFs); Comtrade uses COMTRADE_KEY if set, else the public preview.
fetch-nfhs FILE="":
    @cd {{LOADER}} && .venv/bin/python -c "import openpyxl" 2>/dev/null || .venv/bin/pip install --quiet openpyxl
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py nfhs {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }}
fetch-idsp FILE="": _plant-deps
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py idsp {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }}
# CDSCO Written Confirmations (API exports to the EU): the list + every PDF not yet downloaded (~1.5 GB the first time). LIMIT caps new PDFs per run
fetch-cdsco-wc LIMIT="": _plant-deps
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py cdsco_wc {{ if LIMIT != "" { "--limit " + LIMIT } else { "" } }}
# Copy the Written Confirmations list and any new PDFs to the server (rsync: only what the server lacks)
push-wc HOST KEY="" DIR="/opt/nsq-platform":
    #!/usr/bin/env bash
    set -euo pipefail
    [ -f data/sources/cdsco_wc.json ] || { echo "Run just fetch-cdsco-wc first"; exit 1; }
    k="{{ if KEY != "" { "-i " + KEY } else { "" } }}"
    ssh $k {{HOST}} 'command -v rsync >/dev/null || sudo yum install -y rsync >/dev/null || sudo apt-get install -y rsync >/dev/null; sudo mkdir -p {{DIR}}/data/docs/cdsco_wc {{DIR}}/data/sources'
    rsync -rt --chmod=D755 --chmod=F644 --info=progress2 --rsync-path="sudo rsync" -e "ssh $k" data/docs/cdsco_wc/ {{HOST}}:{{DIR}}/data/docs/cdsco_wc/ 2>/dev/null \
      || rsync -rt --chmod=D755 --chmod=F644 --progress --rsync-path="sudo rsync" -e "ssh $k" data/docs/cdsco_wc/ {{HOST}}:{{DIR}}/data/docs/cdsco_wc/
    scp $k data/sources/cdsco_wc.json {{HOST}}:~/
    ssh $k {{HOST}} 'sudo mv ~/cdsco_wc.json {{DIR}}/data/sources/ && sudo chmod 644 {{DIR}}/data/sources/cdsco_wc.json'
    echo "Written Confirmations copied: $(ls data/docs/cdsco_wc | wc -l | tr -d ' ') files."
fetch-comtrade:
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py comtrade
# Open Reaction Database: download (~1.3 GB, once) and scan for reactions that make tracked molecules (10–20 min)
fetch-ord FILE="":
    @cd {{LOADER}} && .venv/bin/python -c "import ord_schema, rdkit, pyarrow" 2>/dev/null || .venv/bin/pip install --quiet ord-schema rdkit pyarrow
    cd {{LOADER}} && NSQ_IGNORE_INTERVAL=1 DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py ord {{ if FILE != "" { "--from-file '" + join(invocation_directory(), FILE) + "'" } else { "" } }}
# Copy the server's PubChem structures to this laptop (fetch-ord matches reactions to them). The file is root-owned there.
pull-structures HOST KEY="" DIR="/opt/nsq-platform":
    ssh {{ if KEY != "" { "-i " + KEY } else { "" } }} {{HOST}} 'sudo cat {{DIR}}/data/sources/pubchem.json' > data/sources/pubchem.json.tmp && mv data/sources/pubchem.json.tmp data/sources/pubchem.json
    @python3 -c "import json;d=json.load(open('data/sources/pubchem.json'))['data'];print(len(d),'molecules,',sum(1 for v in d.values() if v.get('found')),'with structures')"

# Everything the server can't fetch itself, in one go: run on the laptop, then copy to the server.
# A source that fails is reported and skipped; the rest still run and are pushed.
laptop-refresh HOST KEY="":
    #!/usr/bin/env bash
    failed=()
    for r in fetch-plants fetch-eudragmdp fetch-fda-inspections fetch-cep fetch-nfhs fetch-comtrade fetch-idsp fetch-cdsco-wc; do
      echo "━━ $r"; just $r || failed+=("$r")
    done
    just pull-structures {{HOST}} {{KEY}} && { echo "━━ fetch-ord"; just fetch-ord || failed+=("fetch-ord"); } || failed+=("pull-structures")
    just push-plant-registry {{HOST}} {{KEY}}
    just push-signals {{HOST}} {{KEY}}
    just push-wc {{HOST}} {{KEY}}
    [ ${#failed[@]} -eq 0 ] && echo "All sources refreshed and pushed." || echo "Pushed. Failed (older files kept): ${failed[*]}"

# Copy the signal files to the server (HOST = user@host, KEY = .pem); the API re-reads them on the next request
push-signals HOST KEY="" DIR="/opt/nsq-platform":
    #!/usr/bin/env bash
    set -euo pipefail
    k="{{ if KEY != "" { "-i " + KEY } else { "" } }}"
    files=$(ls data/sources/nfhs.json data/sources/idsp.json data/sources/comtrade.json data/sources/ord.json 2>/dev/null || true)
    [ -n "$files" ] || { echo "No signal files — run just fetch-nfhs / fetch-idsp / fetch-comtrade first"; exit 1; }
    scp $k $files {{HOST}}:~/
    ssh $k {{HOST}} 'sudo mkdir -p {{DIR}}/data/sources && for f in nfhs.json idsp.json comtrade.json ord.json; do if [ -f ~/$f ]; then sudo mv ~/$f {{DIR}}/data/sources/ && sudo chmod 644 {{DIR}}/data/sources/$f; fi; done'
    echo "Signal files copied."

# CDSCO + EU (the app merges them into one registry); add FDA with just fetch-fda-inspections
fetch-plant-registry: fetch-plants fetch-eudragmdp

# Copy the registry files to the server (HOST = user@host, KEY = .pem) and restart the API
push-plant-registry HOST KEY="" DIR="/opt/nsq-platform":
    #!/usr/bin/env bash
    set -euo pipefail
    k="{{ if KEY != "" { "-i " + KEY } else { "" } }}"
    files=$(ls data/sources/cdsco_plants.json data/sources/cdsco_plants.csv data/sources/eudragmdp.json data/sources/fda_inspections.json data/sources/fda_dmf.json data/sources/edqm_cep.json 2>/dev/null || true)
    [ -n "$files" ] || { echo "No registry files — run just fetch-plant-registry first"; exit 1; }
    scp $k $files {{HOST}}:~/
    ssh $k {{HOST}} 'sudo mkdir -p {{DIR}}/data/sources && for f in cdsco_plants.json cdsco_plants.csv eudragmdp.json fda_inspections.json fda_dmf.json edqm_cep.json; do if [ -f ~/$f ]; then sudo mv ~/$f {{DIR}}/data/sources/ && sudo chmod 644 {{DIR}}/data/sources/$f; fi; done && cd {{DIR}} && (docker compose restart api 2>/dev/null || sudo docker compose restart api)'
    echo "Registry files copied; API restarted."

_plant-deps:
    @cd {{LOADER}} && .venv/bin/python -c "import pdfplumber" 2>/dev/null || .venv/bin/pip install --quiet pdfplumber

# ClinicalTrials.gov needs the candidate list, so build the universe first.
fetch-trials: build-universe (fetch-source "clinical_trials")

# Combine curated seeds + fetched sources + NSQ ingredients (+ watchlist) and
# load patents / regulatory / demand into $REDIS_URL. MIN_ALERTS = NSQ alerts
# an ingredient needs before it is considered.
build-universe MIN_ALERTS="5":
    cd {{LOADER}} && DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python build_universe.py --redis-url "$REDIS_URL" --min-alerts {{MIN_ALERTS}}
    cd {{LOADER}} && for f in patents regulatory demand; do .venv/bin/python load_${f}.py --input ../data/generated/${f}.json --redis-url "$REDIS_URL" --flush; done

# Everything: all sources (a source that is down is skipped), then the universe.
sync-sources:
    cd {{LOADER}} && DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py all
    just build-universe
    cd {{LOADER}} && DATA_DIR="$(cd .. && pwd)/data" .venv/bin/python fetch_source.py clinical_trials || true
    just build-universe

# Push a GeoJSON file into Redis as a single key (default: the India
# states file used by analytics/app.py), so it doesn't need to live in git
push-geojson:
    cd {{LOADER}} && .venv/bin/python load_geojson_redis.py --input ../{{GEOJSON}} --key {{GEOJSON_KEY}} --redis-url "$REDIS_URL"

# Shrink a boundary GeoJSON before pushing it. The choropleth's GeoJSON is
# embedded in the Plotly figure and re-sent over the websocket on EVERY
# Streamlit rerun, so its size is a per-interaction cost, not a one-off load.
# The original 7.2 MB / 525k-point export went to 0.27 MB / 19k points with
# no visible change at national zoom (docs/map_simplification_check.png).
# Writes in place by default; run `just push-geojson` afterwards, since the
# apps read geo:india_states from Redis before falling back to the file.
simplify-geojson TOLERANCE="0.01":
    cd {{LOADER}} && python3 simplify_geojson.py \
        --input "../{{GEOJSON}}" --output "../{{GEOJSON}}" --tolerance {{TOLERANCE}}

# Push the GeoJSON to Redis, then delete the local file and remove it
# from git tracking — DESTRUCTIVE, asks for confirmation
remove-geojson: push-geojson
    @echo "This will delete {{GEOJSON}} from disk and 'git rm' it from the repo."
    @read -p "Type 'yes' to continue: " confirm && [ "$confirm" = "yes" ]
    git rm --cached -- {{GEOJSON}}
    rm -f {{GEOJSON}}
    @echo "Removed. Commit the change to finish."
