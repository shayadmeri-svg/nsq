#!/bin/bash
set -euxo pipefail

# --- Docker Engine + Compose plugin (Amazon Linux 2023) --------------------
dnf update -y
dnf install -y docker git awscli
systemctl enable --now docker
usermod -aG docker ec2-user

DOCKER_CONFIG=/usr/local/lib/docker
mkdir -p $DOCKER_CONFIG/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o $DOCKER_CONFIG/cli-plugins/docker-compose
chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose

# --- Clone the app once (code updates happen via `git pull`, not on every
#     boot — see terraform/README.md) ---------------------------------
APP_DIR=/opt/nsq-platform
git clone --branch "${git_ref}" --depth 1 "${github_repo_url}" "$APP_DIR"

# --- Deploy config -------------------------------------------------------
# The only thing user_data writes for the app: which SSM parameters to read
# and from which region. The refresh script itself lives in the repo
# (refresh-env.sh) so a `git pull` can never clobber it. No secrets here —
# user_data is readable by anyone with ec2:DescribeInstanceAttribute.
cat > /etc/nsq-platform.conf << 'CONF_EOF'
AWS_REGION=${aws_region}
REDIS_URL_PARAM=${redis_url_param}
GEMINI_KEY_PARAM=${gemini_key_param}
CONF_EOF
chmod 644 /etc/nsq-platform.conf

# --- First deploy --------------------------------------------------------
# deploy.sh installs a modern buildx, runs refresh-env.sh (SSM -> .env) and
# brings the compose stack up with a build.
"$APP_DIR/deploy.sh"

# --- systemd unit: on every future boot (and on `systemctl restart`), run
# the same deploy.sh — re-fetch secrets from SSM and rebuild + bring the
# stack up. Does NOT re-pull code — see terraform/README.md "Updating the
# deployed app" for that. --------------------------------------------------
cat > /etc/systemd/system/nsq-platform.service << 'UNIT_EOF'
[Unit]
Description=NSQ platform (docker compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/nsq-platform
# deploy.sh = buildx check + refresh-env.sh (SSM -> .env) + compose up --build.
# `--build` matters: without it a `git pull` of changed service code would
# keep serving the previously built images.
ExecStart=/opt/nsq-platform/deploy.sh
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=1800

[Install]
WantedBy=multi-user.target
UNIT_EOF

systemctl daemon-reload
systemctl enable nsq-platform.service
