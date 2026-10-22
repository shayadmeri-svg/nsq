# Eurveda (NSQ Intelligence)

A platform for Indian pharma manufacturers, built on CDSCO **Not-of-Standard-Quality (NSQ)** alerts and the
pharmacopoeial standards they are judged against. For each organisation it answers:

1. **Quality signals** — which of its batches CDSCO flagged, why, how that compares with all of India, and a
   diagnosis + CAPA per alert.
2. **Its plant, live** — every machine, the batch and product on it, each reading against that product's range,
   alarms (Eurveda Connect, below).
3. **Process and product science** — dissolution, process twin and failure tree per molecule, with every limit taken
   from a pharmacopoeia where one gives it (IP → WHO → JP → FDA), and labelled *default* where none does.
4. **Infrastructure, patent opportunities and the EU export route** — plants, certifications, off-patent molecules
   those plants can make, and a per-molecule EU checklist.

Platform staff get an admin area: organisations, users & roles, invites, an audit log, the all-India NSQ explorer,
**Data operations** (jobs, schedules, data map, and a **coverage** report per official source).

Live at **https://app.eurveda.co** (single EC2 instance, `terraform/`).

## Services

```
browser ──https──▶ caddy (:443, :80 → redirect)          TLS (Let's Encrypt), security headers
                     └──▶ gateway (nginx, 127.0.0.1:8080)   routing, rate limits, unbuffered event streams
                            ├── /              web        React + Vite + Tailwind + Motion + Recharts
                            ├── /api/connect/  connect    Eurveda Connect: plants, edge agents, live state, alarms
                            └── /api/          api        FastAPI: auth, dashboards, NSQ data, Lab, limits, jobs
                                                 ├── postgres   users, orgs, sessions, audit, job runs, plant data, Connect
                                                 ├── redis      NSQ dataset + molecule data (in-server copy of Upstash)
                                                 └── sim        PharmaPy crystalliser (optional; the Lab falls back without it)
plant-sim (demo) ── OPC UA simulator + edge agents ──▶ api, connect
```

