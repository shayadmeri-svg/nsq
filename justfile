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
# ./pull-upstash.sh on the server. Same as Admin → Data jobs → Fetch latest CDSCO month.
fetch-nsq: _confirm-flush sync-nsq && reload-csv verify

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
