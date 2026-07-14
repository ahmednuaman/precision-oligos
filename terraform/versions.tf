terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

# Primary provider: the deployment region for the environment.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = var.environment
      Repository  = var.repository
      ManagedBy   = "Terraform"
      Creator     = var.creator
    }
  }
}

# WAF for CloudFront (scope = CLOUDFRONT) and any ACM certificate for the
# distribution must live in us-east-1, so we expose a dedicated aliased provider.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Environment = var.environment
      Repository  = var.repository
      ManagedBy   = "Terraform"
      Creator     = var.creator
    }
  }
}