| Container | What it does | Memory ceiling |
|---|---|---|
| `nsq-caddy` | HTTPS for `$DOMAIN`: obtains and renews the certificate, redirects http→https, adds HSTS / nosniff / frame / referrer headers, leaves event streams uncompressed. The only public ports (80, 443). Profile `https`. | 128 MB |
| `nsq-gateway` | nginx: routes `/`, `/api/connect/`, `/api/`; rate limits per visitor (sign-in 10/min, API 20/s, agents 50/s); event-stream paths unbuffered with a 1 h read timeout, at most 10 open per visitor. Takes the visitor's address from Caddy. | 96 MB |
| `nsq-web` | the built React app (nginx, SPA fallback, long-cached hashed assets). | 64 MB |
| `nsq-api` | FastAPI, one worker (the job runner and the live-line stream keep state in process). Sign-in, organisations, dashboards, NSQ explorer, Lab and process twin, pharmacopoeial limits, data jobs and schedules, plant data. | 1.5 GB |
| `nsq-connect` | Eurveda Connect, one worker (live machine state is in process): plant setup wizard, protocol catalog, edge-agent config and jobs (browse tags, test reads), ingest, batches across machines, alarms, the Plant monitor's event stream. | 256 MB |
| `nsq-postgres` | Postgres 18: everything users create (users, orgs, sessions, audit, job runs, molecule entries, plant data, Connect's `cx_*` tables). Tuned for its 640 MB. | 640 MB |
| `nsq-redis` | Redis 7 (append-only): the NSQ dataset and molecule data the API reads; Upstash is the upstream copy. | 384 MB |
| `sim` | PharmaPy crystalliser for the Lab (needs SUNDIALS and numpy<2, hence its own image). Optional. | 512 MB |
| `nsq-plant-sim` | The demo plant: five simulated machines (RMG, FBD, blender, press, coater) on OPC UA, and the edge agents that read them every second — one feeding plant data (API), one in remote mode for Connect. Profile `demo`. | 384 MB |

Ceilings keep one service from starving the rest on the 4 GB instance; typical use is ~1.6 GB in total. Under host
memory pressure the kernel ends the demo and optional services first and the data stores last (`oom_score_adj`).
Every container's log rotates at 10 MB × 3.

| Directory | What it is |
|---|---|
| `backend/` | The API. `app/insights.py` composes the dashboards from `core/`; `app/limits.py` resolves pharmacopoeial limits; `app/coverage.py` the coverage report. |
| `connect/` | Eurveda Connect (own service, own tests). |
| `edge-agent/` | The plant-side agent (OPC UA, Modbus, CSV) with store-and-forward, and the plant simulator. |
| `core/` | Domain code, one copy: NSQ data layer, ontologies, `identity.py` (one answer to "which molecule is this name?"), diagnostics, process models (`chem/`). |
| `web/` | The React app. |
| `redis-loader/` | Data scripts and source fetchers (`sources/`), run by the job runner or `just`. `ip_import.py` merges extracted IP rows into the IP seed. |
| `sim/` | The PharmaPy sidecar. |
| `data/` | Seeds (incl. `ip_seed.json` + `IP_SEED_GUIDE.md`), the bundled snapshot, fetched sources (`data/sources/`, gitignored). |
| `gateway/` | `nginx.conf` and `Caddyfile`. |
| `ops/backup/` | Off-box backups of Postgres and Redis (script, systemd timer, restore guide). |
| `terraform/` | The AWS instance, security group (22, 80, 443), backup bucket, SSM secrets. |

## Roles

| Role | Can |
|---|---|
| `super_admin` | everything, incl. destructive data jobs and CSV uploads |
| `admin` | all organisations and users (except super admins), non-destructive jobs, audit |
| `org_admin` | their organisation's team and plants |
| `member` | view their organisation |

Sign-in is email + password (argon2), server-side sessions in an httpOnly (secure, over HTTPS) cookie, 12 h sliding
expiry, throttled failed logins (and rate-limited at the gateway). New users join via a single-use invite link
(7 days) or an admin-set temporary password they must change. Every sign-in, access change, org/plant edit and job run
is audited.

## Run it

```bash
cp .env.example .env     # REDIS_URL (Upstash), SUPERADMIN_EMAIL/PASSWORD, APP_BASE_URL, POSTGRES_PASSWORD
docker compose up -d --build
./pull-upstash.sh        # first time: copy the dataset into the in-server Redis
# open http://<host>/  → sign in as the super admin → Admin → Organisations → New
```

Add `COMPOSE_PROFILES=demo` for the simulated plant, and `https` (with `DOMAIN`) for Caddy — see Deployment.

The CDSCO CSV is gitignored; when it is missing the refresh job and the `just` recipes rebuild it from the records in
Redis (`just csv-from-redis`), and **Fetch latest CDSCO month** / `just fetch-nsq` keeps it current from the live CDSCO
table. No Upstash? Admin → Data jobs → **Restore from snapshot** seeds Redis from `data/nsq_snapshot.json.gz`;
**Reload CDMO seeds** loads the patent/plant data.

Local development (Postgres + Redis on localhost):

```bash
just setup && just seed-local
just run-api      # :8001
just run-web      # :5173, proxies /api (and /api/connect → :8020)
just test
```

Connect locally: `cd connect && DATABASE_URL=… API_URL=http://localhost:8001 uvicorn app.main:app --port 8020`.

### Tests

| Command | What it checks | Needs |
|---|---|---|
| `just test` | all four below except the UI | — |
| `just test-core` | engine / shared code, source parsers, identity resolver, IP seed rules (`tests/`) | nothing |
| `just test-loader` | source parsers on offline fixtures (`redis-loader/tests/`) | nothing |
| `just test-api` | FastAPI endpoints, jobs, forensics, the Update-everything DAG (`backend/tests/`) | Postgres `nsq_test` + seeded Redis (`just seed-local`); skips otherwise |
| `cd connect && pytest tests` | Connect: demo plant, agent config and jobs, batches and alarms, the event stream | nothing (SQLite) |
| `just typecheck-web` | TypeScript of the React app (what the Docker build runs) | `cd web && npm install` once |
| `just test-ui [URL]` | signs in and opens every screen; fails on JS errors, API 5xx, error boxes, "Invalid Date"/"NaN" | a running app; `E2E_EMAIL` / `E2E_PASSWORD` in the environment |

## Live plant data (Eurveda Connect)

- **Setup** (Playground → Your plant → Live → Plant setup): machines and their type, protocol and connection, which
  agent reaches them, tag mapping (browse an OPC UA server and auto-match tags), products and their route with the
  range of each parameter at each step (continuous or end-of-step checks).
- **Edge agent** (`edge-agent/`): runs at the plant, reads OPC UA / Modbus / CSV, buffers in SQLite when offline, and in
  remote mode takes its machine list from Connect. The cloud never connects into the plant: the agent polls for jobs.
- **Live view**: one snapshot when the page opens, then a server-sent-events tick within ~0.25 s of each reading (only
  new points and changed sections), and every 15 s regardless. The browser reconnects a dropped stream by itself and
  polls while it is down. Sampling rate is the machine's *Poll every (s)* in Plant setup (1 s for the simulator).
- Raw readings are kept `CONNECT_RETAIN_H` hours (default 6); batches, steps and alarms are kept separately.

## Pharmacopoeial limits

Every limit the Lab and the process twin use (assay, dissolution Q and time, medium, volume, pH, apparatus, speed)
comes from the first source in this chain that gives it, with its reference (`backend/app/limits.py`):

| # | Source | Data | Licence |
|---|---|---|---|
| 1 | Indian Pharmacopoeia | `data/ip_seed.json` → source `ip` | IPC. Entries carry edition, volume and page; unverified ones are flagged until checked against the edition |
| 2 | International Pharmacopoeia (WHO) | source `ph_int` (digicollections.net) | CC BY-NC-SA 3.0 IGO (non-commercial) |
| 3 | Japanese Pharmacopoeia (MHLW, English) | source `jp` (official PDFs) | Public Data License 1.0 |
| 4 | FDA Dissolution Methods Database, and FDA's 2018 guidance for products it refers there | source `fda_dissolution` | US public domain |
| 5 | Default (generic) | — | labelled *default* everywhere it is shown |

The European Pharmacopoeia (EDQM Knowledge Database, source `edqm_kd`) is shown alongside: monograph, status,
revisions in progress. Its limits are in the paid text and are never used.

**Names.** Every source resolves its names through `core/identity.py`: exact name, salt/hydrate removed, INN ↔ USAN,
PubChem synonyms (source `pubchem_synonyms`), the same PubChem parent compound, near spelling — and records how each
name matched. Admin → Data operations → **Coverage** shows, per source, the tracked molecules it covers, the names it
could not map, and molecule by molecule where each limit comes from.

**Adding IP limits.** Append entries to `data/ip_seed.json` following `data/IP_SEED_GUIDE.md` (or merge an extraction
with `python redis-loader/ip_import.py rows.jsonl --write`), then run **Indian Pharmacopoeia (limits seed)**. Every
entry is checked; one with an error is reported, not loaded.

## Data jobs (Admin → Data operations)

| Job | Does | Who |
|---|---|---|
| Check Redis / Verify NSQ data | health checks | admin |
| Pull from Upstash | copy Upstash → in-server Redis (dry run by default) | admin (dry run) / super admin |
| Back up to Upstash | copy in-server Redis (incl. user plants) → Upstash | same |
| Restore from snapshot | seed Redis from the bundled snapshot | admin / super admin with flush |
| Rebuild enriched frame | recompute the precomputed dashboard frame | admin |
| Write snapshot | dump Redis to `data/nsq_snapshot.json.gz` | admin |
| Fetch latest CDSCO month | pull the current (or a given) month from the live CDSCO NSQ table; when there are new alerts, append them, run the full refresh and rebuild the molecule universe | super admin |
| Sync all public sources | every source below, then rebuild + load the molecule universe | admin |
| Rebuild molecule universe | recombine seeds + fetched sources + NSQ + watchlist, load into Redis | admin |
| One job per source | fetch one source (or parse an uploaded file) | admin |
| Monthly NSQ refresh | rebuild from the cumulative CSV (or an uploaded one): load → ontologies → frame → pull | super admin |
| Reload CDMO seeds | rebuild the universe from the seeds (+ fetched sources) and reload seeded plants; user plants are kept | super admin |
| Re-publish user plants | Postgres → Redis | admin |

Destructive runs require typing the job name. Logs stream live and are kept in Postgres. The job runner lives in the
API process — keep the API at one worker.

## Data pipelines (Admin → Data operations → Schedules)

| Source | What it adds | Default schedule |
|---|---|---|
| CDSCO NSQ table | new monthly alerts (skips the reload when nothing is new) | daily 06:30 IST |
| FDA Orange Book / Purple Book, EMA EPAR | patents, exclusivity, authorisations, generics/biosimilars | in the daily sync |
| ClinicalTrials.gov | trial totals, phase 3+, recent starts, India sites | in the daily sync |
| FDA DECRS, Import Alert 66-40, openFDA recalls | FDA registration / red list / recalls for Indian sites | in the daily sync |
| PubChem, PubChem synonyms, ChEMBL, FDA labels | structures, measured properties, the names a molecule goes by, approval and PK data | weekly / monthly |
| FDA Dissolution Methods, WHO Ph. Int., JP, EDQM KD | dissolution methods and pharmacopoeial limits; Ph. Eur. monograph status | weekly |
| CDSCO plants and Written Confirmations, EudraGMDP, EDQM CEPs, FDA DMFs | plant registry, export letters, EU GMP status, API filings | every 3–30 days per source |

**Sync all public sources** runs daily at 02:30 IST. A source that cannot be reached is skipped (the run ends
*partial*) and the rest still load. Each source can parse an **uploaded file** instead of downloading.

**Molecule universe.** The curated molecules plus every NSQ ingredient with ≥ 5 alerts that a public source confirms,
plus the watchlist. Every sourced or derived value carries its source and date. Nothing is invented: market size and
prevalence stay unknown for auto-discovered molecules. Admin → Molecule universe → **Add molecule** to track one by hand.

Schedules live in Postgres and run inside the API (`SCHEDULER=off` disables them; `SCHEDULE_TZ` sets the clock,
default Asia/Kolkata). `just` equivalents: `just sources`, `just sync-sources`, `just build-universe`,
`just fetch-nsq [YYYY-MM]`, …

## Deployment

One EC2 instance (t3.medium, 4 GB, Elastic IP 184.198.15.131) running the compose stack; `terraform/` describes it.
DNS: an `A` record `app` → the Elastic IP at the domain's registrar.

**`.env` on the server** (keys `refresh-env.sh` does not manage are kept):

```
APP_BASE_URL=https://app.eurveda.co
COOKIE_SECURE=true
DOMAIN=app.eurveda.co
GATEWAY_PORT=127.0.0.1:8080       # nginx behind Caddy, not public
COMPOSE_PROFILES=https,demo       # Caddy, and the demo plant
POSTGRES_PASSWORD=…  SUPERADMIN_EMAIL=…  SUPERADMIN_PASSWORD=…  PLANT_SIM_TOKEN=…  PLANT_SIM_ORG=…
```

**Deploy**: `cd /opt/nsq-platform && git pull && sudo ./deploy.sh` (also what systemd runs at boot). It:

1. builds every image while the running containers keep serving;
2. checks the nginx and Caddy configs in throwaway containers — a bad config stops the deploy before anything restarts;
3. replaces services in dependency order, each healthy before the next (Redis, Postgres → API → Connect → web →
   demo and optional services); unchanged containers are left running;
4. reloads nginx and Caddy in place, so open connections and event streams are not dropped;
5. installs the backup timer (below), prunes old images and build cache.

A failure stops the rollout and prints the failing service's logs; what was not replaced yet keeps running. On stop,
the API and Connect finish requests in flight and close event streams after 15 s (browsers reconnect in 3 s).

**Backups** (`ops/backup/`): Postgres (`pg_dump`, checked with `pg_restore --list`) and Redis (fresh RDB snapshot,
checked) go to the S3 bucket from `terraform/backups.tf` 4× a day (02:15, 08:15, 14:15, 20:15 UTC), kept 30 days there
and 14 days on the box. `systemctl list-timers nsq-backup.timer`; restore steps in `ops/backup/README.md`.

**Disk space** (30 GB volume):

```bash
docker system df                          # what is using space
docker image prune -f                     # dangling images left by rebuilds (deploy.sh does this)
docker builder prune -f                   # build cache
docker container prune -f && docker network prune -f
```

## Known gaps

- The schema is created with `create_all`; add Alembic before changing models in production.
- Invites are links an admin copies — no email sending yet.
- IP limits in `data/ip_seed.json` are an OCR extraction from IP 2022 and are unverified; check them against a licensed
  edition (the Coverage tab lists what each entry still needs). WHO Ph. Int. data is non-commercial (CC BY-NC-SA).
- EU checks rely on the curated seeds; "Check" items need a regulatory specialist.
- Market size, disease prevalence and India patent status have no free source; they stay curated estimates or unknown.
- The API and Connect run one worker each (in-process state); more workers need that state in Redis first.
- `tests/test_lab_models.py` uses `np.trapz`, which NumPy 2 removed: 3 tests fail on NumPy 2 locally.
- `tests/test_loader_record_keys.py::test_real_file_preparation_numbers` expects an older CSV row count.
