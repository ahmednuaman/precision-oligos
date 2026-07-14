variable "suffix" { type = string }
variable "suffix_global" { type = string }
variable "aws_region" { type = string }
variable "environment" { type = string }
variable "tags" { type = map(string) }

variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids" { type = list(string) }
variable "alb_sg_id" { type = string }
variable "service_sg_id" { type = string }

variable "container_image" { type = string }
variable "log_retention_days" { type = number }
variable "audit_retention_years" { type = number }
variable "use_spot" { type = bool }
variable "api_desired_count" { type = number }

variable "router_model" { type = string }
variable "extraction_model" { type = string }
variable "drafting_model" { type = string }
variable "knowledge_base_id" { type = string }
variable "knowledge_base_region" { type = string }
variable "kb_assume_role_arn" { type = string }
variable "lims_base_url" { type = string }

variable "public_base_url" { type = string }
variable "acm_certificate_arn" { type = string }

# Optional Logfire ingestion token; when set, spans are also sent to Logfire's
# live platform in addition to the S3 data lake. Stored in Secrets Manager.
variable "logfire_token" {
  type      = string
  default   = ""
  sensitive = true
}

# Whether to capture prompt/response content in spans (may contain sensitive
# retrieved documents). Off by default.
variable "otel_capture_content" {
  type    = bool
  default = false
}

variable "service_version" {
  type    = string
  default = "0.1.0"
}

variable "traces_retention_days" {
  type    = number
  default = 365
}

# --- Remote MCP server -----------------------------------------------------------------
variable "mcp_enabled" {
  description = "Serve the OAuth-protected remote MCP server from the API."
  type        = bool
  default     = true
}

variable "mcp_scopes" {
  description = "Space-separated scopes advertised and required for the MCP resource."
  type        = string
  default     = "oligos:use"
}

# Cognito outputs (from the auth module).
variable "cognito_user_pool_id" { type = string }
variable "cognito_client_id" { type = string }
variable "cognito_client_secret_arn" { type = string }
variable "cognito_domain_url" { type = string }
variable "cognito_region" { type = string }
variable "saml_provider_name" { type = string }
