"""Step Functions state-machine (ASL) definition.

This is the source of truth for the async orchestration. The Terraform backend
module renders an equivalent definition with real Lambda ARNs; keeping the
structure here lets us unit-test its shape and document the flow.

Flow:
    Route -> (intent choice)
      qc_conflict_check: Retrieve -> Detect -> Draft -> (conflicts?)
        yes: AwaitApproval (waitForTaskToken) -> ExecuteWrites -> Done
        no:  Done
      unknown: NeedsReview
      other:   Specialist -> Done
"""

from __future__ import annotations

from oligos_agents.models import Intent

_LAMBDA_RETRY = [
    {
        "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException",
            "States.TaskFailed",
        ],
        "IntervalSeconds": 2,
        "MaxAttempts": 3,
        "BackoffRate": 2.0,
    }
]

_FAIL_CATCH = [{"ErrorEquals": ["States.ALL"], "Next": "Failed", "ResultPath": "$.error"}]


def _task(resource_arn: str, next_state: str) -> dict:
    return {
        "Type": "Task",
        "Resource": resource_arn,
        "Retry": _LAMBDA_RETRY,
        "Catch": _FAIL_CATCH,
        "Next": next_state,
    }


def build_definition(
    arns: dict[str, str],
    approval_timeout_seconds: int = 604800,  # 7 days
    approval_heartbeat_seconds: int = 86400,  # 1 day
) -> dict:
    """Build the ASL definition given a map of state name -> Lambda ARN.

    Required keys in *arns*: route, retrieve, detect, draft, store_token,
    execute_writes, specialist.
    """
    return {
        "Comment": "Precision oligos QC pipeline with HITL approval.",
        "StartAt": "Route",
        "States": {
            "Route": _task(arns["route"], "IntentChoice"),
            "IntentChoice": {
                "Type": "Choice",
                "Choices": [
                    {
                        "Variable": "$.intent",
                        "StringEquals": Intent.QC_CONFLICT_CHECK.value,
                        "Next": "Retrieve",
                    },
                    {
                        "Variable": "$.intent",
                        "StringEquals": Intent.UNKNOWN.value,
                        "Next": "NeedsReview",
                    },
                ],
                "Default": "Specialist",
            },
            "Retrieve": _task(arns["retrieve"], "Detect"),
            "Detect": _task(arns["detect"], "Draft"),
            "Draft": _task(arns["draft"], "DraftChoice"),
            "DraftChoice": {
                "Type": "Choice",
                "Choices": [
                    {
                        "Variable": "$.awaiting_approval",
                        "BooleanEquals": True,
                        "Next": "AwaitApproval",
                    }
                ],
                "Default": "Done",
            },
            "AwaitApproval": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
                "Parameters": {
                    "FunctionName": arns["store_token"],
                    "Payload": {
                        "run_id.$": "$.run_id",
                        "taskToken.$": "$$.Task.Token",
                    },
                },
                "TimeoutSeconds": approval_timeout_seconds,
                "HeartbeatSeconds": approval_heartbeat_seconds,
                "Catch": [
                    {"ErrorEquals": ["States.ALL"], "Next": "Rejected", "ResultPath": "$.error"}
                ],
                "Next": "ExecuteWrites",
            },
            "ExecuteWrites": _task(arns["execute_writes"], "Done"),
            "Specialist": _task(arns["specialist"], "Done"),
            "Done": {"Type": "Succeed"},
            "NeedsReview": {"Type": "Succeed"},
            "Rejected": {"Type": "Succeed"},
            "Failed": {"Type": "Fail", "Error": "PipelineFailed"},
        },
    }
