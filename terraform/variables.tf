variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used for naming all resources."
  type        = string
  default     = "nsq-platform"
}

variable "environment" {
  description = "Deployment environment tag (e.g. dev, demo, prod)."
  type        = string
  default     = "dev"
}

variable "instance_type" {
  description = "EC2 instance type. t3.micro / t4g.micro are free-tier eligible in most accounts."
  type        = string
  default     = "t3.micro"
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size in GB (gp3)."
  type        = number
  default     = 30
}

variable "ssh_cidr" {
  description = "CIDR block allowed to SSH into the instance (port 22). Restrict this to your own IP — do not leave it as 0.0.0.0/0 in anything but a throwaway demo."
  type        = string
  default     = "0.0.0.0/0"
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair for SSH access. Create one first: aws ec2 create-key-pair --key-name nsq-platform --query 'KeyMaterial' --output text > nsq-platform.pem && chmod 400 nsq-platform.pem"
  type        = string
}

# --- App config, mirrors the root .env used by docker-compose locally ---

variable "redis_url" {
  description = "REDIS_URL for both services — reuse your existing Upstash instance (rediss://...) so no Redis needs to run on this box. Required."
  type        = string
  sensitive   = true
}

variable "gemini_api_key" {
  description = "Optional Gemini API key for the simulator's live-LLM diagnostics. Leave blank to stay fully offline."
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_repo_url" {
  description = "HTTPS URL of this repo, so the instance can 'git clone' it on boot and run docker compose directly. Must be public, or the clone step in user_data.sh will need a token."
  type        = string
}

variable "git_ref" {
  description = "Branch or tag to check out on boot."
  type        = string
  default     = "main"
}

variable "tags" {
  description = "Common tags applied to all resources."
  type        = map(string)
  default     = {}
}

variable "app_ingress_cidrs" {
  description = <<-EOT
    CIDRs allowed to reach the newer app ports: the Q-engine gateway (8080),
    the legacy Streamlit manufacturer (8503), and the engine API (8000).
    Defaults to open, matching the existing 8501/8502 rules — but the engine
    is unauthenticated and the manufacturer sign-in is a gate, not auth, so
    narrowing this to your own IP (e.g. ["203.0.113.4/32"]) is strongly
    recommended for anything but a throwaway demo box.
  EOT
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
