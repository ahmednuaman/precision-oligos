# Alarms are named per the workspace standard:
#   <Priority> <TerraformResourceName> <NameSpace> <Metric>

resource "aws_cloudwatch_metric_alarm" "sfn_failed" {
  alarm_name          = "P2 QcPipelineSfn-${var.suffix} AWS/States ExecutionsFailed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_actions       = [aws_sns_topic.notifications.arn]
  dimensions          = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "P2 StepDlqSqsQueue-${var.suffix} AWS/SQS ApproximateNumberOfMessagesVisible"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  alarm_actions       = [aws_sns_topic.notifications.arn]
  dimensions          = { QueueName = aws_sqs_queue.step_dlq.name }
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "P2 ApiAlb-${var.suffix_global} AWS/ApplicationELB HTTPCode_Target_5XX_Count"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_actions       = [aws_sns_topic.notifications.arn]
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix }
  tags                = var.tags
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "PrecisionOligos-${var.suffix}"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "LLM token usage by agent"
          region = var.aws_region
          metrics = [
            ["PrecisionOligos", "LLMInputTokens", "envid", var.suffix_global],
            ["PrecisionOligos", "LLMOutputTokens", "envid", var.suffix_global],
          ]
          view = "timeSeries"
          stat = "Sum"
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title   = "Step Functions executions"
          region  = var.aws_region
          metrics = [["AWS/States", "ExecutionsSucceeded", "StateMachineArn", aws_sfn_state_machine.pipeline.arn], ["AWS/States", "ExecutionsFailed", "StateMachineArn", aws_sfn_state_machine.pipeline.arn]]
          view    = "timeSeries"
          stat    = "Sum"
        }
      },
    ]
  })
}
