variable "suffix" { type = string }
variable "suffix_global" { type = string }
variable "aws_region" { type = string }
variable "tags" { type = map(string) }

variable "public_base_url" { type = string }
variable "cognito_domain_prefix" { type = string }
variable "saml_provider_name" { type = string }
variable "entra_saml_metadata_url" { type = string }
variable "entra_saml_metadata_file" { type = string }
variable "log_retention_days" { type = number }
