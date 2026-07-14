output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}

output "deploy_role_arns" {
  description = "Per-environment deploy role ARNs for the GitHub Environments."
  value       = { for k, r in aws_iam_role.deploy : k => r.arn }
}

output "pr_plan_role_arn" {
  value = aws_iam_role.pr_plan.arn
}
