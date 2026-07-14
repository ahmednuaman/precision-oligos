data "aws_caller_identity" "current" {}

# One CMK for data at rest (DynamoDB, S3, SNS, SQS, logs). Scoped key policy
# lets the account administer it and CloudWatch Logs use it.
resource "aws_kms_key" "data" {
  description             = "Precision oligos data-at-rest CMK (${var.suffix})"
  enable_key_rotation     = true
  deletion_window_in_days = 14
  policy                  = data.aws_iam_policy_document.kms.json
  tags                    = merge(var.tags, { Name = "DataKmsKey-${var.suffix}" })
}

resource "aws_kms_alias" "data" {
  name          = "alias/DataKmsKey-${var.suffix}"
  target_key_id = aws_kms_key.data.key_id
}

data "aws_iam_policy_document" "kms" {
  statement {
    sid       = "AccountAdmin"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }
  }
}
