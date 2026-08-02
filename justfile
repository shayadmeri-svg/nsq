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
CSV := env_var_or_default("NSQ_CSV", "data/data Jan25_May26.csv")
AUGMENT := env_var_or_default("NSQ_AUGMENT", "1")
CDSCO_URL := env_var_or_default("CDSCO_URL", "https://cdscoonline.gov.in/CDSCO/publicNsqDrugTable")
GEOJSON := env_var_or_default("GEOJSON_FILE", "analytics/india_states_slim.geojson")
GEOJSON_KEY := env_var_or_default("GEOJSON_KEY", "geo:india_states")

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
load:
    cd {{LOADER}} && .venv/bin/python load_nsq_redis.py --input ../{{INPUT}} --redis-url "$REDIS_URL"

# Load {{INPUT}} into Redis, wiping existing nsq:* keys first
reload:
    cd {{LOADER}} && .venv/bin/python load_nsq_redis.py --input ../{{INPUT}} --redis-url "$REDIS_URL" --flush

# Load {{CSV}} into Redis (additive, augment=ON by default — populates
# nsq:record:* + nsq:prediction:* + nsq:ontology:companies in one pass).
# Set NSQ_AUGMENT=0 to skip augmentation (raw records only).
load-csv:
    cd {{LOADER}} && .venv/bin/python load_csv_redis.py --input ../{{CSV}} --redis-url "$REDIS_URL" --augment {{AUGMENT}}

# Wipe nsq:* keys and reload {{CSV}} with augmentation. The --flush is
# required after the first load because the loader harmonizes the
# 'Reporting by Lab/State' field (collapsing CDL Kolkata / DTL Jaipur /
# etc. variants), and record_id() is a hash of (batch_no, product_name)
# so a non-flush reload leaves stale un-harmonized rows in Redis.
reload-csv:
    cd {{LOADER}} && .venv/bin/python load_csv_redis.py --input ../{{CSV}} --redis-url "$REDIS_URL" --flush --augment {{AUGMENT}}

# Dry-run: parse the CSV and print what would be written for the first 3
# rows. No Redis connection required.
load-csv-dry:
    cd {{LOADER}} && .venv/bin/python load_csv_redis.py --input ../{{CSV}} --dry-run

# Pre-fill the product ontology (nsq:ontology:products) by ingesting
# every product name in the CSV. Idempotent. The analytics dashboard
# otherwise grows the ontology lazily during its first 5-minute cache
# miss — this is faster for cold starts.
build-product-ontology:
    cd {{LOADER}} && .venv/bin/python build_product_ontology.py --input ../{{CSV}} --redis-url "$REDIS_URL"

# Quick sanity check: count loaded records and show one sample
verify:
    cd {{LOADER}} && .venv/bin/python verify_nsq_redis.py

# Sync the source-of-truth files in shared/ to each service's local copy
# (the Dockerfiles COPY from the service's own shared/ dir, not the
# root). Run this after editing shared/nsq_redis.py or
# shared/company_ontology.py.
sync-shared:
    cp shared/nsq_redis.py analytics/shared/nsq_redis.py
    cp shared/nsq_redis.py simulator/shared/nsq_redis.py
    cp shared/nsq_redis.py engine/shared/nsq_redis.py
    cp shared/company_ontology.py analytics/shared/company_ontology.py
    cp shared/company_ontology.py simulator/shared/company_ontology.py
    cp shared/company_ontology.py engine/shared/company_ontology.py
    @echo "Synced. Verify with: git diff --stat analytics/shared simulator/shared engine/shared"

# Load the CDMO patent intelligence seed into Redis (cdmo:patent:*)
load-patents:
    cd {{LOADER}} && .venv/bin/python load_patents.py --input ../data/patent_seed.json --redis-url "$REDIS_URL" --flush

# Load the CDMO plant asset seed into Redis (cdmo:plant:*)
load-plant-assets:
    cd {{LOADER}} && .venv/bin/python load_plant_assets.py --input ../data/plant_assets_seed.json --redis-url "$REDIS_URL" --flush

# Load the CDMO regulatory passport seed into Redis (cdmo:regulatory:*)
load-regulatory:
    cd {{LOADER}} && .venv/bin/python load_regulatory.py --input ../data/regulatory_seed.json --redis-url "$REDIS_URL" --flush

# Load the CDMO demand signal seed into Redis (cdmo:demand:*)
load-demand:
    cd {{LOADER}} && .venv/bin/python load_demand.py --input ../data/demand_seed.json --redis-url "$REDIS_URL" --flush

# Seed all CDMO intelligence keys in one command
load-intelligence: load-patents load-plant-assets load-regulatory load-demand

# Run the analytics Streamlit app locally on port 8501
run-analytics:
    cd analytics && NSQ_CSV="../{{CSV}}" python3 -m streamlit run app.py --server.headless=true --server.port=8501

# Run the FastAPI scoring engine locally (requires engine dependencies)
run-api:
    cd engine && python3 -m uvicorn api_main:app --host 0.0.0.0 --port 8000 --reload

# Clean only the CDMO intelligence keys (DESTRUCTIVE, no confirmation)
clean-intelligence:
    @cd {{LOADER}} && .venv/bin/python -c "import redis,os; r=redis.from_url(os.environ['REDIS_URL'], decode_responses=True); [r.delete(k) for k in r.scan_iter('cdmo:*')]; print('cdmo:* keys deleted')"

# Remove all nsq:* keys from Redis — DESTRUCTIVE, asks for confirmation
clean:
    @echo "This will delete all nsq:* keys from the target Redis instance."
    @read -p "Type 'yes' to continue: " confirm && [ "$confirm" = "yes" ]
    cd {{LOADER}} && .venv/bin/python clean_nsq_redis.py

# Fetch the live CDSCO publicNsqDrugTable JSON and load it into Redis
# (wipes existing nsq:* keys first, so Redis always reflects the latest fetch)
fetch-cdscoonline:
    cd {{LOADER}} && .venv/bin/python fetch_cdsco.py --url "{{CDSCO_URL}}" --output ../{{INPUT}}
    cd {{LOADER}} && .venv/bin/python load_nsq_redis.py --input ../{{INPUT}} --redis-url "$REDIS_URL" --flush

# Push a GeoJSON file into Redis as a single key (default: the India
# states file used by analytics/app.py), so it doesn't need to live in git
push-geojson:
    cd {{LOADER}} && .venv/bin/python load_geojson_redis.py --input ../{{GEOJSON}} --key {{GEOJSON_KEY}} --redis-url "$REDIS_URL"

# Push the GeoJSON to Redis, then delete the local file and remove it
# from git tracking — DESTRUCTIVE, asks for confirmation
remove-geojson: push-geojson
    @echo "This will delete {{GEOJSON}} from disk and 'git rm' it from the repo."
    @read -p "Type 'yes' to continue: " confirm && [ "$confirm" = "yes" ]
    git rm --cached -- {{GEOJSON}}
    rm -f {{GEOJSON}}
    @echo "Removed. Commit the change to finish."
