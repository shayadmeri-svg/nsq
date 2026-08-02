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

# --- refresh-env.sh: pulls secrets from SSM (KMS-decrypted via the
#     instance's IAM role — see secrets.tf / iam.tf) and writes .env.
#     Called here for first boot, and by the systemd unit below on every
#     subsequent boot/restart, so `systemctl restart nsq-platform` is
#     enough to pick up rotated secrets without re-cloning or re-running
#     the Docker install. ------------------------------------------------
cat > "$APP_DIR/refresh-env.sh" << 'REFRESH_EOF'
#!/bin/bash
set -euxo pipefail
cd /opt/nsq-platform

REDIS_URL=$(aws ssm get-parameter \
  --name "${redis_url_param}" --with-decryption \
  --region "${aws_region}" --query 'Parameter.Value' --output text)

GEMINI_API_KEY=$(aws ssm get-parameter \
  --name "${gemini_key_param}" --with-decryption \
  --region "${aws_region}" --query 'Parameter.Value' --output text)

# The "unset" sentinel in secrets.tf is a single space — collapse it back
# to empty so docker-compose.yml's GEMINI_API_KEY=$${GEMINI_API_KEY:-} still
# behaves as "offline heuristic engine" when nothing was provided.
GEMINI_API_KEY="$(echo "$GEMINI_API_KEY" | xargs || true)"

cat > .env << ENV_EOF
REDIS_URL=$REDIS_URL
GEMINI_API_KEY=$GEMINI_API_KEY
ENV_EOF
chmod 600 .env
REFRESH_EOF
chmod +x "$APP_DIR/refresh-env.sh"

"$APP_DIR/refresh-env.sh"
cd "$APP_DIR"
docker compose up -d --build

# --- systemd unit: on every future boot (and on `systemctl restart`),
# re-fetch secrets from SSM and bring the stack up. Does NOT re-pull code
# — see terraform/README.md "Updating the deployed app" for that. -------
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
ExecStart=/opt/nsq-platform/refresh-env.sh
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
UNIT_EOF

systemctl daemon-reload
systemctl enable nsq-platform.service
