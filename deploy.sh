#!/bin/bash
# deploy.sh — (re)builds and (re)starts the nsq-platform stack.
# Safe to re-run anytime: `sudo /opt/nsq-platform/deploy.sh`
# Called automatically by the nsq-platform systemd unit on boot/restart
# (ExecStart in terraform/user_data.sh.tpl), and after a `git pull` when
# deploying new code.
#
# NOTE: this script ships CODE only — it does NOT load new data. The loaders
# write the NSQ dataset to Upstash (`just refresh-prod` from a dev box), and
# ./pull-upstash.sh (or Admin → Data jobs → Pull from Upstash) copies it into
# this box's own `redis` container, which is what the API reads. Deploy seeds an EMPTY local Redis only; if the
# box shows stale data after a refresh, run ./pull-upstash.sh.
set -euxo pipefail

APP_DIR=${APP_DIR:-/opt/nsq-platform}
cd "$APP_DIR"

# --- buildx: the dnf-packaged docker ships an old buildx (0.12.x) that's
#     too old for `docker compose build` (needs 0.17.0+). Installing to
#     the system-wide plugin dir makes this idempotent — skips the
#     download entirely if a recent-enough version is already there, so
#     re-running this script doesn't re-fetch from GitHub every time. ----
DOCKER_CONFIG=/usr/local/lib/docker
mkdir -p "$DOCKER_CONFIG/cli-plugins"
NEED_BUILDX=1
if [ -x "$DOCKER_CONFIG/cli-plugins/docker-buildx" ]; then
  CURRENT_VER=$("$DOCKER_CONFIG/cli-plugins/docker-buildx" version | grep -oP 'v\K[0-9]+\.[0-9]+' | head -1)
  if [ -n "$CURRENT_VER" ] && awk "BEGIN{exit !($CURRENT_VER >= 0.17)}"; then
    NEED_BUILDX=0
  fi
fi
if [ "$NEED_BUILDX" = "1" ]; then
  case "$(uname -m)" in aarch64|arm64) BUILDX_ARCH=arm64 ;; *) BUILDX_ARCH=amd64 ;; esac
  BUILDX_URL=$(curl -s https://api.github.com/repos/docker/buildx/releases/latest \
    | grep "browser_download_url.*linux-${BUILDX_ARCH}\"" \
    | grep -v '\.sig\|\.sbom\|\.provenance' \
    | cut -d '"' -f 4)
  curl -SL "$BUILDX_URL" -o "$DOCKER_CONFIG/cli-plugins/docker-buildx"
  chmod +x "$DOCKER_CONFIG/cli-plugins/docker-buildx"
fi

# --- refresh-env.sh: pulls secrets from SSM (KMS-decrypted via the
#     instance's IAM role) and writes .env. -------------------------------
"$APP_DIR/refresh-env.sh"

# --- swap: image builds (RDKit, the Vite bundle, and the sim service's
#     Fortran/SUNDIALS compile) run while the live stack keeps serving. A 2 GB
#     swapfile is created once and kept across reboots. ------------------------
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
# Below 8 GB: builds run beside the live stack (see the memory ceilings in docker-compose.yml), so keep 2 GB of swap.
if [ "$MEM_MB" -lt 8000 ] && ! swapon --show | grep -q /swapfile; then
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -q -w vm.swappiness=10 || true  # swap only under real pressure, not to cache

# --- build + start ---------------------------------------------------------
#     Everything except the PharmaPy `sim` service must come up. `sim` is
#     built separately and allowed to fail: the lab falls back to its built-in
#     crystallisation engine while it is down. Set DEPLOY_SIM=0 to skip it.
# The Streamlit dashboard is retired: stop and remove its container (and image) if an older deploy left it running.
if docker ps -a --format '{{.Names}}' | grep -qx nsq-analytics; then
  echo "deploy: removing the retired Streamlit container (nsq-analytics)"
  docker rm -f nsq-analytics >/dev/null
  docker image rm nsq-analytics:local >/dev/null 2>&1 || true
fi
# --- graceful rollout ------------------------------------------------------
#     1. Build every image first: the running containers keep serving meanwhile.
#     2. Check the proxy configs (nginx, Caddy) in throwaway containers.
#     3. Replace services in dependency order, each healthy before the next:
#        data stores → API → Connect → web → demo and optional services.
#        A container whose image and settings are unchanged is left running.
#     4. Reload nginx and Caddy in place: open connections and event streams
#        are not dropped; a new config applies to new requests.
#     A failure stops the rollout with the failing service's logs: what has
#     not been replaced yet keeps running the previous version.
SERVICES=$(docker compose config --services)
has() { echo "$SERVICES" | grep -qx "$1"; }
WAIT="--wait --wait-timeout 240"
on_fail() {
  echo "deploy: FAILED — state and recent logs:" >&2
  docker compose ps >&2 || true
  docker compose logs --tail 60 api connect gateway 2>/dev/null >&2 || true
}
trap on_fail ERR

BUILD=$(echo "$SERVICES" | grep -vx sim | tr '\n' ' ')
# shellcheck disable=SC2086
docker compose build $BUILD

