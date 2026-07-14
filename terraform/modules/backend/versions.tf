terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    # random_password backs the session-signing and CloudFront origin secrets.
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
