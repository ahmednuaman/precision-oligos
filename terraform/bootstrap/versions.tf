terraform {
  required_version = ">= 1.9.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# The bootstrap stack uses local state and is applied once with elevated
# credentials; it creates the remote-state bucket and the CI deploy roles that
# every subsequent workflow relies on.
provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Repository = var.repository
      ManagedBy  = "Terraform"
      Creator    = var.creator
      Purpose    = "cicd-bootstrap"
    }
  }
}
