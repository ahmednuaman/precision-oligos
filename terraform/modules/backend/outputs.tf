output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "alb_dns_name" { value = aws_lb.api.dns_name }
output "state_machine_arn" { value = aws_sfn_state_machine.pipeline.arn }
output "audit_bucket" { value = aws_s3_bucket.audit.bucket }
output "runs_table" { value = aws_dynamodb_table.runs.name }
output "audit_table" { value = aws_dynamodb_table.audit.name }
output "sessions_table" { value = aws_dynamodb_table.sessions.name }
output "mcp_oauth_table" { value = aws_dynamodb_table.mcp_oauth.name }
output "notifications_topic_arn" { value = aws_sns_topic.notifications.arn }
output "kms_key_arn" { value = aws_kms_key.data.arn }
output "traces_bucket" { value = aws_s3_bucket.traces.bucket }
output "traces_firehose_stream" { value = aws_kinesis_firehose_delivery_stream.traces.name }
output "traces_glue_database" { value = aws_glue_catalog_database.traces.name }

# Consumed by the edge module to inject the origin-verify header into CloudFront.
output "cloudfront_origin_secret" {
  value     = random_password.cloudfront_origin.result
  sensitive = true
}
