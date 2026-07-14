locals {
  lambda_retry = [{
    ErrorEquals = [
      "Lambda.ServiceException",
      "Lambda.AWSLambdaException",
      "Lambda.SdkClientException",
      "Lambda.TooManyRequestsException",
      "States.TaskFailed",
    ]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2.0
  }]
  fail_catch = [{ ErrorEquals = ["States.ALL"], Next = "Failed", ResultPath = "$.error" }]

  asl = {
    Comment = "Precision oligos QC pipeline with HITL approval."
    StartAt = "Route"
    States = {
      Route = {
        Type     = "Task"
        Resource = aws_lambda_function.step["RouteStepLambdaFunction"].arn
        Retry    = local.lambda_retry
        Catch    = local.fail_catch
        Next     = "IntentChoice"
      }
      IntentChoice = {
        Type = "Choice"
        Choices = [
          { Variable = "$.intent", StringEquals = "qc_conflict_check", Next = "Retrieve" },
          { Variable = "$.intent", StringEquals = "unknown", Next = "NeedsReview" },
        ]
        Default = "Specialist"
      }
      Retrieve = {
        Type     = "Task"
        Resource = aws_lambda_function.step["RetrieveStepLambdaFunction"].arn
        Retry    = local.lambda_retry
        Catch    = local.fail_catch
        Next     = "Detect"
      }
      Detect = {
        Type     = "Task"
        Resource = aws_lambda_function.step["DetectStepLambdaFunction"].arn
        Retry    = local.lambda_retry
        Catch    = local.fail_catch
        Next     = "Draft"
      }
      Draft = {
        Type     = "Task"
        Resource = aws_lambda_function.step["DraftStepLambdaFunction"].arn
        Retry    = local.lambda_retry
        Catch    = local.fail_catch
        Next     = "DraftChoice"
      }
      DraftChoice = {
        Type    = "Choice"
        Choices = [{ Variable = "$.awaiting_approval", BooleanEquals = true, Next = "AwaitApproval" }]
        Default = "Done"
      }
      AwaitApproval = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke.waitForTaskToken"
        Parameters = {
          FunctionName = aws_lambda_function.step["StoreTokenStepLambdaFunction"].arn
          Payload = {
            "run_id.$"    = "$.run_id"
            "taskToken.$" = "$$.Task.Token"
          }
        }
        TimeoutSeconds   = 604800
        HeartbeatSeconds = 86400
        Catch            = [{ ErrorEquals = ["States.ALL"], Next = "Rejected", ResultPath = "$.error" }]
        Next             = "ExecuteWrites"
      }
      ExecuteWrites = {
        Type     = "Task"
        Resource = aws_lambda_function.step["ExecuteWritesStepLambdaFunction"].arn
        Retry    = local.lambda_retry
        Catch    = local.fail_catch
        Next     = "Done"
      }
      Specialist = {
        Type     = "Task"
        Resource = aws_lambda_function.step["SpecialistStepLambdaFunction"].arn
        Retry    = local.lambda_retry
        Catch    = local.fail_catch
        Next     = "Done"
      }
      Done        = { Type = "Succeed" }
      NeedsReview = { Type = "Succeed" }
      Rejected    = { Type = "Succeed" }
      Failed      = { Type = "Fail", Error = "PipelineFailed" }
    }
  }
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "QcPipelineSfn-${var.suffix}"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = jsonencode(local.asl)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  tags = var.tags
}
