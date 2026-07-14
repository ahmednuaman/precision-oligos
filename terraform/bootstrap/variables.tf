variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "github_org" {
  description = "GitHub organisation or user that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "Repository name (without the org)."
  type        = string
  default     = "oligos-agents"
}

variable "state_bucket_name" {
  description = "Globally-unique S3 bucket name for Terraform remote state."
  type        = string
}

variable "name_prefix" {
  description = "Prefix for the CI roles, e.g. <customer>-oligos."
  type        = string
}

variable "repository" {
  type    = string
  default = "oligos-agents"
}

variable "creator" {
  type    = string
  default = "OpenSource"
}
