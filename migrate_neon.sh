#!/usr/bin/env bash
# migrate_neon.sh - copy the NSQ Postgres database from one Neon project to another.
#
# Uses pg_dump/pg_restore (custom format), so everything is carried over exactly:
# tables, column types, PKs/FKs/indexes/constraints, defaults, and sequence values
# (the SERIAL ids keep counting from where they left off).
#
# pg_dump/pg_restore/psql run inside a postgres Docker image, so nothing needs to be
# installed on the host except Docker (already on your EC2 box).
#
# Usage:
#   export SRC_URL='postgresql://user:pass@ep-old-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require'
#   export DST_URL='postgresql://user:pass@ep-new-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require'
#   ./migrate_neon.sh
#
# Optional env:
#   PG_IMAGE=postgres:17-alpine   client image; major version must be >= both servers
#   FORCE=1                       DST already has tables: drop and replace them
#   KEEP_DUMP=0                   delete the dump file when done (default keeps it)
#   WORK=./some_dir               where the dump and verification files go
#   DOCKER_NETWORK=name           run the client containers on this docker network, needed
#                                 when DST is the compose `postgres` container
#                                 (nsq-platform_nsq-net, host name "postgres")
#
# IMPORTANT: stop the API (docker stop nsq-api) before running, and do NOT start it
# against the new, empty database until this script has finished. On boot the app runs
# create_all() and seeds the super admin, which would collide with the restore.

set -Eeuo pipefail
umask 077

: "${SRC_URL:?set SRC_URL (old Neon connection string)}"
: "${DST_URL:?set DST_URL (new Neon connection string)}"
PG_IMAGE="${PG_IMAGE:-postgres:17-alpine}"
FORCE="${FORCE:-0}"
KEEP_DUMP="${KEEP_DUMP:-1}"
WORK="${WORK:-./nsq_migration_$(date +%Y%m%d_%H%M%S)}"

# pg_dump needs a direct connection; Neon's "-pooler" host is PgBouncer in
# transaction mode and is not reliable for dump/restore.
SRC_URL="${SRC_URL/-pooler/}"
DST_URL="${DST_URL/-pooler/}"
export SRC_URL DST_URL

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"
DUMP="$WORK/nsq.dump"

log() { printf '\n==> %s\n' "$*"; }

# run <SRC|DST> <command string using $URL>   (credentials go via env, not argv)
run() {
  local which="$1" cmd="$2" url
  if [[ "$which" == SRC ]]; then url="$SRC_URL"; else url="$DST_URL"; fi
  docker run --rm -i ${DOCKER_NETWORK:+--network "$DOCKER_NETWORK"} \
    -e URL="$url" -e Q="${Q:-}" -v "$WORK:/work" "$PG_IMAGE" sh -c "$cmd"
}

# psql helper: q <SRC|DST> "<sql>"
q() { Q="$2" run "$1" 'psql "$URL" -v ON_ERROR_STOP=1 -Atq -c "$Q"'; }

COUNTS_SQL="select table_name || '=' || (xpath('/row/c/text()',
  query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text
  from information_schema.tables
  where table_schema = 'public' and table_type = 'BASE TABLE' order by 1"

SEQ_SQL="select sequencename || '=' || coalesce(last_value::text, 'unused')
  from pg_sequences where schemaname = 'public' order by 1"

# ---------------------------------------------------------------- 1. preflight
log "Pre-flight: connecting to source and destination"
echo -n "source:      "; q SRC "select split_part(version(), ' on ', 1)" \
  || { echo "Cannot read the source DB. If the error says 'exceeded the quota', Neon is still blocking it - see notes in the chat."; exit 1; }
echo -n "destination: "; q DST "select split_part(version(), ' on ', 1)"

