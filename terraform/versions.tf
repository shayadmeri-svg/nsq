terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment and fill in once you have a bucket + table for shared state.
  # Local state is fine for a single operator; use this for a team.
  #
  # backend "s3" {
  #   bucket         = "your-tfstate-bucket"
  #   key            = "nsq-platform/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "your-tflock-table"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}
