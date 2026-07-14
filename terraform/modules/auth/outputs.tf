output "user_pool_id" { value = aws_cognito_user_pool.this.id }
output "client_id" { value = aws_cognito_user_pool_client.bff.id }
output "client_secret_arn" { value = aws_secretsmanager_secret.client_secret.arn }
output "domain_url" {
  value = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.aws_region}.amazoncognito.com"
}
output "saml_provider_name" { value = aws_cognito_identity_provider.entra.provider_name }
output "issuer" {
  value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}
