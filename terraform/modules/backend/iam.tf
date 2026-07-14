data "aws_region" "current" {}

locals {
  account_id            = data.aws_caller_identity.current.account_id
  bedrock_arn           = "arn:aws:bedrock:*::foundation-model/*"
  inference_profile_arn = "arn:aws:bedrock:*:${local.account_id}:inference-profile/*"
}

# --- Assume-role policies --------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

# --- Shared statements -----------------------------------------------------------------

data "aws_iam_policy_document" "kms_use" {
  statement {
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = [aws_kms_key.data.arn]
  }
}

# Append-only audit access: allow write/read, explicitly deny mutation/deletion.
data "aws_iam_policy_document" "audit_append_only" {
  statement {
    sid       = "AuditAppendAndRead"
    actions   = ["dynamodb:PutItem", "dynamodb:Query", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.audit.arn, "${aws_dynamodb_table.audit.arn}/index/*"]
  }
  statement {
    sid    = "DenyAuditMutation"
    effect = "Deny"
    actions = [
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:PartiQLUpdate",
      "dynamodb:PartiQLDelete",
    ]
    resources = [aws_dynamodb_table.audit.arn]
  }
}

# --- ECS execution role ----------------------------------------------------------------

resource "aws_iam_role" "task_execution" {
  name               = "ApiExecutionIamRole-${var.suffix_global}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_extra" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.session_signing.arn]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role_policy" "execution_extra" {
  role   = aws_iam_role.task_execution.id
  name   = "execution-extra"
  policy = data.aws_iam_policy_document.execution_extra.json
}

# --- API task role ---------------------------------------------------------------------

resource "aws_iam_role" "api_task" {
  name               = "ApiTaskIamRole-${var.suffix_global}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "api_task" {
  source_policy_documents = [
    data.aws_iam_policy_document.kms_use.json,
    data.aws_iam_policy_document.audit_append_only.json,
  ]

  statement {
    sid       = "Runs"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.runs.arn, "${aws_dynamodb_table.runs.arn}/index/*"]
  }
  statement {
    sid = "Sessions"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem"
    ]
    resources = [aws_dynamodb_table.sessions.arn]
  }
  statement {
    sid = "McpOAuth"
    actions = [
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:Query"
    ]
    resources = [aws_dynamodb_table.mcp_oauth.arn, "${aws_dynamodb_table.mcp_oauth.arn}/index/*"]
  }
  statement {
    sid       = "StepFunctions"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.pipeline.arn]
  }
  statement {
    sid       = "TaskCallbacks"
    actions   = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"]
    resources = ["*"]
  }
  statement {
    sid     = "Secrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.session_signing.arn,
      var.cognito_client_secret_arn,
    ]
  }
  statement {
    sid       = "TracesFirehose"
    actions   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
    resources = [aws_kinesis_firehose_delivery_stream.traces.arn]
  }

  dynamic "statement" {
    for_each = var.logfire_token == "" ? [] : [1]
    content {
      sid       = "LogfireToken"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.logfire_token[0].arn]
    }
  }
}

resource "aws_iam_role_policy" "api_task" {
  role   = aws_iam_role.api_task.id
  name   = "api-task"
  policy = data.aws_iam_policy_document.api_task.json
}

# --- Step Lambda role ------------------------------------------------------------------

resource "aws_iam_role" "step_lambda" {
  name               = "StepLambdaIamRole-${var.suffix_global}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "step_lambda_basic" {
  role       = aws_iam_role.step_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "step_lambda" {
  source_policy_documents = [
    data.aws_iam_policy_document.kms_use.json,
    data.aws_iam_policy_document.audit_append_only.json,
  ]

  statement {
    sid       = "Bedrock"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [local.bedrock_arn, local.inference_profile_arn]
  }
  statement {
    sid       = "BedrockRetrieve"
    actions   = ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"]
    resources = ["*"]
  }
  statement {
    sid       = "Runs"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.runs.arn, "${aws_dynamodb_table.runs.arn}/index/*"]
  }
  statement {
    sid       = "Notify"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notifications.arn]
  }
  statement {
    sid       = "Dlq"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.step_dlq.arn]
  }
  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.lims_api_key.arn]
  }
  statement {
    sid       = "TaskHeartbeat"
    actions   = ["states:SendTaskHeartbeat"]
    resources = ["*"]
  }
  statement {
    sid       = "TracesFirehose"
    actions   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
    resources = [aws_kinesis_firehose_delivery_stream.traces.arn]
  }

  dynamic "statement" {
    for_each = var.logfire_token == "" ? [] : [1]
    content {
      sid       = "LogfireToken"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.logfire_token[0].arn]
    }
  }

  dynamic "statement" {
    for_each = var.kb_assume_role_arn == "" ? [] : [var.kb_assume_role_arn]
    content {
      sid       = "CrossAccountKb"
      actions   = ["sts:AssumeRole"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "step_lambda" {
  role   = aws_iam_role.step_lambda.id
  name   = "step-lambda"
  policy = data.aws_iam_policy_document.step_lambda.json
}

# --- Audit stream mirror role ----------------------------------------------------------

resource "aws_iam_role" "stream_mirror" {
  name               = "AuditStreamMirrorIamRole-${var.suffix_global}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "stream_mirror" {
  source_policy_documents = [data.aws_iam_policy_document.kms_use.json]

  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogStream", "logs:PutLogEvents", "logs:CreateLogGroup"
    ]
    resources = ["*"]
  }
  statement {
    sid = "ReadStream"
    actions = [
      "dynamodb:GetRecords",
      "dynamodb:GetShardIterator",
      "dynamodb:DescribeStream",
      "dynamodb:ListStreams",
    ]
    resources = [aws_dynamodb_table.audit.stream_arn]
  }
  statement {
    sid       = "WriteWorm"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.audit.arn}/*"]
  }
}

resource "aws_iam_role_policy" "stream_mirror" {
  role   = aws_iam_role.stream_mirror.id
  name   = "stream-mirror"
  policy = data.aws_iam_policy_document.stream_mirror.json
}

# --- Step Functions role ---------------------------------------------------------------

resource "aws_iam_role" "sfn" {
  name               = "QcPipelineIamRole-${var.suffix_global}"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "sfn" {
  statement {
    sid       = "InvokeSteps"
    actions   = ["lambda:InvokeFunction"]
    resources = [for fn in aws_lambda_function.step : fn.arn]
  }
  statement {
    sid = "Logging"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "Xray"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  role   = aws_iam_role.sfn.id
  name   = "sfn"
  policy = data.aws_iam_policy_document.sfn.json
}
