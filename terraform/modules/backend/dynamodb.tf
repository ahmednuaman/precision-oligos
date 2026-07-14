# Runs: mutable pipeline state.
resource "aws_dynamodb_table" "runs" {
  name         = "RunsDdbTable-${var.suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"

  attribute {
    name = "run_id"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "batch_id"
    type = "S"
  }
  attribute {
    name = "submitter_sub"
    type = "S"
  }

  global_secondary_index {
    name            = "by_status"
    hash_key        = "status"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "by_batch"
    hash_key        = "batch_id"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "by_submitter"
    hash_key        = "submitter_sub"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
  tags = merge(var.tags, { Name = "RunsDdbTable-${var.suffix}" })
}

# Audit: append-only, tamper-evident. Streams feed the WORM mirror.
resource "aws_dynamodb_table" "audit" {
  name             = "AuditDdbTable-${var.suffix}"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "run_id"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  attribute {
    name = "run_id"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
  tags = merge(var.tags, { Name = "AuditDdbTable-${var.suffix}" })
}

# MCP OAuth: dynamically-registered clients, short-lived authorization codes /
# pending authorizations, and issued access/refresh tokens. TTL auto-expires
# the ephemeral rows; the resource server validates access tokens by lookup.
resource "aws_dynamodb_table" "mcp_oauth" {
  name         = "McpOAuthDdbTable-${var.suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
  tags = merge(var.tags, { Name = "McpOAuthDdbTable-${var.suffix}" })
}

# Sessions: BFF server-side tokens, auto-expired via TTL.
resource "aws_dynamodb_table" "sessions" {
  name         = "SessionsDdbTable-${var.suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
  tags = merge(var.tags, { Name = "SessionsDdbTable-${var.suffix}" })
}
