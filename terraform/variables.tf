variable "envid" {
  description = "Environment identity: <customer>-<project>-<env> (e.g. acme-oligos-dev)."
  type        = string
}

variable "environment" {
  description = "Environment segment: sbx | dev | stg | prd."
  type        = string
}

variable "aws_region" {
  description = "Primary deployment region."
  type        = string
  default     = "eu-west-1"
}

variable "repository" {
  description = "Source repository name, for the Repository tag."
  type        = string
  default     = "oligos-agents"
}

variable "creator" {
  description = "Creator tag value."
  type        = string
  default     = "OpenSource"
}

variable "vpc_cidr" {
  type    = string
  default = "10.60.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones (>= 2 for multi-AZ)."
  type        = number
  default     = 2
}

# --- Application configuration ---
variable "container_image" {
  description = "Full ECR image URI:tag for the API/steps container. Set by CI."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  type    = number
  default = 90
}

variable "audit_retention_years" {
  description = "S3 Object Lock (COMPLIANCE) retention for the WORM audit mirror."
  type        = number
  default     = 7
}

variable "use_spot" {
  description = "Use Fargate Spot for non-production capacity."
  type        = bool
  default     = false
}

variable "api_desired_count" {
  type    = number
  default = 2
}

# --- Models / knowledge base ---
variable "router_model" {
  type    = string
  default = "bedrock:eu.anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "extraction_model" {
  type    = string
  default = "bedrock:eu.anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "drafting_model" {
  type    = string
  default = "bedrock:eu.anthropic.claude-sonnet-5"
}

variable "knowledge_base_id" {
  type    = string
  default = ""
}

variable "knowledge_base_region" {
  type    = string
  default = "eu-west-1"
}

variable "kb_assume_role_arn" {
  description = "Optional cross-account role ARN for the knowledge base."
  type        = string
  default     = ""
}

variable "lims_base_url" {
  type    = string
  default = ""
}

# --- Observability data lake / tracing ---
variable "service_version" {
  description = "Service version stamped onto OTel spans."
  type        = string
  default     = "0.1.0"
}

variable "logfire_token" {
  description = "Optional Logfire ingestion token; when set, spans also go to Logfire."
  type        = string
  default     = ""
  sensitive   = true
}

variable "otel_capture_content" {
  description = "Capture prompt/response content in spans (may contain sensitive data)."
  type        = bool
  default     = false
}

variable "traces_retention_days" {
  description = "Lifecycle expiry (days) for span objects in the traces data lake."
  type        = number
  default     = 365
}

# --- Edge / TLS ---
variable "acm_certificate_arn" {
  description = "ACM certificate ARN in us-east-1 for the CloudFront custom domain (optional)."
  type        = string
  default     = ""
}

variable "cloudfront_aliases" {
  description = "Optional custom domain names for CloudFront."
  type        = list(string)
  default     = []
}

variable "waf_rate_limit" {
  type    = number
  default = 2000
}

# --- Authentication (Cognito + Entra SAML) ---
variable "entra_saml_metadata_url" {
  description = "Entra federation metadata URL (mutually exclusive with the file)."
  type        = string
  default     = ""
}

variable "entra_saml_metadata_file" {
  description = "Path to Entra federation metadata XML (mutually exclusive with the URL)."
  type        = string
  default     = ""
}

variable "saml_provider_name" {
  type    = string
  default = "EntraSAML"
}

variable "cognito_domain_prefix" {
  description = "Globally-unique Cognito Hosted UI domain prefix."
  type        = string
}

variable "public_base_url_override" {
  description = <<-EOT
    Public URL when no custom CloudFront domain is used. On a first apply this can
    be left blank; after the CloudFront domain is known, set it to
    https://<distribution-domain> and re-apply so Cognito callback URLs and the
    OIDC redirect are correct.
  EOT
  type        = string
  default     = ""
}
