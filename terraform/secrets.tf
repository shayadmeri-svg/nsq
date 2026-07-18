# Secrets live in SSM Parameter Store as SecureStrings, encrypted with a
# dedicated KMS key — not baked into user_data / instance metadata, and
# not visible in `terraform show` beyond the parameter's ARN. The
# instance pulls them at boot via its IAM role (see iam.tf).
#
# Cost: SSM Parameter Store (standard tier) is free. The KMS key is the
# only new line item here — ~$1/month plus $0.03 per 10k API calls
# (boot-time reads only, negligible).

resource "aws_kms_key" "secrets" {
  description             = "${local.name} - encrypts REDIS_URL / GEMINI_API_KEY in SSM Parameter Store"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = local.common_tags
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${local.name}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

resource "aws_ssm_parameter" "redis_url" {
  name   = "/${local.name}/redis_url"
  type   = "SecureString"
  value  = var.redis_url
  key_id = aws_kms_key.secrets.key_id

  tags = local.common_tags
}

resource "aws_ssm_parameter" "gemini_api_key" {
  name   = "/${local.name}/gemini_api_key"
  type   = "SecureString"
  # SSM SecureString values can't be empty — use a single space as the
  # "unset" sentinel; user_data.sh.tpl strips whitespace-only values back
  # to "" before writing .env, so the app still sees it as unset.
  value  = var.gemini_api_key != "" ? var.gemini_api_key : " "
  key_id = aws_kms_key.secrets.key_id

  tags = local.common_tags
}
