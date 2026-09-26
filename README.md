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
audit log, an all-India NSQ explorer, data-store health, and a **job runner**
for the data scripts that used to live only in the justfile.

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
cp .env.example .env     # REDIS_URL (Upstash), POSTGRES_PASSWORD, SUPERADMIN_EMAIL/PASSWORD, APP_BASE_URL
docker compose up -d --build
./pull-upstash.sh        # first time: copy the dataset into the in-server Redis
# open http://<host>/  → sign in as the super admin → Admin → Organisations → New
```

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
| Monthly NSQ refresh | upload the new cumulative CDSCO CSV, then: load → ontologies → frame → pull | super admin |
| Reload CDMO seeds | patents / regulatory / demand / seeded plants; user plants are kept | super admin |
| Re-publish user plants | Postgres → Redis | admin |

Destructive runs require typing the job name. Logs stream live and are kept in
Postgres. The job runner lives in the API process — keep the API at one worker.

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
- Regulatory and demand pillars in the CDMO scorer are still neutral placeholders.
- `tests/test_loader_record_keys.py::test_real_file_preparation_numbers` expects an older CSV row count (5,635 vs 5,619).
