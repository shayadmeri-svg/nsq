# NSQ Intelligence

A demo-grade platform for Indian pharma manufacturers, built on CDSCO
**Not-of-Standard-Quality (NSQ)** alerts. For each organisation it answers:

1. **Quality signals** — which of its batches CDSCO flagged, why, how that
   compares with all of India, and a diagnosis + CAPA per alert.
2. **Infrastructure** — its plants, certifications and capability coverage.
3. **Patent opportunities** — which off-patent / LOE molecules those plants can
   make, and which additions (capabilities, certifications) unlock the rest.
4. **EU export route** — a per-molecule checklist for the EU generic route
   (patents & SPC, Ph. Eur., EU GMP, Annex 1, FMD serialisation, QP release,
   API written confirmation, open quality signals) with how to close each gap.

Platform staff get an admin area: organisations, users & roles, invites, an
audit log, an all-India NSQ explorer, data-store health, a **job runner**
for the data scripts that used to live only in the justfile, and **data
pipelines** that keep public sources, the molecule universe and the site
directory current on a schedule.

## Architecture

```
browser ──▶ gateway (nginx :80)
              ├── /        web       React + Vite + Tailwind + Motion + Recharts
              ├── /api/    api       FastAPI (one service)
              │              ├── Postgres  users, orgs, sessions, invites, audit, job runs, user plants
              │              └── Redis     NSQ dataset + CDMO seeds (in-server copy)
              └── /analytics/  legacy Streamlit dashboard (optional, behind login)

Upstash Redis (free tier) = upstream/backup copy. Only the Sync / refresh jobs touch it.
```

| Directory | What it is |
|---|---|
| `backend/` | The API: auth, org dashboards, admin, jobs. `app/insights.py` composes the dashboards from `core/`. |
| `core/` | Domain code, one copy: NSQ data layer, ontologies, diagnostics, GMP/pharmacopoeia knowledge, CDMO scorer, EU export checklist, process models. |
| `web/` | The React app. |
| `redis-loader/` | Data scripts (CSV load, seeds, frame build, snapshot, Upstash pull/push). Run by the job runner or `just`. |
| `data/` | Seeds, the bundled snapshot, CSV uploads (the CDSCO CSV itself is gitignored). |
| `analytics/` | Legacy Streamlit dashboard (`--profile legacy`). To be retired. |
| `gateway/`, `deploy/`, `terraform/` | nginx routing, optional host nginx, AWS single-box deploy. |

Replaced in this version: `engine/`, `manufacturer_api/` (→ `backend/`), the
Streamlit `manufacturer/` app (→ `web/`), `simulator/` (patent/plant/portfolio
pages → Opportunities & EU; process-model API → `/api/process/*`). The old
16-drug simulator catalogue is in git history (`b4d9a3d:simulator/app.py`).

## Roles

| Role | Can |
|---|---|
| `super_admin` | everything, incl. destructive data jobs and CSV uploads |
| `admin` | all organisations and users (except super admins), non-destructive jobs, audit |
| `org_admin` | their organisation's team and plants |
| `member` | view their organisation |

Sign-in is email + password (argon2), server-side sessions in an httpOnly
cookie, 12 h sliding expiry, throttled failed logins. New users join via a
single-use invite link (7 days) or an admin-set temporary password they must
change. Every sign-in, access change, org/plant edit and job run is audited.

## Run it

```bash
cp .env.example .env     # REDIS_URL (Upstash), DATABASE_URL (Neon etc.) or POSTGRES_PASSWORD, SUPERADMIN_EMAIL/PASSWORD, APP_BASE_URL
docker compose up -d --build
./pull-upstash.sh        # first time: copy the dataset into the in-server Redis
# open http://<host>/  → sign in as the super admin → Admin → Organisations → New
```

The CDSCO CSV is gitignored; when it is missing the refresh job and the
`just` recipes rebuild it from the records in Redis (`just csv-from-redis`),
and **Fetch latest CDSCO month** / `just fetch-nsq` keeps it current from the
live CDSCO table.

No Upstash? Admin → Data jobs → **Restore from snapshot** seeds Redis from
`data/nsq_snapshot.json.gz`; **Reload CDMO seeds** loads the patent/plant data.

Local development (Postgres + Redis on localhost):

```bash
just setup && just seed-local
just run-api      # :8001
just run-web      # :5173, proxies /api
just test
```

## Data jobs (Admin → Data jobs)

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
| FDA Orange Book / Purple Book / EMA / ClinicalTrials.gov / FDA site records | fetch one source (or parse an uploaded file) | admin |
| Monthly NSQ refresh | rebuild from the cumulative CSV (or an uploaded one): load → ontologies → frame → pull. A missing CSV is rebuilt from Redis first | super admin |
| Reload CDMO seeds | rebuild the universe from the seeds (+ fetched sources) and reload seeded plants; user plants are kept | super admin |
| Re-publish user plants | Postgres → Redis | admin |

