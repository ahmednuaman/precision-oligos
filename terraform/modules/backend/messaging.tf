# Notifications topic (subscriptions managed out of band).
resource "aws_sns_topic" "notifications" {
  name              = "NotificationsSnsTopic-${var.suffix}"
  kms_master_key_id = aws_kms_key.data.id
  tags              = merge(var.tags, { Name = "NotificationsSnsTopic-${var.suffix}" })
}

# Per-step dead-letter queues for the Lambda pipeline tasks.
resource "aws_sqs_queue" "step_dlq" {
  name                              = "StepDlqSqsQueue-${var.suffix}"
  kms_master_key_id                 = aws_kms_key.data.id
  message_retention_seconds         = 1209600
  kms_data_key_reuse_period_seconds = 300
  tags                              = merge(var.tags, { Name = "StepDlqSqsQueue-${var.suffix}" })
}
