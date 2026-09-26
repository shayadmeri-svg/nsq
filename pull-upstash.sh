#!/usr/bin/env bash
# Copy the static NSQ dataset from Upstash (REDIS_URL in .env) into the
# in-server `redis` container, then restart the services that read it.
#
#   ./pull-upstash.sh                  # after every data refresh
#   ./pull-upstash.sh --only-if-empty  # deploy.sh: seed a fresh box only
#   ./pull-upstash.sh --dry-run        # show what would change
#
# Runs redis-loader/pull_upstash.py inside the api image on the
# compose network, so the host needs nothing but docker (no `just`, no
# venv — matches the EC2 box). The only Upstash traffic in the whole
# stack happens here. Exit codes: 0 copied, 10 already seeded (with
# --only-if-empty), 2 Upstash unavailable, 1 other refusal.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${REDIS_URL:?REDIS_URL (the upstream Upstash URL) is not set in .env}"

docker compose up -d --wait redis

rc=0
docker compose run --rm --no-deps -T \
  -e UPSTREAM_REDIS_URL="$REDIS_URL" \
  -e TARGET_REDIS_URL="redis://redis:6379/0" \
  --entrypoint python3 api /app/redis-loader/pull_upstash.py "$@" || rc=$?

case " $* " in *" --dry-run "*) exit "$rc" ;; esac

if [ "$rc" -eq 0 ]; then
  # The API memoises the enriched frame in-process; restart so it reads the
  # fresh copy. (The in-app "Pull from Upstash" job invalidates it instead.)
  echo "pull-upstash: restarting the api"
  docker compose restart api || true
fi
exit "$rc"
