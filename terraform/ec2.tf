locals {
  name = "${var.project_name}-${var.environment}"

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.tags,
  )
}

# Amazon Linux 2023 — free-tier eligible, small, well-supported by dnf/docker.
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.chosen.id
  vpc_security_group_ids = [aws_security_group.app.id]
  key_name               = var.key_pair_name
  iam_instance_profile   = aws_iam_instance_profile.app.name

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size_gb
  }

  # No secrets here — REDIS_URL/GEMINI_API_KEY are fetched from SSM
  # Parameter Store (KMS-encrypted, see secrets.tf) at boot via the
  # instance's IAM role, not baked into user_data. user_data itself is
  # visible to anyone with ec2:DescribeInstanceAttribute on this
  # instance/account, so keeping it secret-free is the point.
  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    github_repo_url    = var.github_repo_url
    git_ref            = var.git_ref
    aws_region         = var.aws_region
    redis_url_param    = aws_ssm_parameter.redis_url.name
    gemini_key_param   = aws_ssm_parameter.gemini_api_key.name
  })

  tags = merge(local.common_tags, { Name = "${local.name}-app" })
}
