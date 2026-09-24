#!/bin/bash
# deploy.sh — (re)builds and (re)starts the nsq-platform stack.
# Safe to re-run anytime: `sudo /opt/nsq-platform/deploy.sh`
# Called automatically by the nsq-platform systemd unit on boot/restart
# (ExecStart in terraform/user_data.sh.tpl), and after a `git pull` when
# deploying new code.
#
# NOTE: this script ships CODE only — it does NOT load data into Redis.
# The NSQ dataset lives in the Upstash Redis and is refreshed separately
# with `just refresh-prod` (see README "Production data refresh"). If the
# box shows stale data, run that step; redeploying alone won't fix it.
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
  BUILDX_URL=$(curl -s https://api.github.com/repos/docker/buildx/releases/latest \
    | grep "browser_download_url.*linux-amd64" \
    | grep -v '\.sig\|\.sbom\|\.provenance' \
    | cut -d '"' -f 4)
  curl -SL "$BUILDX_URL" -o "$DOCKER_CONFIG/cli-plugins/docker-buildx"
  chmod +x "$DOCKER_CONFIG/cli-plugins/docker-buildx"
fi

# --- refresh-env.sh: pulls secrets from SSM (KMS-decrypted via the
#     instance's IAM role) and writes .env. -------------------------------
"$APP_DIR/refresh-env.sh"

# --- build + start ---------------------------------------------------------
docker compose up -d --build

# --- restart the snapshot-mounted services ---------------------------------
#     A data-only commit (fresh data/nsq_snapshot.json.gz) changes no image,
#     and a single-file bind mount pins the inode — os.replace on the host
#     leaves running containers reading the old snapshot bytes. Restarting
#     picks up the new file. Seconds of downtime; safe to re-run.
docker compose restart analytics manufacturer manufacturer-api

# --- host nginx (optional) -------------------------------------------------
# Nothing in this repo installs a host-level nginx: the stack's own gateway
# container terminates on :8080 and the two Streamlit apps publish their own
# ports. This block only matters if you have hand-installed an nginx in front
# (e.g. to add TLS); it is a no-op otherwise.
if command -v nginx >/dev/null 2>&1 && systemctl is-active --quiet nginx; then
  nginx -t && systemctl reload nginx
fi

echo "deploy: stack is up. docker compose ps:"
docker compose ps
