# Observability data lake: pydantic-ai OTel spans (captured via Logfire) are
# pushed to Kinesis Data Firehose, which buffers, compresses, date-partitions,
# and lands them in S3 as GZIP JSON. A Glue table with partition projection
# makes the lake immediately queryable from Athena for cost/quality analysis.

resource "aws_s3_bucket" "traces" {
  bucket = "traces-${var.suffix}"
  tags   = merge(var.tags, { Name = "traces-${var.suffix}" })
}

resource "aws_s3_bucket_versioning" "traces" {
  bucket = aws_s3_bucket.traces.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "traces" {
  bucket = aws_s3_bucket.traces.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "traces" {
  bucket                  = aws_s3_bucket.traces.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "traces" {
  bucket = aws_s3_bucket.traces.id
  rule {
    id     = "expire-and-archive"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration {
      days = var.traces_retention_days
    }
  }
}

resource "aws_s3_bucket_policy" "traces" {
  bucket = aws_s3_bucket.traces.id
  policy = data.aws_iam_policy_document.traces_bucket.json
}

data "aws_iam_policy_document" "traces_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.traces.arn, "${aws_s3_bucket.traces.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# --- Firehose delivery stream ----------------------------------------------------------

resource "aws_cloudwatch_log_group" "firehose" {
  name              = "/aws/kinesisfirehose/OligoTracesFirehose-${var.suffix}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
  tags              = var.tags
}

resource "aws_cloudwatch_log_stream" "firehose" {
  name           = "S3Delivery"
  log_group_name = aws_cloudwatch_log_group.firehose.name
}

data "aws_iam_policy_document" "firehose_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "firehose" {
  name               = "OligoTracesFirehoseIamRole-${var.suffix_global}"
  assume_role_policy = data.aws_iam_policy_document.firehose_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "firehose" {
  statement {
    sid = "WriteToLake"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:PutObject",
    ]
    resources = [aws_s3_bucket.traces.arn, "${aws_s3_bucket.traces.arn}/*"]
  }
  statement {
    sid       = "UseDataKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
  statement {
    sid       = "Logging"
    actions   = ["logs:PutLogEvents"]
    resources = [aws_cloudwatch_log_group.firehose.arn, "${aws_cloudwatch_log_group.firehose.arn}:*"]
  }
}

resource "aws_iam_role_policy" "firehose" {
  role   = aws_iam_role.firehose.id
  name   = "firehose"
  policy = data.aws_iam_policy_document.firehose.json
}

resource "aws_kinesis_firehose_delivery_stream" "traces" {
  name        = "OligoTracesFirehose-${var.suffix}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose.arn
    bucket_arn = aws_s3_bucket.traces.arn

    # Arrival-time partitioning so Athena partition projection can prune scans.
    prefix              = "spans/environment=${var.environment}/dt=!{timestamp:yyyy-MM-dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/dt=!{timestamp:yyyy-MM-dd}/"

    buffering_size     = 64
    buffering_interval = 60
    compression_format = "GZIP"
    kms_key_arn        = aws_kms_key.data.arn

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose.name
      log_stream_name = aws_cloudwatch_log_stream.firehose.name
    }
  }

  server_side_encryption {
    enabled  = true
    key_type = "CUSTOMER_MANAGED_CMK"
    key_arn  = aws_kms_key.data.arn
  }

  tags = var.tags
}

# --- Glue catalog (Athena) -------------------------------------------------------------

resource "aws_glue_catalog_database" "traces" {
  name = replace("oligo_traces_${var.suffix_global}", "-", "_")
}

resource "aws_glue_catalog_table" "spans" {
  name          = "spans"
  database_name = aws_glue_catalog_database.traces.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                = "json"
    "projection.enabled"          = "true"
    "projection.environment.type" = "injected"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2024-01-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "projection.hour.type"        = "integer"
    "projection.hour.range"       = "0,23"
    "projection.hour.digits"      = "2"
    "storage.location.template"   = "s3://${aws_s3_bucket.traces.bucket}/spans/environment=$${environment}/dt=$${dt}/hour=$${hour}/"
    "EXTERNAL"                    = "TRUE"
  }

  partition_keys {
    name = "environment"
    type = "string"
  }
  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.traces.bucket}/spans/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters            = { "ignore.malformed.json" = "true" }
    }

    columns {
      name = "trace_id"
      type = "string"
    }
    columns {
      name = "span_id"
      type = "string"
    }
    columns {
      name = "parent_span_id"
      type = "string"
    }
    columns {
      name = "name"
      type = "string"
    }
    columns {
      name = "kind"
      type = "string"
    }
    columns {
      name = "start_time"
      type = "string"
    }
    columns {
      name = "end_time"
      type = "string"
    }
    columns {
      name = "duration_ms"
      type = "double"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "status_message"
      type = "string"
    }
    columns {
      name = "service_name"
      type = "string"
    }
    columns {
      name = "service_version"
      type = "string"
    }
    # Dynamic OTel attributes (incl. gen_ai.* token usage) kept as raw JSON.
    columns {
      name = "attributes"
      type = "string"
    }
    columns {
      name = "events"
      type = "string"
    }
  }
}

# --- Optional Logfire token secret -----------------------------------------------------

resource "aws_secretsmanager_secret" "logfire_token" {
  count       = var.logfire_token == "" ? 0 : 1
  name        = "LogfireToken-${var.suffix}"
  description = "Logfire ingestion token for live tracing."
  kms_key_id  = aws_kms_key.data.arn
  tags        = var.tags
}

resource "aws_secretsmanager_secret_version" "logfire_token" {
  count         = var.logfire_token == "" ? 0 : 1
  secret_id     = aws_secretsmanager_secret.logfire_token[0].id
  secret_string = var.logfire_token
}