Destructive runs require typing the job name. Logs stream live and are kept in
Postgres. The job runner lives in the API process — keep the API at one worker.

## Data pipelines (Admin → Pipelines)

```
CDSCO NSQ ─┐                                   ┌─ molecule universe ─┐
Orange Book ├─ fetch_source.py → data/sources ─┤  build_universe.py  ├─ Redis cdmo:* → Opportunities, EU route
Purple Book │   (raw kept in data/raw)          │                     │
EMA         │                                   └─ site directory ────┴─ Infrastructure "your sites", Site directory
ClinicalTrials.gov, FDA DECRS, Import Alert 66-40, openFDA recalls ─┘
```

| Source | What it adds | Default schedule |
|---|---|---|
| CDSCO NSQ table | new monthly alerts (skips the reload when nothing is new) | daily 06:30 IST |
| FDA Orange Book | US patents, exclusivity, RLD/TE code, active ANDAs, Indian ANDA holders | in the daily sync |
| FDA Purple Book | biologic references, exclusivity, biosimilar counts | in the daily sync |
| EMA EPAR report | EU authorisations, generics/biosimilars, therapeutic area | in the daily sync |
| ClinicalTrials.gov | trial totals, phase 3+, recent starts, India sites (120 molecules/run, weekly per molecule) | in the daily sync |
| FDA DECRS, Import Alert 66-40, openFDA recalls | FDA registration / red list / recalls for Indian sites | in the daily sync |

**Sync all public sources** runs daily at 02:30 IST. A source that cannot be reached is
skipped (the run ends *partial*) and the rest still load. Each source also has its own job
and schedule, and can parse an **uploaded file** instead of downloading — use that when the
server's network cannot reach a site.

**Molecule universe.** The 26 curated molecules plus every NSQ ingredient with ≥ 5 alerts
that a public source confirms (Orange Book single-ingredient product, EMA central
authorisation or Purple Book licence), plus the watchlist. Indian (INN/BAN) and US names
are reconciled (paracetamol ↔ acetaminophen, amoxycillin ↔ amoxicillin, …). Every
sourced or derived value carries its source and date; the dashboards' disclaimer icon shows
it per value. Nothing is invented: market size and prevalence stay unknown for
auto-discovered molecules.

**Adding or editing a molecule.** Admin → Molecule universe → **Add molecule** (or
"Track" on a skipped ingredient, or "Start tracking" on an organisation's untracked
ingredient). The form pre-fills from the curated seed, the fetched sources and the NSQ
alerts, grouped as identity / patents / regulatory / demand (`core/molecule_fields.py`
lists every field). Only fields you type are stored (Postgres `molecule_entries`); on
every rebuild they win over the sources, and the source value is kept alongside
(visible in the molecule drawer and the value's info icon). "Use source" on a field or
"Clear typed values" drops them; a molecule added in the app stops being tracked when
cleared. Saving starts a universe rebuild.

**Site directory.** Every manufacturer × PIN code printed on an NSQ alert (~2,000 sites),
with the dosage forms it made and FDA matches. An organisation admin can add one of their
sites as a plant; its capabilities are marked *inferred*.

Schedules live in Postgres and run inside the API (`SCHEDULER=off` disables them;
`SCHEDULE_TZ` sets the clock, default Asia/Kolkata).

`just` equivalents: `just sources`, `just fetch-orange-book [file]`, `just fetch-purple-book`,
`just fetch-ema`, `just fetch-fda-sites`, `just fetch-trials`, `just build-universe`,
`just sync-sources`, `just fetch-nsq [YYYY-MM]`, `just backfill-nsq 2021-01`, `just nsq-gaps`.

## Deployment

`deploy.sh` (EC2, systemd) rebuilds and restarts the stack. `refresh-env.sh`
writes `REDIS_URL`/`GEMINI_API_KEY` from SSM and keeps any other keys already
in `.env` — add `POSTGRES_PASSWORD`, `SUPERADMIN_*`, `APP_BASE_URL` to the
box's `.env` once. The security group now opens only 22 and 80; put TLS in
front (then set `COOKIE_SECURE=true`).

## Known gaps

- The schema is created with `create_all`; add Alembic before changing models in production.
- Invites are links an admin copies — no email sending yet.
- EU checks rely on the curated seeds; "Check" items need a regulatory specialist.
- Market size, disease prevalence and India patent status have no free source; they stay curated estimates or unknown.
- The DECRS and Import Alert parsers find columns/sections by name; the first live run logs the header it saw — check it.
- CDSCO's month filter parameter names are undocumented; `backfill-nsq` tries several spellings and refuses rows for the wrong month.
- `tests/test_loader_record_keys.py::test_real_file_preparation_numbers` expects an older CSV row count (5,635 vs 5,619).