DST_TABLES="$(q DST "select count(*) from information_schema.tables where table_schema='public'")"
RESTORE_FLAGS=()
if [[ "$DST_TABLES" != "0" ]]; then
  if [[ "$FORCE" == "1" ]]; then
    echo "destination has $DST_TABLES table(s) in public; FORCE=1, they will be dropped and replaced"
    RESTORE_FLAGS+=(--clean --if-exists)
  else
    echo "destination already has $DST_TABLES table(s) in public. Refusing to overwrite (use FORCE=1)." >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- 2. dump
log "Dumping source (schema + data + sequence values)"
run SRC 'pg_dump "$URL" --format=custom --schema=public --no-owner --no-acl --verbose -f /work/nsq.dump' 2> "$WORK/dump.log" \
  || { tail -20 "$WORK/dump.log" >&2; exit 1; }
ls -lh "$DUMP"

# ---------------------------------------------------------------- 3. restore
log "Restoring into destination"
set +e
run DST "pg_restore --dbname=\"\$URL\" --no-owner --no-acl ${RESTORE_FLAGS[*]:-} --verbose /work/nsq.dump" 2> "$WORK/restore.log"
RESTORE_RC=$?
set -e
if [[ $RESTORE_RC -ne 0 ]]; then
  echo "pg_restore reported errors (exit $RESTORE_RC). Relevant lines:" >&2
  grep -iE 'error|fatal' "$WORK/restore.log" | head -20 >&2 || true
  echo "(A lone 'schema \"public\" already exists' error is harmless. Verification below is what counts.)" >&2
fi

# ---------------------------------------------------------------- 4. verify
log "Verifying: row counts per table"
q SRC "$COUNTS_SQL" > "$WORK/counts.src"
q DST "$COUNTS_SQL" > "$WORK/counts.dst"
FAIL=0
if diff -u "$WORK/counts.src" "$WORK/counts.dst"; then
  echo "OK: row counts identical"; cat "$WORK/counts.dst"
else
  echo "MISMATCH in row counts" >&2; FAIL=1
fi

log "Verifying: sequences (auto-increment counters)"
q SRC "$SEQ_SQL" > "$WORK/seq.src"
q DST "$SEQ_SQL" > "$WORK/seq.dst"
if diff -u "$WORK/seq.src" "$WORK/seq.dst"; then
  echo "OK: sequence values identical"; cat "$WORK/seq.dst"
else
  echo "MISMATCH in sequences" >&2; FAIL=1
fi

log "Verifying: schema definition (tables, indexes, constraints, defaults)"
for side in SRC DST; do
  run "$side" 'pg_dump "$URL" --schema-only --schema=public --no-owner --no-acl' \
    | grep -vE '^(--|\\restrict|\\unrestrict)' > "$WORK/schema.$side"
done
if diff -u "$WORK/schema.SRC" "$WORK/schema.DST"; then
  echo "OK: schema identical"
else
  echo "MISMATCH in schema" >&2; FAIL=1
fi

# ---------------------------------------------------------------- 5. wrap up
if [[ "$KEEP_DUMP" == "0" ]]; then
  rm -f "$DUMP"; echo "dump file deleted"
else
  echo
  echo "Dump kept at $DUMP - it contains password hashes and session data. Store it safely or delete it."
fi

if [[ $FAIL -ne 0 ]]; then
  echo; echo "MIGRATION NOT VERIFIED - do not switch the app over yet. Logs: $WORK/dump.log, $WORK/restore.log" >&2
  exit 2
fi

cat <<'EOF'

MIGRATION VERIFIED. Next:
  1. On the server, edit .env: set DATABASE_URL to the NEW Neon connection string
     (the "-pooler" URL is fine for the app, the app handles it).
  2. Recreate the API so it re-reads .env (a plain `docker restart` does NOT):
       docker compose up -d --force-recreate api
  3. Test: curl -i -X POST http://localhost/api/auth/login \
       -H 'Content-Type: application/json' -H 'x-nsq-client: web' \
       -d '{"email":"x@y.com","password":"wrong"}'      # expect 401, not 500
EOF
