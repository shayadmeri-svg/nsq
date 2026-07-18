#!/bin/bash
set -euxo pipefail

# --- Swap space: t3.micro/small have limited RAM, and building two Python
#     images (pandas/streamlit/plotly) back-to-back can otherwise trigger
#     the OOM killer and leave sshd unresponsive. 2GB swap is cheap insurance.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- Docker Engine + Compose plugin + nginx (Amazon Linux 2023) -----------
dnf update -y
dnf install -y docker git awscli nginx
systemctl enable --now docker
usermod -aG docker ec2-user

DOCKER_CONFIG=/usr/local/lib/docker
mkdir -p $DOCKER_CONFIG/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o $DOCKER_CONFIG/cli-plugins/docker-compose
chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose

# --- nginx: path-based reverse proxy -> /analytics (8501), /simulator (8502)
cat > /etc/nginx/conf.d/nsq-nsq.conf << 'NGINX_EOF'
${nginx_conf}
NGINX_EOF
rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
# AL2023's nginx package ships its own default server block in nginx.conf's
# http{} — strip conflicting default_server if present isn't needed here
# since our conf.d file already declares default_server.
systemctl enable --now nginx

# --- Clone the app once (code updates happen via `git pull`, not on every
#     boot — see terraform/README.md) ---------------------------------
APP_DIR=/opt/nsq-platform
git clone --branch "${git_ref}" --depth 1 "${github_repo_url}" "$APP_DIR"

# --- refresh-env.sh: pulls secrets from SSM and writes .env. Called by
#     deploy.sh on every boot/restart via the systemd unit below. ---------
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

# --- deploy.sh: buildx fix + build + start. Idempotent, safe to re-run
#     manually any time as `sudo /opt/nsq-platform/deploy.sh`. ------------
cat > "$APP_DIR/deploy.sh" << 'DEPLOY_EOF'
${deploy_script}
DEPLOY_EOF
chmod +x "$APP_DIR/deploy.sh"

# --- systemd unit: runs deploy.sh on boot and on `systemctl restart`,
#     so bringing the stack up is always one command: -----------------
#     sudo systemctl restart nsq-platform
cat > /etc/systemd/system/nsq-platform.service << 'UNIT_EOF'
[Unit]
Description=NSQ platform (docker compose behind nginx)
Requires=docker.service
After=docker.service network-online.target nginx.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/nsq-platform
ExecStart=/opt/nsq-platform/deploy.sh
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
UNIT_EOF

systemctl daemon-reload
systemctl enable nsq-platform.service
systemctl start nsq-platform.service
