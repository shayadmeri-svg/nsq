#!/bin/bash
# deploy.sh — (re)builds and (re)starts the nsq-platform stack.
# Safe to re-run anytime: `sudo /opt/nsq-platform/deploy.sh`
# Called automatically by the nsq-platform systemd unit on boot/restart.
set -euxo pipefail

APP_DIR=/opt/nsq-platform
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

# --- nginx: reload in case the site config changed underneath it ----------
if systemctl is-active --quiet nginx; then
  nginx -t && systemctl reload nginx
fi