docker run --rm -v "$APP_DIR/gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine nginx -t -q
if has caddy; then
  docker run --rm -e DOMAIN="${DOMAIN:-$(grep -E '^DOMAIN=' .env | cut -d= -f2-)}" \
    -v "$APP_DIR/gateway/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.8.4-alpine \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
fi

# shellcheck disable=SC2086
docker compose up -d $WAIT redis postgres
# shellcheck disable=SC2086
docker compose up -d --no-deps $WAIT api
# shellcheck disable=SC2086
docker compose up -d --no-deps $WAIT connect
# shellcheck disable=SC2086
docker compose up -d --no-deps $WAIT web
if has plant-sim; then docker compose up -d --no-deps plant-sim; fi
if [ "${DEPLOY_SIM:-1}" = "1" ]; then
  docker compose up -d --build --no-deps sim \
    || echo "deploy: WARNING — sim (PharmaPy) failed to build/start; the lab uses its built-in engine." >&2
fi

# --- seed the in-server Redis on a fresh box --------------------------------
#     The services read the stack's own `redis` container, not Upstash. On a
#     new box (empty redis-data volume) copy the dataset down once; on every
#     later deploy this is a no-op with zero Upstash commands. Refreshing the
#     data after a monthly load is a separate, explicit step:
#     ./pull-upstash.sh (see README "Production data refresh").
#     A failure here must not fail the deploy: the apps fall back to the
#     bundled snapshot until the pull succeeds.
./pull-upstash.sh --only-if-empty || {
  rc=$?
  [ "$rc" -eq 10 ] || echo "deploy: WARNING — could not seed local Redis from Upstash (exit $rc); services will serve data/nsq_snapshot.json.gz until ./pull-upstash.sh succeeds." >&2
}

# --- a new bundled snapshot: the API reads it at start ----------------------
#     Restart the API only when data/nsq_snapshot.json.gz changed since the last
#     deploy (a data-only commit changes no image, so nothing above replaced it).
SNAP_SUM=$(sha256sum data/nsq_snapshot.json.gz 2>/dev/null | cut -d' ' -f1 || true)
if [ -n "$SNAP_SUM" ] && [ "$SNAP_SUM" != "$(cat .deploy-snapshot.sha 2>/dev/null || true)" ]; then
  # shellcheck disable=SC2086
  docker compose restart -t 25 api && docker compose up -d --no-deps $WAIT api
  echo "$SNAP_SUM" > .deploy-snapshot.sha
fi

# --- proxies: start or apply a changed definition, then reload in place -------
# shellcheck disable=SC2086
docker compose up -d --no-deps $WAIT gateway
docker compose exec -T gateway nginx -s reload
if has caddy; then
  docker compose up -d --no-deps caddy
  docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
fi
trap - ERR

# --- backups: Postgres and Redis to S3, 4x daily (ops/backup/) ----------------
#     Installed from the repo on every deploy, so a rebuilt box gets them too. It needs /etc/nsq-backup.conf
#     (S3_BUCKET=<terraform output backup_bucket>, AWS_REGION=…); without it the deploy says so and carries on.
#     Replaces the earlier hand-installed, Postgres-only nsq-pg-backup timer.
if [ -r /etc/nsq-backup.conf ]; then
  install -m 0755 ops/backup/nsq-backup.sh /usr/local/bin/nsq-backup.sh
  install -m 0644 ops/backup/nsq-backup.service ops/backup/nsq-backup.timer /etc/systemd/system/
  if systemctl list-unit-files nsq-pg-backup.timer >/dev/null 2>&1; then
    systemctl disable --now nsq-pg-backup.timer >/dev/null 2>&1 || true
  fi
  systemctl daemon-reload
  systemctl enable --now nsq-backup.timer
  echo "deploy: backups scheduled — $(systemctl list-timers nsq-backup.timer --no-pager | sed -n 2p)"
else
  echo "deploy: WARNING — /etc/nsq-backup.conf missing: Postgres and Redis are NOT being backed up off this box." >&2
fi

# --- host nginx (optional) -------------------------------------------------
# Nothing in this repo installs a host-level nginx: the stack's own gateway
# container owns :80 and no other container port is published. This block only matters if you have hand-installed an nginx in front
# (e.g. to add TLS); it is a no-op otherwise.
if command -v nginx >/dev/null 2>&1 && systemctl is-active --quiet nginx; then
  nginx -t && systemctl reload nginx
fi

# --- clean up ----------------------------------------------------------------
#     Every --build leaves the previous images untagged ("dangling") plus build
#     cache; on a small disk that adds up to GBs within weeks. Remove dangling
#     images and build cache older than 3 days (recent cache keeps rebuilds
#     fast). Never touches volumes, so Redis data is safe.
echo "deploy: removing dangling images and old build cache"
docker image prune -f >/dev/null || true
docker builder prune -f --filter "until=72h" >/dev/null || true
docker system df 2>/dev/null | sed 's/^/deploy:   /' || true

echo "deploy: stack is up. docker compose ps:"
docker compose ps
