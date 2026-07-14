resource "aws_lambda_function" "step" {
  for_each      = local.steps
  function_name = "${each.key}-${var.suffix}"
  role          = aws_iam_role.step_lambda.arn
  package_type  = "Image"
  image_uri     = var.container_image
  timeout       = 300
  memory_size   = 1024

  image_config {
    command = ["oligos_agents.steps.handlers.${each.value}"]
  }

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.service_sg_id]
  }

  environment {
    variables = local.app_env
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.step_dlq.arn
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_cloudwatch_log_group.steps]
  tags       = var.tags
}

# Audit stream mirror runs outside the VPC (only needs S3/KMS over AWS APIs).
resource "aws_lambda_function" "stream_mirror" {
  function_name = "AuditStreamMirror-${var.suffix}"
  role          = aws_iam_role.stream_mirror.arn
  package_type  = "Image"
  image_uri     = var.container_image
  timeout       = 60
  memory_size   = 256

  image_config {
    command = ["oligos_agents.steps.handlers.stream_mirror_handler"]
  }

  environment {
    variables = local.app_env
  }

  depends_on = [aws_cloudwatch_log_group.stream_mirror]
  tags       = var.tags
}

resource "aws_lambda_event_source_mapping" "audit_stream" {
  event_source_arn       = aws_dynamodb_table.audit.stream_arn
  function_name          = aws_lambda_function.stream_mirror.arn
  starting_position      = "LATEST"
  batch_size             = 25
  maximum_retry_attempts = 3
}
