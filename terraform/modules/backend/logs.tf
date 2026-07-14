resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/ApiService-${var.suffix}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "steps" {
  for_each          = toset(local.step_names)
  name              = "/aws/lambda/${each.value}-${var.suffix}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "stream_mirror" {
  name              = "/aws/lambda/AuditStreamMirror-${var.suffix}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/QcPipeline-${var.suffix}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
  tags              = var.tags
}
