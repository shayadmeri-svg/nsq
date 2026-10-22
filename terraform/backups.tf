# backups.tf - off-box home for the nightly Postgres dumps.
#
# Adds a private, encrypted, versioned S3 bucket and lets the instance role
# UPLOAD to it (and list it, for verification). The role cannot read or delete
# objects, so a compromised box cannot wipe or exfiltrate the backups.
# Old dumps expire via the lifecycle rule below.
#
# Adds resources only; it does not modify aws_instance.app.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "backups" {
  # bucket names are global; the account id keeps this unique
  bucket = "${local.name}-db-backups-${data.aws_caller_identity.current.account_id}"
  tags   = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning: an upload with the same key can never destroy the previous copy.
resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket     = aws_s3_bucket.backups.id
  depends_on = [aws_s3_bucket_versioning.backups]

  rule {
    id     = "expire-old-dumps"
    status = "Enabled"
    filter {}

    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}

resource "aws_iam_role_policy" "backup_upload" {
  name = "${local.name}-backup-upload"
  role = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${aws_s3_bucket.backups.arn}/db/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.backups.arn]
      }
    ]
  })
}

output "backup_bucket" {
  description = "S3 bucket receiving the nightly Postgres dumps."
  value       = aws_s3_bucket.backups.bucket
}
