output "cloudfront_domain" {
  description = "CloudFront distribution domain (the app entry point)."
  value       = module.edge.distribution_domain
}

output "cloudfront_distribution_id" {
  value = module.edge.distribution_id
}

output "public_url" {
  value = module.edge.public_url
}

output "spa_bucket" {
  description = "S3 bucket for the SPA assets (target for s3 sync in CI)."
  value       = module.edge.spa_bucket
}

output "ecr_repository_url" {
  value = module.backend.ecr_repository_url
}

output "state_machine_arn" {
  value = module.backend.state_machine_arn
}

output "traces_bucket" {
  description = "S3 data-lake bucket holding OTel spans (query via Athena)."
  value       = module.backend.traces_bucket
}

output "traces_glue_database" {
  value = module.backend.traces_glue_database
}

output "cognito_user_pool_id" {
  value = module.auth.user_pool_id
}

output "cognito_hosted_ui_domain" {
  value = module.auth.domain_url
}

output "cognito_client_id" {
  value = module.auth.client_id
}
