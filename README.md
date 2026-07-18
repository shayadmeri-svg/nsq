# NSQ Platform — merged local stack

Two independent Streamlit services, orchestrated with Docker Compose,
both reading live data from a shared Redis instance.

```
merged/
├── analytics/            # real CDSCO NSQ alert dashboard (was nsq-env_copy_2.zip)
│   ├── app.py
│   ├── shared/nsq_redis.py   # copy of shared loader (Docker build context needs it locally)
│   ├── requirements.txt
│   └── Dockerfile
├── simulator/             # GMP root-cause / grading simulator (was nsq-agent.zip)
│   ├── app.py
│   ├── shared/nsq_redis.py
│   ├── requirements.txt
│   └── Dockerfile
├── shared/
│   └── nsq_redis.py        # source of truth — Redis-to-DataFrame loader, copied into each service
├── redis-loader/           # scripts that populate Redis (invoked via the root justfile)
│   ├── fetch_cdsco.py       # pulls the live CDSCO publicNsqDrugTable JSON
│   ├── load_nsq_redis.py
│   ├── load_geojson_redis.py
│   ├── ping_redis.py / verify_nsq_redis.py / clean_nsq_redis.py
│   └── requirements.txt
├── data/                   (fetched publicNsqDrugTable.json lands here — gitignored)
├── justfile                 # single entry point: setup, fetch-cdscoonline, push-geojson, ...
├── docker-compose.yml
├── .env.example
└── README.md

```

## What each service does

**analytics** (port 8501) — loads data from Redis, derives missing columns
(form type, drug category, dissolution-failure flag, state), and renders
Plotly charts / a state choropleth.

**simulator** (port 8502) — the GMP formulation/root-cause workbench.
Its 16-drug catalog (excipients, process windows, patent refs) is still
hardcoded fixture data — that part was never sourced from CDSCO. What
**is** live: on startup it reads the same Redis data and overlays real
`total_alerts` counts and top failure reasons onto each matching drug,
replacing the static numbers. The header shows
`● LIVE CDSCO DATA (N drugs matched)` when this succeeds, or
`○ STATIC CATALOG DATA` if Redis is unreachable/empty — it never hard-fails.

## How they interact

Neither service calls the other over the network. Both are independent
Redis clients reading the same keyspace:

```
Redis (nsq:record:*, nsq:records, nsq:meta)
   ├── read by analytics  (dashboard + charts)
   └── read by simulator  (live alert-count overlay)
```

`analytics` starts first (compose `depends_on: condition: service_healthy`)
as a basic startup ordering — there's no runtime dependency between the two
containers beyond that; if you stop analytics, the simulator keeps working
off whatever it already cached from Redis (`@st.cache_data(ttl=300)`).

## Prerequisite: get data into Redis

Both services expect `nsq:*` keys to already exist in Redis. Everything —
loader setup, data fetch, and running the two services — is driven from
one `justfile` at the repo root, reading one `.env` at the repo root.

```bash
cp .env.example .env
# edit .env: paste your Redis URL (rediss:// for Upstash — TLS is required)
just setup            # creates redis-loader/.venv and installs its deps
just ping             # confirm connectivity
just fetch-cdscoonline  # pulls the live CDSCO publicNsqDrugTable JSON and loads it into Redis
just verify            # sanity check
```

`just fetch-cdscoonline` hits `cdscoonline.gov.in/CDSCO/publicNsqDrugTable`
directly (it's a plain, unauthenticated GET) and flushes/reloads Redis with
the result, so Redis always reflects the latest fetch. If you'd rather
supply your own export (browser network tab, or whatever official export
mechanism CDSCO provides), save it to `data/publicNsqDrugTable.json` and
run `just reload` instead.

The India-states GeoJSON used by the analytics choropleth also lives in
Redis rather than as a checked-in file:

```bash
just push-geojson     # push analytics/india_states_slim.geojson into Redis
```

## Running the two services locally

```bash
docker compose up --build
```

- Analytics dashboard: http://localhost:8501
- Simulator workbench:  http://localhost:8502

To use the simulator's optional live-LLM diagnostics instead of the local
heuristic engine, set `GEMINI_API_KEY` in the root `.env` before starting.

## Updating the dataset

Just re-run `just fetch-cdscoonline` for a fresh pull, or `just reload` if
you're supplying your own export at `data/publicNsqDrugTable.json`. Both
flush and reload Redis. Both services will pick up the new data
automatically within their 5-minute cache TTL, or immediately on container
restart:

```bash
docker compose restart analytics simulator
```

No schema migration needed — the Redis loader only requires
`str_product_name` and, ideally, `str_nsq_result` fields (the CDSCO API's
own field names — see `redis-loader/load_nsq_redis.py` for the full
expected shape).

## Next step

This local stack is the input to the Terraform module (AWS) — same two
images, same Redis dependency, translated to ECS/Fargate + either
continuing with Upstash or moving to ElastiCache. That comes next.
