# Terraform — single EC2 box

Cheapest possible way to get this stack running on a public URL: one EC2
instance, running the exact same `docker-compose.yml` you already use
locally, with Redis staying on your existing Upstash instance (so nothing
extra to pay for or manage). No VPC, no NAT gateway, no ALB, no
ElastiCache, no ECS — just a box with Docker on it.

## What this creates

- 1× EC2 instance (default: `t3.micro`, free-tier eligible) in your
  account's **default VPC** — no new networking resources
- 1× security group opening 22 (SSH, restrict this), 8501 (analytics),
  8502 (simulator)
- 1× KMS key + 2× SSM Parameter Store SecureStrings (`redis_url`,
  `gemini_api_key`) — your Redis URL and Gemini key are encrypted at
  rest and never appear in `user_data` or instance metadata in plaintext
- 1× IAM role/instance profile scoped to just `ssm:GetParameter` on
  those two parameters + `kms:Decrypt` on that one key — nothing else
- On boot, the instance installs Docker, clones this repo, fetches the
  two secrets from SSM via its IAM role, writes a `.env`, and runs
  `docker compose up -d`

Estimated cost: **$0/month** if you're in the free-tier window
(`t3.micro` + 20GB gp3 root volume both qualify), otherwise roughly
$7–8/month for the instance + ~$1.60/month for the EBS volume + ~$1/month
for the KMS key. SSM Parameter Store (standard tier) is free. No ALB, no
NAT gateway, no ElastiCache node.

## Setup

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: redis_url, key_pair_name, github_repo_url, ssh_cidr

# one-time: create the SSH key pair if you don't have one
aws ec2 create-key-pair --key-name nsq-platform \
  --query 'KeyMaterial' --output text > nsq-platform.pem
chmod 400 nsq-platform.pem

terraform init
terraform plan
terraform apply
```

`terraform apply` prints `analytics_url` and `simulator_url` — those are
your public links. First boot takes a couple of minutes (installing
Docker, cloning, building images) before Streamlit responds; check
progress with:

```bash
ssh -i nsq-platform.pem ec2-user@$(terraform output -raw public_dns)
sudo cat /var/log/cloud-init-output.log   # boot script progress/errors
docker compose -f /opt/nsq-platform/docker-compose.yml ps
```

## Updating the deployed app

The box only clones the repo once, on first boot. To push a new version:

```bash
ssh -i nsq-platform.pem ec2-user@$(terraform output -raw public_dns)
cd /opt/nsq-platform
git pull
docker compose up -d --build
```

(A GitHub Actions workflow that does this over SSH on every push to
`main` is a natural next step if you want it automated — ask and I'll
add it.)

## Rotating secrets

`REDIS_URL`/`GEMINI_API_KEY` are only read from SSM once, at first boot.
Changing `terraform.tfvars` and re-applying updates the SSM parameter,
but the running instance won't pick it up on its own:

```bash
# update terraform.tfvars, then:
terraform apply   # updates the SSM SecureString

# then on the box:
ssh -i nsq-platform.pem ec2-user@$(terraform output -raw public_dns)
sudo systemctl start nsq-platform.service   # re-runs the fetch-from-SSM + docker compose up
```

Or just `terraform destroy && terraform apply` for a fully clean redeploy
if you don't mind the downtime — cheapest environments usually do.

## Tearing down

```bash
terraform destroy
```

Deletes the instance and its EBS volume. Nothing else in your AWS
account is touched (default VPC and your Upstash Redis are unaffected).

## Notes / tradeoffs of the "minimum money" choice

- **Secrets are KMS-encrypted, not plaintext** — `REDIS_URL` and
  `GEMINI_API_KEY` live in SSM Parameter Store as SecureStrings under a
  dedicated KMS key (`secrets.tf`), fetched at boot via the instance's
  IAM role (`iam.tf`). They still end up in `/opt/nsq-platform/.env` on
  the box itself (`chmod 600`, root/ec2-user only) — Docker Compose needs
  them as plain env vars at that point — but never sit in `user_data`,
  instance metadata, or Terraform's plan output in plaintext.
- **No load balancer** → no TLS, no custom domain, no health-check-based
  auto-recovery. You get `http://ec2-x-x-x-x.compute-1.amazonaws.com:8501`
  and `:8502` directly. Fine for a demo; add an ALB + ACM cert + Route 53
  later if you want `https://` and a real domain.
- **No auto-scaling / self-healing** — if the instance or Docker crashes,
  nothing brings it back except your `nsq-platform.service` (systemd)
  restarting `docker compose up -d` on instance *boot*, not on crash. If
  you stop/start the EC2 instance from the console, the app comes back
  automatically; a crashed *container* inside a running instance won't
  restart unless you add `restart: unless-stopped` (already in
  `docker-compose.yml` — no action needed there).
- **Redis stays external (Upstash)** — deliberate, to avoid paying for
  ElastiCache or managing a Redis container/volume on the box. If you'd
  rather run Redis locally on the instance instead (e.g. to drop the
  Upstash dependency entirely), that's a small change to
  `docker-compose.yml` (add a `redis:` service) — ask if you want that
  variant.
- **Public repo assumed** (`github_repo_url` is cloned with plain
  `git clone`, no auth). For a private repo, either make it public,
  or switch the clone step in `user_data.sh.tpl` to use a deploy key /
  PAT (ask and I'll wire that in).
