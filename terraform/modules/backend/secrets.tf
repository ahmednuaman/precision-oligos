# Signing secret for the CSRF token / login-state cookie.
resource "random_password" "session_signing" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "session_signing" {
  name       = "SessionSigning-${var.suffix}"
  kms_key_id = aws_kms_key.data.arn
  tags       = merge(var.tags, { Name = "SessionSigning-${var.suffix}" })
}

resource "aws_secretsmanager_secret_version" "session_signing" {
  secret_id     = aws_secretsmanager_secret.session_signing.id
  secret_string = random_password.session_signing.result
}

# LIMS API key - populated by operators; created empty so IAM can reference it.
resource "aws_secretsmanager_secret" "lims_api_key" {
  name       = "LimsApiKey-${var.suffix}"
  kms_key_id = aws_kms_key.data.arn
  tags       = merge(var.tags, { Name = "LimsApiKey-${var.suffix}" })
}

# Secret header injected by CloudFront and verified by the ALB listener, so the
# public ALB only serves requests that came through CloudFront. Two versions are
# kept live to allow zero-downtime rotation.
resource "random_password" "cloudfront_origin" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "cloudfront_origin" {
  name       = "CloudFrontOriginHeader-${var.suffix}"
  kms_key_id = aws_kms_key.data.arn
  tags       = merge(var.tags, { Name = "CloudFrontOriginHeader-${var.suffix}" })
}

resource "aws_secretsmanager_secret_version" "cloudfront_origin" {
  secret_id     = aws_secretsmanager_secret.cloudfront_origin.id
  secret_string = random_password.cloudfront_origin.result
}
