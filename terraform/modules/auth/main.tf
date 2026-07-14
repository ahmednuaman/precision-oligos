locals {
  qc_groups = ["QCApprover", "QCLead", "QCManager", "Director"]
}

# --- Pre-token-generation Lambda -------------------------------------------------------

data "archive_file" "pretoken" {
  type        = "zip"
  source_file = "${path.module}/lambda_src/pretoken.py"
  output_path = "${path.module}/build/pretoken.zip"
}

data "aws_iam_policy_document" "pretoken_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pretoken" {
  name               = "PreTokenIamRole-${var.suffix_global}"
  assume_role_policy = data.aws_iam_policy_document.pretoken_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "pretoken_basic" {
  role       = aws_iam_role.pretoken.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "pretoken" {
  name              = "/aws/lambda/PreTokenLambdaFunction-${var.suffix}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "pretoken" {
  function_name    = "PreTokenLambdaFunction-${var.suffix}"
  role             = aws_iam_role.pretoken.arn
  runtime          = "python3.12"
  handler          = "pretoken.handler"
  filename         = data.archive_file.pretoken.output_path
  source_code_hash = data.archive_file.pretoken.output_base64sha256
  timeout          = 5
  depends_on       = [aws_cloudwatch_log_group.pretoken]
  tags             = var.tags
}

resource "aws_lambda_permission" "cognito_invoke" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pretoken.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.this.arn
}

# --- User pool -------------------------------------------------------------------------

resource "aws_cognito_user_pool" "this" {
  name                     = "UserPool-${var.suffix}"
  mfa_configuration        = "OFF" # MFA is enforced upstream in Entra.
  deletion_protection      = "ACTIVE"
  auto_verified_attributes = ["email"]

  username_attributes = ["email"]

  user_pool_add_ons {
    advanced_security_mode = "ENFORCED"
  }

  schema {
    name                = "role"
    attribute_data_type = "String"
    mutable             = true
    string_attribute_constraints {
      min_length = 0
      max_length = 256
    }
  }

  lambda_config {
    pre_token_generation_config {
      lambda_arn     = aws_lambda_function.pretoken.arn
      lambda_version = "V2_0"
    }
  }

  tags = var.tags
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

# --- SAML identity provider (Entra) ----------------------------------------------------

resource "aws_cognito_identity_provider" "entra" {
  user_pool_id  = aws_cognito_user_pool.this.id
  provider_name = var.saml_provider_name
  provider_type = "SAML"

  provider_details = var.entra_saml_metadata_url != "" ? {
    MetadataURL = var.entra_saml_metadata_url
    IDPSignout  = "true"
    } : {
    MetadataFile = file(var.entra_saml_metadata_file)
    IDPSignout   = "true"
  }

  # Map SAML assertions to Cognito attributes; App Roles land in custom:role and
  # are then normalised into groups by the pre-token Lambda.
  attribute_mapping = {
    email         = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
    "custom:role" = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
  }
}

# --- App client (confidential BFF) -----------------------------------------------------

resource "aws_cognito_user_pool_client" "bff" {
  name                                 = "BffClient-${var.suffix}"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = [aws_cognito_identity_provider.entra.provider_name]

  # The browser BFF callback and the MCP OAuth broker's upstream callback both
  # use this confidential client; register both redirect URIs.
  callback_urls = [
    "${var.public_base_url}/api/auth/callback",
    "${var.public_base_url}/oauth/callback",
  ]
  logout_urls = ["${var.public_base_url}/"]

  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]

  access_token_validity  = 15
  id_token_validity      = 15
  refresh_token_validity = 8
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}

# --- Groups ----------------------------------------------------------------------------

resource "aws_cognito_user_group" "qc" {
  for_each     = toset(local.qc_groups)
  name         = each.value
  user_pool_id = aws_cognito_user_pool.this.id
}

# --- Client secret published to Secrets Manager for the BFF ---------------------------

resource "aws_secretsmanager_secret" "client_secret" {
  name = "CognitoClientSecret-${var.suffix}"
  tags = merge(var.tags, { Name = "CognitoClientSecret-${var.suffix}" })
}

resource "aws_secretsmanager_secret_version" "client_secret" {
  secret_id     = aws_secretsmanager_secret.client_secret.id
  secret_string = aws_cognito_user_pool_client.bff.client_secret
}
